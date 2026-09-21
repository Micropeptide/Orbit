"""Orbit's side work — summaries, and the review of what an answer changed — goes to a
model you pick, not to the one that just answered. A model on this Mac takes one request
at a time, so reviewing a turn on it means queueing behind that turn."""
import os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))
import qqcore as q


class TestTheDiffItReviews(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orbit-review-")

    def change(self, name, before, after, created=False):
        f = os.path.join(self.tmp, name)
        snap = os.path.join(self.tmp, name + ".snap")
        if before is not None: open(snap, "w").write(before)
        open(f, "w").write(after)
        return {"path": f, "snap": snap if before is not None else None, "created": created}

    def test_it_is_a_real_diff_of_what_changed(self):
        d = q.turn_diff([self.change("calc.py", "def add(a, b):\n    return a + b\n",
                                                "def add(a, b):\n    return a - b\n")])
        self.assertIn("-    return a + b", d)
        self.assertIn("+    return a - b", d)

    def test_a_new_file_is_all_additions(self):
        d = q.turn_diff([self.change("new.py", None, "print('hi')\n", created=True)])
        self.assertIn("+print('hi')", d)
        self.assertNotIn("-", d.split("@@")[-1])

    def test_a_file_that_did_not_really_change_is_left_out(self):
        same = "x = 1\n"
        self.assertEqual(q.turn_diff([self.change("same.py", same, same)]), "")

    def test_an_enormous_diff_is_named_but_not_included(self):
        big = "".join(f"line {i}\n" for i in range(20000))
        d = q.turn_diff([self.change("big.txt", "", big)], cap=2000)
        self.assertIn("diff too large", d)
        self.assertLess(len(d), 4000)

    def test_nothing_changed_means_no_review_call_at_all(self):
        called = []
        saved = q.stream_call
        q.stream_call = lambda *a, **k: called.append(1) or {"content": "x"}
        self.addCleanup(setattr, q, "stream_call", saved)
        self.assertEqual(q.review_changes([]), "")
        self.assertEqual(called, [])


class TestWhichModelDoesTheSideWork(unittest.TestCase):
    def setUp(self):
        self.saved = q.S.get("helper_model")
        self.addCleanup(q.S.__setitem__, "helper_model", self.saved)

    def test_unset_means_whatever_the_chat_uses(self):
        q.S["helper_model"] = ""
        self.assertIsNone(q.helper_model())

    def test_a_model_that_is_not_in_the_picker_is_not_used(self):
        """current_model() answers an unknown id with the default, which would send the
        side work somewhere the user never chose."""
        q.S["helper_model"] = "nosuch:model"
        self.assertIsNone(q.helper_model())

    def test_the_review_goes_to_the_model_you_picked(self):
        seen = {}
        saved = q.stream_call
        def fake(messages, tools, **kw):
            seen["model"] = kw.get("model")
            seen["prompt"] = messages[-1]["content"]
            return {"content": "line 2 flips the sign"}
        q.stream_call = fake
        self.addCleanup(setattr, q, "stream_call", saved)
        tmp = tempfile.mkdtemp()
        f, snap = os.path.join(tmp, "a.py"), os.path.join(tmp, "a.snap")
        open(snap, "w").write("a + b\n"); open(f, "w").write("a - b\n")
        out = q.review_changes([{"path": f, "snap": snap, "created": False}], model="claude:opus")
        self.assertEqual(out, "line 2 flips the sign")
        self.assertEqual(seen["model"], "claude:opus")
        self.assertIn("-a + b", seen["prompt"])          # the diff really went with it

    def test_a_review_that_fails_says_so_instead_of_breaking_the_turn(self):
        saved = q.stream_call
        def boom(*a, **k): raise RuntimeError("provider down")
        q.stream_call = boom
        self.addCleanup(setattr, q, "stream_call", saved)
        tmp = tempfile.mkdtemp()
        f, snap = os.path.join(tmp, "a.py"), os.path.join(tmp, "a.snap")
        open(snap, "w").write("1\n"); open(f, "w").write("2\n")
        out = q.review_changes([{"path": f, "snap": snap, "created": False}])
        self.assertIn("could not run", out)
        self.assertIn("provider down", out)


if __name__ == "__main__":
    unittest.main()
