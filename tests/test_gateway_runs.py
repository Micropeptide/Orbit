"""A Claude Code run that goes through Orbit's gateway (or any provider's endpoint) is told
not to wait for Anthropic's server-side auto-mode checks, which cannot reach it there.
Your own Claude subscription talks to Anthropic directly and keeps them."""
import os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))

import claude_engine as CE


class TestAutoModeServerChecks(unittest.TestCase):
    def test_a_run_through_the_gateway_does_not_wait_for_them(self):
        env = CE.harness_env("http://127.0.0.1:8897/h/opencode-go", "m", 128000)
        self.assertEqual(env["CLAUDE_CODE_AUTO_MODE_SERVER"], "0")

    def test_a_provider_endpoint_is_the_same(self):
        env = CE.harness_env("https://api.deepseek.com/anthropic", "m", 128000, auth={"ANTHROPIC_AUTH_TOKEN": "k"})
        self.assertEqual(env["CLAUDE_CODE_AUTO_MODE_SERVER"], "0")

    def test_the_subscription_talks_to_anthropic_and_is_left_alone(self):
        env = CE.harness_env(None, "sonnet", 200000)
        self.assertNotIn("CLAUDE_CODE_AUTO_MODE_SERVER", env)


if __name__ == "__main__":
    unittest.main()
