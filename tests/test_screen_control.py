"""Claude Code (and Codex) chats can see and drive this Mac's screen through the look server.

Nothing here touches the real screen: the click tool is pointed at a fake cliclick and the
screenshot at a fake screencapture."""
import importlib.machinery, importlib.util, json, os, shutil, stat, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))

import qqcore as q
import claude_engine as CE

LOOK_PATH = os.path.join(os.path.dirname(HERE), "bin", "orbit-look")


def load_look():
    loader = importlib.machinery.SourceFileLoader("orbit_look_screen", LOOK_PATH)
    spec = importlib.util.spec_from_loader("orbit_look_screen", loader)
    mod = importlib.util.module_from_spec(spec)
    keep, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try: loader.exec_module(mod)
    finally: sys.dont_write_bytecode = keep
    return mod


look = load_look()
ACTIONS = ("screen_click", "screen_move", "screen_drag", "screen_type", "screen_key", "screen_scroll")


class Switch(unittest.TestCase):
    def setUp(self):
        self.saved = dict(q.S)
        self.addCleanup(lambda: (q.S.clear(), q.S.update(self.saved)))
        for k in ("look_engines", "look_groups", "computer_use_enabled"): q.S.pop(k, None)


class TestWhoGetsTheScreen(Switch):
    def test_off_by_default(self):
        self.assertNotIn("screen", q.look_env("claude")["ORBIT_LOOK_GROUPS"].split(","))

    def test_on_for_claude_and_codex_only(self):
        q.S["computer_use_enabled"] = True
        for e in ("claude", "codex"):
            self.assertIn("screen", q.look_server(e)["env"]["ORBIT_LOOK_GROUPS"].split(","), e)
        for e in ("opencode", "orbit", None):                 # no approval step there / built in already
            self.assertNotIn("screen", q.look_server(e)["env"]["ORBIT_LOOK_GROUPS"].split(","), e)

    def test_screen_alone_is_enough_to_start_the_server(self):
        q.S["computer_use_enabled"] = True
        q.S["look_groups"] = []
        self.assertTrue(q.look_enabled("claude"))
        self.assertFalse(q.look_enabled("opencode"))

    def test_the_server_lists_the_tools_only_when_asked(self):
        with mock.patch.dict(os.environ, {"ORBIT_LOOK_GROUPS": "browser,simulator,mac"}):
            self.assertFalse([n for n in look.enabled_tools() if n.startswith("screen_")])
        with mock.patch.dict(os.environ, {"ORBIT_LOOK_GROUPS": "mac,screen"}):
            self.assertEqual({n for n in look.enabled_tools() if n.startswith("screen_")}, {"screen_look", *ACTIONS})


class TestTheGate(unittest.TestCase):
    def ctx(self, **kw):
        return {"cfg": dict(CE.DEFAULTS), "read_only": False, "emit": lambda k, p: None, "approve": None, "ask": None, **kw}

    def test_looking_is_free_acting_asks(self):
        self.assertTrue(CE.decide("mcp__orbit-look__screen_look", {}, self.ctx())[0])
        for name in ACTIONS:
            self.assertFalse(CE.decide("mcp__orbit-look__" + name, {"x": 1, "y": 1}, self.ctx())[0], name)   # nobody to ask

    def test_the_person_can_allow_one(self):
        asked = []

        def approve(fn, args, reason, *rest):
            asked.append((fn, args))
            return True
        got = CE.decide("mcp__orbit-look__screen_click", {"x": 5, "y": 6}, self.ctx(approve=approve))
        self.assertTrue(got[0])
        self.assertEqual(asked[0][0], "screen_click")
        self.assertEqual(asked[0][1], {"x": 5, "y": 6})

    def test_plan_mode_refuses_them(self):
        ok, msg, *_ = CE.decide("mcp__orbit-look__screen_type", {"text": "hi"}, self.ctx(read_only=True))
        self.assertFalse(ok)
        self.assertIn("Plan mode", msg)
        self.assertTrue(CE.decide("mcp__orbit-look__screen_look", {}, self.ctx(read_only=True))[0])

    def test_the_screenshot_shows_in_the_chat(self):
        root = tempfile.mkdtemp(prefix="orbit-ws-")
        self.addCleanup(shutil.rmtree, root, True)
        shot = os.path.join(root, "s.png")
        open(shot, "wb").write(b"x")
        with mock.patch.object(q, "WORKSPACE", root):
            self.assertEqual(CE.look_screenshots("mcp__orbit-look__screen_look", f"Screenshot saved: {shot} (10x10 px)."), ["s.png"])


