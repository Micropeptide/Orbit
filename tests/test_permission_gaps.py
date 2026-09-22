"""Three ways an action could slip past the autonomy gates, each found by reading
Z.ai's ZCode (Apache-2.0) and checking whether Orbit had the same hole. It did.
Nothing here runs a tool; only the decision functions are asked."""
import json, os, shutil, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))
import qqcore as q


class TestNeverAutoCannotBeSuffixed(unittest.TestCase):
    """REGRESSION: risk_check appends "(inside workspace)" to the reason, and the
    never-auto test compared the whole sentence. So "rewriting git history" was
    refused and "rewriting git history (inside workspace)" was allowed — naming the
    workspace in the command turned every never-auto action into an automatic one."""

    def test_the_suffix_does_not_launder_a_never_auto_reason(self):
        for reason in sorted(q.NEVER_AUTO):
            self.assertTrue(q._never_auto("run_shell", reason), reason)
            self.assertTrue(q._never_auto("run_shell", f"{reason} {q.INSIDE_WS}"),
                            f"{reason} laundered by the suffix")

    def test_a_never_auto_action_naming_the_workspace_still_asks(self):
        ws = os.path.abspath(q.WORKSPACE)
        args = {"command": f"cd {ws} && git filter-branch --all"}
        level, why = q.risk_check("run_shell", args)
        self.assertEqual(level, "confirm")
        self.assertFalse(q._auto_approvable("run_shell", args, why))   # autonomy "auto"
        self.assertTrue(q._never_auto("run_shell", why))               # autonomy "full"

    def test_self_modification_is_never_automatic(self):
        for fn in sorted(q.NEVER_AUTO_FNS):
            self.assertTrue(q._never_auto(fn, "anything at all"))


class TestWorkspaceContainment(unittest.TestCase):
    """REGRESSION: "inside the workspace" was `workspace_path in " ".join(args)`. One
    mention of the workspace anywhere in any argument downgraded the whole call."""

    def setUp(self):
        self.ws = os.path.abspath(q.WORKSPACE)

    def test_a_path_outside_disqualifies_the_whole_call(self):
        args = {"command": f"rm -rf ~/Documents {self.ws}/tmp"}
        self.assertFalse(q._confined_to_workspace(args))
        self.assertFalse(q._auto_approvable("run_shell", args, q.risk_check("run_shell", args)[1]))

    def test_a_call_that_is_really_inside_still_runs_unattended(self):
        args = {"command": f"rm -rf {self.ws}/build"}
        self.assertTrue(q._confined_to_workspace(args))
        self.assertTrue(q._auto_approvable("run_shell", args, q.risk_check("run_shell", args)[1]))

    def test_naming_no_path_at_all_does_not_qualify(self):
        self.assertFalse(q._confined_to_workspace({"command": "rm -rf build"}))
        self.assertFalse(q._confined_to_workspace({}))

    def test_a_sibling_directory_is_not_inside(self):
        self.assertFalse(q._confined_to_workspace({"path": self.ws + "-other/x"}))
        self.assertTrue(q._confined_to_workspace({"path": os.path.join(self.ws, "x")}))

    def test_a_path_argument_counts_as_well_as_a_command(self):
        self.assertTrue(q._confined_to_workspace({"path": os.path.join(self.ws, "a.txt")}))
        self.assertFalse(q._confined_to_workspace({"path": "~/.ssh/id_rsa"}))


class TestRulePatternsMatchTheSubject(unittest.TestCase):
    """REGRESSION: a rule's pattern was matched against the tool's *name* as well as
    against what the call does. An allow rule of "python*" — meant for a shell command
    — also matched the `python` tool, handing over arbitrary code execution."""

    def rule(self, pattern, tool="*"):
        return [{"tool": tool, "pattern": pattern, "note": ""}]

    def test_a_command_pattern_does_not_match_the_tool_name(self):
        self.assertIsNone(q._rule_match(self.rule("python*"), "python", {"code": "import os"}))
        self.assertIsNotNone(q._rule_match(self.rule("python*"), "run_shell",
                                           {"command": "python build.py"}))

    def test_an_exact_tool_name_still_means_that_whole_tool(self):
        self.assertIsNotNone(q._rule_match(self.rule("read_file"), "read_file", {"path": "/etc/hosts"}))

    def test_a_rule_scoped_to_one_tool_does_not_leak_to_another(self):
        self.assertIsNone(q._rule_match(self.rule("*", tool="read_file"), "run_shell",
                                        {"command": "rm -rf /"}))


