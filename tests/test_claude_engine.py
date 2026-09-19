"""The Claude Code engine, end to end: the real `claude` binary, driven by
Orbit, talking to a scripted stand-in for the model (tests/mock_anthropic.py).
Skipped when Claude Code is not installed."""
import json, os, shutil, socket, subprocess, sys, tempfile, threading, time, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin"))
HERE = os.path.dirname(os.path.abspath(__file__))

import qqcore as q                        # noqa: E402
import claude_engine as CE                # noqa: E402

CLAUDE = CE.which_claude()


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


@unittest.skipUnless(CLAUDE, "Claude Code is not installed")
class TestClaudeEngine(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="orbit-ce-")
        cls.cfgdir = os.path.join(cls.tmp, "claude-config")
        os.makedirs(cls.cfgdir)
        os.environ["ORBIT_CLAUDE_CONFIG_DIR"] = cls.cfgdir     # nothing lands in ~/.claude
        cls.work = os.path.join(cls.tmp, "work")
        os.makedirs(cls.work)
        cls.saved = {k: getattr(q, k) for k in ("WORKSPACE", "SESSIONS")}
        q.WORKSPACE = cls.work
        q.SESSIONS = os.path.join(cls.tmp, "sessions")           # nor into your chats
        os.makedirs(q.SESSIONS)
        cls.saved_endpoint, cls.saved_wake = CE.model_endpoint, CE._wake_model
        cls.saved_settings = dict(q.S)
        CE._wake_model = lambda emit: None
        cls.saved_runlog = CE._run_log
        CE._run_log = lambda *a, **k: None                      # nor into Orbit's logs
        cls.saved_workdir = CE._work_dir
        wd = os.path.join(cls.tmp, "engine-files"); os.makedirs(wd)
        CE._work_dir = lambda: wd                               # nor into Orbit's config
        q.S["claude_qwen"] = {"mcp_servers": [], "permission_mode": ""}      # ask first: these tests check approvals
        q.S["autonomy_mode"] = "ask"

    @classmethod
    def tearDownClass(cls):
        for k, v in cls.saved.items(): setattr(q, k, v)
        CE.model_endpoint, CE._wake_model = cls.saved_endpoint, cls.saved_wake
        CE._work_dir = cls.saved_workdir
        CE._run_log = cls.saved_runlog
        q.S.clear(); q.S.update(cls.saved_settings)
        os.environ.pop("ORBIT_CLAUDE_CONFIG_DIR", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def serve(self, script):
        port = free_port()
        sp = os.path.join(self.tmp, f"script-{port}.json")
        self.log = os.path.join(self.tmp, f"log-{port}.jsonl")
        json.dump(script, open(sp, "w"))
        proc = subprocess.Popen([sys.executable, os.path.join(HERE, "mock_anthropic.py"), str(port), sp, self.log])
        self.addCleanup(proc.kill)
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close(); break
            except OSError:
                time.sleep(0.1)
        CE.model_endpoint = lambda: (f"http://127.0.0.1:{port}", "mtplx-test-model", 131072)

    def setUp(self):
        # these run on the local model (the stand-in answers for it), whatever your
        # own default model is; the harness tests below name theirs
        q.TURN_CTX.model = CE.BACKEND + ":default"

    def run_turn(self, msgs, text, approve=None, cancel=None, ask=None, read_only=False):
        events = []
        q.TURN_CTX.ask = ask
        out = CE.run_turn(msgs, text, [], emit=lambda k, p: events.append((k, p)),
                          approve=approve, cancel=cancel or threading.Event(), sid="test-ce",
                          project=None, read_only=read_only)
        return out, events

    def requests(self):
        if not os.path.exists(self.log): return []
        rows = [json.loads(l)["body"] for l in open(self.log)]
        return [r for r in rows if r.get("tools")]

    def test_a_command_you_ran_yourself_reaches_a_resumed_session(self):
        """"! command" output lives in Orbit's chat; Claude's own session never saw it.
        The next message hands it over, once."""
        self.serve([[{"text": "first answer"}], [{"text": "saw it"}], [{"text": "third"}]])
        msgs = [{"role": "system", "content": "sys"}]
        self.assertEqual(self.run_turn(msgs, "hello")[0], "first answer")
        msgs.append({"role": "user", "content": "I ran this myself:\n```bash\n$ echo zebra-output\n```\nzebra-output",
                     "bang": {"cmd": "echo zebra-output", "rc": 0, "out": "zebra-output"}})
        self.assertEqual(self.run_turn(msgs, "what did the command print?")[0], "saw it")
        self.assertIn("zebra-output", json.dumps(self.requests()[-1]["messages"]))
        self.assertIn("ran these commands themselves", json.dumps(self.requests()[-1]["messages"]))
        self.run_turn(msgs, "and now?")
        last_user = [m for m in self.requests()[-1]["messages"] if m["role"] == "user"][-1]
        self.assertNotIn("ran these commands themselves", json.dumps(last_user))

    def test_tools_approval_resume_and_history(self):
        target = os.path.join(self.work, "hello.txt")
        self.serve([
            [{"thinking": "I will write the file."}, {"text": "Writing it."},
             {"tool_use": {"name": "Write", "input": {"file_path": target, "content": "hi there\n"}}}],
            [{"text": "Done: wrote hello.txt."}],
            [{"text": "Still the same chat."}],
        ])
        asked = []
        def approve(fn, args, reason):
            asked.append((fn, args.get("path")))
            return True
        msgs = [{"role": "system", "content": "sys"}]
        out, ev = self.run_turn(msgs, "write hello.txt", approve=approve)
        kinds = [k for k, _ in ev]
        self.assertEqual(out, "Done: wrote hello.txt.")
        self.assertEqual(open(target).read(), "hi there\n")
        self.assertIn("thinking_delta", kinds)
        self.assertIn("content_delta", kinds)
        tool = next(p for k, p in ev if k == "tool")
        self.assertEqual(tool["name"], "Write")
        res = next(p for k, p in ev if k == "tool_result" and p.get("name") == "Write")
        self.assertTrue(res["ok"])
        self.assertIn("+hi there", res["diff"]["diff"])
        # Orbit's own record of the step: text, its tool call, the result, the answer
        roles = [m["role"] for m in msgs]
        self.assertEqual(roles, ["system", "user", "assistant", "tool", "assistant"])
        self.assertEqual(msgs[2]["tool_calls"][0]["function"]["name"], "Write")
        self.assertIn("I will write", msgs[2]["reasoning_content"])
        self.assertIn("claude", msgs[1])
        self.assertTrue(msgs[1]["content"] == "write hello.txt")
        self.assertIn("secs", msgs[-1])
        # as in the terminal: the message goes to Claude as typed (no Orbit additions)
        said = json.dumps(self.requests()[0]["messages"])
        self.assertNotRegex(said, r"\[\w{3} \d{2} \w{3} \d{4}, \d{2}:\d{2}")
        self.assertNotIn("Running inside Orbit", json.dumps(self.requests()[0].get("system")))

        # a second message resumes the same Claude session: the model sees the history
        out2, _ = self.run_turn(msgs, "and again?")
        self.assertEqual(out2, "Still the same chat.")
        last = self.requests()[-1]
        self.assertIn("Writing it.", json.dumps(last["messages"]))
        self.assertEqual(msgs[-2]["claude"]["session"], msgs[1]["claude"]["session"])

        # the transcript Claude kept converts back into the same conversation
        path = CE.jsonl_path(msgs[1]["claude"]["session"], msgs[1]["claude"]["cwd"])
        self.assertTrue(path and os.path.exists(path))
        conv, title, cwd = CE.convert(path)
        self.assertEqual(title, "write hello.txt")
        self.assertEqual(os.path.realpath(cwd), os.path.realpath(self.work))
        self.assertEqual([m["role"] for m in conv], ["user", "assistant", "tool", "assistant", "user", "assistant"])
        self.assertEqual(conv[0]["content"], "write hello.txt")         # the time stamp is not shown
        hist = CE.scan_history()
        self.assertTrue(any(h["session"] == msgs[1]["claude"]["session"] for h in hist))

    def test_denied_write_is_not_made_and_the_model_is_told(self):
        outside = tempfile.mkdtemp(prefix="orbit-ce-out-")
        self.addCleanup(shutil.rmtree, outside, True)
        target = os.path.join(outside, "nope.txt")
        self.serve([
            [{"tool_use": {"name": "Write", "input": {"file_path": target, "content": "x"}}}],
            [{"text": "OK, I won't."}],
        ])
        msgs = [{"role": "system", "content": "sys"}]
        out, ev = self.run_turn(msgs, "write nope", approve=lambda *a: (False, "not now"))
        self.assertFalse(os.path.exists(target))
        self.assertEqual(out, "OK, I won't.")
        seen = json.dumps(self.requests()[-1]["messages"])
        self.assertIn("not now", seen)

    def test_nobody_watching_refuses_what_needs_approval(self):
        target = os.path.join(self.work, "keepme")
        os.makedirs(target, exist_ok=True)
        self.serve([
            [{"tool_use": {"name": "Bash", "input": {"command": f"rm -rf {target}"}}}],
            [{"text": "Could not."}],
        ])
        out, _ = self.run_turn([{"role": "system", "content": "s"}], "go", approve=None)
        self.assertTrue(os.path.isdir(target))
        self.assertIn("Nobody is watching", json.dumps(self.requests()[-1]["messages"]))

    def test_question_goes_to_orbits_question_box(self):
        self.serve([
            [{"tool_use": {"name": "AskUserQuestion", "input": {"questions": [{
                "question": "Which colour?", "header": "Colour", "multiSelect": False,
                "options": [{"label": "Red", "description": "warm"},
                            {"label": "Blue", "description": "cool"}]}]}}}],
            [{"text": "Blue it is."}],
        ])
        asked = []
        out, _ = self.run_turn([{"role": "system", "content": "s"}], "pick",
                               ask=lambda qn, opts, multi: asked.append((qn, opts)) or "Blue")
        self.assertEqual(asked, [("Which colour?", ["Red", "Blue"])])
        self.assertEqual(out, "Blue it is.")
        self.assertIn("Blue", json.dumps(self.requests()[-1]["messages"]))

    def test_a_chat_on_another_machine_keeps_claude_running_between_messages(self):
        """The remote path, played on this Mac: the wrapper that runs on the host, the real
        claude, the stand-in model. Three messages, one Claude Code process."""
        import ssh_remote
        self.serve([[{"text": "ok"}], [{"text": "42"}], [{"text": "50"}]])
        starts = []
        clean = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "ANTHROPIC"))}
        # the "remote" claude is the real CLI on this Mac: keep its transcripts out of ~/.claude
        clean["CLAUDE_CONFIG_DIR"] = self.cfgdir
        def fake_popen(host, claude_path, cwd, args, env, forward=None):
            p = subprocess.Popen(["bash", "-c", ssh_remote.WRAPPER, "orbit", *args], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, env=clean)
            p.stdin.write(ssh_remote.env_line({"ORBIT_CLAUDE": claude_path, "ORBIT_CWD": cwd, **env}).encode())
            p.stdin.flush()
            starts.append(p)
            return p
        saved = (ssh_remote.popen, ssh_remote.probe, CE.remote_target_env)
        ssh_remote.popen = fake_popen
        ssh_remote.probe = lambda host, **k: {"ok": True, "claude": CLAUDE, "home": os.path.expanduser("~")}
        CE.remote_target_env = lambda target, env: (ssh_remote.remote_env(env), None)
        CE.set_chat_pref("test-ce", host="testhost", cwd=self.work)
        try:
            msgs = [{"role": "system", "content": "s"}]
            outs = [self.run_turn(msgs, t)[0] for t in ("remember 42", "what number?", "add 8")]
            self.assertEqual(outs, ["ok", "42", "50"])
            self.assertEqual(len(starts), 1, "each message started Claude Code again")
            self.assertIn("test-ce", CE.LIVE)
            self.assertEqual(CE.marker_of(msgs)["host"], "testhost")
            # the second message went into the same session: the model saw the first exchange
            last = self.requests()[-1]["messages"]
            self.assertIn("remember 42", json.dumps(last))
            proc = CE.LIVE["test-ce"]["proc"]
            CE.close_live("test-ce")
            proc.wait(timeout=30)
            self.assertNotIn("test-ce", CE.LIVE)
            # a changed model or mode starts a fresh process that resumes the session
            q.CE.set_chat_pref("test-ce", permission_mode="plan")
            self.serve([[{"text": "planned"}]])
            self.assertEqual(self.run_turn(msgs, "and now?")[0], "planned")
            self.assertEqual(len(starts), 2)
        finally:
            ssh_remote.popen, ssh_remote.probe, CE.remote_target_env = saved
            CE.close_live("test-ce")
            CE.set_chat_pref("test-ce", host=None, cwd=None, permission_mode=None, remote_last_uuid=None)

    def test_todo_list_becomes_the_plan(self):
        self.serve([
            [{"tool_use": {"name": "TaskCreate", "input": {"subject": "Read the data", "description": "d"}}}],
            [{"text": "Planned."}],
        ])
        _, ev = self.run_turn([{"role": "system", "content": "s"}], "plan it", approve=lambda *a: True)
        if any("is disabled for this session" in str((p or {}).get("output")) for k, p in ev if k == "tool_result"):
            self.skipTest("this Claude Code has its Task tools switched off (its own setting, not Orbit's)")
        plans = [p for k, p in ev if k == "tool_result" and p.get("name") == "plan"]
        self.assertTrue(plans, [k for k, _ in ev])
        self.assertIn("[ ] Read the data", plans[-1]["output"])
        self.assertEqual(q.PLANS["test-ce"]["steps"][0]["text"], "Read the data")

    def test_a_subagent_shows_its_steps_and_a_done_line(self):
        self.serve([
            [{"tool_use": {"name": "Agent", "input": {"description": "Look around", "prompt": "list the files",
                                                      "subagent_type": "general-purpose"}}}],
            [{"tool_use": {"name": "Glob", "input": {"pattern": "*.md"}}}],
            [{"text": "Nothing much here."}],
            [{"text": "Done."}],
        ])
        msgs = [{"role": "system", "content": "s"}]
        out, ev = self.run_turn(msgs, "look around", approve=lambda *a: True)
        subs = [p for k, p in ev if k == "subagent"]
        if not subs:
            self.skipTest("this Claude Code ran no subagent against the stand-in model")
        self.assertEqual(subs[0]["description"], "Look around")
        self.assertEqual(subs[0]["name"], "Glob")
        # finished in line, or (sent to the background) when its task reports back
        done = [p["subagent"] for k, p in ev if k == "subagent_done"] or \
               [p["subagent"] for k, p in ev if k == "tool_result" and p.get("subagent") and not p["subagent"].get("background")]
        self.assertTrue(done, [k for k, _ in ev])
        self.assertEqual(done[0]["tools"], 1)
        self.assertEqual(done[0]["steps"][0]["args"]["pattern"], "*.md")
        saved = [m for m in msgs if m.get("role") == "tool" and m.get("subagent")]
        self.assertTrue(saved, "the subagent's steps are kept with the chat")
        self.assertFalse(saved[0]["subagent"].get("background"), "saved as finished, not still running")

    def test_a_background_shell_is_listed_until_it_ends(self):
        self.serve([
            [{"tool_use": {"name": "Bash", "input": {"command": "sleep 20", "run_in_background": True,
                                                     "description": "Wait a while"}}}],
            [{"text": "Started it."}],
        ])
        CE.BG_TASKS.pop("test-ce", None)
        _, ev = self.run_turn([{"role": "system", "content": "s"}], "run it in the background",
                              approve=lambda *a: True)
        res = [p for k, p in ev if k == "tool_result" and p.get("name") == "Bash"]
        self.assertTrue(res)
        if "background" not in str(res[0].get("output")).lower():
            self.skipTest("this Claude Code ran the command in the foreground")
        self.assertTrue(res[0].get("background"))
        rows = CE.bg_tasks("test-ce")
        self.assertTrue(rows)
        self.assertEqual(rows[0]["kind"], "shell")
        self.assertEqual(rows[0]["description"], "Wait a while")
        # the answer is over but the shell is not: the chat's Claude Code is kept for it
        self.addCleanup(CE.close_live, "test-ce")
        self.assertIn("test-ce", CE.LIVE)
        self.assertIsNone(CE.LIVE["test-ce"]["host"])
        self.assertTrue(CE.bg_running("test-ce"))
        CE.close_live("test-ce")                     # closing it ends the work with it
        self.assertNotIn("test-ce", CE.LIVE)
        self.assertNotIn(CE.bg_tasks("test-ce")[0]["status"], ("running", "pending"))

    def test_stop_mid_answer(self):
        self.serve([[{"text": "Starting a long job"}, {"sleep": 30}, {"text": " never"}]])
        cancel = threading.Event()
        threading.Timer(2.0, cancel.set).start()
        t0 = time.time()
        msgs = [{"role": "system", "content": "s"}]
        out, ev = self.run_turn(msgs, "go", cancel=cancel)
        self.assertLess(time.time() - t0, 20)
        self.assertIn("(stopped)", out)
        self.assertEqual(ev[-1][0], "done")

    def test_plan_mode_refuses_writes(self):
        target = os.path.join(self.work, "planned.txt")
        self.serve([
            [{"tool_use": {"name": "Write", "input": {"file_path": target, "content": "x"}}}],
            [{"text": "Here is the plan instead."}],
        ])
        out, _ = self.run_turn([{"role": "system", "content": "s"}], "do it",
                               approve=lambda *a: True, read_only=True)
        self.assertFalse(os.path.exists(target))

    def test_mode_changes_while_it_answers(self):
        self.serve([[{"text": "Working"}, {"sleep": 4}, {"text": " done."}]])
        got = {}
        self.addCleanup(CE.set_chat_pref, "test-ce", permission_mode=None)
        def poke():
            for _ in range(60):
                if "test-ce" in CE.RUNS: break
                time.sleep(0.1)
            time.sleep(0.8)
            got["mode"] = CE.set_permission_mode("test-ce", "acceptEdits")
            got["ctx"] = CE.control("test-ce", "get_context_usage")
        th = threading.Thread(target=poke); th.start()
        out, _ = self.run_turn([{"role": "system", "content": "s"}], "go")
        th.join()
        self.assertTrue(out.endswith("done."))       # Claude's result is its last text block
        self.assertTrue(got["mode"]["live"])
        self.assertNotIn("error", got["ctx"] or {"error": "none"})
        self.assertEqual(CE.chat_prefs("test-ce")["permission_mode"], "acceptEdits")
        self.assertNotIn("test-ce", CE.RUNS)
        self.assertTrue(CE.INIT.get("commands"))

    def test_undo_puts_back_what_claude_changed(self):
        target = os.path.join(self.work, "notes.txt")
        open(target, "w").write("original\n")
        self.serve([
            [{"tool_use": {"name": "Edit", "input": {"file_path": target, "old_string": "original",
                                                     "new_string": "changed"}}},
             {"tool_use": {"name": "Write", "input": {"file_path": os.path.join(self.work, "new.txt"),
                                                      "content": "new\n"}}}],
            [{"text": "Edited."}],
        ])
        msgs = [{"role": "system", "content": "s"}]
        self.run_turn(msgs, "edit", approve=lambda *a: True)
        self.assertEqual(open(target).read(), "changed\n")
        ch = msgs[-1]["changes"]
        self.assertEqual({os.path.basename(c["path"]) for c in ch}, {"notes.txt", "new.txt"})
        q.undo_changes(ch)
        self.assertEqual(open(target).read(), "original\n")
        self.assertFalse(os.path.exists(os.path.join(self.work, "new.txt")))

    def test_regenerated_and_forked_chats_follow_orbits_history(self):
        self.serve([
            [{"text": "Answer one."}],
            [{"text": "Answer two (to be regenerated)."}],
            [{"text": "Answer two, again."}],
            [{"text": "Fork answer."}],
        ])
        msgs = [{"role": "system", "content": "s"}]
        self.run_turn(msgs, "first")
        self.run_turn(msgs, "second")
        # regenerate: Orbit drops the last question and answer, then asks again
        del msgs[-2:]
        out, _ = self.run_turn(msgs, "second, reworded")
        self.assertEqual(out, "Answer two, again.")
        seen = json.dumps(self.requests()[-1]["messages"])
        self.assertIn("Answer one.", seen)
        self.assertNotIn("to be regenerated", seen)
        # a fork into another chat branches off a session of its own
        forked = [dict(m) for m in msgs]
        events = []
        CE.run_turn(forked, "in the fork", [], emit=lambda k, p: events.append(k), approve=None,
                    cancel=threading.Event(), sid="test-ce-fork", project=None)
        self.assertNotEqual(forked[-2]["claude"]["session"], msgs[1]["claude"]["session"])
        self.assertEqual(forked[-2]["claude"]["owner"], "test-ce-fork")
        self.assertIn("Answer two, again.", json.dumps(self.requests()[-1]["messages"]))

    def test_skill_routing_picks_matching_skills(self):
        base = os.path.join(self.cfgdir, "skills")
        for name, desc in (("pubmed-database", "Search PubMed for biomedical literature and abstracts"),
                           ("pdb-database", "Fetch protein structures from the Protein Data Bank"),
                           ("docx", "Create and edit Word documents")):
            os.makedirs(os.path.join(base, name), exist_ok=True)
            open(os.path.join(base, name, "SKILL.md"), "w").write(
                f"---\nname: {name}\ndescription: {desc}\n---\nbody\n")
        CE._SKILL_INDEX["key"] = None
        hits = [s["name"] for s in CE.route_skills("find pubmed literature on DNA methylation readers")]
        self.assertEqual(hits[0], "pubmed-database")
        self.assertNotIn("docx", hits)
        sp, _ = CE.launcher_files({**CE.DEFAULTS, "skill_routing": True}, "t", skills=["pubmed-database"])
        st = json.load(open(sp))
        self.assertEqual(st["skillOverrides"].get("docx"), "off")
        self.assertNotIn("pubmed-database", st["skillOverrides"])
        self.assertEqual(CE.launcher_files(dict(CE.DEFAULTS), "t", skills=["x"])[0], None)   # off: Claude lists all

    def test_your_claude_setup_is_changed_in_claude(self):
        src = os.path.join(self.tmp, "repo")
        for n in ("alpha", "nested/beta"):
            os.makedirs(os.path.join(src, n))
            open(os.path.join(src, n, "SKILL.md"), "w").write(f"---\nname: {n.split('/')[-1]}\ndescription: d\n---\nx")
        r = CE.skill_install(src)
        self.assertEqual(sorted(r["installed"]), ["alpha", "beta"])
        self.assertTrue(os.path.isfile(os.path.join(self.cfgdir, "skills", "beta", "SKILL.md")))
        self.assertEqual(sorted(CE.skill_install(src)["skipped"]), ["alpha", "beta"])
        CE.skill_set_enabled("alpha", False)
        self.assertEqual(CE.read_claude_settings()["skillOverrides"], {"alpha": "off"})
        self.assertFalse(next(x for x in CE.skills_list() if x["name"] == "alpha")["enabled"])
        CE.skill_set_enabled("alpha", True)
        self.assertEqual(CE.read_claude_settings()["skillOverrides"], {})
        CE.write_claude_settings({"permissions": {"allow": ["Bash(ls:*)"], "defaultMode": "acceptEdits"}})
        CE.write_claude_settings({"permissions": {"defaultMode": None}})
        self.assertEqual(CE.read_claude_settings()["permissions"], {"allow": ["Bash(ls:*)"]})
        self.assertEqual(CE.write_claude_skill("My Proc", "# Do the thing\n1. step"), "my-proc")
        self.assertIn("name: my-proc", open(os.path.join(self.cfgdir, "skills", "my-proc", "SKILL.md")).read())

    def test_new_chat_starts_in_its_chosen_folder_and_local_commands_show(self):
        chosen = os.path.join(self.tmp, "chosen")
        os.makedirs(chosen, exist_ok=True)
        CE.set_chat_pref("test-ce-dir", cwd=chosen)
        self.addCleanup(CE.set_chat_pref, "test-ce-dir", cwd=None)
        self.serve([[{"text": "unused"}]])
        msgs = [{"role": "system", "content": "s"}]
        events = []
        CE.run_turn(msgs, "/cost", [], emit=lambda k, p: events.append((k, p)), approve=None,
                    cancel=threading.Event(), sid="test-ce-dir", project=None)
        self.assertEqual(os.path.realpath(msgs[1]["claude"]["cwd"]), os.path.realpath(chosen))
        said = "".join(p for k, p in events if k == "content_delta")
        self.assertIn("Total cost", said)            # Claude's own /cost output, not a model answer
        self.assertEqual(self.requests(), [])


