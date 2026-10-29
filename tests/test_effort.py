"""A chat's own effort: chosen next to the model, kept for that chat, and handed to Claude
Code as --effort. Nothing here starts Claude Code or calls a model."""
import os, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin"))

import qqcore as q                        # noqa: E402,F401  (binds claude_engine.Q)
import claude_engine as CE                # noqa: E402


def effort_of(argv):
    return argv[argv.index("--effort") + 1] if "--effort" in argv else None


class TestChatEffort(unittest.TestCase):
    def setUp(self):
        self.saved = dict(q.S)
        self.addCleanup(lambda: (q.S.clear(), q.S.update(self.saved)))
        # an earlier test in the run may have left an effort on this thread's turn context
        self.had = getattr(q.TURN_CTX, "effort", None)
        q.TURN_CTX.effort = None
        self.addCleanup(setattr, q.TURN_CTX, "effort", self.had)
        self.saved_prefs = CE.chat_prefs
        CE.chat_prefs = lambda sid=None: {"c1": {"reasoning_effort": "low"}}.get(sid, {}) if sid else {}
        self.addCleanup(setattr, CE, "chat_prefs", self.saved_prefs)

    def test_every_level_reaches_claude_code(self):
        for lvl in ("low", "medium", "high", "xhigh", "max"):
            self.assertEqual(effort_of(CE.build_argv(CE.DEFAULTS, effort=lvl)), lvl)

    def test_a_chat_that_picked_low_asks_for_low(self):
        self.assertEqual(CE._run_effort({"reasoning_effort": "low"}, "c1"), "low")

    def test_a_chat_that_never_picked_follows_claudes_own(self):
        q.S["reasoning_effort"] = "medium"          # Orbit's own value is always set: it must not be passed
        self.assertIsNone(CE._run_effort({}, "other"))
        self.assertIsNone(effort_of(CE.build_argv(CE.DEFAULTS, effort=CE._run_effort({}, "other"))))

    def test_orbits_own_setting_still_applies_when_it_is_a_step_up(self):
        q.S["reasoning_effort"] = "high"
        self.assertEqual(CE._run_effort({}, "other"), "high")

    def test_the_chats_choice_wins_over_orbits_setting(self):
        q.S["reasoning_effort"] = "max"
        self.assertEqual(CE._run_effort({"reasoning_effort": "low"}, "c1"), "low")


if __name__ == "__main__":
    unittest.main()
