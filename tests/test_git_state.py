"""What the folder a chat works in looks like to git — the line in the dock, and the
chip on the phone. Read-only: nothing here may commit, stage or touch the tree."""
import os, subprocess, sys, tempfile, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))
import qqcore as q


def git(folder, *a):
    return subprocess.run(["git", "-C", folder, *a], capture_output=True, text=True, check=True)


class TestGitState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orbit-git-")
        q._GIT_CACHE.clear()
        self.addCleanup(q._GIT_CACHE.clear)

    def repo(self):
        git(self.tmp, "init", "-q", "-b", "main")
        git(self.tmp, "config", "user.email", "t@example.invalid")
        git(self.tmp, "config", "user.name", "Test")
        open(os.path.join(self.tmp, "a.txt"), "w").write("one\n")
        git(self.tmp, "add", "a.txt")
        git(self.tmp, "commit", "-qm", "first")
        return self.tmp

    def test_a_folder_that_is_not_a_repository_says_so(self):
        st = q.git_state(self.tmp)
        self.assertFalse(st["repo"])
        self.assertNotIn("branch", st)

    def test_a_clean_repository(self):
        st = q.git_state(self.repo())
        self.assertTrue(st["repo"])
        self.assertEqual(st["branch"], "main")
        self.assertEqual(st["dirty"], 0)
        self.assertEqual(st["last"], "first")

    def test_it_counts_what_is_uncommitted(self):
        folder = self.repo()
        open(os.path.join(folder, "a.txt"), "a").write("two\n")
        open(os.path.join(folder, "new.txt"), "w").write("hello\n")
        st = q.git_state(folder, max_age=0)
        self.assertEqual(st["dirty"], 2)
        self.assertEqual(st["untracked"], 1)
        self.assertIn("1 file changed", st["diff"])

    def test_no_upstream_means_no_ahead_or_behind(self):
        """A branch that was never pushed has nothing to be ahead of, and the dock
        must not show it as level with something that does not exist."""
        st = q.git_state(self.repo())
        self.assertNotIn("ahead", st)
        self.assertNotIn("behind", st)

    def test_it_is_cached_for_a_few_seconds(self):
        """`git status` on a big repository is not free and the dock asks often."""
        folder = self.repo()
        first = q.git_state(folder)
        open(os.path.join(folder, "b.txt"), "w").write("x\n")
        self.assertEqual(q.git_state(folder)["dirty"], first["dirty"])
        self.assertEqual(q.git_state(folder, max_age=0)["dirty"], 1)

    def test_the_caller_cannot_corrupt_the_cache(self):
        folder = self.repo()
        q.git_state(folder)["branch"] = "tampered"
        self.assertEqual(q.git_state(folder)["branch"], "main")

    def test_a_folder_that_is_not_there_is_not_an_exception(self):
        st = q.git_state(os.path.join(self.tmp, "no", "such", "place"))
        self.assertFalse(st["repo"])

    def test_it_changes_nothing(self):
        folder = self.repo()
        open(os.path.join(folder, "a.txt"), "a").write("two\n")
        before = git(folder, "status", "--porcelain").stdout
        q.git_state(folder, max_age=0)
        self.assertEqual(git(folder, "status", "--porcelain").stdout, before)
        self.assertEqual(len(git(folder, "log", "--oneline").stdout.splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
