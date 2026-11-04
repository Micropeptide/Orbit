import json, os, sys, tempfile, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))
import claude_features as F


class Agents(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(); self.proj = tempfile.mkdtemp()
        os.environ["ORBIT_CLAUDE_CONFIG_DIR"] = self.home
        self.addCleanup(os.environ.pop, "ORBIT_CLAUDE_CONFIG_DIR", None)

    def test_save_list_delete_round_trip_with_a_model(self):
        r = F.save_agent("user", None, "Searcher", 'Finds "things" fast', "Search only.", "haiku", "Read, Grep", "blue")
        self.assertTrue(r.get("ok"), r)
        text = open(os.path.join(self.home, "agents", "searcher.md")).read()
        self.assertIn("model: haiku", text); self.assertIn("tools: Read, Grep", text)
        got = F.list_agents()[0]
        self.assertEqual((got["name"], got["model"], got["tools"], got["scope"]), ("searcher", "haiku", "Read, Grep", "user"))
        self.assertEqual(got["prompt"], "Search only.")
        self.assertTrue(F.delete_agent("user", None, "searcher").get("ok"))
        self.assertEqual(F.list_agents(), [])

    def test_inherit_leaves_the_model_line_out_and_project_scope_needs_a_folder(self):
        F.save_agent("project", self.proj, "rev", "reviews", "Review.", "inherit")
        self.assertNotIn("model:", open(os.path.join(self.proj, ".claude", "agents", "rev.md")).read())
        self.assertEqual(F.list_agents(self.proj)[0]["scope"], "project")
        self.assertIn("error", F.save_agent("project", None, "x", "d", "p"))

    def test_bad_names_and_empty_fields_are_refused_and_nothing_escapes_the_folder(self):
        for bad in ("../evil", "a b", "", "X/Y"):
            self.assertIn("error", F.save_agent("user", None, bad, "d", "p"), bad)
        self.assertIn("error", F.save_agent("user", None, "ok", "", "p"))
        self.assertIn("error", F.save_agent("user", None, "ok", "d", ""))
        self.assertIn("error", F.save_agent("user", None, "ok", "d", "p", "bad model!"))
        self.assertIn("error", F.delete_agent("user", None, "../x"))

    def test_hooks_are_listed_by_event_and_source(self):
        os.makedirs(os.path.join(self.proj, ".claude"))
        json.dump({"hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi"}]}]}},
                  open(os.path.join(self.proj, ".claude", "settings.json"), "w"))
        h = F.hooks(self.proj)
        self.assertEqual((h[0]["event"], h[0]["matcher"], h[0]["command"], h[0]["source"]), ("PostToolUse", "Bash", "echo hi", "project"))

    def test_the_starting_templates_are_valid(self):
        for t in F.TEMPLATES:
            self.assertTrue(F.save_agent("user", None, t["name"], t["description"], t["prompt"], t["model"], t["tools"]).get("ok"), t)


if __name__ == "__main__":
    unittest.main()


class Background(unittest.TestCase):
    """The background-session commands, against a stand-in `claude` that records what it was asked."""
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.log = os.path.join(self.d, "calls.txt")
        self.exe = os.path.join(self.d, "claude")
        with open(self.exe, "w") as f:
            f.write("#!/bin/sh\necho \"$PWD|$@\" >> %s\n"
                    "case \"$1\" in\n agents) echo '[{\"sessionId\":\"abc12345\",\"name\":\"job\",\"status\":\"busy\",\"cwd\":\"/x\",\"kind\":\"background\",\"startedAt\":1000}]';;\n"
                    " --bg) echo 'started background session 9f3a21c4';;\n logs) echo 'line one';;\n *) echo done;;\nesac\n" % self.log)
        os.chmod(self.exe, 0o755)
        self.calls = lambda: open(self.log).read().splitlines()

    def test_list_reads_the_json_and_the_all_flag_is_passed(self):
        r = F.bg_list(self.exe, everything=True)
        self.assertEqual(r["sessions"][0]["id"], "abc12345"); self.assertEqual(r["sessions"][0]["status"], "busy")
        self.assertIn("agents --json --all", self.calls()[0])

    def test_start_runs_in_the_folder_with_the_prompt_after_dashes_and_returns_the_id(self):
        r = F.bg_start(self.exe, "-rf do the thing", self.d, model="haiku", mode="acceptEdits")
        self.assertEqual(r["id"], "9f3a21c4")
        call = self.calls()[0]
        self.assertTrue(call.startswith(os.path.realpath(self.d)) or call.startswith(self.d))
        self.assertIn("--bg --model haiku --permission-mode acceptEdits -- -rf do the thing", call)

    def test_start_refuses_what_it_should(self):
        for kw in ({"prompt": ""}, {"prompt": "x", "mode": "bypassPermissions"}, {"prompt": "x", "model": "a b;"},
                   {"prompt": "x", "resume": "not-a-session"}, {"prompt": "x", "cwd": "relative"}):
            a = dict(prompt="x", cwd=self.d); a.update(kw)
            self.assertIn("error", F.bg_start(self.exe, a.pop("prompt"), a.pop("cwd"), **a), kw)
        self.assertFalse(os.path.exists(self.log), "nothing was run")

    def test_commands_take_only_a_plain_id(self):
        self.assertTrue(F.bg_logs(self.exe, "abc12345")["ok"])
        self.assertIn("logs abc12345", self.calls()[0])
        for bad in ("", "--force", "a;b", "../x", "$(x)"):
            self.assertIn("error", F.bg_stop(self.exe, bad), bad)
        self.assertEqual(len(self.calls()), 1)


class StatusAndKeys(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(); os.environ["ORBIT_CLAUDE_CONFIG_DIR"] = self.home
        self.addCleanup(os.environ.pop, "ORBIT_CLAUDE_CONFIG_DIR", None)

    def test_the_status_line_command_gets_the_session_as_json_and_its_colours_are_dropped(self):
        cmd = "python3 -c \"import json,sys;d=json.load(sys.stdin);print('\\033[32m'+d['model']['display_name']+'\\033[0m $'+str(d['cost']['total_cost_usd']))\""
        json.dump({"statusLine": {"type": "command", "command": cmd}}, open(os.path.join(self.home, "settings.json"), "w"))
        self.assertEqual(F.statusline(None, "s1", "m", "Sonnet", 1.5), "Sonnet $1.5")

    def test_no_command_or_a_slow_one_gives_nothing(self):
        self.assertEqual(F.statusline(None), "")
        json.dump({"statusLine": {"type": "command", "command": "sleep 5"}}, open(os.path.join(self.home, "settings.json"), "w"))
        self.assertEqual(F.statusline(None, timeout=0.5), "")

    def test_keybindings_are_saved_only_as_json_and_the_old_file_is_kept(self):
        self.assertIn("error", F.write_keybindings("{nope"))
        self.assertTrue(F.write_keybindings('{"a": 1}').get("ok"))
        self.assertTrue(F.write_keybindings('{"a": 2}').get("ok"))
        self.assertEqual(open(F.keybindings_path() + ".orbit-bak").read().strip(), '{"a": 1}')
        self.assertIn('"a": 2', F.read_keybindings()["text"])
