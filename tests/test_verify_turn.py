"""Before an answer is final, a model is asked whether the request was actually carried
out. The rules that make that safe to ship are the ones ZCode learned the hard way: a
verifier that breaks must never be able to trap finished work in a loop."""
import json, os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))
import qqcore as q


class TestReadingTheVerdict(unittest.TestCase):
    def test_bare_fenced_and_surrounded_json_all_parse(self):
        self.assertEqual(q._verify_json('{"passed": true}')["passed"], True)
        self.assertEqual(q._verify_json('```json\n{"passed": false}\n```')["passed"], False)
        self.assertEqual(q._verify_json('Sure! {"passed": true} hope that helps')["passed"], True)

    def test_prose_is_not_a_verdict(self):
        self.assertIsNone(q._verify_json("looks fine to me"))
        self.assertIsNone(q._verify_json(""))


class TestTheVerdict(unittest.TestCase):
    def reply(self, text):
        saved = q.stream_call
        q.stream_call = lambda *a, **k: {"content": text}
        self.addCleanup(setattr, q, "stream_call", saved)

    def test_a_clear_failure_comes_back_with_what_to_do_next(self):
        self.reply('{"passed": false, "reason": "no tests were run", "next": "run pytest"}')
        v = q.verify_turn([], "add a test")
        self.assertFalse(v["passed"])
        self.assertEqual(v["next"], "run pytest")
        self.assertFalse(v["fail_open"])

    def test_a_verifier_that_answers_nonsense_passes_the_work(self):
        self.reply("I'd say it's probably fine")
        v = q.verify_turn([], "add a test")
        self.assertTrue(v["passed"])
        self.assertTrue(v["fail_open"])
        self.assertIn("did not answer", v["reason"])

    def test_a_verifier_that_cannot_be_reached_passes_the_work(self):
        saved = q.stream_call
        def boom(*a, **k): raise RuntimeError("provider down")
        q.stream_call = boom
        self.addCleanup(setattr, q, "stream_call", saved)
        v = q.verify_turn([], "add a test")
        self.assertTrue(v["passed"])
        self.assertTrue(v["fail_open"])

    def test_the_transcript_it_reads_names_the_tools_and_their_outcome(self):
        msgs = [{"role": "system", "content": "secret prompt"},
                {"role": "user", "content": "add a test"},
                {"role": "tool", "name": "run_shell", "ok": False, "content": "pytest: not found"},
                {"role": "assistant", "content": "done!"}]
        t = q._transcript_for_verify(msgs)
        self.assertIn("[tool run_shell FAILED]", t)
        self.assertIn("pytest: not found", t)
        self.assertIn("user: add a test", t)
        self.assertNotIn("secret prompt", t)    # the system prompt is not evidence

    def test_it_asks_for_evidence_rather_than_a_guess(self):
        self.assertIn("insufficient evidence", q.VERIFY_ASK)
        self.assertIn("do not call tools", q.VERIFY_ASK)
        # a standalone "thanks" must not be failed for having no deliverables
        self.assertIn("conversational", q.VERIFY_ASK)


if __name__ == "__main__":
    unittest.main()