@unittest.skipUnless(CLAUDE, "Claude Code is not installed")
class TestHarnessModels(unittest.TestCase):
    """Models other than the local one, through the same engine: a provider with
    Anthropic's API (key given to Claude Code), and one with OpenAI's API (through
    Orbit's gateway, which adds the key)."""

    serve = TestClaudeEngine.serve
    run_turn = TestClaudeEngine.run_turn
    requests = TestClaudeEngine.requests

    @classmethod
    def setUpClass(cls):
        TestClaudeEngine.setUpClass.__func__(cls)
        import harness, harness_gateway, http.server
        cls.H = harness
        cls.reg = os.path.join(cls.tmp, "harness.json")
        cls.saved_path, cls.saved_secrets = harness._path, q.secrets_load
        harness._path = lambda root: cls.reg
        q.secrets_load = lambda: {"MOCKA_KEY": "sk-direct-test", "MOCKO_KEY": "sk-gateway-test"}
        sys.path.insert(0, HERE)
        from test_harness_gateway import Upstream
        cls.Upstream = Upstream
        cls.up = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        threading.Thread(target=cls.up.serve_forever, daemon=True).start()
        def route(provider, model):
            spec = harness.resolve(q.ROOT, f"harness:{provider}/{model}", q.secrets_load(), "x")
            if not spec: return None
            pc = spec["provider_cfg"]
            return {"base": pc["base"], "format": pc["format"], "api_key": pc["api_key"]}
        cls.gw = harness_gateway.serve(0, route)
        cls.saved_port = q.HARNESS_PORT
        q.HARNESS_PORT = cls.gw.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.H._path, q.secrets_load = cls.saved_path, cls.saved_secrets
        q.HARNESS_PORT = cls.saved_port
        cls.gw.shutdown(); cls.up.shutdown()
        q.TURN_CTX.model = None
        TestClaudeEngine.tearDownClass.__func__(cls)

    def register(self, mock_port=None):
        json.dump({"custom": {
            "mocka": {"label": "Mock A", "base": f"http://127.0.0.1:{mock_port}", "key": "MOCKA_KEY", "auth": "api_key",
                      "models": [{"id": "model-a", "format": "messages", "context": 50000}]},
            "mocko": {"label": "Mock O", "base": f"http://127.0.0.1:{self.up.server_address[1]}/v1", "key": "MOCKO_KEY",
                      "auth": "gateway", "models": [{"id": "model-o", "format": "chat", "context": 60000}]}}},
            open(self.reg, "w"))

    def test_anthropic_api_provider_gets_its_key_and_model(self):
        self.serve([[{"text": "Hello from A."}]])
        port = int(CE.model_endpoint()[0].rsplit(":", 1)[1])
        self.register(port)
        q.TURN_CTX.model = "harness:mocka/model-a"
        out, ev = self.run_turn([{"role": "system", "content": "s"}], "hi")
        self.assertEqual(out, "Hello from A.")
        rows = [json.loads(l) for l in open(self.log)]
        main = [r for r in rows if r["body"].get("tools")][-1]
        self.assertEqual(main["body"]["model"], "model-a")
        self.assertEqual(main["headers"].get("x-api-key"), "sk-direct-test")
        self.assertEqual(next(p for k, p in ev if k == "model")["label"], "Claude Code · Model A · Mock A")

    def test_openai_api_provider_goes_through_the_gateway(self):
        self.register(1)
        from test_harness_gateway import delta
        self.Upstream.seen.clear()
        self.Upstream.script = [{"chunks": [delta(reasoning_content="thinking it over"), delta(content="Hello from O."),
                                            {"id": "c", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}]}] * 3
        q.TURN_CTX.model = "harness:mocko/model-o"
        msgs = [{"role": "system", "content": "s"}]
        out, ev = self.run_turn(msgs, "hi")
        self.assertEqual(out, "Hello from O.")
        self.assertIn("thinking it over", msgs[-1].get("reasoning_content") or "")
        seen = [s for s in self.Upstream.seen if s["path"] == "/v1/chat/completions"]
        self.assertTrue(seen)
        self.assertEqual(seen[-1]["headers"].get("Authorization"), "Bearer sk-gateway-test")
        self.assertEqual(seen[-1]["body"]["model"], "model-o")

    def test_resume_command_and_imported_model_follow_the_provider(self):
        self.register(1)
        msgs = [{"role": "user", "content": "x", "claude": {"session": "abc", "cwd": "/tmp"}}]
        spec = q.current_model("harness:mocko/model-o")
        self.assertIn('claude-harness "harness:mocko/model-o" --resume abc', CE.resume_command(msgs, spec))
        self.assertIn("claude-qwen --resume abc", CE.resume_command(msgs, q.current_model("claude-qwen-cli:default")))
        self.assertEqual(CE.model_for_session(["model-o"]), "harness:mocko/model-o")
        self.assertEqual(CE.model_for_session(["something-else"]), "claude-qwen-cli:default")

    def test_orbits_own_chat_uses_the_same_provider_directly(self):
        self.register(1)
        from test_harness_gateway import delta
        self.Upstream.script = [{"chunks": [delta(content="Direct from O."),
                                            {"id": "c", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}]}]
        self.assertTrue(any(m["id"] == "harness-direct:mocko/model-o" for m in q.model_catalogue()))
        spec = q.current_model("harness-direct:mocko/model-o")
        self.assertFalse(CE.is_engine(spec))
        out = q.stream_call([{"role": "user", "content": "hi"}], None, think=False, model="harness-direct:mocko/model-o")
        self.assertEqual(out.get("content"), "Direct from O.")

    def test_claude_subscription_runs_plain_claude_or_explains_the_login(self):
        spec = q.current_model("harness:claude/opus")
        t = CE.harness_target(spec)
        self.assertTrue(t["subscription"])
        env = CE.target_env(t)
        for k in ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_MAX_CONTEXT_TOKENS",
                  "ANTHROPIC_DEFAULT_SONNET_MODEL"):
            self.assertNotIn(k, env)
        argv = CE.build_argv(CE.DEFAULTS, model=t["cli_model"])
        # a sign-in token saved in Orbit (from `claude setup-token`) goes to Claude Code itself
        old_secrets = q.secrets_load
        q.secrets_load = lambda: {"CLAUDE_CODE_OAUTH_TOKEN": "tok-from-setup"}
        try:
            self.assertEqual(CE.target_env(CE.harness_target(spec)).get("CLAUDE_CODE_OAUTH_TOKEN"), "tok-from-setup")
        finally:
            q.secrets_load = old_secrets
        self.assertEqual(argv[argv.index("--model") + 1], "opus")
        old = self.H.claude_login
        self.H.claude_login = lambda max_age=120, token=None: "no"
        try:
            q.TURN_CTX.model = "harness:claude/opus"
            out, ev = self.run_turn([{"role": "system", "content": "s"}], "hi")
        finally:
            self.H.claude_login = old
        self.assertIn("claude auth login", out)

    def test_missing_key_is_explained_not_run(self):
        self.register(1)
        q.secrets_load, old = (lambda: {}), q.secrets_load
        try:
            q.TURN_CTX.model = "harness:mocko/model-o"
            out, ev = self.run_turn([{"role": "system", "content": "s"}], "hi")
        finally:
            q.secrets_load = old
        self.assertIn("No API key", out)
        self.assertIn("error", [k for k, _ in ev])


