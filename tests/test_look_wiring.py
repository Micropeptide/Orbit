"""The look tools (bin/orbit-look) reach every engine, with the switches you set.

Claude Code, Codex and OpenCode get them by default; Orbit's own agent only when asked;
the groups -- browser, simulator, Mac -- can be left out one by one.
"""
import json, os, shutil, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))

import qqcore as q
import claude_engine as CE


class Switches(unittest.TestCase):
    def setUp(self):
        self.saved = {k: q.S.get(k) for k in ("look_engines", "look_groups", "computer_use_enabled")}
        for k in self.saved: q.S.pop(k, None)
        self.addCleanup(self.restore)

    def restore(self):
        for k, v in self.saved.items():
            if v is None: q.S.pop(k, None)
            else: q.S[k] = v


class TestWho(Switches):
    def test_the_agents_that_build_things_get_them_by_default(self):
        self.assertEqual([e for e in ("claude", "codex", "opencode", "orbit") if q.look_enabled(e)],
                         ["claude", "codex", "opencode"])

    def test_orbits_own_agent_only_when_asked(self):
        q.S["look_engines"] = ["orbit"]
        self.assertTrue(q.look_enabled("orbit"))
        self.assertFalse(q.look_enabled("claude"))

    def test_no_group_no_tools(self):
        q.S["look_groups"] = []
        self.assertFalse(q.look_enabled("claude"))

    def test_the_server_is_started_with_the_groups_and_a_place_for_screenshots(self):
        q.S["look_groups"] = ["browser", "mac", "nonsense"]
        env = q.look_server()["env"]
        self.assertEqual(env["ORBIT_LOOK_GROUPS"], "browser,mac")
        self.assertIn(".screenshots", env["ORBIT_LOOK_DIR"])
        self.assertEqual(q.look_server()["args"], [q.LOOK_PATH])

    def test_status_says_what_it_can_use(self):
        st = q.look_status()
        self.assertTrue(st["installed"])
        self.assertEqual(st["engines"], ["claude", "codex", "opencode"])
        self.assertEqual(st["groups"], ["browser", "simulator", "mac"])


class TestOrbitsOwnAgent(Switches):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="orbit-mcp-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.saved_cfg = (q.MCPCFG, q.snapshot_config)
        q.MCPCFG = os.path.join(self.tmp, "mcp.json")
        q.snapshot_config = lambda *a, **k: None
        self.addCleanup(lambda: (setattr(q, "MCPCFG", self.saved_cfg[0]), setattr(q, "snapshot_config", self.saved_cfg[1])))
        json.dump({"mcpServers": {"mine": {"command": "x"}}}, open(q.MCPCFG, "w"))

    def test_offered_without_being_written_to_mcp_json(self):
        self.assertNotIn("look", q.mcp_config()["mcpServers"])           # off for Orbit's own agent
        q.S["look_engines"] = ["orbit"]
        self.assertIn("look", q.mcp_config()["mcpServers"])
        self.assertIn("mine", q.mcp_config()["mcpServers"])
        self.assertNotIn("look", json.load(open(q.MCPCFG))["mcpServers"])

    def test_saving_the_list_back_does_not_keep_it(self):
        q.S["look_engines"] = ["orbit"]
        q.mcp_save(q.mcp_config())                                       # what Settings does on Save
        self.assertEqual(list(json.load(open(q.MCPCFG))["mcpServers"]), ["mine"])


class TestTheGate(unittest.TestCase):
    CTX = {"cfg": dict(CE.DEFAULTS), "read_only": False, "emit": lambda k, p: None, "approve": None, "ask": None}

    def test_looking_is_not_asked_about(self):
        for name in ("browser_open", "browser_click", "simulator_launch", "mac_screenshot", "simulator_tap"):
            self.assertTrue(CE.decide(f"mcp__orbit-look__{name}", {}, self.CTX)[0], name)

    def test_starting_or_quitting_an_app_on_this_mac_is_decided_by_the_usual_rules(self):
        # nobody to ask here: not allowed
        for name in ("mac_launch", "mac_quit"):
            self.assertFalse(CE.decide(f"mcp__orbit-look__{name}", {"app": "Calculator"}, self.CTX)[0], name)


if __name__ == "__main__":
    unittest.main()


class TestScreenshotsShowInTheChat(unittest.TestCase):
    """A look tool's result names the screenshot it saved; the chat shows the picture."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orbit-shots-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.saved = q.WORKSPACE
        q.WORKSPACE = os.path.join(self.tmp, "my workspace")            # a folder with a space in its name
        os.makedirs(os.path.join(q.WORKSPACE, ".screenshots", "look"))
        self.addCleanup(setattr, q, "WORKSPACE", self.saved)
        self.shot = os.path.join(q.WORKSPACE, ".screenshots", "look", "page-001.png")
        open(self.shot, "wb").write(b"\x89PNG\r\n\x1a\n")

    def test_the_path_becomes_a_picture(self):
        text = f"Opened http://x/\nScreenshot saved: {self.shot} (1100x640 px)\nTitle: x"
        self.assertEqual(CE.look_screenshots("mcp__orbit-look__browser_open", text), [".screenshots/look/page-001.png"])

    def test_only_look_tools_and_only_inside_the_workspace(self):
        text = f"Screenshot saved: {self.shot} (1x1 px)"
        self.assertEqual(CE.look_screenshots("Bash", text), [])
        outside = os.path.join(self.tmp, "elsewhere.png")
        open(outside, "wb").write(b"x")
        self.assertEqual(CE.look_screenshots("mcp__orbit-look__browser_screenshot", f"Screenshot saved: {outside} (1x1 px)"), [])
        self.assertEqual(CE.look_screenshots("mcp__orbit-look__browser_open", "Screenshot saved: /nope/missing.png (1x1 px)"), [])

    def test_a_reopened_chat_shows_it_too(self):
        import importlib.machinery, importlib.util
        loader = importlib.machinery.SourceFileLoader("orbit_ui_shots", os.path.join(os.path.dirname(HERE), "bin", "orbit-ui"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        ui = importlib.util.module_from_spec(spec); loader.exec_module(ui)
        text = f"Screenshot saved: {self.shot} (1x1 px)"
        shots = CE.look_screenshots("mcp__orbit-look__browser_open", text)
        msgs = [{"role": "user", "content": "go"},
                {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function",
                 "function": {"name": "mcp__orbit-look__browser_open", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "c1", "name": "mcp__orbit-look__browser_open", "ok": True,
                 "content": text + f"\n[created images: {', '.join(shots)}]"}]
        plots = [pl for m in ui.render(msgs) for pl in m.get("plots", [])]
        self.assertEqual(plots, ["/api/ws/.screenshots/look/page-001.png"])
