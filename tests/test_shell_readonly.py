"""`run_shell` is the one tool that is not read-only or not by its name: the same tool
runs `ls` and `rm -rf`. Classifying the command line is what lets three greps and a
`git log` share a round, and stops them asking three times for nothing.

Unknown is never "safe" here. A command nobody has written a rule for falls through to
asking, exactly as it did before there was a classifier."""
import os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))
import qqcore as q


class TestReadOnlyShell(unittest.TestCase):
    def reads(self, cmd): return q._shell_is_readonly(cmd)

    def test_plain_reads(self):
        for c in ("ls -la", "cat notes.md", "grep -rn todo .", "rg pattern src/",
                  "wc -l *.py", "head -20 log.txt", "du -sh .", "jq . data.json",
                  "git log --oneline", "git status", "git diff --stat", "find . -name '*.py'"):
            self.assertIs(self.reads(c), True, c)

    def test_several_reads_on_one_line(self):
        self.assertIs(self.reads("cat a && grep b c"), True)
        self.assertIs(self.reads("echo hi; wc -l f"), True)
        self.assertIs(self.reads("cat f | jq . | head -5"), True)

    def test_one_writer_on_the_line_is_enough(self):
        self.assertIs(self.reads("grep x f && rm -rf build"), None)
        self.assertIs(self.reads("cat a; git push"), False)

    def test_a_redirect_writes(self):
        for c in ("ls > out.txt", "cat a >> b", "cat f | tee out.txt"):
            self.assertIs(self.reads(c), False, c)

    def test_the_flag_that_changes_everything(self):
        self.assertIs(self.reads("sed s/a/b/ f.py"), True)
        self.assertIs(self.reads("sed -i s/a/b/ f.py"), False)
        self.assertIs(self.reads("find . -name x"), True)
        self.assertIs(self.reads("find . -delete"), False)
        self.assertIs(self.reads("find . -exec rm {} ;"), False)
        self.assertIs(self.reads("git config a.b"), True)
        self.assertIs(self.reads("git config --unset a.b"), False)

    def test_git_dash_c_can_run_anything(self):
        """`git -c core.pager=sh log` runs a shell, so it is not a read."""
        self.assertIs(self.reads("git -c core.pager=sh log"), False)
        self.assertIs(self.reads("git --git-dir=/tmp/x log"), False)

    def test_an_interpreter_only_reads_when_asked_its_version(self):
        self.assertIs(self.reads("python3 -V"), True)
        self.assertIs(self.reads("python3 build.py"), False)
        self.assertIs(self.reads("pip list"), True)
        self.assertIs(self.reads("pip install requests"), False)

    def test_an_unknown_command_claims_nothing(self):
        for c in ("rm -rf build", "samtools sort in.bam", "./configure", ""):
            self.assertIsNone(self.reads(c), c)

    def test_a_wrapper_does_not_hide_the_command(self):
        self.assertIs(self.reads("env ls -la"), True)
        self.assertIs(self.reads("nice git log"), True)
        self.assertIs(self.reads("env git push"), False)


class TestWhatItUnlocks(unittest.TestCase):
    def setUp(self):
        self.saved = dict(q.S)
        self.addCleanup(lambda: (q.S.clear(), q.S.update(self.saved)))
        q.S["autonomy_mode"] = "auto"
        q.S["shell_enabled"] = True
        q.S["permission_rules"] = {"allow": [], "deny": []}

    def test_reads_can_share_a_round(self):
        self.assertTrue(q._parallel_ok("run_shell", {"command": "git log --oneline"}))
        self.assertTrue(q._parallel_ok("run_shell", {"command": "grep -rn x ."}))

    def test_and_writes_cannot(self):
        self.assertFalse(q._parallel_ok("run_shell", {"command": "rm -rf build"}))
        self.assertFalse(q._parallel_ok("run_shell", {"command": "sed -i s/a/b/ f"}))

    def test_a_read_does_not_need_approving(self):
        self.assertTrue(q._auto_approvable("run_shell", {"command": "git status"}, ""))

    def test_a_command_nobody_classified_still_asks(self):
        """Unknown is not safe: it is simply not claimed, and everything else decides."""
        self.assertIsNone(q._shell_is_readonly("samtools sort in.bam"))
        self.assertFalse(q._parallel_ok("run_shell", {"command": "samtools sort in.bam"}))
        cmd = "rm -rf /tmp/somewhere-else"
        lvl, why = q.risk_check("run_shell", {"command": cmd})
        self.assertEqual(lvl, "confirm")
        self.assertFalse(q._auto_approvable("run_shell", {"command": cmd}, why))

    def test_a_deny_rule_still_wins(self):
        q.S["permission_rules"] = {"allow": [],
                                   "deny": [{"tool": "run_shell", "pattern": "*git*", "note": "no"}]}
        self.assertFalse(q._parallel_ok("run_shell", {"command": "git log"}))


if __name__ == "__main__":
    unittest.main()