class TestClaudeEngineOffline(unittest.TestCase):
    """The parts that need no Claude Code at all."""

    def test_claude_memory_and_instructions_are_claudes_own_files(self):
        import tempfile, shutil
        cdir, folder = tempfile.mkdtemp(), tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, cdir, True); self.addCleanup(shutil.rmtree, folder, True)
        old_env, old_trash = os.environ.get("ORBIT_CLAUDE_CONFIG_DIR"), CE._to_trash
        os.environ["ORBIT_CLAUDE_CONFIG_DIR"] = cdir
        trashed = []
        CE._to_trash = lambda path: (trashed.append(path), os.remove(path))[0]
        try:
            self.assertTrue(CE.save_claude_instructions("user", "Be brief.")["ok"])
            self.assertEqual(open(os.path.join(cdir, "CLAUDE.md")).read(), "Be brief.\n")
            self.assertTrue(CE.save_claude_instructions("local", "Only here.", folder)["ok"])
            self.assertTrue(os.path.isfile(os.path.join(folder, "CLAUDE.local.md")))
            self.assertIn("error", CE.save_claude_instructions("project", "x"))       # no folder chosen
            text = "---\nname: lab\ndescription: the lab's setup\nmetadata:\n  type: user\n---\n\nUses MTPLX.\n"
            r = CE.save_claude_memory(folder, "lab.md", text)
            self.assertTrue(r["new"])
            m = CE.claude_memory(folder)
            self.assertEqual([(i["name"], i["description"]) for i in m["items"]], [("lab", "the lab's setup")])
            self.assertIn("- [lab](lab.md) — the lab's setup", m["index"])
            esc = CE.save_claude_memory(folder, "../escape.md", "x")        # only ever inside the memory folder
            self.assertEqual(os.path.dirname(esc["path"]), CE.claude_memory_dir(folder))
            CE.delete_claude_memory(folder, "escape.md"); trashed.clear()
            self.assertIn("error", CE.delete_claude_memory(folder, "../../CLAUDE.md"))
            self.assertTrue(CE.delete_claude_memory(folder, "lab.md")["ok"])
            self.assertNotIn("lab.md", CE.claude_memory(folder)["index"])
            self.assertEqual(len(trashed), 1)
            old_scratch, CE._SCRATCH = CE._SCRATCH, ()     # this test's folder is a temporary one
            try: self.assertEqual(CE.claude_memory_folders()[0]["count"], 0)
            finally: CE._SCRATCH = old_scratch
        finally:
            CE._to_trash = old_trash
            if old_env is None: os.environ.pop("ORBIT_CLAUDE_CONFIG_DIR", None)
            else: os.environ["ORBIT_CLAUDE_CONFIG_DIR"] = old_env

    def test_claude_code_starts_fresh_outside_the_local_model(self):
        """REGRESSION: Orbit chose a subset of MCP servers (dropping plugins' servers, whose
        hooks still redirected web fetches to them) and added local-model tweaks to every
        model. Outside the local model Claude Code starts as your setup has it."""
        import tempfile, shutil
        c = dict(CE.DEFAULTS)
        local = CE.build_argv(c, kind="local", append=CE.launcher_append(c, None, "local"))
        prov = CE.build_argv(c, kind="provider", append=CE.launcher_append(c, None, "provider"))
        sub = CE.build_argv(c, kind="subscription", append=CE.launcher_append(c, None, "subscription"))
        self.assertIn("--exclude-dynamic-system-prompt-sections", local)
        self.assertIn("Workflow", local)
        for a in (prov, sub):
            self.assertNotIn("--exclude-dynamic-system-prompt-sections", a)
            self.assertNotIn("--append-system-prompt", a)
            self.assertNotIn("--strict-mcp-config", a)
            self.assertNotIn("Workflow", a)
        self.assertEqual(prov[prov.index("--disallowedTools") + 1], "WebSearch")
        self.assertNotIn("--disallowedTools", sub)
        self.assertEqual(CE.launcher_files(c, "fresh")[1], None)          # no --mcp-config: all of yours
        # plugins that bring MCP servers are named, so Claude Code starts their servers
        home = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, home, True)
        with_mcp, without = os.path.join(home, "a"), os.path.join(home, "b")
        for d in (with_mcp, without): os.makedirs(os.path.join(d, ".claude-plugin"))
        json.dump({"name": "a", "mcpServers": {"s": {"command": "node"}}}, open(os.path.join(with_mcp, ".claude-plugin", "plugin.json"), "w"))
        json.dump({"name": "b"}, open(os.path.join(without, ".claude-plugin", "plugin.json"), "w"))
        os.makedirs(os.path.join(home, "plugins"))
        json.dump({"plugins": {"a@m": [{"installPath": with_mcp}], "b@m": [{"installPath": without}]},
                   "enabledPlugins": {"a@m": True, "b@m": True}}, open(os.path.join(home, "plugins", "installed_plugins.json"), "w"))
        old = CE.claude_dir
        CE.claude_dir = lambda: home
        try:
            self.assertEqual(CE.plugin_dirs_with_mcp(), [with_mcp])
            argv = CE.build_argv(c, kind="provider")
            self.assertEqual(argv[argv.index("--plugin-dir") + 1], with_mcp)
            self.assertNotIn("--plugin-dir", CE.build_argv(c, kind="provider", remote=True))
        finally:
            CE.claude_dir = old

    def test_a_chats_own_instructions_reach_claude(self):
        a = CE._orbit_append(None, dict(CE.DEFAULTS), False, "Answer in French.")
        self.assertIn("Answer in French.", a)
        self.assertNotIn("standing instructions", a)      # Orbit's own instructions stay out

    def test_argv_profiles(self):
        c = {**CE.DEFAULTS}
        a = CE.build_argv(c, session_id="abc", resume=True, read_only=True)
        self.assertIn("--resume", a); self.assertIn("plan", a)
        self.assertNotIn("--setting-sources", a)          # standard: Claude as set up
        self.assertIn("WebSearch", a)                     # unusable on a local model
        self.assertIn("--permission-prompt-tool", a)
        self.assertNotIn("--permission-mode", CE.build_argv(c, session_id="abc"))   # Claude's own default
        self.assertIn("acceptEdits", CE.build_argv(c, mode="acceptEdits"))
        self.assertIn("--add-dir", CE.build_argv(c, add_dirs=["/a"]))
        lean = CE.build_argv({**c, "profile": "lean"}, session_id="abc")
        self.assertIn("--safe-mode", lean); self.assertIn("--session-id", lean)
        # the terminal command and Orbit's differ only in the transport and session
        term = CE.build_argv(c, sdk=False)
        orbit = CE.build_argv(c, sdk=True)
        self.assertNotIn("--print", term)
        extra = [x for x in orbit if x not in term]
        self.assertEqual(set(extra), {"--print", "--output-format", "stream-json", "--verbose", "--input-format",
                                      "--include-partial-messages", "--include-hook-events",
                                      "--permission-prompt-tool", "stdio"})
        # no Orbit extras by default
        for k in ("orbit_rules", "orbit_tools", "project_tools", "skill_routing", "skill_hint",
                  "orbit_skills", "orbit_context", "message_time"):
            self.assertFalse(CE.DEFAULTS[k], k)

    def test_env_drops_other_claude_sessions_and_real_keys(self):
        os.environ["CLAUDE_CODE_ENTRYPOINT"] = "claude-desktop"
        os.environ["ANTHROPIC_API_KEY"] = "sk-real"
        try:
            env = CE.harness_env("http://127.0.0.1:1", "m", 1000)
        finally:
            os.environ.pop("CLAUDE_CODE_ENTRYPOINT"); os.environ.pop("ANTHROPIC_API_KEY")
        self.assertNotIn("CLAUDE_CODE_ENTRYPOINT", env)
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "http://127.0.0.1:1")
        self.assertEqual(env["ANTHROPIC_DEFAULT_HAIKU_MODEL"], "m")

    def test_permission_mapping(self):
        seen = []
        def approve(fn, args, reason, info):
            seen.append(info)
            return {"allow": True, "always": True, "pattern": "Bash(git diff:*)"}
        ctx = {"cfg": dict(CE.DEFAULTS), "read_only": False, "emit": lambda k, p: None,
               "approve": approve, "ask": None}
        req = {"description": "show the diff", "permission_suggestions": [
            {"type": "addRules", "rules": [{"toolName": "Bash", "ruleContent": "git diff:*"}],
             "behavior": "allow", "destination": "localSettings"}]}
        # Claude asked, so Orbit asks you -- no rules of its own by default
        ok, _, upd, perms = CE.decide("Bash", {"command": "git diff"}, ctx, req)
        self.assertTrue(ok)
        self.assertEqual(seen[0]["suggested_pattern"], "Bash(git diff:*)")
        self.assertIn("show the diff", CE.decide.__doc__ and "show the diff")
        self.assertEqual(perms, [{"type": "addRules", "rules": [{"toolName": "Bash", "ruleContent": "git diff:*"}],
                                  "behavior": "allow", "destination": "localSettings"}])
        # "Always allow" to a chosen place, or a mode change
        self.assertEqual(CE._always("mode:acceptEdits", None, "Write", CE.DEFAULTS)[0]["mode"], "acceptEdits")
        self.assertEqual(CE._always("Read", None, "Read", {**CE.DEFAULTS, "rule_destination": "userSettings"}),
                         [{"type": "addRules", "rules": [{"toolName": "Read"}], "behavior": "allow",
                           "destination": "userSettings"}])
        # nobody watching: refused
        self.assertFalse(CE.decide("Bash", {"command": "ls"}, {**ctx, "approve": None})[0])
        self.assertFalse(CE.decide("ExitPlanMode", {}, {**ctx, "read_only": True})[0])
        self.assertFalse(CE.decide("Write", {"file_path": "/x"}, {**ctx, "read_only": True})[0])
        # Orbit's own rules only when asked for
        rules = {**ctx, "cfg": {**CE.DEFAULTS, "orbit_rules": True}, "approve": None}
        self.assertTrue(CE.decide("Read", {"file_path": "/etc/hosts"}, rules)[0])
        self.assertEqual(CE.orbit_view("Bash", {"command": "ls"}), ("run_shell", {"command": "ls"}))

    def test_questions_asking_to_continue_answer_themselves(self):
        ctx = {"ask": lambda *a: self.fail("should not ask")}
        ok, _, upd = CE._answer_questions({"questions": [{"question": "Should I continue?",
                                                          "options": [{"label": "Yes"}, {"label": "No"}]}]}, ctx)
        self.assertTrue(ok)
        self.assertEqual(upd["answers"]["Should I continue?"], "Yes")

    def test_user_text_strips_harness_wrappers(self):
        self.assertIsNone(CE._user_text("<local-command-stdout>x</local-command-stdout>"))
        self.assertEqual(CE._user_text("<command-name>/compact</command-name>\n<command-args></command-args>"),
                         "/compact")
        self.assertEqual(CE._user_text("[Wed 16 Sep 2026, 14:30 PDT] hello"), "hello")
        self.assertEqual(CE._user_text([{"type": "text", "text": "<system-reminder>x</system-reminder>hi"}]), "hi")
        self.assertIsNone(CE._user_text([{"type": "tool_result", "content": "x"}]))

    def test_plan_from_todo_tools(self):
        p = CE._Plan()
        p.from_tool("TodoWrite", {"todos": [{"content": "a", "status": "completed"},
                                            {"content": "b", "status": "pending"}]}, "")
        self.assertEqual(p.text(), "0. [x] a\n1. [ ] b")
        p2 = CE._Plan()
        p2.from_tool("TaskCreate", {"subject": "one"}, "Task #1 created successfully: one")
        p2.from_tool("TaskUpdate", {"taskId": "1", "status": "completed"}, "")
        self.assertEqual(p2.steps(), [{"text": "one", "done": True, "active": False}])
        # the step in hand is marked, as Claude Code's list marks it
        p3 = CE._Plan()
        p3.from_tool("TodoWrite", {"todos": [{"content": "a", "status": "completed"},
                                             {"content": "b", "status": "in_progress"},
                                             {"content": "c", "status": "pending"}]}, "")
        self.assertEqual(p3.text(), "0. [x] a\n1. [>] b\n2. [ ] c")

    def test_messages_never_carry_the_marker_to_a_model(self):
        self.assertIn("claude", q.PRIVATE_KEYS)



