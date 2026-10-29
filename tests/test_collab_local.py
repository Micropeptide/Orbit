"""Reading a local chat so it can be shared: only user and assistant text, nothing from tools, and a warning when something looks like a key."""
import json, os, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
import collab_local as L      # noqa: E402


class TestExtract(unittest.TestCase):
    def test_only_what_people_and_models_said_is_taken(self):
        msgs = [{"role": "system", "content": "secret system prompt"}, {"role": "user", "content": "hello", "t": 5.0},
                {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "function": {"name": "read_file", "arguments": "{}"}}]},
                {"role": "tool", "content": "FILE CONTENTS", "tool_call_id": "c1"}, {"role": "assistant", "content": "done", "model": "Qwen3"},
                {"role": "user", "content": [{"type": "text", "text": "look"}, {"type": "image_url", "image_url": {"url": "data:..."}}]}]
        out, st = L.extract(msgs)
        self.assertEqual([(m["role"], m["text"]) for m in out], [("user", "hello"), ("assistant", "done"), ("user", "look")])
        self.assertEqual(out[0]["ts"], 5.0); self.assertEqual(out[1]["label"], "Qwen3")
        self.assertEqual((st["user"], st["assistant"], st["tools_skipped"], st["images_skipped"], st["system_skipped"]), (2, 1, 2, 1, 1))
        self.assertNotIn("FILE CONTENTS", json.dumps(out)); self.assertNotIn("secret system prompt", json.dumps(out))

    def test_orbits_own_notes_after_a_message_are_cut(self):
        out, _ = L.extract([{"role": "user", "content": "do it\n\n[Orbit says: internal]"}], strip_marker="[Orbit says:")
        self.assertEqual(out[0]["text"], "do it")

    def test_odd_input_never_crashes(self):
        for bad in (None, 5, "x", [None, 5, "x", {}, {"role": "user"}, {"role": "user", "content": 5}, {"role": "user", "content": [None, 3]}]):
            out, st = L.extract(bad); self.assertEqual(out, [])


class TestWarnings(unittest.TestCase):
    def test_things_that_look_like_keys_are_named_without_being_repeated(self):
        texts = ["my key is sk-ant-api03-" + "a" * 40, "token ghp_" + "b" * 36, "AKIA" + "C" * 16, "-----BEGIN OPENSSH PRIVATE KEY-----", "password: hunter2hunter2", "all clear"]
        w = L.warnings(texts)
        kinds = {x["kind"] for x in w}
        self.assertTrue({"an API key", "a GitHub token", "an AWS key", "a private key", "a password"} <= kinds, kinds)
        self.assertNotIn("hunter2", json.dumps(w)); self.assertNotIn("aaaaaaaa", json.dumps(w))
        self.assertEqual(sorted({x["message"] for x in w}), [1, 2, 3, 4, 5])
        self.assertEqual(L.warnings(["nothing here", "just words about passwords in general"]), [])


class TestReadSession(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.tmp, True)

    def write(self, name, obj):
        p = os.path.join(self.tmp, name + ".json"); json.dump(obj, open(p, "w")); return p

    def test_both_file_shapes_and_nothing_is_written(self):
        a = self.write("a", {"schema": 2, "title": "Pollen", "messages": [{"role": "user", "content": "hi"}]}); b = self.write("b", [{"role": "user", "content": "yo"}])
        before = {n: os.stat(os.path.join(self.tmp, n)).st_mtime_ns for n in os.listdir(self.tmp)}
        self.assertEqual(L.read_session(a), ("Pollen", [{"role": "user", "content": "hi"}])); self.assertEqual(L.read_session(b), (None, [{"role": "user", "content": "yo"}]))
        self.assertEqual({n: os.stat(os.path.join(self.tmp, n)).st_mtime_ns for n in os.listdir(self.tmp)}, before)
        self.assertEqual(sorted(os.listdir(self.tmp)), ["a.json", "b.json"])

    def test_missing_or_damaged_is_an_error_not_a_crash(self):
        open(os.path.join(self.tmp, "c.json"), "w").write("{broken")
        for p in (os.path.join(self.tmp, "nope.json"), os.path.join(self.tmp, "c.json")):
            with self.assertRaises(ValueError): L.read_session(p)

    def test_a_chat_id_cannot_point_outside_the_sessions_folder(self):
        for bad in ("../x", "a/b", "", "a b", None, "x" * 200, "..", "a\x00b"):
            with self.assertRaises(ValueError): L.session_file(self.tmp, bad)
        self.assertEqual(L.session_file(self.tmp, "cq-1_a"), os.path.join(self.tmp, "cq-1_a.json"))


if __name__ == "__main__":
    unittest.main()
