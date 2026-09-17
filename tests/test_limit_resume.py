"""An answer stopped by a used-up plan allowance carries on by itself after the reset:
reading when it resets, scheduling one run per chat, and doing so from a chat's own
answers and from scheduled tasks. Temporary schedule file and chats; no model is called."""
import importlib.machinery, importlib.util, json, os, shutil, sys, tempfile, threading, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "bin"))


def load_ui():
    loader = importlib.machinery.SourceFileLoader("orbit_ui_limit_test", os.path.join(ROOT, "bin", "orbit-ui"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class TestLimitResume(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = load_ui()
        cls.q = cls.ui.q

    def setUp(self):
        q = self.q
        self.tmp = tempfile.mkdtemp(prefix="orbit-limit-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = (q.SCHED, q.snapshot_config, q.notify, q.S.get("resume_after_limit"))
        q.SCHED = os.path.join(self.tmp, "schedule.json")
        q.snapshot_config = lambda *a, **k: None
        q.notify = lambda *a, **k: None
        q.S["resume_after_limit"] = True
        def restore():
            q.SCHED, q.snapshot_config, q.notify = saved[:3]
            q.S["resume_after_limit"] = saved[3]
        self.addCleanup(restore)
        q.sched_save({"jobs": []})

    def jobs(self):
        return [j for j in self.q.sched_load()["jobs"] if j.get("kind") == "limit_resume"]

    # -- reading the reset time ---------------------------------------------------------
    def test_reset_times_in_the_forms_the_agents_write_them(self):
        now = time.mktime((2026, 9, 17, 10, 0, 0, 0, 0, -1))          # a Thursday, 10:00 local
        at = self.q.limit_reset_at
        self.assertEqual(at(["Claude AI usage limit reached|1789660800"], now)[0], 1789660800.0)
        t, _ = at(["You've hit your limit · resets 3pm"], now)
        self.assertEqual(time.localtime(t)[:5], (2026, 9, 17, 15, 0))
        t, _ = at(["5-hour limit reached · resets 9:30am"], now)       # already past today: tomorrow
        self.assertEqual(time.localtime(t)[:5], (2026, 9, 18, 9, 30))
        t, _ = at(["You've hit your usage limit. Try again in 2h 15m."], now)
        self.assertAlmostEqual(t, now + 2 * 3600 + 15 * 60)
        t, _ = at(['{"error": {"type": "GoUsageLimitError", "message": "weekly limit"}, "resetsAt": "2026-09-18T01:00:00Z"}'], now)
        self.assertEqual(t, 1789693200.0)
        self.assertEqual(at(["usage limit reached"], now)[0], None)     # no time given
        self.assertIsNone(at(["a network error, retrying"], now))
        self.assertIsNone(at(["rate limit, retrying in 4s"], now))       # a short wait is not a used-up plan

    # -- scheduling -----------------------------------------------------------------------
    def test_one_run_per_chat_a_minute_after_the_reset(self):
        now = time.time()
        reset = now + 3 * 3600
        job = self.q.schedule_limit_resume("chat-1", "My work", [f"Claude AI usage limit reached|{int(reset)}"], now=now)
        self.assertEqual(job["sid"], "chat-1")
        self.assertAlmostEqual(job["at_ts"], int(reset) + 60, delta=1)
        self.assertEqual(job["every"], "once")
        later = now + 5 * 3600
        self.q.schedule_limit_resume("chat-1", "My work", [f"Claude AI usage limit reached|{int(later)}"], now=now)
        self.assertEqual(len(self.jobs()), 1)                          # moved, not added
        self.assertAlmostEqual(self.jobs()[0]["at_ts"], int(later) + 60, delta=1)

    def test_unknown_time_waits_an_hour_and_the_setting_turns_it_off(self):
        now = time.time()
        job = self.q.schedule_limit_resume("chat-2", "t", ["usage limit reached"], now=now)
        self.assertAlmostEqual(job["at_ts"], now + self.q.LIMIT_UNKNOWN_WAIT + 60, delta=2)
        self.q.S["resume_after_limit"] = False
        self.assertIsNone(self.q.schedule_limit_resume("chat-3", "t", ["usage limit reached"], now=now))

    def test_gives_up_after_repeated_limits(self):
        self.assertIsNone(self.q.schedule_limit_resume("chat-4", "t", ["usage limit reached"],
                                                       attempt=self.q.LIMIT_MAX_ATTEMPTS))

    # -- from a chat's own answer ---------------------------------------------------------
    def test_watch_only_when_the_answer_failed(self):
        ui = self.ui
        st = ui.State(); st.temp = True; st.title = "x"
        w = ui._LimitWatch()
        w.see("retry", {"error": "usage limit reached, resets at 15:00"})
        st.msgs = [{"role": "assistant", "content": "done, all good"}]
        self.assertIsNone(w.check(st, 0))                     # a fallback carried it through
        w.see("error", "Claude AI usage limit reached|%d" % int(time.time() + 3600))
        job = w.check(st, 0)
        self.assertIsNotNone(job)
        self.assertEqual(job["sid"], st.sid)
        self.assertIsNone(ui._LimitWatch().check(st, 0, cancelled=True))

    def test_the_limit_message_written_as_the_answer_counts(self):
        ui = self.ui
        st = ui.State(); st.temp = True; st.title = "x"
        st.msgs = [{"role": "user", "content": "go"},
                   {"role": "assistant", "content": "5-hour limit reached ∙ resets 11pm"}]
        self.assertIsNotNone(ui._LimitWatch().check(st, 1))
        long_answer = "Here is how usage limit reached errors work in general. " * 20
        st2 = ui.State(); st2.temp = True
        st2.msgs = [{"role": "assistant", "content": long_answer}]
        self.assertIsNone(ui._LimitWatch().check(st2, 0))

    # -- from a scheduled task -------------------------------------------------------------
    def test_a_scheduled_run_that_hits_the_limit_carries_on_later(self):
        ui, q = self.ui, self.q
        saved = (q.turn, q.session_save, ui._learn_later, ui._refresh_system)
        reset = int(time.time() + 7200)
        def fake_turn(msgs, prompt, tools, emit=None, **kw):
            if emit: emit("error", f"Claude AI usage limit reached|{reset}")
            return ""
        q.turn = fake_turn
        written = {}
        q.session_save = lambda sid, msgs, title=None, extra=None: written.update({sid: title})
        ui._learn_later = lambda *a, **k: None
        try:
            job = {"id": "jobx", "name": "overnight", "prompt": "research", "every": "daily", "at": "02:00",
                   "enabled": True}
            q.sched_save({"jobs": [job]})
            result = ui.run_job(job)
        finally:
            q.turn, q.session_save, ui._learn_later, ui._refresh_system = saved
        self.assertIn("Usage limit reached", result)
        rj = self.jobs()
        self.assertEqual(len(rj), 1)
        self.assertTrue(rj[0]["sid"].startswith("sched-"))
        self.assertAlmostEqual(rj[0]["at_ts"], reset + 60, delta=1)
        # the carry-on run counts as a second attempt if it too meets the limit
        self.assertEqual(ui._limit_attempt(rj[0]), 1)

    def test_the_reset_time_claude_code_reports_is_used(self):
        ui = self.ui
        st = ui.State(); st.temp = True; st.title = "x"; st.msgs = []
        w = ui._LimitWatch()
        reset = int(time.time() + 4 * 3600)
        w.see("notice", {"msg": "Claude's 5-hour limit reached — it resets Thu 15:00", "kind": "limit", "resets_at": reset})
        w.see("error", "Claude Code exited (1) without answering")
        job = w.check(st, 0)
        self.assertAlmostEqual(job["at_ts"], reset + 60, delta=1)

    def test_a_limit_mid_answer_counts_but_not_after_a_fallback_took_over(self):
        ui = self.ui
        st = ui.State(); st.temp = True; st.title = "x"; st.msgs = []
        w = ui._LimitWatch()
        w.see("notice", {"msg": "limit", "kind": "limit", "resets_at": time.time() + 3600})
        self.assertIsNotNone(w.check(st, 0))                  # stopped part-way, no error event
        w2 = ui._LimitWatch()
        w2.see("notice", {"msg": "limit", "kind": "limit", "resets_at": time.time() + 3600})
        w2.see("fallback", {"from": "a", "to": "b"})
        st2 = ui.State(); st2.temp = True; st2.msgs = []
        self.assertIsNone(w2.check(st2, 0))


if __name__ == "__main__":
    unittest.main()