class TestTaggingAChatCannotTruncateIt(unittest.TestCase):
    """REGRESSION: session_meta rewrote the whole transcript with a plain open(w) —
    a crash or a concurrent save from the running answer cut the file in half."""

    def test_the_transcript_survives_a_metadata_write(self):
        tmp = tempfile.mkdtemp(prefix="orbit-meta-")
        self.addCleanup(shutil.rmtree, tmp, True)
        saved = q.SESSIONS
        q.SESSIONS = tmp
        self.addCleanup(setattr, q, "SESSIONS", saved)
        sid = "20260920-000000-test"
        msgs = [{"role": "user", "content": "x" * 5000} for _ in range(20)]
        with open(q.session_path(sid), "w") as fh:
            json.dump({"messages": msgs, "title": "before"}, fh)
        out = q.session_meta(sid, title="after", pinned=True)
        self.assertEqual(out["title"], "after")
        again = json.load(open(q.session_path(sid)))
        self.assertEqual(len(again["messages"]), 20)      # nothing lost
        self.assertTrue(again["pinned"])
        # nothing left behind to be mistaken for a session
        self.assertEqual([f for f in os.listdir(tmp) if f.endswith(".tmp")], [])


class TestClaudesClassifierIsNotUsedOnALocalModel(unittest.TestCase):
    """A chat kept answering "cannot determine the safety of Bash". Claude Code's "auto"
    permission mode asks the *model* to classify each tool call, it times out at 60s, and
    a classifier that times out refuses the tool.

    This was first read as a local-model problem -- a model on this Mac waits behind the
    very turn that is asking it. It is not: the same thing happened on a small free model
    reached through the harness, which is nowhere near this Mac. What the two share is
    that the model being asked is the model doing the work. A real Claude subscription is
    the exception, because there the classifying is done for you and quickly, so that one
    keeps Claude's own."""

    def modes(self, kind):
        argv = q.CE.build_argv(dict(q.CE.DEFAULTS), kind=kind, mode="auto")
        return argv[argv.index("--permission-mode") + 1] if "--permission-mode" in argv else "default"

    def test_a_local_model_gets_orbits_own_gate_instead(self):
        self.assertEqual(self.modes("local"), "default")

    def test_and_so_does_a_model_reached_through_the_harness(self):
        self.assertEqual(self.modes("provider"), "default")

    def test_but_a_claude_subscription_keeps_claudes_own(self):
        self.assertEqual(self.modes("subscription"), "auto")

    def test_orbits_own_gate_is_attached_whichever_way(self):
        """Replacing Claude's classifier only helps because something else answers the
        question. Orbit's does, in microseconds, and it is on the command line either way."""
        for kind in ("local", "provider", "subscription"):
            with self.subTest(kind=kind):
                argv = q.CE.build_argv(dict(q.CE.DEFAULTS), kind=kind, mode="auto")
                self.assertIn("--permission-prompt-tool", argv)

    def test_the_modes_you_chose_yourself_are_untouched(self):
        """Only "auto" is the model's own judgement; the rest are the user's."""
        for kind in ("local", "provider"):
            for mode in ("plan", "acceptEdits", "bypassPermissions"):
                with self.subTest(kind=kind, mode=mode):
                    argv = q.CE.build_argv(dict(q.CE.DEFAULTS), kind=kind, mode=mode)
                    self.assertEqual(argv[argv.index("--permission-mode") + 1], mode)

    def test_other_modes_are_untouched_on_the_local_model(self):
        for mode in ("plan", "acceptEdits", "bypassPermissions"):
            argv = q.CE.build_argv(dict(q.CE.DEFAULTS), kind="local", mode=mode)
            self.assertEqual(argv[argv.index("--permission-mode") + 1], mode)


if __name__ == "__main__":
    unittest.main()
