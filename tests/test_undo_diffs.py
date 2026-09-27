"""Undo, rewind and the diffs shown for them.

Each of these showed you something other than what happened -- another chat's diff, a
cut-off diff presented as whole, a staged change reported as nothing -- or put back
less than it said it did. Everything runs in a temporary workspace.
"""
import importlib.machinery, importlib.util, json, os, shutil, subprocess, sys, tempfile, time, types, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "bin"))

import qqcore as q


def load_ui():
    loader = importlib.machinery.SourceFileLoader("orbit_ui_undo_diffs", os.path.join(ROOT, "bin", "orbit-ui"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orbit-undo-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = {k: getattr(q, k) for k in ("WORKSPACE", "CHECKPOINTS")}
        self.addCleanup(lambda: [setattr(q, k, v) for k, v in saved.items()])
        q.WORKSPACE = self.tmp
        q.CHECKPOINTS = os.path.join(self.tmp, ".checkpoints")
        ctx = {k: getattr(q.TURN_CTX, k, None) for k in ("sid", "settings_sid", "changes")}
        self.addCleanup(lambda: [setattr(q.TURN_CTX, k, v) for k, v in ctx.items()])
        q.READ_STATE.clear(); self.addCleanup(q.READ_STATE.clear)
        q.LAST_DIFF.clear(); self.addCleanup(q.LAST_DIFF.clear)
        self.chat("A")

    def chat(self, sid):
        q.TURN_CTX.sid = q.TURN_CTX.settings_sid = sid

    def file(self, name, text):
        p = os.path.join(self.tmp, name)
        with open(p, "w") as f: f.write(text)
        return p


class TestEachChatKeepsItsOwnReadRecord(Workspace):
    def test_another_chats_edit_does_not_vouch_for_this_ones_read(self):
        """Keyed by path, chat B's edit refreshed the record and chat A -- still holding
        the older text -- passed the check and wrote over B's work."""
        p = self.file("shared.py", "x = 1\n")
        self.chat("A"); q.t_read_file(p)
        self.chat("B"); q.t_read_file(p)
        self.assertTrue(q.t_edit_file(p, "x = 1", "x = 2").startswith("Edited"))
        self.chat("A")
        out = q.t_edit_file(p, "x = 1", "x = 3")
        self.assertIn("changed on disk since you read it", out)
        self.assertIn("x = 2", open(p).read())

    def test_a_reformat_in_one_chat_is_news_to_the_other(self):
        p = self.file("f.py", "a\n")
        self.chat("A"); q.t_read_file(p)
        self.chat("B"); q.t_read_file(p)
        open(p, "w").write("b\n"); q._forget_reads({"f.py"})       # B's run_shell rewrote it
        self.assertEqual(q._changed_since_read(p), "", "B's own work should not trip B")
        self.chat("A")
        self.assertIn("changed on disk", q._changed_since_read(p))


class TestDiffCardsBelongToTheirChat(Workspace):
    def test_one_chat_cannot_take_anothers_diff(self):
        p = self.file("a.txt", "one\n")
        self.chat("A"); q.t_read_file(p); q.t_edit_file(p, "one", "two")
        self.assertIsNone(q.take_last_diff("B"))
        d = q.take_last_diff("A")
        self.assertEqual(d["path"], p)
        self.assertIsNone(q.take_last_diff("A"), "a card is taken once")

    def test_a_failed_edit_leaves_no_card(self):
        p = self.file("b.txt", "one\n")
        q.t_read_file(p)
        self.assertTrue(q.t_edit_file(p, "absent", "x").startswith("Error"))
        self.assertIsNone(q.take_last_diff("A"))

    def test_multi_edit_has_a_card_and_a_preview(self):
        p = self.file("c.txt", "one\ntwo\n")
        edits = [{"old_string": "one", "new_string": "ONE"}, {"old_string": "two", "new_string": "TWO"}]
        pv = q.preview_edit("multi_edit", {"path": p, "edits": edits})
        self.assertEqual((pv["added"], pv["removed"]), (2, 2))
        self.assertIsNone(q.preview_edit("multi_edit", {"path": p, "edits": [{"old_string": "zz", "new_string": "y"}]}))
        q.t_read_file(p); q.t_multi_edit(p, edits)
        self.assertEqual(q.take_last_diff("A")["added"], 2)


class TestDiffsSayWhatTheyLeaveOut(Workspace):
    def test_a_long_diff_says_it_was_cut(self):
        p = self.file("big.txt", "")
        d = q.file_diff(p, "".join(f"line {i}\n" for i in range(900)))
        self.assertTrue(d["truncated"])
        self.assertIn("more diff lines not shown", d["diff"])
        self.assertEqual(d["added"], 900)

    def test_a_short_one_does_not(self):
        p = self.file("small.txt", "a\n")
        self.assertFalse(q.file_diff(p, "b\n")["truncated"])


class TestTheReviewDiffIsOnePerFile(Workspace):
    def test_three_edits_one_file_one_diff(self):
        """Each of three changes was diffed from its own midpoint: three overlapping
        diffs of one file, the first two describing states that no longer exist."""
        p = self.file("r.py", "a = 1\n")
        q.TURN_CTX.changes = []
        q.t_read_file(p)
        for old, new in (("a = 1", "a = 2"), ("a = 2", "a = 3"), ("a = 3", "a = 4")):
            q.t_edit_file(p, old, new)
        d = q.turn_diff(q.TURN_CTX.changes)
        self.assertEqual(d.count(f"+++ b/{p}"), 1)
        self.assertIn("-a = 1", d); self.assertIn("+a = 4", d)


class TestGitStatus(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="orbit-git-")
        self.addCleanup(shutil.rmtree, self.repo, True)
        q._GIT_CACHE.clear()

    def git(self, *a):
        subprocess.run(["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@example.com", *a],
                       check=True, capture_output=True)

    def test_a_new_repository_has_a_branch_name(self):
        self.git("init", "-q", "-b", "trunk")
        self.assertEqual(q.git_state(self.repo)["branch"], "trunk")

    def test_staged_work_is_counted(self):
        """`git diff` alone compares with the index, so staged work read as no change."""
        self.git("init", "-q")
        open(os.path.join(self.repo, "f.txt"), "w").write("a\n")
        self.git("add", "f.txt"); self.git("commit", "-q", "-m", "one")
        open(os.path.join(self.repo, "f.txt"), "w").write("a\nb\n")
        self.git("add", "f.txt")
        st = q.git_state(self.repo, max_age=0)
        self.assertEqual(st["staged"], 1)
        self.assertIn("1 insertion", st["diff"])

    def test_it_takes_no_lock(self):
        self.assertIn("--no-optional-locks", open(os.path.join(ROOT, "bin", "qqcore.py")).read())


class TestRewindIsAllOrNothing(Workspace):
    @classmethod
    def setUpClass(cls):
        cls.ui = load_ui()

    def call(self, body):
        out = types.SimpleNamespace(code=None, body=None)
        ui = self.ui
        class Fake(ui.H):
            def __init__(self): self.path = "/api/rewind"; self.headers = {}
            def _body(self): return body
            def _send(self, code, b, ctype="application/json", headers=None):
                out.code, out.body = code, json.loads(b)
        Fake()._post("/api/rewind")
        return out

    def answer_that_edits(self, p, old, new):
        q.TURN_CTX.changes = []
        q.t_read_file(p); q.t_edit_file(p, old, new)
        return {"role": "assistant", "content": "done", "changes": q.TURN_CTX.changes}

    def test_one_file_you_changed_stops_the_whole_rewind(self):
        ui = self.ui
        a = self.file("a.txt", "a0\n"); b = self.file("b.txt", "b0\n")
        st = ui.State(); st.temp = True
        st.msgs = [{"role": "system", "content": "s"},
                   {"role": "user", "content": "first"}, self.answer_that_edits(a, "a0", "a1"),
                   {"role": "user", "content": "second"}, self.answer_that_edits(b, "b0", "b1")]
        ui.STATES[st.sid] = st; self.addCleanup(ui.STATES.pop, st.sid, None)
        open(a, "w").write("mine\n")                         # you edited a.txt since
        r = self.call({"sid": st.sid, "index": 0, "files": True})
        self.assertEqual(r.code, 409, r.body)
        self.assertEqual(r.body["refused"], [a])
        self.assertEqual(open(b).read(), "b1\n", "b.txt was rewound although the rewind was refused")
        self.assertEqual(len(st.msgs), 5, "the messages were cut although the rewind was refused")

    def test_a_file_two_answers_edited_rewinds_cleanly(self):
        """The changes were gathered newest first, pairing a file's newest snapshot with
        its oldest after-hash -- so any file two answers touched looked changed by you."""
        ui = self.ui
        a = self.file("a.txt", "v0\n")
        st = ui.State(); st.temp = True
        st.msgs = [{"role": "system", "content": "s"},
                   {"role": "user", "content": "first"}, self.answer_that_edits(a, "v0", "v1"),
                   {"role": "user", "content": "second"}, self.answer_that_edits(a, "v1", "v2")]
        ui.STATES[st.sid] = st; self.addCleanup(ui.STATES.pop, st.sid, None)
        r = self.call({"sid": st.sid, "index": 0, "files": True})
        self.assertEqual(r.code, 200, r.body)
        self.assertEqual(open(a).read(), "v0\n")


class TestUndoSaysWhatItDid(Workspace):
    def test_a_missing_snapshot_is_not_undone(self):
        p = self.file("m.txt", "x\n")
        q.TURN_CTX.changes = []
        q.t_read_file(p); q.t_edit_file(p, "x", "y")
        ch = q.TURN_CTX.changes
        os.remove(ch[0]["snap"])
        r = q.undo_result(ch)
        self.assertFalse(r["undone"])
        self.assertIn("no longer kept", " ".join(r["lines"]))

    def test_recent_snapshots_outlive_the_count(self):
        """An answer editing one file more than CHECKPOINTS_KEEP times pruned its own
        starting point; undo then left the file as the answer had left it."""
        p = self.file("n.txt", "start\n")
        q.TURN_CTX.changes = []
        q.t_read_file(p)
        cur = "start"
        for i in range(q.CHECKPOINTS_KEEP + 5):
            q.t_edit_file(p, cur, f"v{i}"); cur = f"v{i}"
        r = q.undo_result(q.TURN_CTX.changes)
        self.assertTrue(r["undone"], r["lines"])
        self.assertEqual(open(p).read(), "start\n")


class TestRedoAfterUndo(Workspace):
    def test_undo_then_redo_puts_the_answers_work_back(self):
        a = self.file("a.txt", "before\n")
        q.TURN_CTX.changes = []
        q.t_read_file(a); q.t_edit_file(a, "before", "after")
        q.t_write_file(os.path.join(self.tmp, "new.txt"), "made here\n")
        ch = q.TURN_CTX.changes
        u = q.undo_result(ch)
        self.assertTrue(u["undone"])
        self.assertEqual(open(a).read(), "before\n")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "new.txt")))
        r = q.redo_result(u["redo"])
        self.assertTrue(r["redone"], r["lines"])
        self.assertEqual(open(a).read(), "after\n")
        self.assertEqual(open(os.path.join(self.tmp, "new.txt")).read(), "made here\n")
        self.assertFalse([k for k, v in q._trash_index().items() if v.get("original", "").endswith("new.txt")],
                         "the bin still lists a file redo put back")

    def test_your_edits_since_the_undo_stop_it(self):
        a = self.file("b.txt", "one\n")
        q.TURN_CTX.changes = []
        q.t_read_file(a); q.t_edit_file(a, "one", "two")
        u = q.undo_result(q.TURN_CTX.changes)
        open(a, "w").write("mine\n")
        r = q.redo_result(u["redo"])
        self.assertFalse(r["redone"]); self.assertEqual(open(a).read(), "mine\n")
        self.assertTrue(q.redo_result(u["redo"], force=True)["redone"])
        self.assertEqual(open(a).read(), "two\n")


