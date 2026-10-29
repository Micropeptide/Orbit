"""Copying a shared chat into one's own Orbit: the saved file, who may save it, and turning it into a local chat safely."""
import json, os, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
import collab_local as L       # noqa: E402
import collab_policy as P      # noqa: E402
import collab_store as S       # noqa: E402
import collab_server as V      # noqa: E402


def ev(seq, etype, author, payload, chat="main", id_=None):
    return {"seq": seq, "id": id_ or f"e{seq}", "ts": 1700000000.0 + seq, "type": etype, "author": author, "chat": chat, "payload": payload}


class TestPayload(unittest.TestCase):
    NAMES = {"m_a": "Mei", "m_b": "Theo"}

    def test_a_chat_becomes_a_plain_list_of_who_said_what(self):
        events = [ev(1, "msg", "m_a", {"text": "hi all"}), ev(2, "tool_request", "system", {"tool": "read_file"}), ev(3, "msg", "model:qwen", {"text": "hello", "model_label": "Qwen3 27B", "initiated_by": "m_a"}),
                  ev(4, "msg", "m_b", {"deleted": True}), ev(5, "msg", "m_b", {"text": "second"}, id_="e5"), ev(6, "edit", "m_b", {"target": "e5", "text": "second, fixed"})]
        p = L.shared_chat_payload("Lab", "main", "Main", events, self.NAMES, "Mei", 1800000000.0)
        self.assertEqual((p["format"], p["version"], p["project"], p["chat"]["name"]), ("orbit-shared-chat", 1, "Lab", "Main"))
        self.assertEqual([(m["author"], m["is_model"], m["text"]) for m in p["messages"]], [("Mei", False, "hi all"), ("Qwen3 27B", True, "hello"), ("Theo", False, "second, fixed")])
        self.assertNotIn("read_file", json.dumps(p)); self.assertEqual(p["messages"][1]["asked_by"], "Mei")

    def test_unknown_authors_are_named_plainly_and_imported_messages_keep_their_mark(self):
        p = L.shared_chat_payload("Lab", "c1", "Old", [ev(1, "msg", "m_zzz", {"text": "x"}), ev(2, "msg", "model:imported", {"text": "y", "imported": True, "model_label": "Qwen"})], {}, "Me", 1.0)
        self.assertEqual([m["author"] for m in p["messages"]], ["someone", "Qwen"]); self.assertTrue(p["messages"][1]["imported"])


class TestToLocal(unittest.TestCase):
    def payload(self, **over):
        p = {"format": "orbit-shared-chat", "version": 1, "project": "Lab", "chat": {"id": "main", "name": "Main"}, "exported_by": "Mei", "exported_at": 1.0,
             "messages": [{"author": "Theo", "is_model": False, "text": "question", "ts": 5.0}, {"author": "Qwen", "is_model": True, "text": "answer", "ts": 6.0, "asked_by": "Theo"}]}
        p.update(over); return p

    def test_it_becomes_a_chat_with_a_note_first_and_people_named(self):
        title, msgs = L.local_messages(self.payload())
        self.assertEqual(title, "Main (from Lab)")
        self.assertEqual([m["role"] for m in msgs], ["user", "user", "assistant"])
        self.assertIn("Lab", msgs[0]["content"]); self.assertIn("not orders", msgs[0]["content"])
        self.assertEqual(msgs[1]["content"], "Theo: question"); self.assertEqual(msgs[2]["content"], "answer"); self.assertEqual(msgs[2]["model_label"], "Qwen")
        self.assertEqual((msgs[1]["t"], msgs[2]["t"]), (5.0, 6.0))

    def test_what_is_refused(self):
        bad = [None, [], {}, self.payload(format="other"), self.payload(version=2), self.payload(messages="x"), self.payload(messages=[{"author": "a", "text": 5}]),
               self.payload(messages=[{"author": "a", "is_model": False, "text": "x"}] * 5001), self.payload(messages=[5]),
               self.payload(messages=[{"author": "a", "is_model": False, "text": "x" * (S.MAX_TEXT + 1)}])]
        for p in bad:
            with self.assertRaises(ValueError): L.local_messages(p)

    def test_text_is_cleaned_not_interpreted(self):
        title, msgs = L.local_messages(self.payload(chat={"id": "x", "name": "Bad\x00 <b>name</b>\n"}, project="P\x07roj",
                                                    messages=[{"author": "A\x00\nB", "is_model": False, "text": "<script>alert(1)</script>\x00 ok"}]))
        self.assertNotIn("\x00", json.dumps(msgs) + title); self.assertNotIn("\n", title); self.assertEqual(msgs[1]["content"], "A B: <script>alert(1)</script> ok")

    def test_the_number_of_messages_and_names_are_limited(self):
        t, msgs = L.local_messages(self.payload(chat={"id": "x", "name": "n" * 300}, messages=[{"author": "a" * 300, "is_model": False, "text": "t"}]))
        self.assertLessEqual(len(t), 100); self.assertTrue(msgs[1]["content"].startswith("a" * 40 + ": "))

    def test_a_session_id_is_safe(self):
        import re
        self.assertTrue(re.fullmatch(r"[0-9]{8}-[0-9]{6}-[0-9a-f]{4}", L.new_session_id(1800000000.0)))


