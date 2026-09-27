"""Ways a chat, a setting or a file was lost or changed without anyone asking.

Found by reading OpenChamber's session and file handling against Orbit's. Every test
here runs against a temporary sessions folder and workspace: nothing touches real chats.
"""
import importlib.machinery, importlib.util, json, os, shutil, sys, tempfile, threading, types, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "bin"))


def load_ui():
    loader = importlib.machinery.SourceFileLoader("orbit_ui_data_loss", os.path.join(ROOT, "bin", "orbit-ui"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = load_ui()
        cls.q = cls.ui.q

    def setUp(self):
        q = self.q
        self.tmp = tempfile.mkdtemp(prefix="orbit-dataloss-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        # the bin too, all of it: the index lives under TRASH, and the first version of
        # these tests redirected only one of its folders -- so binning a test chat wrote
        # a record, and the file, into the real bin
        saved = {k: getattr(q, k) for k in ("SESSIONS", "WORKSPACE", "UPLOADS",
                                             "TRASH", "TRASH_SESS", "TRASH_FILE")}
        self.addCleanup(lambda: [setattr(q, k, v) for k, v in saved.items()])
        q.SESSIONS = os.path.join(self.tmp, "sessions"); os.makedirs(q.SESSIONS)
        q.WORKSPACE = os.path.join(self.tmp, "workspace"); os.makedirs(q.WORKSPACE)
        q.UPLOADS = os.path.join(q.WORKSPACE, "uploads"); os.makedirs(q.UPLOADS)
        q.TRASH = os.path.join(self.tmp, "trash")
        q.TRASH_SESS = os.path.join(q.TRASH, "sessions"); os.makedirs(q.TRASH_SESS)
        q.TRASH_FILE = os.path.join(q.TRASH, "files"); os.makedirs(q.TRASH_FILE)
        q._SESS_CACHE["key"] = None

    def write_chat(self, sid, **extra):
        body = {"schema": 1, "title": "old name", "messages": [
            {"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}], **extra}
        json.dump(body, open(self.q.session_path(sid), "w"))

    def read_chat(self, sid):
        return json.load(open(self.q.session_path(sid)))

    def call(self, method, path, body=None):
        out = types.SimpleNamespace(code=None, body=None, headers={}, ctype=None)
        ui = self.ui

        class Fake(ui.H):
            def __init__(self): self.path = path; self.headers = {}
            def _body(self): return body or {}
            def _send(self, code, b, ctype="application/json", headers=None):
                out.code, out.ctype, out.headers = code, ctype, headers or {}
                try: out.body = json.loads(b)
                except Exception: out.body = b
        getattr(Fake(), "_" + method)(path)
        return out


class TestRenamingAChatKeepsEverythingElse(Base):
    def test_pin_tags_project_and_queued_messages_survive(self):
        """Rename rewrote the file from its messages alone, so it dropped all of these --
        and a message scheduled to send later was gone for good."""
        self.write_chat("c1", pinned=True, tags=["lab"], project="p1",
                        queue=[{"id": "x", "text": "send me at 9", "at": 9e9}])
        r = self.call("post", "/api/session/rename", {"id": "c1", "title": "new name"})
        self.assertEqual(r.code, 200, r.body)
        d = self.read_chat("c1")
        self.assertEqual(d["title"], "new name")
        self.assertTrue(d["pinned"]); self.assertEqual(d["tags"], ["lab"])
        self.assertEqual(d["project"], "p1")
        self.assertEqual(d["queue"][0]["text"], "send me at 9")
        self.assertIs(d["title_auto"], False)


class TestPinsAndArchives(Base):
    def test_the_write_is_whole_and_keeps_the_rest(self):
        self.write_chat("c2", tags=["x"])
        r = self.call("post", "/api/session/flag", {"id": "c2", "archived": True})
        self.assertEqual(r.code, 200, r.body)
        d = self.read_chat("c2")
        self.assertTrue(d["archived"]); self.assertEqual(d["tags"], ["x"])
        self.assertIsInstance(d.get("archived_at"), (int, float))
        self.assertFalse([f for f in os.listdir(self.q.SESSIONS) if f.endswith(".tmp")])

    def test_an_unpin_is_not_undone_by_the_next_save(self):
        """A pin set before the chat's first save sat in memory and beat the file."""
        ui = self.ui
        st = ui.State(); st.sid = "c3"; st.msgs = [{"role": "user", "content": "hi"}]
        st.flags["pinned"] = True
        ui.STATES["c3"] = st; self.addCleanup(ui.STATES.pop, "c3", None)
        ui.save_session(st)
        self.assertTrue(self.read_chat("c3")["pinned"])
        self.call("post", "/api/session/flag", {"id": "c3", "pinned": False})
        ui.save_session(st)                               # the running answer's next checkpoint
        self.assertFalse(self.read_chat("c3")["pinned"], "the unpin came back as a pin")


class TestSaveKeepsWhatItDoesNotOwn(Base):
    def test_moving_a_chat_out_of_a_project_sticks(self):
        """save_session kept five keys by name and dropped the rest, project_set among them."""
        ui = self.ui
        self.write_chat("c4", project_set=True, some_future_key={"a": 1})
        st = ui.State(); st.sid = "c4"; st.msgs = [{"role": "user", "content": "hi"}]
        ui.save_session(st)
        d = self.read_chat("c4")
        self.assertIs(d.get("project_set"), True)
        self.assertEqual(d.get("some_future_key"), {"a": 1})

    def test_but_what_it_owns_is_rewritten(self):
        ui = self.ui
        self.write_chat("c5", running_since=123.0, queue=[{"id": "gone"}])
        st = ui.State(); st.sid = "c5"; st.msgs = [{"role": "user", "content": "hi"}]
        ui.save_session(st)
        d = self.read_chat("c5")
        self.assertNotIn("running_since", d, "a stale 'running' stamp was carried over")
        self.assertNotIn("queue", d)


class TestBinningAChatThatIsAnswering(Base):
    def test_the_bin_used_is_the_tests_own(self):
        self.assertTrue(self.q.TRASH.startswith(self.tmp))

    def test_it_is_stopped_and_cannot_write_itself_back(self):
        ui = self.ui
        self.write_chat("c6")
        st = ui.State(); st.sid = "c6"; st.msgs = [{"role": "user", "content": "hi"}]
        ui.STATES["c6"] = st; self.addCleanup(ui.STATES.pop, "c6", None)
        r = self.call("post", "/api/delete", {"id": "c6"})
        self.assertEqual(r.code, 200, r.body)
        self.assertTrue(st.cancel.is_set(), "the answer was not stopped")
        ui.save_session(st)                               # what its next checkpoint would do
        self.assertFalse(os.path.exists(self.q.session_path("c6")), "the binned chat came back")


class TestNotWhileItAnswers(Base):
    def test_truncate_is_refused_mid_answer(self):
        ui = self.ui
        S = ui.S
        saved = (S.msgs, S.sid)
        self.addCleanup(lambda: (setattr(S, "msgs", saved[0]), setattr(S, "sid", saved[1])))
        S.msgs = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
        S.lock.acquire(); self.addCleanup(S.lock.release)
        r = self.call("post", "/api/truncate", {"id": S.sid, "index": 0})
        self.assertEqual(r.code, 409)
        self.assertEqual(len(S.msgs), 2, "the chat was cut under a running answer")

    def test_stop_must_name_a_chat(self):
        """With no sid it stopped whichever chat the Mac had open last."""
        cancel = self.ui.S.cancel
        cancel.clear()
        r = self.call("post", "/api/cancel", {})
        self.assertEqual(r.code, 400)
        self.assertFalse(cancel.is_set())


class TestServedFilesStayInsideAndStayInert(Base):
    def test_a_sibling_folder_is_not_the_workspace(self):
        sib = self.q.WORKSPACE + "-old"; os.makedirs(sib)
        open(os.path.join(sib, "secret.txt"), "w").write("x")
        r = self.call("get", "/api/ws/..%2F" + os.path.basename(sib) + "%2Fsecret.txt")
        self.assertEqual(r.code, 404)

    def test_a_link_out_of_the_workspace_is_not_followed(self):
        outside = os.path.join(self.tmp, "outside.txt"); open(outside, "w").write("x")
        os.symlink(outside, os.path.join(self.q.WORKSPACE, "link.txt"))
        self.assertEqual(self.call("get", "/api/ws/link.txt").code, 404)

    def test_an_svg_is_served_as_a_picture_and_nothing_more(self):
        open(os.path.join(self.q.WORKSPACE, "plot.svg"), "w").write("<svg><script>x</script></svg>")
        r = self.call("get", "/api/ws/plot.svg")
        self.assertEqual(r.code, 200)
        self.assertIn("sandbox", r.headers.get("Content-Security-Policy", ""))


class TestConfigWritesAreWhole(Base):
    def test_mcp_and_prompts_are_written_atomically_with_a_backup(self):
        q = self.q
        saved = (q.MCPCFG, q.PROMPTS, q.CONFIG_HISTORY)
        self.addCleanup(lambda: (setattr(q, "MCPCFG", saved[0]), setattr(q, "PROMPTS", saved[1]),
                                 setattr(q, "CONFIG_HISTORY", saved[2])))
        q.MCPCFG = os.path.join(self.tmp, "mcp.json"); q.PROMPTS = os.path.join(self.tmp, "p.json")
        q.CONFIG_HISTORY = os.path.join(self.tmp, "hist")
        q.mcp_save({"mcpServers": {"a": {"command": "x"}}})
        q.mcp_save({"mcpServers": {"b": {"command": "y"}}})
        self.assertEqual(json.load(open(q.MCPCFG))["mcpServers"], {"b": {"command": "y"}})
        self.assertTrue(os.listdir(q.CONFIG_HISTORY), "the previous MCP config was not kept")
        q.prompts_save({"x": {"text": "t"}})
        self.assertEqual(json.load(open(q.PROMPTS)), {"x": {"text": "t"}})
        self.assertFalse([f for f in os.listdir(self.tmp) if f.endswith(".tmp")])

    def test_deleting_a_skill_puts_it_in_the_bin(self):
        q = self.q
        saved = q.SKILLS
        self.addCleanup(setattr, q, "SKILLS", saved)
        q.SKILLS = os.path.join(self.tmp, "skills"); os.makedirs(q.SKILLS)
        q.skill_write("mine", "# a procedure I wrote by hand")
        self.assertTrue(q.skill_delete("mine"))
        kept = os.listdir(q.TRASH_FILE)
        self.assertTrue(kept, "the skill was deleted outright")
        self.assertIn("a procedure I wrote by hand", open(os.path.join(q.TRASH_FILE, kept[0])).read())


if __name__ == "__main__":
    unittest.main()
