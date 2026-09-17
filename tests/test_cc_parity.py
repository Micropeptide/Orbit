"""Claude Code-style features on the server (bin/orbit-ui): rewinding a chat (and its
files), running a shell command yourself ("!"), and the context breakdown behind
/context. Temporary chats and temporary files only; no model is called."""
import importlib.machinery, importlib.util, json, os, shutil, sys, tempfile, time, types, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "bin"))


def load_ui():
    loader = importlib.machinery.SourceFileLoader("orbit_ui_cc_parity", os.path.join(ROOT, "bin", "orbit-ui"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class TestParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = load_ui()
        cls.q = cls.ui.q

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orbit-cc-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = self.q._save_checkpoint
        self.q._save_checkpoint = lambda *a, **k: None       # no snapshots into the real store
        self.addCleanup(setattr, self.q, "_save_checkpoint", saved)

    def chat(self, msgs=None):
        st = self.ui.State()
        st.temp = True                     # never written to disk
        st.msgs = list(msgs or [])
        self.ui.STATES[st.sid] = st
        self.addCleanup(self.ui.STATES.pop, st.sid, None)
        return st

    def call(self, method, path, body=None):
        out = types.SimpleNamespace(code=None, body=None)
        ui = self.ui

        class Fake(ui.H):
            def __init__(self): self.path = path
            def _body(self): return body or {}
            def _send(self, code, b, ctype="application/json"):
                out.code, out.body = code, json.loads(b) if isinstance(b, (str, bytes)) else b
        getattr(Fake(), "_" + method)(path)
        return out.code, out.body

    # -- rewind -----------------------------------------------------------------
    def test_rewind_cuts_the_chat_before_the_chosen_message(self):
        st = self.chat([{"role": "system", "content": "sys"},
                        {"role": "user", "content": "one"}, {"role": "assistant", "content": "a1"},
                        {"role": "user", "content": "two"}, {"role": "assistant", "content": "a2"},
                        {"role": "user", "content": "three"}, {"role": "assistant", "content": "a3"}])
        code, d = self.call("post", "/api/rewind", {"sid": st.sid, "index": 1})
        self.assertEqual(code, 200, d)
        self.assertEqual([m["content"] for m in st.msgs], ["sys", "one", "a1"])
        self.assertEqual(d["dropped"], 4)

    def test_rewind_can_put_the_files_back(self):
        path = os.path.join(self.tmp, "notes.md")
        snap = os.path.join(self.tmp, "notes.snap")
        open(path, "w").write("changed by the answer")
        open(snap, "w").write("the original")
        st = self.chat([{"role": "user", "content": "one"}, {"role": "assistant", "content": "a1"},
                        {"role": "user", "content": "edit it"},
                        {"role": "assistant", "content": "done", "changes": [{"path": path, "snap": snap}]}])
        code, d = self.call("post", "/api/rewind", {"sid": st.sid, "index": 1, "files": False})
        self.assertEqual(open(path).read(), "changed by the answer")   # chat only: files untouched
        st.msgs += [{"role": "user", "content": "edit it"},
                    {"role": "assistant", "content": "done", "changes": [{"path": path, "snap": snap}]}]
        code, d = self.call("post", "/api/rewind", {"sid": st.sid, "index": 1, "files": True})
        self.assertEqual(code, 200, d)
        self.assertEqual(open(path).read(), "the original")
        self.assertEqual(len(d["undone"]), 1)

    def test_rewind_refuses_a_chat_that_is_answering_or_a_missing_message(self):
        st = self.chat([{"role": "user", "content": "one"}])
        self.assertEqual(self.call("post", "/api/rewind", {"sid": st.sid, "index": 5})[0], 404)
        st.lock.acquire()
        try:
            self.assertEqual(self.call("post", "/api/rewind", {"sid": st.sid, "index": 0})[0], 409)
        finally:
            st.lock.release()

    # -- ! shell mode -----------------------------------------------------------
    def test_a_command_you_run_joins_the_conversation(self):
        st = self.chat([{"role": "user", "content": "hi"}])
        code, d = self.call("post", "/api/bang", {"sid": st.sid, "command": "echo orbit-bang-ok"})
        self.assertEqual(code, 200, d)
        self.assertTrue(d["ok"])
        self.assertEqual(d["rc"], 0)
        self.assertIn("orbit-bang-ok", d["output"])
        last = st.msgs[-1]
        self.assertEqual(last["role"], "user")
        self.assertIn("orbit-bang-ok", last["content"])
        self.assertEqual(last["bang"]["cmd"], "echo orbit-bang-ok")
        # the flag is Orbit's own and never goes to a model
        self.assertIn("bang", self.q.PRIVATE_KEYS)

    def test_a_dangerous_command_is_refused_or_asked_about(self):
        st = self.chat()
        code, d = self.call("post", "/api/bang", {"sid": st.sid, "command": "rm -rf /"})
        self.assertTrue(code == 403 or (d and d.get("confirm")), (code, d))
        self.assertEqual(st.msgs, [])

    def test_shell_mode_waits_for_a_running_answer(self):
        st = self.chat()
        st.lock.acquire()
        try:
            self.assertEqual(self.call("post", "/api/bang", {"sid": st.sid, "command": "echo x"})[0], 409)
        finally:
            st.lock.release()

    # -- /context -----------------------------------------------------------------
    def test_context_breakdown_adds_up(self):
        msgs = [{"role": "system", "content": "you are helpful " * 50},
                {"role": "user", "content": "question " * 40},
                {"role": "assistant", "content": "answer " * 80, "reasoning_content": "hmm " * 100},
                {"role": "tool", "content": "output " * 200, "tool_call_id": "x"}]
        d = self.q.context_breakdown(msgs)
        for k in ("system prompt", "your messages", "answers", "tool results", "thinking"):
            self.assertIn(k, d["parts"])
            self.assertGreater(d["parts"][k], 0)
        self.assertEqual(d["messages"], 3)
        self.assertEqual(d["free"], max(0, d["max"] - d["used"]))

    def test_context_and_status_follow_the_chat_asked_about(self):
        st = self.chat([{"role": "user", "content": "word " * 3000}])
        code, d = self.call("get", f"/api/context?sid={st.sid}&full=1")
        self.assertEqual(code, 200)
        self.assertGreater(d["parts"]["your messages"], 2000)
        code, d2 = self.call("get", f"/api/status?sid={st.sid}")
        self.assertEqual(code, 200)
        self.assertEqual(d2["context"]["used"], d["used"])

    # -- /tasks -------------------------------------------------------------------
    def test_tasks_lists_answers_queues_and_background_shells(self):
        import subprocess as sp
        st = self.chat([{"role": "user", "content": "hi"}])
        st.title = "busy chat"
        st.queue.append({"id": "qq1", "text": "later please", "attachments": []})
        proc = sp.Popen(["sleep", "30"])
        self.q.BG_JOBS["bgtest"] = {"id": "bgtest", "proc": proc, "command": "sleep 30", "started": time.time(),
                                    "out_path": os.path.join(self.tmp, "o.log")}
        def done():
            self.q.BG_JOBS.pop("bgtest", None)
            if proc.poll() is None: proc.kill()
        self.addCleanup(done)
        st.lock.acquire()
        try:
            code, d = self.call("get", "/api/tasks")
        finally:
            st.lock.release()
        self.assertEqual(code, 200)
        kinds = {(x["kind"], x["id"]) for x in d["items"]}
        self.assertIn(("answer", st.sid), kinds)
        self.assertIn(("queued", "qq1"), kinds)
        self.assertIn(("shell", "bgtest"), kinds)
        code, r = self.call("post", "/api/tasks/stop", {"kind": "shell", "id": "bgtest"})
        self.assertEqual(code, 200)
        proc.wait(timeout=5)
        self.assertIsNotNone(proc.poll())


if __name__ == "__main__":
    unittest.main()
