"""A chat in a copy of its own: a git worktree on its own branch, merged back or thrown
away. Every repository here is a temporary one."""
import os, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))

import worktree as WT


def git(cwd, *a):
    return subprocess.run(["git", "-C", cwd, *a], capture_output=True, text=True, check=True).stdout.strip()


class Repo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orbit-wt-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = os.path.join(self.tmp, "proj"); os.makedirs(os.path.join(self.repo, "src"))
        self.home = os.path.join(self.tmp, "orbit")
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t@example.com"); git(self.repo, "config", "user.name", "T")
        open(os.path.join(self.repo, "src", "a.txt"), "w").write("one\n")
        git(self.repo, "add", "-A"); git(self.repo, "commit", "-q", "-m", "first")

    def write(self, root, rel, text):
        open(os.path.join(root, rel), "w").write(text)


class TestCreate(Repo):
    def test_it_makes_a_branch_and_a_folder_outside_your_repo(self):
        wt = WT.create(os.path.join(self.repo, "src"), self.home, "", title="Fix the parser!")
        self.assertEqual(wt["branch"], "orbit/fix-the-parser")
        self.assertTrue(wt["path"].startswith(self.home))
        self.assertTrue(wt["cwd"].endswith(os.path.join("fix-the-parser", "src")))   # same place inside
        self.assertEqual(open(os.path.join(wt["cwd"], "a.txt")).read(), "one\n")
        self.assertEqual(wt["base"], "main")

    def test_a_taken_name_gets_a_number(self):
        a = WT.create(self.repo, self.home, "x")
        b = WT.create(self.repo, self.home, "x")
        self.assertEqual((a["branch"], b["branch"]), ("orbit/x", "orbit/x-2"))

    def test_it_says_when_uncommitted_work_stays_behind(self):
        self.write(self.repo, "src/a.txt", "changed\n")
        self.assertTrue(WT.create(self.repo, self.home, "y")["left_behind"])

    def test_not_a_repository(self):
        plain = os.path.join(self.tmp, "plain"); os.makedirs(plain)
        with self.assertRaises(RuntimeError): WT.create(plain, self.home, "z")


class TestMergeAndDiscard(Repo):
    def test_merge_commits_what_is_left_brings_it_back_and_tidies_up(self):
        wt = WT.create(self.repo, self.home, "feat")
        self.write(wt["path"], "src/a.txt", "one\ntwo\n")
        st = WT.status(wt)
        self.assertEqual((st["dirty"], st["ahead"]), (1, 0))
        got = WT.merge(wt, "add two")
        self.assertTrue(got["merged"])
        self.assertEqual(open(os.path.join(self.repo, "src", "a.txt")).read(), "one\ntwo\n")
        self.assertFalse(os.path.exists(wt["path"]))
        self.assertEqual(git(self.repo, "branch", "--list", "orbit/feat"), "")

    def test_a_conflict_changes_nothing(self):
        wt = WT.create(self.repo, self.home, "c")
        self.write(wt["path"], "src/a.txt", "theirs\n")
        self.write(self.repo, "src/a.txt", "mine\n")
        git(self.repo, "commit", "-qam", "mine")
        with self.assertRaises(RuntimeError) as e:
            WT.merge(wt, "x")
        self.assertIn("src/a.txt", str(e.exception))
        self.assertEqual(open(os.path.join(self.repo, "src", "a.txt")).read(), "mine\n")
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")
        self.assertTrue(os.path.exists(wt["path"]))             # the work is still there

    def test_your_checkout_on_another_branch_is_refused(self):
        wt = WT.create(self.repo, self.home, "d")
        self.write(wt["path"], "src/a.txt", "x\n")
        git(self.repo, "checkout", "-qb", "other")
        with self.assertRaises(RuntimeError) as e:
            WT.merge(wt, "x")
        self.assertIn("other", str(e.exception))

    def test_nothing_done_just_tidies_up(self):
        wt = WT.create(self.repo, self.home, "e")
        self.assertFalse(WT.merge(wt, "x")["merged"])
        self.assertFalse(os.path.exists(wt["path"]))

    def test_discard_throws_it_away(self):
        wt = WT.create(self.repo, self.home, "f")
        self.write(wt["path"], "src/new.txt", "scratch\n")
        WT.remove(wt, force=True)
        self.assertFalse(os.path.exists(wt["path"]))
        self.assertEqual(git(self.repo, "branch", "--list", "orbit/f"), "")
        self.assertFalse(os.path.exists(os.path.join(self.repo, "src", "new.txt")))


if __name__ == "__main__":
    unittest.main()
