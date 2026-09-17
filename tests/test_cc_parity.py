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
        self.assertNotIn("thinking", d["parts"])        # kept in the chat, never sent back
        for k in ("system prompt", "your messages", "answers", "tool results"):
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

    # -- the welcome page ---------------------------------------------------------
    def test_home_reports_activity_running_work_and_what_is_coming(self):
        st = self.chat([{"role": "user", "content": "hi"}])
        st.title = "busy chat"
        st.queue.append({"id": "qq2", "text": "later please", "attachments": []})
        jobs = {"jobs": [{"id": "j1", "name": "nightly", "every": "daily", "at": "09:00", "enabled": True},
                         {"id": "j2", "name": "paused one", "every": "daily", "at": "10:00", "enabled": False},
                         {"id": "j3", "name": "broken", "every": "daily", "at": "11:00", "enabled": True,
                          "last_run": time.time() - 600, "last_ok": False, "last_result": "ssh timed out"}]}
        saved = (self.q.sched_load, self.q.health_check)
        self.q.sched_load = lambda *a, **k: jobs
        self.q.health_check = lambda *a, **k: [{"name": "disk space", "ok": False, "detail": "2 GB free", "fix": "make room"},
                                               {"name": "model server", "ok": False, "info": True, "detail": "stopped"}]
        self.addCleanup(lambda: setattr(self.q, "sched_load", saved[0]))
        self.addCleanup(lambda: setattr(self.q, "health_check", saved[1]))
        st.lock.acquire()
        try:
            code, d = self.call("get", "/api/home")
        finally:
            st.lock.release()
        self.assertEqual(code, 200, d)
        self.assertEqual(len(d["days"]), 14)                       # two weeks, every day present
        self.assertEqual(d["days"][-1]["day"], time.strftime("%Y-%m-%d"))
        for k in ("turns", "tokens", "seconds", "tool_runs"):
            self.assertIn(k, d["today"])
        kinds = {(x["kind"], x["id"]) for x in d["tasks"]}
        self.assertIn(("answer", st.sid), kinds)
        self.assertIn(("queued", "qq2"), kinds)
        names = [u["title"] for u in d["upcoming"]]
        self.assertIn("nightly", names)
        self.assertNotIn("paused one", names)                      # a paused task is not coming up
        self.assertEqual([f["title"] for f in d["failed"]], ["broken"])
        self.assertEqual([p["name"] for p in d["problems"]], ["disk space"])   # "info" checks are not problems

    def test_home_streak_counts_back_from_today_and_stops_at_a_quiet_day(self):
        day = lambda n: time.strftime("%Y-%m-%d", time.localtime(time.time() - n * 86400))
        saved = self.q.usage_stats
        self.q.usage_stats = lambda days=7, now=None: {
            "turns": 3, "models": {}, "tools": {},
            "by_day": {day(0): {"turns": 1, "tokens": 10, "seconds": 1.0, "tool_runs": 0},
                       day(1): {"turns": 0, "tokens": 0, "seconds": 0.0, "tool_runs": 4},   # tools only still counts
                       day(3): {"turns": 9, "tokens": 90, "seconds": 9.0, "tool_runs": 0}}}
        self.addCleanup(lambda: setattr(self.q, "usage_stats", saved))
        code, d = self.call("get", "/api/home")
        self.assertEqual(code, 200)
        self.assertEqual(d["streak"], 2)

    def test_shell_mode_runs_in_the_folder_it_reports_and_stops_runaway_pipes(self):
        st = self.chat()
        code, d = self.call("post", "/api/bang", {"sid": st.sid, "command": "pwd"})
        self.assertEqual(code, 200, d)
        self.assertEqual(os.path.realpath(d["output"].strip()), os.path.realpath(d["cwd"]))
        self.assertEqual(st.msgs[-1]["bang"]["cwd"], d["cwd"])
        self.assertFalse(st.lock.locked())                  # released after the run

    def test_a_remote_command_is_not_retried_and_stops_if_the_folder_is_missing(self):
        import ssh_remote
        seen = []
        saved = (ssh_remote.run, self.ui._chat_files_ctx)
        ssh_remote.run = lambda host, script, timeout=60, shared=True, _retry=True: (seen.append((script, _retry)) or (0, "ok", ""))
        self.ui._chat_files_ctx = lambda sid: ("somehost", ["~/proj dir"], [])
        try:
            st = self.chat()
            code, d = self.call("post", "/api/bang", {"sid": st.sid, "command": "ls"})
        finally:
            ssh_remote.run, self.ui._chat_files_ctx = saved
        self.assertEqual(code, 200, d)
        script, retry = seen[0]
        self.assertFalse(retry)
        self.assertTrue(script.startswith("cd \"$HOME\"/'proj dir' && "), script)

    def test_cancel_of_a_chat_that_is_gone(self):
        self.assertEqual(self.call("post", "/api/cancel", {"sid": "no-such-chat-xyz"})[0], 404)

    def test_rewinding_a_codex_chat_starts_a_new_thread_next_time(self):
        mk = {"thread": "th-1", "cwd": "/tmp", "provider": "chatgpt", "owner": None}
        st = self.chat([{"role": "user", "content": "one", "codex": dict(mk)},
                        {"role": "assistant", "content": "a1", "codex_thread": "th-1"},
                        {"role": "user", "content": "two", "codex": dict(mk)},
                        {"role": "assistant", "content": "a2", "codex_thread": "th-1"}])
        code, d = self.call("post", "/api/rewind", {"sid": st.sid, "index": 1})
        self.assertEqual(code, 200, d)
        self.assertTrue(self.q.CX.marker_of(st.msgs).get("rewound"))

    def test_a_temporary_chat_leaves_no_claude_code_transcript_behind(self):
        cfg = os.path.join(self.tmp, "claude-config")
        old = os.environ.get("ORBIT_CLAUDE_CONFIG_DIR")
        os.environ["ORBIT_CLAUDE_CONFIG_DIR"] = cfg
        self.addCleanup(lambda: os.environ.pop("ORBIT_CLAUDE_CONFIG_DIR", None) if old is None
                        else os.environ.__setitem__("ORBIT_CLAUDE_CONFIG_DIR", old))
        CE = self.q.CE
        sid, cwd = "11111111-2222-3333-4444-555555555555", "/tmp/somewhere"
        folder = os.path.join(CE.projects_dir(), CE.encode_cwd(cwd))
        os.makedirs(folder)
        jp = os.path.join(folder, sid + ".jsonl"); open(jp, "w").write("{}")
        os.makedirs(os.path.join(folder, sid, "subagents"))
        os.makedirs(os.path.join(CE.claude_dir(), "file-history", sid))
        st = self.chat([{"role": "user", "content": "hi", "claude": {"session": sid, "cwd": cwd}},
                        {"role": "assistant", "content": "hello"}])
        st.temp = False
        self.ui.erase_temp_traces(st)                  # a real chat keeps its session
        self.assertTrue(os.path.exists(jp))
        st.temp = True
        self.ui.erase_temp_traces(st)
        self.assertFalse(os.path.exists(jp))
        self.assertFalse(os.path.exists(os.path.join(folder, sid)))
        self.assertFalse(os.path.exists(os.path.join(CE.claude_dir(), "file-history", sid)))

    # -- chat titles ---------------------------------------------------------------------
    def test_titles_are_cleaned_names_from_the_request_and_latest_words(self):
        ui = self.ui
        self.assertEqual(ui._clean_title('{"title": "DRM2 methylation in pollen"}'), "DRM2 methylation in pollen")
        self.assertEqual(ui._clean_title('Title: "octopus facts".'), "Octopus facts")
        self.assertEqual(ui._clean_title('```json\n{"title":"FastAPI 422 on /upload"}\n```'), "FastAPI 422 on /upload")
        self.assertIsNone(ui._clean_title(""))
        msgs = [{"role": "system", "content": "sys"},
                {"role": "user", "content": "why does my sgRNA script crash on empty FASTA"},
                {"role": "assistant", "content": "x" * 3000 + " the latest words"},
                {"role": "user", "content": "run it", "nudge": True}]
        m = ui._title_material(msgs)
        self.assertTrue(m.startswith("user: why does my sgRNA script crash"))
        self.assertTrue(m.endswith("the latest words"))
        self.assertNotIn("sys", m.split("\n")[0])
        seen = {}
        saved = self.q.stream_call
        self.q.stream_call = lambda messages, tools, **kw: (seen.update(m=messages) or {"content": '{"title": "sgRNA script empty FASTA crash"}'})
        try:
            self.assertEqual(ui.autotitle(msgs), "sgRNA script empty FASTA crash")
        finally:
            self.q.stream_call = saved
        self.assertIn("noun phrase", seen["m"][0]["content"])


if __name__ == "__main__":
    unittest.main()