class TestChatPrefsUnderLoad(unittest.TestCase):
    def test_many_chats_saving_settings_at_once_lose_nothing(self):
        import threading, tempfile, shutil
        d = tempfile.mkdtemp(prefix="orbit-prefs-"); self.addCleanup(shutil.rmtree, d, True)
        saved = CE._work_dir; CE._work_dir = lambda: d
        try:
            errors = []
            def one(i):
                try: CE.set_chat_pref(f"chat{i}", cwd=f"/work/{i}", permission_mode="auto")
                except Exception as e: errors.append(e)
            ths = [threading.Thread(target=one, args=(i,)) for i in range(40)]
            [t.start() for t in ths]; [t.join() for t in ths]
            self.assertEqual(errors, [])
            prefs = CE.chat_prefs()
            self.assertEqual(len(prefs), 40)
            self.assertEqual(prefs["chat7"]["cwd"], "/work/7")
        finally:
            CE._work_dir = saved

if __name__ == "__main__":
    unittest.main()


class TestBackgroundRegistry(unittest.TestCase):
    def test_tasks_update_and_end(self):
        CE.BG_TASKS.pop("reg", None)
        CE.bg_task("reg", "t1", kind="shell", description="build")
        CE.bg_task("reg", "t1", status="completed", summary="built")
        r = CE.bg_tasks("reg")[0]
        self.assertEqual((r["status"], r["summary"]), ("completed", "built"))
        self.assertIsNotNone(r["ended"])
        CE.bg_task("reg", "t2", description="watch")
        CE.bg_ended("reg")
        self.assertTrue(all(x["status"] not in ("running", "pending") for x in CE.bg_tasks("reg")))
        CE.BG_TASKS.pop("reg", None)
