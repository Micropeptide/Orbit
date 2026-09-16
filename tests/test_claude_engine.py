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
        cls.saved = {k: getattr(q, k) for k in ("WORKSPACE",)}
        q.WORKSPACE = cls.work
        cls.saved_endpoint, cls.saved_wake = CE.model_endpoint, CE._wake_model
        cls.saved_settings = dict(q.S)
        CE._wake_model = lambda emit: None
        cls.saved_runlog = CE._run_log
        CE._run_log = lambda *a, **k: None                      # nor into Orbit's logs
        cls.saved_workdir = CE._work_dir
        wd = os.path.join(cls.tmp, "engine-files"); os.makedirs(wd)
        CE._work_dir = lambda: wd                               # nor into Orbit's config
        q.S["claude_qwen"] = {"mcp_servers": []}
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

    def test_todo_list_becomes_the_plan(self):
        self.serve([
            [{"tool_use": {"name": "TaskCreate", "input": {"subject": "Read the data", "description": "d"}}}],
            [{"text": "Planned."}],
        ])
        _, ev = self.run_turn([{"role": "system", "content": "s"}], "plan it", approve=lambda *a: True)
        plans = [p for k, p in ev if k == "tool_result" and p.get("name") == "plan"]
        self.assertTrue(plans, [k for k, _ in ev])
        self.assertIn("[ ] Read the data", plans[-1]["output"])
        self.assertEqual(q.PLANS["test-ce"]["steps"][0]["text"], "Read the data")

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


class TestClaudeEngineOffline(unittest.TestCase):
    """The parts that need no Claude Code at all."""

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
        self.assertEqual(p2.steps(), [{"text": "one", "done": True}])

    def test_messages_never_carry_the_marker_to_a_model(self):
        self.assertIn("claude", q.PRIVATE_KEYS)


if __name__ == "__main__":
    unittest.main()
