"""«Let pytest run here» is the natural size of a permission grant, and Orbit could only
say it everywhere. Rules now live with the project too — narrowing only, never widening."""
import json, os, shutil, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))
import qqcore as q


class TestProjectRules(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orbit-projrule-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = q.PROJECTS
        q.PROJECTS = os.path.join(self.tmp, "projects.json")
        self.addCleanup(setattr, q, "PROJECTS", saved)
        json.dump({"p1": {"name": "Assays"}, "p2": {"name": "Other"}}, open(q.PROJECTS, "w"))
        self.here = q.current_project
        q.current_project = lambda: "p1"
        self.addCleanup(setattr, q, "current_project", self.here)
        q.SESSION_RULES.clear()
        self.addCleanup(q.SESSION_RULES.clear)

    def test_a_rule_applies_in_its_own_project(self):
        self.assertIsNone(q.allowed_by_rule("run_shell", {"command": "pytest -q"}))
        q.add_project_rule("allow", "run_shell", "pytest*")
        hit = q.allowed_by_rule("run_shell", {"command": "pytest -q"})
        self.assertIsNotNone(hit)
        self.assertIn("this project", hit["note"])

    def test_and_nowhere_else(self):
        q.add_project_rule("allow", "run_shell", "pytest*")
        q.current_project = lambda: "p2"
        self.assertIsNone(q.allowed_by_rule("run_shell", {"command": "pytest -q"}))
        q.current_project = lambda: None
        self.assertIsNone(q.allowed_by_rule("run_shell", {"command": "pytest -q"}))

    def test_a_project_deny_is_honoured(self):
        q.add_project_rule("deny", "run_shell", "*curl*")
        self.assertIsNotNone(q.denied_by_rule("run_shell", {"command": "curl example.com"}))

    def test_a_project_cannot_undo_a_global_deny(self):
        """A project may narrow what is allowed; it may not widen it."""
        saved = q.S.get("permission_rules")
        q.S["permission_rules"] = {"allow": [], "deny": [{"tool": "*", "pattern": "*rm -rf*"}]}
        self.addCleanup(q.S.__setitem__, "permission_rules", saved)
        q.add_project_rule("allow", "run_shell", "*")
        level, _ = q.risk_check("run_shell", {"command": "rm -rf /tmp/x"})
        self.assertEqual(level, "block")

    def test_it_is_written_where_the_project_lives(self):
        q.add_project_rule("allow", "run_shell", "pytest*", note="tests here")
        saved = json.load(open(q.PROJECTS))
        self.assertEqual(saved["p1"]["permission_rules"]["allow"][0]["pattern"], "pytest*")
        self.assertNotIn("permission_rules", saved["p2"])

    def test_no_project_no_rule(self):
        q.current_project = lambda: None
        self.assertEqual(q.add_project_rule("allow", "run_shell", "*"), [])


if __name__ == "__main__":
    unittest.main()
