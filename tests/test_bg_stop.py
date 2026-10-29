"""Stopping a background task, and moving a running command to the background, as the Claude
Code CLI's /tasks and Ctrl+B do. The Claude Code process is a stand-in that records what it is
sent; nothing is started."""
import importlib.machinery, importlib.util, os, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin"))

import qqcore as q                        # noqa: E402,F401  (binds claude_engine.Q)
import claude_engine as CE                # noqa: E402

SID = "bg-test-chat"


class FakeRun:
    """What RUNS holds for a chat that is answering: a way to send, and waiters for replies."""
    def __init__(self, reply):
        self.sent, self.reply = [], reply
        self.d = {"waiters": {}, "send": self.send}

    def send(self, obj):
        self.sent.append(obj)
        w = self.d["waiters"].get(obj["request_id"])
        if w is not None:
            w["response"] = self.reply; w["event"].set()
        return True


class TestStopAndBackground(unittest.TestCase):
    def setUp(self):
        CE.BG_TASKS.pop(SID, None)
        self.addCleanup(CE.BG_TASKS.pop, SID, None)
        self.addCleanup(CE.RUNS.pop, SID, None)
        CE.bg_task(SID, "b123", kind="shell", description="npx vitest run", tool_id="toolu_1", status="running")

    def answering(self, reply):
        run = FakeRun(reply)
        CE.RUNS[SID] = run.d
        return run

    def test_a_running_task_can_be_stopped_while_the_chat_answers(self):
        run = self.answering({"subtype": "success", "request_id": "x", "response": {}})
        self.assertTrue(CE.can_stop_task(SID))
        self.assertEqual(CE.stop_task(SID, "b123"), {"ok": True})
        req = run.sent[0]["request"]
        self.assertEqual((req["subtype"], req["task_id"]), ("stop_task", "b123"))
        self.assertEqual(CE.bg_tasks(SID)[0]["status"], "stopped")

    def test_the_call_that_started_it_names_it_too(self):
        self.answering({"subtype": "success", "request_id": "x", "response": {}})
        self.assertEqual(CE.stop_task(SID, "toolu_1"), {"ok": True})

    def test_a_refusal_comes_back_and_the_task_stays_as_it_was(self):
        self.answering({"subtype": "error", "request_id": "x", "error": "already finished"})
        self.assertIn("already finished", CE.stop_task(SID, "b123")["error"])
        self.assertEqual(CE.bg_tasks(SID)[0]["status"], "running")

    def test_nothing_to_stop(self):
        self.assertFalse(CE.can_stop_task(SID))
        self.assertIn("error", CE.stop_task(SID, "b123"))                 # no process to ask
        self.assertIn("error", CE.stop_task(SID, "nope"))
        CE.bg_task(SID, "b123", status="completed")
        self.answering({"subtype": "success", "response": {}})
        self.assertEqual(CE.stop_task(SID, "b123"), {"error": "it has already ended"})

    def test_a_running_command_goes_to_the_background(self):
        run = self.answering({"subtype": "success", "request_id": "x", "response": {"backgrounded": True}})
        self.assertEqual(CE.to_background(SID, "toolu_9"), {"ok": True})
        req = run.sent[0]["request"]
        self.assertEqual((req["subtype"], req["tool_use_id"]), ("background_tasks", "toolu_9"))
        self.assertIn("error", CE.to_background("no-such-chat", "toolu_9"))


class TestLiveStatusFollowsTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        loader = importlib.machinery.SourceFileLoader("orbit_ui_bg_test", os.path.join(ROOT, "bin", "orbit-ui"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        cls.ui = importlib.util.module_from_spec(spec)
        loader.exec_module(cls.ui)

    def test_not_waiting_for_the_model_while_a_command_runs(self):
        st = self.ui.State(); st.temp = True
        rec = self.ui._live_record
        rec(st, "status", {"msg": "waiting for the model"})
        self.assertEqual(st.live["status"], "waiting for the model")
        rec(st, "tool", {"name": "Bash", "args": {}, "id": "t1", "t": 0})
        self.assertEqual(st.live["status"], "running Bash")
        rec(st, "tool", {"name": "Read", "args": {}, "id": "t2", "t": 0})
        rec(st, "tool_result", {"name": "Read", "id": "t2", "ok": True, "secs": 1})
        self.assertEqual(st.live["status"], "running Bash")               # another is still going
        rec(st, "tool_result", {"name": "Bash", "id": "t1", "ok": True, "secs": 2})
        self.assertEqual(st.live["status"], "waiting for the model")


if __name__ == "__main__":
    unittest.main()


class TestResumePoint(unittest.TestCase):
    """--resume-session-at must name a message on the branch the transcript ends on: another
    branch's id (left by a stopped and restarted run) fails at once with "No message found"."""
    def setUp(self):
        import tempfile
        self.f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        self.addCleanup(os.unlink, self.f.name)
        def rec(u, parent, kind="assistant"):
            self.f.write(json.dumps({"type": kind, "uuid": u, "parentUuid": parent}) + "\n")
        rec("u1", None, "user"); rec("a1", "u1"); rec("u2", "a1", "user")
        rec("a2-dead", "u2")                 # a step that ended up on a branch of its own
        rec("a2", "u2"); rec("u3", "a2", "user"); rec("a3", "u3")
        self.f.close()

    def test_the_branch_the_transcript_ends_on(self):
        chain = CE.transcript_chain(self.f.name, "a3")
        self.assertEqual(chain, {"u1", "a1", "u2", "a2", "u3", "a3"})
        self.assertNotIn("a2-dead", chain)

    def test_a_missing_file_or_tip_is_an_empty_chain(self):
        self.assertEqual(CE.transcript_chain("/no/such/file.jsonl", "a3"), set())
        self.assertEqual(CE.transcript_chain(self.f.name, None), set())


import json                                       # noqa: E402  (used by the class above)


class TestRestartWaitsForBackgroundWork(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        loader = importlib.machinery.SourceFileLoader("orbit_ui_restart_test", os.path.join(ROOT, "bin", "orbit-ui"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        cls.ui = importlib.util.module_from_spec(spec)
        loader.exec_module(cls.ui)

    def test_a_chat_with_a_background_agent_blocks_a_restart(self):
        sid = "restart-test-chat"
        CE.BG_TASKS.pop(sid, None)
        self.addCleanup(CE.BG_TASKS.pop, sid, None)
        self.assertNotIn(sid, self.ui.restart_blockers())
        CE.bg_task(sid, "agent1", kind="agent", description="docs", status="running")
        self.assertIn(sid, self.ui.restart_blockers())
        CE.bg_task(sid, "agent1", status="completed")
        self.assertNotIn(sid, self.ui.restart_blockers())


class TestKeptProcessIsNotClosedWhileWorking(unittest.TestCase):
    """A chat's Claude Code is kept for its background agents. Closing it after the idle limit,
    or right after the last agent reports (it answers that report by itself), ended the work."""
    SID = "reap-test-chat"

    class Proc:
        def __init__(self): self.closed = False
        def poll(self): return None

    def setUp(self):
        import collections
        self.proc = self.Proc()
        CE.LIVE[self.SID] = {"proc": self.proc, "sig": "x", "lines": collections.deque(), "got": [], "err_tail": [],
                             "wlock": None, "host": "box", "used": time.time() - 3600, "token": None}
        self.addCleanup(CE.LIVE.pop, self.SID, None)
        self.closed, self.whys = [], []
        self.saved = CE.close_live
        CE.close_live = lambda k, why="": (self.closed.append(k), self.whys.append(why), CE.LIVE.pop(k, None))
        self.addCleanup(setattr, CE, "close_live", self.saved)
        CE.BG_TASKS.pop(self.SID, None)
        self.addCleanup(CE.BG_TASKS.pop, self.SID, None)

    def test_idle_for_an_hour_with_nothing_going_on_is_closed(self):
        CE.reap_live(max_idle_min=30)
        self.assertEqual(self.closed, [self.SID])
        self.assertIn("idle for more than 30 minutes", self.whys[0])           # and it says why

    def test_idle_for_an_hour_with_an_agent_still_running_is_kept(self):
        CE.bg_task(self.SID, "agent1", kind="agent", description="ux", status="running")
        CE.reap_live(max_idle_min=30)
        self.assertEqual(self.closed, [])

    def test_a_process_answering_an_agents_report_is_kept(self):
        CE.LIVE[self.SID]["lines"].append(json.dumps({"type": "assistant", "message": {"content": []}}))
        CE.reap_live(max_idle_min=30)
        self.assertEqual(self.closed, [])
        CE.LIVE[self.SID]["lines"].append(json.dumps({"type": "result", "subtype": "success"}))
        CE.reap_live(max_idle_min=30)
        self.assertEqual(self.closed, [self.SID])           # that turn is over: nothing left to wait for

    def test_a_chat_is_kept_for_the_answer_to_a_shell_that_just_finished(self):
        """The report of a finished background shell wakes Claude Code up; its answer begins a moment later.
        Closing the chat in that moment left it silent -- 'I'll check once the build finishes', then nothing."""
        CE.LIVE[self.SID]["host"] = None                          # a chat on this Mac
        CE.bg_task(self.SID, "t1", kind="shell", description="wait for the build", status="running")
        CE.LIVE[self.SID]["lines"].append(json.dumps({"type": "system", "subtype": "task_notification",
                                                      "task_id": "t1", "status": "completed"}))
        CE.reap_live(max_idle_min=30)
        self.assertFalse(CE.bg_running(self.SID))
        self.assertEqual(self.closed, [], "closed before Claude Code could answer the report")
        CE.LIVE[self.SID]["active_at"] -= 120                      # no answer ever started
        CE.reap_live(max_idle_min=30)
        self.assertEqual(self.closed, [self.SID])


import time                                       # noqa: E402


class TestEveryCloseLeavesARecord(unittest.TestCase):
    def test_a_close_is_logged_with_its_reason_and_the_work_it_cut_off(self):
        import tempfile, collections
        sid = "log-test-chat"
        tmp = tempfile.mkdtemp()
        saved_logs, saved_notify = CE.Q.LOGS, CE.Q.notify
        CE.Q.LOGS = tmp
        said = []
        CE.Q.notify = lambda *a, **k: said.append(a)
        class P:
            stdin = type("S", (), {"close": lambda self: None})()
            def poll(self): return None
            def wait(self, timeout=None): return 0
        CE.LIVE[sid] = {"proc": P(), "sig": "x", "lines": collections.deque(), "got": [], "err_tail": [],
                        "wlock": None, "host": None, "used": time.time(), "token": None}
        CE.bg_task(sid, "agent1", kind="agent", description="ux", status="running")
        try:
            CE.close_live(sid, "the chat was rewound to an earlier message")
            row = json.loads(open(os.path.join(tmp, "live.log")).read().splitlines()[-1])
            self.assertEqual((row["chat"], row["event"], row["background_running"]), (sid, "closed", 1))
            self.assertIn("rewound", row["why"])
            self.assertTrue(said, "the cut-off work is announced")
        finally:
            CE.Q.LOGS, CE.Q.notify = saved_logs, saved_notify
            CE.LIVE.pop(sid, None); CE.BG_TASKS.pop(sid, None)


class TestDesktopSshSessions(unittest.TestCase):
    """A chat the Claude desktop app ran on a server runs there in Orbit too, not on this Mac."""
    def setUp(self):
        import tempfile
        self.home = tempfile.mkdtemp()
        base = os.path.join(self.home, "Library", "Application Support", "Claude", "claude-code-sessions", "a", "b")
        os.makedirs(base)
        json.dump({"cliSessionId": "sess-ssh", "cwd": "/path/to/project/lab/work/sub", "originCwd": "/path/to/project/lab/work",
                   "sshConfig": {"name": "hpc", "sshHost": "hpc"},
                   "sshRemoteTranscriptPath": "/u/home/x/.claude/projects/-u-project-lab-work/sess-ssh.jsonl"},
                  open(os.path.join(base, "local_1.json"), "w"))
        json.dump({"cliSessionId": "sess-local", "cwd": "/Users/me/proj"}, open(os.path.join(base, "local_2.json"), "w"))
        self.saved_home = os.environ.get("HOME")
        os.environ["HOME"] = self.home
        CE._DESKTOP_SSH.update(at=0.0, by={})
        self.addCleanup(lambda: (os.environ.__setitem__("HOME", self.saved_home), CE._DESKTOP_SSH.update(at=0.0, by={})))

    def test_an_ssh_session_names_its_server_and_the_folder_it_began_in(self):
        got = CE.desktop_ssh_session("sess-ssh")
        self.assertEqual((got["host"], got["cwd"]), ("hpc", "/path/to/project/lab/work"))   # origin: where its transcript lives
        self.assertTrue(got["transcript"].endswith("sess-ssh.jsonl"))

    def test_a_local_or_unknown_session_is_not_one(self):
        self.assertIsNone(CE.desktop_ssh_session("sess-local"))
        self.assertIsNone(CE.desktop_ssh_session("nope"))
        self.assertIsNone(CE.desktop_ssh_session(None))


class TestDesktopOnlyToolsNote(unittest.TestCase):
    def test_every_orbit_run_is_told_sendUserFile_does_not_exist_here(self):
        text = CE._orbit_append(None, dict(CE.DEFAULTS), False)
        self.assertIn("SendUserFile", text)
        self.assertIn("full path", text)


class TestCliSpecials(unittest.TestCase):
    """Things the CLI prints or sends that are not the person's words or the model's: shown as what
    they are, in an imported chat and in a live one."""
    def convert(self, rows):
        import tempfile
        f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        f.write("\n".join(json.dumps(r) for r in rows)); f.close()
        self.addCleanup(os.unlink, f.name)
        return CE.convert(f.name)[0]

    def user(self, content, **k): return {"type": "user", "message": {"role": "user", "content": content}, **k}

    def test_an_agent_reporting_back_is_a_line_not_something_the_person_said(self):
        m = self.convert([self.user("<task-notification>\n<status>completed</status>\n<summary>Agent \"docs\" completed</summary>\n<result>All good</result>\n</task-notification>")])
        self.assertEqual(len(m), 1)
        self.assertTrue(m[0].get("nudge"))
        self.assertIn("Agent \"docs\" completed", m[0]["content"]); self.assertIn("All good", m[0]["content"])
        self.assertNotIn("<task-notification>", m[0]["content"])

    def test_a_bang_command_comes_in_as_one_command_run(self):
        m = self.convert([self.user("<bash-input>ls -la</bash-input>"),
                          self.user("<bash-stdout>total 0</bash-stdout><bash-stderr></bash-stderr>")])
        self.assertEqual(len(m), 1)
        self.assertEqual(m[0]["bang"]["cmd"], "ls -la"); self.assertIn("total 0", m[0]["bang"]["out"])

    def test_a_slash_commands_output_is_kept(self):
        m = self.convert([self.user("<local-command-stdout>Total cost: $0.01</local-command-stdout>")])
        self.assertEqual([x["content"] for x in m], ["Total cost: $0.01"])

    def test_an_api_error_is_not_glued_to_the_answer_before_it(self):
        a = {"type": "assistant", "message": {"id": "m1", "model": "x", "content": [{"type": "text", "text": "Hello"}]}}
        e = {"type": "assistant", "isApiErrorMessage": True, "message": {"id": "m2", "model": "<synthetic>", "content": [{"type": "text", "text": "API Error: 529"}]}}
        m = self.convert([a, e])
        self.assertEqual(m[0]["content"], "Hello")
        self.assertIn("API Error: 529", m[1]["content"]); self.assertTrue(m[1].get("nudge"))

    def test_the_systems_own_failure_lines_are_shown(self):
        m = self.convert([{"type": "system", "subtype": "api_error", "content": "Request failed"},
                          {"type": "system", "subtype": "stop_hook_summary"}])
        self.assertEqual(len(m), 1); self.assertIn("Request failed", m[0]["content"])

    def test_a_run_that_stops_for_its_own_reasons_says_so_in_words(self):
        self.assertIn("continue", CE._RESULT_ERRORS["error_max_turns"])

    def test_an_mcp_server_asking_for_input_is_put_to_the_person(self):
        asked = []
        def ask(text, opts, multi): asked.append((text, opts)); return {"Pick one": "B"}.get(text.split("\n")[-1].split(" — ")[0], "x")
        r = {"subtype": "elicitation", "mcp_server_name": "lab", "message": "Choose",
             "requested_schema": {"properties": {"Pick one": {"type": "string", "enum": ["A", "B"]},
                                                 "confirm": {"type": "boolean"}}}}
        out = CE._answer_elicitation(r, {"ask": ask})
        self.assertEqual(out["action"], "accept"); self.assertEqual(out["content"]["Pick one"], "B")
        self.assertIn("confirm", out["content"])
        self.assertEqual(CE._answer_elicitation(r, {"ask": lambda *a: None}), {"action": "decline"})   # nobody there
        self.assertEqual(CE._answer_elicitation(r, {}), {"action": "decline"})


class TestCatchingTheServersSessionUp(unittest.TestCase):
    """The server's copy of a session gets only what this Mac added -- appended, never replaced --
    and only when its file is exactly the start of this Mac's and nothing is writing to it."""
    def setUp(self):
        import hashlib, tempfile, ssh_remote
        self.S, self.hl = ssh_remote, hashlib
        self.f = tempfile.NamedTemporaryFile("wb", suffix=".jsonl", delete=False)
        self.f.write(b'{"a":1}\n{"b":2}\n{"c":3}\n'); self.f.close()
        self.addCleanup(os.unlink, self.f.name)
        self.saved = (ssh_remote.run, ssh_remote.subprocess.run)
        self.sent = []
        def fake_sub(argv, input=None, **k):
            self.sent.append(input)
            return type("R", (), {"stdout": b"OK", "stderr": b"", "returncode": 0})()
        ssh_remote.subprocess.run = fake_sub
        self.addCleanup(lambda: (setattr(ssh_remote, "run", self.saved[0]), setattr(ssh_remote.subprocess, "run", self.saved[1])))

    def remote(self, prefix, age=600):
        sha = self.hl.sha256(prefix).hexdigest()
        self.S.run = lambda host, script, timeout=60, **k: (0, f"SIZE={len(prefix)}\nAGE={age}\nSHA={sha}\n", "")

    def test_the_difference_is_appended(self):
        self.remote(b'{"a":1}\n')
        status, n = self.S.append_transcript_delta("box", "/r/x.jsonl", self.f.name)
        self.assertEqual((status, n), ("added", len(b'{"b":2}\n{"c":3}\n')))
        import base64
        self.assertEqual(base64.b64decode(self.sent[0]), b'{"b":2}\n{"c":3}\n')

    def test_a_copy_that_is_not_the_start_of_ours_is_left_alone(self):
        self.remote(b'{"zzz":9}\n')
        self.assertEqual(self.S.append_transcript_delta("box", "/r/x.jsonl", self.f.name), ("differs", 0))
        self.assertEqual(self.sent, [])

    def test_a_session_being_written_is_left_alone(self):
        self.remote(b'{"a":1}\n', age=5)
        self.assertEqual(self.S.append_transcript_delta("box", "/r/x.jsonl", self.f.name), ("busy", 0))
        self.assertEqual(self.sent, [])

    def test_equal_copies_need_nothing(self):
        self.remote(b'{"a":1}\n{"b":2}\n{"c":3}\n')
        self.assertEqual(self.S.append_transcript_delta("box", "/r/x.jsonl", self.f.name), ("same", 0))


class TestToolProgressAndSuggestions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        loader = importlib.machinery.SourceFileLoader("orbit_ui_prog_test", os.path.join(ROOT, "bin", "orbit-ui"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        cls.ui = importlib.util.module_from_spec(spec)
        loader.exec_module(cls.ui)

    def test_a_tools_elapsed_time_reaches_the_live_status(self):
        st = self.ui.State(); st.temp = True
        self.ui._live_record(st, "tool", {"name": "Bash", "args": {}, "id": "t1", "t": 0})
        self.ui._live_record(st, "tool_progress", {"id": "t1", "name": "Bash", "elapsed": 7})
        self.assertEqual(st.live["status"], "running Bash · 7s")
        self.assertEqual(st.live["tools"][-1]["elapsed"], 7)
        self.ui._live_record(st, "tool_progress", {"id": "t1", "name": "Bash", "elapsed": 135})
        self.assertEqual(st.live["status"], "running Bash · 2m 15s")

    def test_suggestions_are_off_until_asked_for(self):
        self.assertNotIn("--prompt-suggestions", CE.build_argv(dict(CE.DEFAULTS), kind="subscription"))
        on = CE.build_argv({**CE.DEFAULTS, "prompt_suggestions": True}, kind="subscription")
        self.assertIn("--prompt-suggestions", on)
        local = CE.build_argv({**CE.DEFAULTS, "prompt_suggestions": True}, kind="local")
        self.assertNotIn("--prompt-suggestions", local)             # a local model pays for every extra call


class TestDesktopHoldsTheSession(unittest.TestCase):
    SID = "39c25cfa-2b46-480d-91e1-439250181cc4"
    APP = "/Users/me/Library/Application Support/Claude/claude-code/2.1.308/abc/claude.app/Contents/MacOS/claude"
    PS = "\n".join([
        f"  3564 {APP} --output-format stream-json --resume={SID} --allowedTools x",
        f"  3563 /Applications/Claude.app/Contents/Helpers/disclaimer --pgroup -- {APP} --resume={SID}",
        f"  9001 /Users/me/.local/bin/claude --print --resume {SID}",
        f"  9002 {APP} --resume=aaaaaaaa-0000-0000-0000-000000000000"])

    def test_only_the_desktop_apps_own_process_for_that_session_counts(self):
        self.assertEqual(CE._holders_in(self.PS, self.SID), [3564, 3563])     # not Orbit's (9001), not another session's (9002)
        self.assertEqual(CE._holders_in(self.PS, "nope"), [])


class TestToolSummaries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        loader = importlib.machinery.SourceFileLoader("orbit_ui_sum_test", os.path.join(ROOT, "bin", "orbit-ui"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        cls.ui = importlib.util.module_from_spec(spec)
        loader.exec_module(cls.ui)

    def test_a_saved_steps_summary_reaches_the_page(self):
        msgs = [{"role": "user", "content": "count", "t": 1},
                {"role": "assistant", "content": "", "t": 2, "tool_calls": [{"id": "t1", "type": "function",
                    "function": {"name": "Bash", "arguments": "{}"}}],
                 "tool_summaries": [{"ids": ["t1"], "text": "Counted 12985 jsonl files"}]},
                {"role": "tool", "tool_call_id": "t1", "name": "Bash", "content": "12985", "ok": True}]
        out = self.ui.render(msgs)
        step = next(m for m in out if m["role"] == "assistant")
        self.assertEqual(step["tool_summaries"], [{"ids": ["t1"], "text": "Counted 12985 jsonl files"}])

    def test_the_switch_is_on_for_hosted_models_and_not_for_local_ones(self):
        self.assertTrue(CE.DEFAULTS["tool_summaries"])
        src = open(os.path.join(ROOT, "bin", "claude_engine.py")).read()
        self.assertIn('env["CLAUDE_CODE_EMIT_TOOL_USE_SUMMARIES"] = "1"', src)
        self.assertIn('c.get("tool_summaries") and kind != "local"', src)


class TestHandoffNote(unittest.TestCase):
    def msgs(self, host=None):
        mk = {"session": "11111111-2222-3333-4444-555555555555", "cwd": "/work/proj", "skills": []}
        if host: mk.update(host=host, remote_ready=True)
        return [{"role": "system", "content": "sys"},
                {"role": "user", "content": "Remember PINEAPPLE", "claude": mk, "t": 1},
                {"role": "assistant", "content": "noted", "t": 2, "changes": [{"path": "/work/proj/a.py"}]},
                {"role": "user", "content": "<nudge>", "nudge": True},
                {"role": "user", "content": "Also MANGO", "claude": mk, "t": 3},
                {"role": "assistant", "content": "PINEAPPLE and MANGO", "t": 4}]

    def test_the_note_says_where_the_session_is_and_what_just_happened(self):
        h = CE.handoff_text("cq-x", "Fruit test", self.msgs())
        t = h["text"]
        self.assertIn("11111111-2222-3333-4444-555555555555", t); self.assertIn("/work/proj", t)
        self.assertIn("**You:** Remember PINEAPPLE", t); self.assertIn("**Claude:** PINEAPPLE and MANGO", t)
        self.assertIn("/work/proj/a.py", t)
        self.assertNotIn("<nudge>", t)                      # Orbit's own prompts are not part of the story
        self.assertIn("claude --resume", h["resume"] + "claude --resume") 

    def test_a_chat_on_a_server_names_the_server_copy(self):
        h = CE.handoff_text("cq-x", "On the cluster", self.msgs(host="hpc"))
        self.assertIn("hpc", h["text"]); self.assertEqual(h["host"], "hpc")
        self.assertIn(".claude/projects/", h["transcript"])

    def test_a_chat_without_a_session_has_nothing_to_hand_off(self):
        self.assertIsNone(CE.handoff_text("x", "t", [{"role": "user", "content": "hi"}]))
        self.assertIn("HANDOFF.md", CE.HANDOFF_PROMPT)


class TestReleasingTheDesktopsCopy(unittest.TestCase):
    def test_nothing_held_means_nothing_to_do(self):
        saved = CE.desktop_holders
        CE.desktop_holders = lambda s: []
        self.addCleanup(setattr, CE, "desktop_holders", saved)
        r = CE.release_from_desktop("sess")
        self.assertTrue(r["ok"]); self.assertIn("not holding", r["msg"])

    def test_it_will_not_end_a_copy_that_is_working(self):
        import tempfile
        f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False); f.write("{}\n"); f.close()
        self.addCleanup(os.unlink, f.name)
        saved = (CE.desktop_holders, CE.jsonl_path, os.kill)
        killed = []
        CE.desktop_holders = lambda s: [4242]
        CE.jsonl_path = lambda s, c=None: f.name                     # written just now: it is working
        os.kill = lambda pid, sig: killed.append(pid)
        self.addCleanup(lambda: (setattr(CE, "desktop_holders", saved[0]), setattr(CE, "jsonl_path", saved[1]), setattr(os, "kill", saved[2])))
        self.assertFalse(CE.release_from_desktop("sess")["ok"]); self.assertEqual(killed, [])
        os.utime(f.name, (time.time() - 300, time.time() - 300))     # quiet for five minutes
        r = CE.release_from_desktop("sess")
        self.assertTrue(r["ok"]); self.assertEqual(killed, [4242])


class TestTurnsByOtherModels(unittest.TestCase):
    """A chat moved between engines: Claude's own session lacks what another model said in between."""
    def test_what_another_model_said_is_handed_back_to_claude(self):
        msgs = [{"role": "system", "content": "s"},
                {"role": "user", "content": "Remember PINEAPPLE"},
                {"role": "assistant", "content": "noted", "claude_uuid": "u1", "model": "Claude Code · Haiku"},
                {"role": "user", "content": "Also MANGO"},
                {"role": "assistant", "content": "PINEAPPLE MANGO", "model": "Antigravity · Gemini 3.8 Flash (Low) · CLI"}]
        got = CE._missed_turns(msgs)
        self.assertIn("User: Also MANGO", got)
        self.assertIn("Antigravity · Gemini 3.8 Flash (Low): PINEAPPLE MANGO", got)
        self.assertNotIn("Remember PINEAPPLE", got)          # Claude's own session already has that

    def test_nothing_missed_when_claude_answered_last(self):
        msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello", "claude_uuid": "u1"}]
        self.assertEqual(CE._missed_turns(msgs), "")
        self.assertEqual(CE._missed_turns([]), "")