class TestClaudeIsToldAboutIt(Switch):
    def note(self):
        return str(CE._orbit_append(None, dict(CE.DEFAULTS), [], None, "local", look=True))

    def test_the_prompt_names_the_tools_when_screen_control_is_on(self):
        self.assertNotIn("screen_look", self.note())
        q.S["computer_use_enabled"] = True
        self.assertIn("mcp__orbit-look__screen_", self.note())


class TestTheTools(unittest.TestCase):
    """The tools against a fake cliclick that records what it was asked."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orbit-screen-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.log = os.path.join(self.tmp, "calls.txt")
        fake = os.path.join(self.tmp, "cliclick")
        open(fake, "w").write('#!/bin/sh\necho "$@" >> %s\n' % self.log)
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IXUSR)
        for p in (mock.patch.object(look, "cliclick_path", lambda: fake),
                  mock.patch.object(look, "screen_points", lambda: (1000, 600))):
            p.start(); self.addCleanup(p.stop)

    def calls(self):
        return open(self.log).read().splitlines() if os.path.exists(self.log) else []

    def run_tool(self, name, **args):
        return look.TOOLS[name]["fn"](**args)

    def test_click_forms(self):
        self.run_tool("screen_click", x=10, y=20)
        self.run_tool("screen_click", x=10, y=20, clicks=2)
        self.run_tool("screen_click", x=10, y=20, button="right")
        self.assertEqual(self.calls(), ["c:10,20", "dc:10,20", "rc:10,20"])

    def test_off_screen_is_refused_with_the_size(self):
        with self.assertRaises(look.ToolError) as cm: self.run_tool("screen_click", x=5000, y=5)
        self.assertIn("1000x600", str(cm.exception))
        self.assertEqual(self.calls(), [])

    def test_bad_button_and_double_right_click(self):
        with self.assertRaises(look.ToolError): self.run_tool("screen_click", x=1, y=1, button="middle")
        with self.assertRaises(look.ToolError): self.run_tool("screen_click", x=1, y=1, button="right", clicks=2)

    def test_drag_and_move(self):
        self.run_tool("screen_drag", x1=1, y1=2, x2=30, y2=40)
        self.run_tool("screen_move", x=7, y=8)
        self.assertEqual(self.calls(), ["dd:1,2 dm:30,40 du:30,40", "m:7,8"])

    def test_typing_and_keys(self):
        self.run_tool("screen_type", text="hello world")
        self.run_tool("screen_key", key="cmd+shift+a")
        self.run_tool("screen_key", key="Return")
        self.run_tool("screen_key", key="escape")
        self.assertEqual(self.calls(), ["t:hello world", "kd:cmd,shift t:a ku:cmd,shift", "kp:return", "kp:esc"])
        with self.assertRaises(look.ToolError): self.run_tool("screen_key", key="hyper+a")
        with self.assertRaises(look.ToolError): self.run_tool("screen_type", text="")

    def test_a_refusal_from_macos_says_what_to_allow(self):
        with mock.patch.object(look, "run_cmd", lambda *a, **k: (1, "", "")):
            with self.assertRaises(look.ToolError) as cm: self.run_tool("screen_click", x=1, y=1)
        self.assertIn("Accessibility", str(cm.exception))

    def test_scroll_down_is_a_negative_wheel(self):
        seen = []

        def fake(cmd, timeout=30, env=None):
            seen.append(cmd)
            return 0, "ok", ""
        with mock.patch.object(look, "run_cmd", fake):
            self.assertIn("down", self.run_tool("screen_scroll", amount=4))
            self.assertIn("up", self.run_tool("screen_scroll", amount=-2))
        self.assertIn(",-4)", seen[0][-1])
        self.assertIn(",2)", seen[1][-1])
        with self.assertRaises(look.ToolError): self.run_tool("screen_scroll", x=5)

    def test_the_look_result_has_an_image_and_a_saved_path(self):
        shots = os.path.join(self.tmp, "shots")
        png = look.__dict__  # noqa
        import base64
        tiny = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")

        def fake(cmd, timeout=30, env=None):
            if cmd[0] == "screencapture": open(cmd[-1], "wb").write(tiny * 40)
            return 0, "", ""
        with mock.patch.dict(os.environ, {"ORBIT_LOOK_DIR": shots}), mock.patch.object(look, "run_cmd", fake), \
                mock.patch.object(look, "png_size", lambda p: (1000, 600)), mock.patch.object(look, "finish_shot", lambda p: (p, 1000, 600)):
            res = self.run_tool("screen_look")
        self.assertEqual(res[1]["type"], "image")
        self.assertRegex(res[0]["text"], r"Screenshot saved: .+\.png \(1000x600 px\)")
        self.assertIn("1000x600 points", res[0]["text"])


if __name__ == "__main__":
    unittest.main()
