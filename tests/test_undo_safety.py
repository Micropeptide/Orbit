"""Undo used to put every snapshot back without looking. If you had edited one of those
files yourself after the answer, your edit was overwritten with no warning."""
import os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))
import qqcore as q


class TestUndo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orbit-undo-")

    def wrote(self, name, before, after):
        """A file an answer edited: snapshot of the old text, and what it left behind."""
        f = os.path.join(self.tmp, name)
        snap = os.path.join(self.tmp, name + ".snap")
        open(snap, "w").write(before)
        open(f, "w").write(after)
        return {"path": f, "snap": snap, "created": False, "after_sha": q._file_sha(f)}

    def test_an_untouched_file_is_restored(self):
        ch = self.wrote("a.txt", "before\n", "after\n")
        out = q.undo_changes([ch])
        self.assertEqual(open(ch["path"]).read(), "before\n")
        self.assertTrue(any("restored" in line for line in out))

    def test_a_file_you_edited_yourself_is_not_overwritten(self):
        ch = self.wrote("a.txt", "before\n", "after\n")
        open(ch["path"], "w").write("my own edit\n")
        out = q.undo_changes([ch])
        self.assertEqual(open(ch["path"]).read(), "my own edit\n")
        self.assertTrue(any("changed since" in line for line in out))

    def test_it_is_all_or_nothing(self):
        """A half-undone tree is worse than an un-undone one."""
        good = self.wrote("good.txt", "old\n", "new\n")
        mine = self.wrote("mine.txt", "old\n", "new\n")
        open(mine["path"], "w").write("mine\n")
        q.undo_changes([good, mine])
        self.assertEqual(open(good["path"]).read(), "new\n", "it restored one anyway")
        self.assertEqual(open(mine["path"]).read(), "mine\n")

    def test_force_goes_ahead(self):
        ch = self.wrote("a.txt", "before\n", "after\n")
        open(ch["path"], "w").write("mine\n")
        q.undo_changes([ch], force=True)
        self.assertEqual(open(ch["path"]).read(), "before\n")

    def test_the_preview_says_which_is_which(self):
        good = self.wrote("good.txt", "old\n", "new\n")
        mine = self.wrote("mine.txt", "old\n", "new\n")
        open(mine["path"], "w").write("mine\n")
        outside = {"path": os.path.join(self.tmp, "nosnap.txt"), "snap": None, "created": False}
        open(outside["path"], "w").write("x\n")
        look = q.preview_undo([good, mine, outside])
        self.assertEqual([x["path"] for x in look["safe"]], [good["path"]])
        self.assertEqual([x["path"] for x in look["unsafe"]], [mine["path"]])
        self.assertEqual([x["path"] for x in look["gone"]], [outside["path"]])

    def test_a_file_created_by_the_answer_is_removable(self):
        f = os.path.join(self.tmp, "new.txt")
        open(f, "w").write("hello\n")
        look = q.preview_undo([{"path": f, "snap": None, "created": True}])
        self.assertEqual(len(look["safe"]), 1)
        self.assertIn("created here", look["safe"][0]["what"])

    def test_an_older_change_without_a_hash_still_undoes(self):
        """Changes recorded before this existed have no after_sha; they behave as before."""
        ch = self.wrote("a.txt", "before\n", "after\n")
        ch.pop("after_sha")
        q.undo_changes([ch])
        self.assertEqual(open(ch["path"]).read(), "before\n")


if __name__ == "__main__":
    unittest.main()
