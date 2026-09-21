"""Easy mode: a short bench of tools for a small model, in both engines. Settings are
stood in for; nothing is saved and no model is called."""
import os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))
import qqcore as q
import claude_engine as CE


class TestOrbitsOwnAgent(unittest.TestCase):
    def setUp(self):
        self.saved = {k: q.S.get(k) for k in ("easy_mode", "easy_tools")}
        self.addCleanup(lambda: q.S.update(self.saved))

    def specs(self, *names):
        return [{"type": "function", "function": {"name": n, "parameters": {}}} for n in names]

    def test_off_by_default_everything_is_offered(self):
        q.S["easy_mode"] = False
        s = self.specs("read_file", "cluster_qdel", "screen_type")
        self.assertEqual(q.easy_tools(s), s)

    def test_on_only_the_listed_tools_are_offered(self):
        q.S["easy_mode"] = True
        q.S["easy_tools"] = ["read_file", "run_shell"]
        got = q.easy_tools(self.specs("read_file", "cluster_qdel", "run_shell", "screen_type"))
        self.assertEqual([t["function"]["name"] for t in got], ["read_file", "run_shell"])

    def test_an_empty_list_is_not_a_way_to_lose_every_tool(self):
        q.S["easy_mode"] = True
        q.S["easy_tools"] = []
        s = self.specs("read_file")
        self.assertEqual(q.easy_tools(s), s)

    def test_an_agents_own_list_still_narrows_it(self):
        q.S["easy_mode"] = True
        q.S["easy_tools"] = ["read_file", "run_shell"]
        saved = q.agents_load
        q.agents_load = lambda: {"reader": {"tools": ["read_file"]}}
        self.addCleanup(setattr, q, "agents_load", saved)
        got = q.tools_for("reader", self.specs("read_file", "run_shell"))
        self.assertEqual([t["function"]["name"] for t in got], ["read_file"])


class TestClaudeCode(unittest.TestCase):
    def setUp(self):
        self.saved = q.S.get("easy_mode")
        self.addCleanup(q.S.__setitem__, "easy_mode", self.saved)
        seen = CE.known_tools()
        self.addCleanup(CE.known_tools, seen)          # the file is a union: nothing is lost

    def test_it_denies_only_tools_claude_code_said_it_has(self):
        """A name Claude Code does not know stops the run before it starts, so easy mode
        never invents one."""
        q.S["easy_mode"] = True
        CE.known_tools(["Read", "Bash", "NotebookEdit", "TaskStop"])
        argv = CE.build_argv({**CE.DEFAULTS, "easy_tools": ["Read", "Bash"],
                              "disallowed_tools": []}, kind="local")
        deny = argv[argv.index("--disallowedTools") + 1:]
        deny = deny[:next((i for i, a in enumerate(deny) if a.startswith("--")), len(deny))]
        self.assertIn("NotebookEdit", deny)
        self.assertIn("TaskStop", deny)
        self.assertNotIn("Read", deny)
        self.assertNotIn("Bash", deny)
        self.assertTrue(all(t in CE.known_tools() for t in deny))

    def test_it_also_takes_the_mcp_servers_away(self):
        """A server's tools are in every request whether they are ever called or not."""
        import json, tempfile, shutil
        tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, tmp, True)
        saved = (CE.user_mcp_servers, CE._write_json)
        CE.user_mcp_servers = lambda: {"paper-fetch": {"command": "x"}, "wpcom": {"command": "y"}}
        def write(name, data):
            path = os.path.join(tmp, name)
            with open(path, "w") as fh: json.dump(data, fh)
            return path
        CE._write_json = write
        self.addCleanup(lambda: setattr(CE, "user_mcp_servers", saved[0]))
        self.addCleanup(lambda: setattr(CE, "_write_json", saved[1]))
        c = {**CE.DEFAULTS, "mcp_servers": ["*"]}

        q.S["easy_mode"] = False
        sp, mp = CE.launcher_files(c, "t-off")
        self.assertIsNone(mp)                      # all of yours, no file needed
        self.assertIsNone(sp)                      # hooks as your Claude has them

        q.S["easy_mode"] = True
        sp, mp = CE.launcher_files(c, "t-on")
        self.assertEqual(json.load(open(mp))["mcpServers"], {})
        self.assertEqual(json.load(open(sp)), {"disableAllHooks": True})
        argv = CE.build_argv(c, settings_path=sp, mcp_path=mp, kind="local")
        self.assertIn("--strict-mcp-config", argv)
        self.assertNotIn("--plugin-dir", argv)

        sp, mp = CE.launcher_files({**c, "easy_mcp": ["paper-fetch"]}, "t-keep")
        self.assertEqual(list(json.load(open(mp))["mcpServers"]), ["paper-fetch"])

    def test_off_it_changes_nothing(self):
        q.S["easy_mode"] = False
        argv = CE.build_argv({**CE.DEFAULTS, "disallowed_tools": ["WebSearch"]}, kind="local")
        deny = argv[argv.index("--disallowedTools") + 1:]
        deny = deny[:next((i for i, a in enumerate(deny) if a.startswith("--")), len(deny))]
        self.assertEqual(deny, ["WebSearch"])


if __name__ == "__main__":
    unittest.main()