class TestWhoMaySaveACopy(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.work = os.path.join(self.tmp, "work"); os.makedirs(self.work)
        self.pol = P.Policy(never=[], home=os.path.join(self.tmp, "home"), sensitive=lambda p: None)
        self.st = S.Store(os.path.join(self.tmp, "collab"), policy=self.pol)
        p = self.st.create_project("Lab", owner_name="Owner", working_dir=self.work)
        self.pid, self.owner, self.otok = p["project"]["id"], p["member"]["id"], p["token"]
        inv = self.st.create_invite(self.pid, self.owner, grant=P.template("viewer", project=self.work)); j = self.st.join(self.pid, inv["id"], inv["secret"], name="Vi")
        self.vi, self.vtok = j["member"]["id"], j["token"]
        self.st.submit(self.pid, self.otok, {"id": "m1", "type": "msg", "chat": "main", "payload": {"text": "hello"}})

    def test_members_may_by_default_and_the_owner_can_turn_it_off(self):
        self.assertTrue(self.st.project_view(self.pid, self.vi)["allow_export"])
        self.st.export_events(self.pid, self.vi, "main")
        self.st.set_allow_export(self.pid, self.owner, False)
        with self.assertRaises(S.CollabError) as cm: self.st.export_events(self.pid, self.vi, "main")
        self.assertEqual(cm.exception.code, "forbidden")
        self.assertTrue(self.st.export_events(self.pid, self.owner, "main"), "the owner can always save a copy")
        self.st.set_allow_export(self.pid, self.owner, True); self.st.export_events(self.pid, self.vi, "main")

    def test_only_a_moderator_changes_it_and_only_for_chats_you_can_read(self):
        with self.assertRaises(S.CollabError): self.st.set_allow_export(self.pid, self.vi, False)
        m_inv = self.st.create_invite(self.pid, self.owner, grant=P.template("editor", project=self.work)); j = self.st.join(self.pid, m_inv["id"], m_inv["secret"], name="Ed")
        self.st.create_chat(self.pid, j["member"]["id"], "mine", visibility={"mode": "members", "members": [j["member"]["id"]]})
        with self.assertRaises(S.CollabError) as cm: self.st.export_events(self.pid, self.vi, "mine")
        self.assertIn(cm.exception.code, ("forbidden", "not_found"))
        with self.assertRaises(S.CollabError): self.st.export_events(self.pid, self.owner, "mine")      # not even the owner: it is private to its members
        with self.assertRaises(S.CollabError): self.st.export_events(self.pid, self.vi, "nope")

    def test_the_setting_is_logged_and_survives_a_restart(self):
        self.st.set_allow_export(self.pid, self.owner, False)
        self.assertEqual([e["payload"] for e in self.st.read(self.pid, self.owner) if e["type"] == "config"][-1]["allow_export"], False)
        self.assertFalse(S.Store(os.path.join(self.tmp, "collab"), policy=self.pol).project_view(self.pid, self.vi)["allow_export"])


if __name__ == "__main__":
    unittest.main()


class TestLocalImportRoute(unittest.TestCase):
    """/api/chat/import and the owner's direct copy, through the real server module with the sessions folder pointed at a temp dir."""

    @classmethod
    def setUpClass(cls):
        import importlib.machinery, importlib.util
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_loader("qqui_imp", importlib.machinery.SourceFileLoader("qqui_imp", os.path.join(root, "bin", "orbit-ui")))
        cls.ui = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.ui)

    def setUp(self):
        import qqcore as q
        self.q = q; self.tmp = os.path.realpath(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.old = q.SESSIONS; q.SESSIONS = os.path.join(self.tmp, "sessions"); os.makedirs(q.SESSIONS); self.addCleanup(setattr, q, "SESSIONS", self.old)

    def payload(self):
        return {"format": "orbit-shared-chat", "version": 1, "project": "Lab", "chat": {"id": "main", "name": "Main"}, "exported_by": "Mei",
                "messages": [{"author": "Theo", "is_model": False, "text": "question", "ts": 5.0}, {"author": "Qwen", "is_model": True, "text": "answer", "ts": 6.0}]}

    def test_a_saved_chat_becomes_a_new_local_chat_and_nothing_else_changes(self):
        existing = os.path.join(self.q.SESSIONS, "mine.json"); json.dump({"schema": 2, "title": "Mine", "messages": []}, open(existing, "w")); before = open(existing).read()
        r = self.ui._import_shared_chat(self.payload())
        self.assertEqual((r["title"], r["messages"]), ("Main (from Lab)", 2))
        msgs, title = self.q.session_load(r["sid"])
        self.assertEqual(title, "Main (from Lab)"); self.assertEqual([m["role"] for m in msgs], ["user", "user", "assistant"]); self.assertIn("Theo: question", msgs[1]["content"])
        self.assertEqual(open(existing).read(), before); self.assertEqual(sorted(os.listdir(self.q.SESSIONS)), sorted(["mine.json", r["sid"] + ".json"]))
        self.assertEqual(json.load(open(os.path.join(self.q.SESSIONS, r["sid"] + ".json")))["tags"], ["imported"])

    def test_bad_files_are_refused_and_create_nothing(self):
        for bad in (None, {}, {"format": "other"}, [], "x"):
            with self.assertRaises(ValueError): self.ui._import_shared_chat(bad)
        self.assertEqual(os.listdir(self.q.SESSIONS), [])

    def test_the_hosts_own_copy_uses_the_same_path(self):
        import collab_host as H
        pol = P.Policy(never=[], home=os.path.join(self.tmp, "home"), sensitive=lambda p: None)
        work = os.path.join(self.tmp, "work"); os.makedirs(work)
        h = H.Host(self.tmp, policy=pol); self.addCleanup(h._stop_engine)
        h.configure(port=0, enabled=True); p = h.create_project("Lab", "Me", work); pid, owner = p["project"]["id"], p["member"]["id"]
        h.store.submit_as(pid, owner, {"id": "a", "type": "msg", "chat": "main", "payload": {"text": "hello from the project"}})
        orig, self.ui.COLLAB_HOST = self.ui.COLLAB_HOST, h; self.addCleanup(setattr, self.ui, "COLLAB_HOST", orig)
        code, body = self.ui._collab_route({"op": "copy_chat", "project": pid, "chat": "main"}); r = json.loads(body)
        self.assertEqual(code, 200); msgs, _ = self.q.session_load(r["sid"]); self.assertIn("Me: hello from the project", msgs[1]["content"])
        code, body = self.ui._collab_route({"op": "project_settings", "project": pid, "allow_export": False}); self.assertEqual(code, 200)
        self.assertFalse(h.store.project_view(pid, owner)["allow_export"])
