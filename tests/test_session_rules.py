"""«Yes, and stop asking» used to mean forever, written to settings. Most of the time it
means "for the next twenty minutes" — and a grant you cannot mean loosely is one people
reach for the permanent version of instead."""
import os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))
import qqcore as q


class TestSessionRules(unittest.TestCase):
    def setUp(self):
        q.SESSION_RULES.clear()
        self.addCleanup(q.SESSION_RULES.clear)
        self.saved = getattr(q.TURN_CTX, "sid", None)
        self.addCleanup(setattr, q.TURN_CTX, "sid", self.saved)
        q.TURN_CTX.sid = "chat-1"

    def test_it_allows_the_thing_it_was_asked_about(self):
        self.assertIsNone(q.allowed_by_rule("run_shell", {"command": "pytest -q"}))
        q.add_session_rule("run_shell", "pytest*")
        hit = q.allowed_by_rule("run_shell", {"command": "pytest -q"})
        self.assertIsNotNone(hit)
        self.assertIn("this chat", hit["note"])

    def test_it_does_not_leak_into_another_chat(self):
        q.add_session_rule("run_shell", "pytest*")
        q.TURN_CTX.sid = "chat-2"
        self.assertIsNone(q.allowed_by_rule("run_shell", {"command": "pytest -q"}))

    def test_it_is_gone_when_the_chat_is(self):
        q.add_session_rule("run_shell", "pytest*")
        q.drop_session_rules()
        self.assertIsNone(q.allowed_by_rule("run_shell", {"command": "pytest -q"}))

    def test_nothing_is_written_to_settings(self):
        before = dict(q.S.get("permission_rules") or {})
        q.add_session_rule("run_shell", "pytest*")
        self.assertEqual(dict(q.S.get("permission_rules") or {}), before)

    def test_a_permanent_rule_still_works(self):
        q.TURN_CTX.sid = "chat-3"
        saved = q.S.get("permission_rules")
        q.S["permission_rules"] = {"allow": [{"tool": "read_file", "pattern": "*"}], "deny": []}
        self.addCleanup(q.S.__setitem__, "permission_rules", saved)
        self.assertIsNotNone(q.allowed_by_rule("read_file", {"path": "/etc/hosts"}))

    def test_a_session_rule_cannot_reach_past_a_deny(self):
        """Allow only ever pre-answers a question that would have been asked; a denied
        action stays denied."""
        saved = q.S.get("permission_rules")
        q.S["permission_rules"] = {"allow": [], "deny": [{"tool": "*", "pattern": "*rm -rf*"}]}
        self.addCleanup(q.S.__setitem__, "permission_rules", saved)
        q.add_session_rule("run_shell", "*")
        level, _ = q.risk_check("run_shell", {"command": "rm -rf /tmp/x"})
        self.assertEqual(level, "block")


if __name__ == "__main__":
    unittest.main()
