"""scripts/seed-demo: a scripted mock model + invented demo chats for the sandbox.

The generator (seed_demo.py) is what fills the sandbox; the bash wrapper around it
(starts the sandbox + the mock server) is exercised by hand. Here we run the generator
against a throwaway data folder and check the demo data it writes is well-formed and
has the shapes the UI and the rest of the suite test against.
"""
import json, os, shutil, subprocess, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEN = os.path.join(ROOT, "scripts", "seed_demo.py")
DEMO = ("demo-long", "demo-tools", "demo-failed", "demo-goal", "demo-plain")


class TestSeedDemo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.tmp, True)
        os.makedirs(os.path.join(self.tmp, "config")); os.makedirs(os.path.join(self.tmp, "sessions"))
        r = subprocess.run([sys.executable, GEN, self.tmp, "8999"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, "seed_demo.py failed: %s" % r.stderr)

    def sess(self, name):
        return json.load(open(os.path.join(self.tmp, "sessions", name + ".json")))

    def cfg(self, name):
        return json.load(open(os.path.join(self.tmp, "config", name)))

    def test_writes_all_five_demo_sessions(self):
        for name in DEMO:
            d = self.sess(name)
            self.assertEqual(d["schema"], 2, name)
            self.assertTrue(len(d["messages"]) >= 3, name)
            self.assertTrue(d["title"], name)
        # the long chat really is ~1,700 messages
        self.assertGreaterEqual(len(self.sess("demo-long")["messages"]), 1700)

    def test_long_chat_has_tool_calls_with_diffs(self):
        msgs = self.sess("demo-long")["messages"]
        calls = [m for m in msgs if m.get("role") == "assistant" and m.get("tool_calls")]
        diffs = [m for m in msgs if m.get("role") == "tool" and m.get("diff")]
        self.assertTrue(calls, "no tool calls in the long chat")
        self.assertTrue(diffs, "no diffs in the long chat")
        # every tool_call has a matching tool result
        ids = {c["id"] for c in calls for c in c["tool_calls"]}
        got = {m["tool_call_id"] for m in msgs if m.get("role") == "tool"}
        self.assertTrue(ids <= got, "a tool call has no result")

    def test_tools_chat_has_diffs_and_a_plot(self):
        msgs = self.sess("demo-tools")["messages"]
        self.assertGreaterEqual(len([m for m in msgs if m.get("role") == "tool" and m.get("diff")]), 2)
        self.assertTrue(any(m.get("role") == "tool" and m.get("images") for m in msgs), "no plot image")

    def test_failed_chat_has_tool_and_model_errors(self):
        msgs = self.sess("demo-failed")["messages"]
        self.assertGreaterEqual(len([m for m in msgs if m.get("role") == "tool" and m.get("ok") is False]), 2)
        self.assertTrue(any(m.get("role") == "assistant" and m.get("error") for m in msgs), "no model error")

    def test_goal_chat_has_a_goal_and_a_scheduled_message(self):
        d = self.sess("demo-goal")
        self.assertTrue(d.get("goal") and d["goal"].get("text"))
        self.assertTrue(d.get("queue"))
        self.assertIn("at", d["queue"][0])

    def test_registers_mock_model_projects_and_crew(self):
        cfg = self.cfg("models.json")
        self.assertEqual(cfg["providers"]["mock"]["kind"], "anthropic")
        self.assertTrue(cfg["providers"]["mock"]["base_url"].startswith("http://127.0.0.1:"))
        self.assertTrue(any(m.get("provider") == "mock" for m in cfg["models"]))
        projects = self.cfg("projects.json")
        for name in ("demo-long", "demo-tools", "demo-failed", "demo-goal"):
            self.assertIn(name, projects)
        self.assertIn("demo-crew", self.cfg("crews.json"))

    def test_rerun_is_idempotent(self):
        before = set(os.listdir(os.path.join(self.tmp, "sessions")))
        r = subprocess.run([sys.executable, GEN, self.tmp, "8999"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(before, set(os.listdir(os.path.join(self.tmp, "sessions"))), "re-seeding duplicated chats")


if __name__ == "__main__":
    unittest.main()