class TestTheDockListsFiles(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="orbit-gitfiles-")
        self.addCleanup(shutil.rmtree, self.repo, True)
        q._GIT_CACHE.clear()

    def git(self, *a):
        subprocess.run(["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@example.com", *a],
                       check=True, capture_output=True)

    def test_each_file_with_its_counts_and_its_diff(self):
        self.git("init", "-q")
        open(os.path.join(self.repo, "a.py"), "w").write("x = 1\n")
        self.git("add", "a.py"); self.git("commit", "-q", "-m", "one")
        open(os.path.join(self.repo, "a.py"), "w").write("x = 2\ny = 3\n")
        open(os.path.join(self.repo, "new.md"), "w").write("hello\n")
        st = q.git_state(self.repo, max_age=0)
        byp = {f["path"]: f for f in st["files"]}
        self.assertEqual((byp["a.py"]["status"], byp["a.py"]["added"], byp["a.py"]["removed"]), ("M", 2, 1))
        self.assertEqual(byp["new.md"]["status"], "?")
        d = q.git_file_diff(self.repo, "a.py")
        self.assertIn("+x = 2", d["diff"])
        self.assertIn("+hello", q.git_file_diff(self.repo, "new.md")["diff"])
        self.assertIn("error", q.git_file_diff(self.repo, "../outside"))

    def test_a_merge_left_half_done_is_named(self):
        self.git("init", "-q", "-b", "main")
        f = os.path.join(self.repo, "f.txt")
        open(f, "w").write("base\n"); self.git("add", "."); self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "other"); open(f, "w").write("other\n"); self.git("commit", "-qam", "o")
        self.git("checkout", "-q", "main"); open(f, "w").write("main\n"); self.git("commit", "-qam", "m")
        subprocess.run(["git", "-C", self.repo, "merge", "other"], capture_output=True)
        st = q.git_state(self.repo, max_age=0)
        self.assertEqual((st.get("op"), st["conflicts"]), ("merge", 1))


if __name__ == "__main__":
    unittest.main()
