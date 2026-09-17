"""Scheduled tasks (qqcore sched_* and orbit-ui's scheduler): editing a task in
place, pausing it, times that cannot be read, when the next run is, and tasks not
starving while other chats answer. Uses a temporary schedule file; runs nothing."""
import importlib.machinery, importlib.util, json, os, shutil, sys, tempfile, threading, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "bin"))


def load_ui():
    loader = importlib.machinery.SourceFileLoader("orbit_ui_sched_test", os.path.join(ROOT, "bin", "orbit-ui"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class TestScheduler(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = load_ui()
        cls.q = cls.ui.q

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orbit-sched-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.saved = (self.q.SCHED, self.q.snapshot_config)
        self.q.SCHED = os.path.join(self.tmp, "schedule.json")
        self.q.snapshot_config = lambda *a, **k: None
        self.addCleanup(self.restore)

    def restore(self):
        self.q.SCHED, self.q.snapshot_config = self.saved

    def job(self, **kw):
        j = {"id": "job1", "name": "digest", "prompt": "summarise", "every": "daily", "at": "09:00",
             "enabled": True, "created": time.time() - 86400 * 3}
        j.update(kw)
        self.q.sched_save({"jobs": [j]})
        return j

    def test_editing_one_field_keeps_the_rest(self):
        self.job(model="harness:x/y", stop_at="10:00")
        cfg, err = self.ui.schedule_save({"id": "job1", "name": "morning digest", "at": "8:30"})
        self.assertIsNone(err)
        j = self.q.sched_load()["jobs"][0]
        self.assertEqual((j["name"], j["at"], j["prompt"], j["model"], j["stop_at"]),
                         ("morning digest", "08:30", "summarise", "harness:x/y", "10:00"))

    def test_pausing_needs_no_prompt(self):
        self.job()
        cfg, err = self.ui.schedule_save({"id": "job1", "enabled": False})
        self.assertIsNone(err)
        self.assertFalse(self.q.sched_load()["jobs"][0]["enabled"])

    def test_a_new_task_needs_a_prompt_and_a_readable_time(self):
        self.q.sched_save({"jobs": []})
        self.assertIsNotNone(self.ui.schedule_save({"name": "x"})[1])
        err = self.ui.schedule_save({"prompt": "go", "every": "daily", "at": "830"})[1]
        self.assertIn("time", err)
        self.assertIsNotNone(self.ui.schedule_save({"prompt": "go", "every": "weekly", "at": "07:00", "weekday": 9})[1])
        self.assertIsNotNone(self.ui.schedule_save({"prompt": "go", "every": "minutes", "n": 0})[1])
        cfg, err = self.ui.schedule_save({"prompt": "go", "every": "weekly", "at": "7:05", "weekday": 2})
        self.assertIsNone(err)
        j = self.q.sched_load()["jobs"][0]
        self.assertTrue(j["id"].startswith("job"))
        self.assertEqual((j["name"], j["at"]), ("go", "07:05"))

    def test_bad_data_never_stops_the_scheduler(self):
        for bad in ({"every": "daily", "at": "830"}, {"every": "weekly", "at": "x", "weekday": "?"},
                    {"every": "minutes", "n": "lots"}, {"every": "once", "at_ts": "soon"}):
            self.assertFalse(self.q.sched_due({"enabled": True, **bad}), bad)
            self.q.sched_next(dict(bad))                                   # no exception
            self.q.sched_next_ts(dict(bad))

    def test_next_run_time(self):
        now = time.mktime((2026, 9, 16, 10, 0, 0, 0, 0, -1))              # a Wednesday, 10:00
        t = self.q.sched_next_ts({"every": "daily", "at": "09:00"}, now)
        self.assertEqual(time.localtime(t)[:5], (2026, 9, 17, 9, 0))
        t = self.q.sched_next_ts({"every": "daily", "at": "11:30"}, now)
        self.assertEqual(time.localtime(t)[:5], (2026, 9, 16, 11, 30))
        t = self.q.sched_next_ts({"every": "weekly", "at": "08:00", "weekday": 0}, now)
        self.assertEqual(time.localtime(t)[:5], (2026, 9, 21, 8, 0))
        t = self.q.sched_next_ts({"every": "minutes", "n": 30, "last_run": now - 600}, now)
        self.assertAlmostEqual(t, now + 1200, delta=1)
        self.assertIsNone(self.q.sched_next_ts({"every": "once", "at_ts": now - 5, "last_run": now - 1}, now))
        self.assertIsNone(self.q.sched_next_ts({"every": "daily", "at": "09:00", "enabled": False}, now))

    def test_a_task_is_not_held_back_by_other_chats_answering(self):
        due = {"id": "jobA", "prompt": "p", "every": "minutes", "n": 5, "enabled": True, "last_run": 1,
               "model": "harness:opencode-go/deepseek-v4-flash"}
        local = dict(due, id="jobL", model="local:qwen")
        own = dict(due, id="jobC", sid="chat-busy")
        self.q.sched_save({"jobs": [due, local, own]})
        ui, q = self.ui, self.q
        saved = (ui.running_sids, q.slot_busy, q.model_is_local)
        ui.running_sids = lambda: ["some-other-chat", "chat-busy"]
        q.slot_busy = lambda: True
        q.model_is_local = lambda mid=None: str(mid or "").startswith("local:")
        try:
            picked = [j["id"] for j in ui.jobs_ready_to_start()]
        finally:
            ui.running_sids, q.slot_busy, q.model_is_local = saved
        self.assertEqual(picked, ["jobA"])      # not the local one (model busy), not the one whose chat answers

    def test_moving_a_task_earlier_does_not_fire_it_and_a_finished_one_off_can_run_again(self):
        now = time.time()
        lt = time.localtime(now)
        earlier = time.strftime("%H:%M", time.localtime(now - 3600)) if lt.tm_hour >= 1 else None
        if earlier:
            self.job(at=time.strftime("%H:%M", time.localtime(now + 3600)), last_run=now - 86400)
            self.ui.schedule_save({"id": "job1", "at": earlier})
            self.assertFalse(self.q.sched_due(self.q.sched_load()["jobs"][0]))       # not "missed" today
        self.job(every="once", at_ts=now - 7200, last_run=now - 7000)
        self.assertIsNone(self.q.sched_next_ts(self.q.sched_load()["jobs"][0]))
        cfg, err = self.ui.schedule_save({"id": "job1", "at_ts": now - 1})
        self.assertIsNone(err)
        j = self.q.sched_load()["jobs"][0]
        self.assertNotIn("last_run", j)
        self.assertTrue(self.q.sched_due(j))


if __name__ == "__main__":
    unittest.main()
