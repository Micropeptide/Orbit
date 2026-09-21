"""A file you changed yourself, in your own editor, while an answer was running.

The model read it three steps ago and edits from what it read. Without a check the
edit is applied to text that no longer exists and your change is gone with no word
said — and the loose edit matchers make a wrong match likelier, not less likely."""
import os, sys, tempfile, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))
import qqcore as q


class TestReadBeforeEdit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orbit-stale-")
        self.p = os.path.join(self.tmp, "a.py")
        open(self.p, "w").write("one\ntwo\nthree\n")
        q.READ_STATE.clear()
        self.addCleanup(q.READ_STATE.clear)
        self.saved_ws = q.WORKSPACE
        q.WORKSPACE = self.tmp
        self.addCleanup(setattr, q, "WORKSPACE", self.saved_ws)

    def touch(self, text):
        """Change it the way you would: a moment later, with different content."""
        time.sleep(0.01)
        open(self.p, "w").write(text)

    def test_an_edit_after_your_change_is_refused(self):
        q.t_read_file(self.p)
        self.touch("one\ntwo\nthree\nfour I added myself\n")
        out = q.t_edit_file(self.p, "two", "TWO")
        self.assertIn("changed on disk since you read it", out)
        self.assertIn("four I added myself", open(self.p).read())

    def test_reading_it_again_makes_the_edit_fine(self):
        q.t_read_file(self.p)
        self.touch("one\ntwo\nthree\nfour\n")
        q.t_read_file(self.p)
        out = q.t_edit_file(self.p, "two", "TWO")
        self.assertNotIn("Error", out)
        self.assertIn("TWO", open(self.p).read())

    def test_an_edit_the_answer_made_itself_does_not_trip_it(self):
        """Two edits to one file in one turn is ordinary work, not a conflict."""
        q.t_read_file(self.p)
        self.assertNotIn("Error", q.t_edit_file(self.p, "one", "ONE"))
        self.assertNotIn("Error", q.t_edit_file(self.p, "two", "TWO"))
        self.assertEqual(open(self.p).read(), "ONE\nTWO\nthree\n")

    def test_a_file_it_never_read_is_not_guarded(self):
        """The guard is about a stale read, not about ownership: a file the answer
        never read has nothing to be stale against."""
        out = q.t_edit_file(self.p, "two", "TWO")
        self.assertNotIn("changed on disk", out)

    def test_write_file_is_guarded_too(self):
        q.t_read_file(self.p)
        self.touch("mine\n")
        out = q.BUILTIN["write_file"](self.p, "the model's idea of the file\n")
        self.assertIn("changed on disk since you read it", out)
        self.assertEqual(open(self.p).read(), "mine\n")

    def test_multi_edit_is_guarded_too(self):
        q.t_read_file(self.p)
        self.touch("one\ntwo\nthree\nmine\n")
        out = q.t_multi_edit(self.p, [{"old_string": "one", "new_string": "ONE"}])
        self.assertIn("changed on disk since you read it", out)
        self.assertIn("mine", open(self.p).read())

    def test_it_remembers_only_so_many_files(self):
        for i in range(q.READ_STATE_MAX + 40):
            p = os.path.join(self.tmp, f"f{i}.txt")
            open(p, "w").write("x")
            q._note_read(p)
        self.assertLessEqual(len(q.READ_STATE), q.READ_STATE_MAX)
        # the newest are the ones kept
        self.assertIn(os.path.join(self.tmp, f"f{q.READ_STATE_MAX + 39}.txt"), q.READ_STATE)


if __name__ == "__main__":
    unittest.main()
