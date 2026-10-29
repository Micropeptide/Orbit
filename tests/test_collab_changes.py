"""Who changed what: a snapshot of the project folder before and after each model turn, written to the record, and undo for what Orbit's file tools did."""
import json, os, shutil, sys, tempfile, time, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
import collab_files as F       # noqa: E402


class TestSnapshot(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)
        os.makedirs(os.path.join(self.tmp, "src")); open(os.path.join(self.tmp, "src", "a.py"), "w").write("a"); open(os.path.join(self.tmp, "keep.txt"), "w").write("k")

    def test_created_modified_and_deleted_files_are_told_apart(self):
        before = F.snapshot(self.tmp)
        time.sleep(0.01)
        open(os.path.join(self.tmp, "src", "a.py"), "w").write("changed!"); open(os.path.join(self.tmp, "new.txt"), "w").write("n"); os.unlink(os.path.join(self.tmp, "keep.txt"))
        d = F.diff(before, F.snapshot(self.tmp))
        self.assertEqual((d["created"], d["modified"], d["deleted"]), (["new.txt"], [os.path.join("src", "a.py")], ["keep.txt"]))

    def test_nothing_changed_is_nothing(self):
        d = F.diff(F.snapshot(self.tmp), F.snapshot(self.tmp)); self.assertEqual((d["created"], d["modified"], d["deleted"]), ([], [], []))

    def test_version_control_and_dependency_folders_are_left_out(self):
        for d in (".git", "node_modules", "__pycache__", ".venv"):
            os.makedirs(os.path.join(self.tmp, d)); open(os.path.join(self.tmp, d, "x"), "w").write("x")
        self.assertEqual(sorted(F.snapshot(self.tmp)), ["keep.txt", os.path.join("src", "a.py")])

    def test_links_are_not_followed_and_unreadable_places_do_not_break_it(self):
        out = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, out, True); open(os.path.join(out, "o.txt"), "w").write("o")
        os.symlink(out, os.path.join(self.tmp, "link_dir")); os.symlink(os.path.join(out, "o.txt"), os.path.join(self.tmp, "link_file"))
        snap = F.snapshot(self.tmp); self.assertNotIn(os.path.join("link_dir", "o.txt"), snap)
        os.makedirs(os.path.join(self.tmp, "locked")); os.chmod(os.path.join(self.tmp, "locked"), 0)
        self.addCleanup(os.chmod, os.path.join(self.tmp, "locked"), 0o700); self.assertIn("keep.txt", F.snapshot(self.tmp))

    def test_a_huge_folder_is_reported_not_walked_forever(self):
        for i in range(30): open(os.path.join(self.tmp, f"f{i}.txt"), "w").write("x")
        s = F.snapshot(self.tmp, max_files=10); self.assertTrue(s.truncated); self.assertLessEqual(len(s), 10)
        self.assertTrue(F.diff(s, F.snapshot(self.tmp, max_files=10))["truncated"])

    def test_long_lists_are_cut_and_say_how_many(self):
        before = F.snapshot(self.tmp)
        for i in range(30): open(os.path.join(self.tmp, f"n{i}.txt"), "w").write("x")
        d = F.diff(before, F.snapshot(self.tmp), limit=10); self.assertEqual((len(d["created"]), d["more"]), (10, 20))


if __name__ == "__main__":
    unittest.main()
