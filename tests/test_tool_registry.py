"""Every tool Orbit offers has to exist, and everything that exists has to be offered.

A schema with no implementation is a call the model will make and Orbit will fail; an
implementation with no schema is dead code that still has to be read and maintained.
Both are easy to create and neither shows up until a model happens to try it — and a
schema costs tokens in every single request, whether or not anything can run it."""
import os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))
import qqcore as q


class TestSpecsAndImplementationsAgree(unittest.TestCase):
    def setUp(self):
        self.names = [t["function"]["name"] for t in q.ALL_SPECS]

    def test_every_offered_tool_can_run(self):
        missing = [n for n in self.names if n not in q.BUILTIN]
        self.assertEqual(missing, [], "offered to the model with nothing behind them")

    def test_every_implementation_is_offered(self):
        extra = [n for n in q.BUILTIN if n not in self.names]
        self.assertEqual(extra, [], "implemented but never offered — dead weight")

    def test_no_tool_is_offered_twice(self):
        dupes = sorted({n for n in self.names if self.names.count(n) > 1})
        self.assertEqual(dupes, [], "the same name twice in the schema list")

    def test_every_schema_is_well_formed(self):
        for t in q.ALL_SPECS:
            f = t.get("function") or {}
            with self.subTest(tool=f.get("name")):
                self.assertEqual(t.get("type"), "function")
                self.assertTrue((f.get("description") or "").strip(), "no description")
                p = f.get("parameters") or {}
                self.assertEqual(p.get("type"), "object")
                self.assertIsInstance(p.get("properties"), dict)
                for req in p.get("required") or []:
                    self.assertIn(req, p["properties"], "required but not a property")


class TestTheListsThatNameTools(unittest.TestCase):
    """Several settings and safety lists name tools. A name that no longer exists in
    one of them is a rule that silently applies to nothing."""

    def setUp(self):
        self.known = {t["function"]["name"] for t in q.ALL_SPECS}

    def test_easy_mode_keeps_tools_that_exist(self):
        for n in q.S.get("easy_tools") or []:
            self.assertIn(n, self.known, f"easy mode keeps {n}, which is not a tool")

    def test_the_parallel_list_names_tools_that_exist(self):
        for n in q.PARALLEL_SAFE:
            self.assertIn(n, self.known, f"{n} may run in parallel but is not a tool")

    def test_the_never_auto_list_names_tools_that_exist(self):
        for n in q.NEVER_AUTO_FNS:
            self.assertIn(n, self.known, f"{n} always asks but is not a tool")

    def test_the_untrusted_list_names_tools_that_exist(self):
        for n in q.UNTRUSTED_TOOLS:
            if n.startswith("paperfetch_"): continue
            self.assertIn(n, self.known, f"{n}'s output is fenced but it is not a tool")

    def test_the_output_budget_names_tools_that_exist(self):
        for n in q.TOOL_BUDGET:
            self.assertIn(n, self.known, f"{n} has an output budget but is not a tool")

    def test_the_writing_tools_exist(self):
        for n in q._WRITE_TOOLS:
            self.assertIn(n, self.known, f"{n} is treated as a writing tool but is not a tool")


class TestTheHelperProfile(unittest.TestCase):
    """A helper is sent to find something out. It has no plan of its own and nobody is
    watching it, so by default it may read, search and fetch and change nothing — its
    mistakes belong in its report, not in your tree."""

    def setUp(self):
        self.known = {t["function"]["name"] for t in q.ALL_SPECS}

    def test_the_explore_profile_names_tools_that_exist(self):
        for n in q.TASK_PROFILES["explore"]:
            self.assertIn(n, self.known, f"a helper may use {n}, which is not a tool")

    def test_and_none_of_them_writes(self):
        for n in q.TASK_PROFILES["explore"]:
            self.assertNotIn(n, q._WRITE_TOOLS, f"{n} can change things")
            self.assertFalse(q._changes_things(n), n)

    def test_the_task_tool_offers_the_choice(self):
        spec = next(t for t in q.ALL_SPECS if t["function"]["name"] == "task")
        opts = spec["function"]["parameters"]["properties"]["profile"]["enum"]
        self.assertEqual(sorted(opts), ["build", "explore"])


if __name__ == "__main__":
    unittest.main()
