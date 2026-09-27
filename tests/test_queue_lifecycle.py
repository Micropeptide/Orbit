"""Queued messages, notes, restarts, forks and scheduled runs.

Each of these lost something you had sent, or did it at the wrong time: a queued
message dropped on its way into the chat, a note sent as an answer ended and never
read, five queued messages spent one after another on a provider that was down.
Everything runs against a temporary sessions folder.
"""
import importlib.machinery, importlib.util, json, os, shutil, sys, tempfile, threading, time, types, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "bin"))


def load_ui():
    loader = importlib.machinery.SourceFileLoader("orbit_ui_queue", os.path.join(ROOT, "bin", "orbit-ui"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = load_ui()
        cls.q = cls.ui.q

    def setUp(self):
        q, ui = self.q, self.ui
        self.tmp = tempfile.mkdtemp(prefix="orbit-queue-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = {k: getattr(q, k) for k in ("SESSIONS",)}
        self.addCleanup(lambda: [setattr(q, k, v) for k, v in saved.items()])
        q.SESSIONS = os.path.join(self.tmp, "sessions"); os.makedirs(q.SESSIONS)
        q._SESS_CACHE["key"] = None
        saved_idx = ui.QUEUE_INDEX
        ui.QUEUE_INDEX = os.path.join(self.tmp, "queues.json")
        self.addCleanup(setattr, ui, "QUEUE_INDEX", saved_idx)

    def chat(self, temp=True, queue=()):
        st = self.ui.State(); st.temp = temp
        st.msgs = [{"role": "system", "content": "s"}]
        st.queue = [dict(it) for it in queue]
        self.ui.STATES[st.sid] = st
        self.addCleanup(self.ui.STATES.pop, st.sid, None)
        return st

    def patch(self, obj, name, value):
        old = getattr(obj, name)
        setattr(obj, name, value)
        self.addCleanup(setattr, obj, name, old)

    def wait_free(self, st, secs=10):
        end = time.time() + secs
        while st.lock.locked() and time.time() < end: time.sleep(0.02)
        self.assertFalse(st.lock.locked(), "the chat was never released")


class TestAQueuedMessageIsNeverDropped(Base):
    def test_a_failed_start_puts_it_back_and_waits(self):
        """The item was taken off the queue first; if starting it raised, it was gone."""
        def boom(*a, **k): raise RuntimeError("no")
        self.patch(self.ui, "start_turn", boom)
        st = self.chat(queue=[{"id": "m1", "text": "next please", "t": 1}])
        self.ui._drain()
        self.assertEqual([x["id"] for x in st.queue], ["m1"])
        self.assertTrue(st.queue_paused)
        self.assertFalse(st.lock.locked())
        self.assertIsNone(st.handing)

    def test_one_on_its_way_in_survives_a_restart(self):
        st = self.chat(temp=False)
        st.msgs.append({"role": "user", "content": "earlier"})
        st.handing = {"id": "h1", "text": "on its way", "t": 1}
        st.queue = [{"id": "m2", "text": "after it", "t": 2}]
        self.ui._queue_saved(st)                           # what _drain does as it hands it in
        raw = json.load(open(self.q.session_path(st.sid)))
        self.assertEqual([x["id"] for x in self.ui._disk_queue(raw)], ["h1", "m2"])
        self.assertIn(st.sid, json.load(open(self.ui.QUEUE_INDEX)))
        st.handing = None; self.ui.save_session(st)          # once it is in, it is not kept
        self.assertNotIn("handing", json.load(open(self.q.session_path(st.sid))))


class TestAFailedAnswerStopsTheQueue(Base):
    def run_answer(self, st, result):
        def fake_turn(msgs, content, tools, **kw):
            msgs.append({"role": "user", "content": content})
            msgs.append({"role": "assistant", "content": "x"})
            self.q.LAST_TURN[kw.get("sid")] = dict(result)
            return "x"
        self.patch(self.q, "turn", fake_turn)
        self.patch(self.q, "slot_enter", lambda *a, **k: True)
        self.patch(self.q, "slot_exit", lambda *a, **k: None)
        self.patch(self.ui, "_learn_later", lambda *a, **k: None)
        # the answer's end drains the queue on a thread of its own, which could start the
        # next message after this test has put the real model back
        self.patch(self.ui, "_drain", lambda *a, **k: None)
        self.assertTrue(st.lock.acquire(blocking=False))
        self.ui.start_turn(st, "first", [], None)
        self.wait_free(st)

    def test_the_rest_wait_for_you(self):
        """Every queued message went out in turn, each ending in the same failure."""
        st = self.chat(queue=[{"id": f"m{i}", "text": f"q{i}", "t": i} for i in range(3)])
        self.run_answer(st, {"failed": "network"})
        self.assertTrue(st.queue_paused)
        self.assertEqual(len(st.queue), 3)

    def test_a_good_answer_lets_the_next_one_go(self):
        started = []
        st = self.chat(queue=[{"id": "m0", "text": "q0", "t": 0}])
        self.run_answer(st, {"secs": 1})
        self.assertFalse(st.queue_paused)


class TestNotesSentAsAnAnswerEnds(Base):
    def test_no_answer_running_means_no_note(self):
        st = self.chat()
        self.assertFalse(self.ui._note_if_answering(st, "hello"))
        self.assertEqual(len(st.inbox), 0)

    def test_a_note_too_late_for_the_answer_is_queued_not_stranded(self):
        st = self.chat()
        st.lock.acquire()
        self.assertTrue(self.ui._note_if_answering(st, "one more thing"))
        self.ui._release_chat(st)                          # the answer had already read its inbox
        self.assertFalse(st.lock.locked())
        self.assertEqual(len(st.inbox), 0)
        self.assertEqual(st.queue[0]["text"], "one more thing")

    def test_the_routes_use_the_one_check(self):
        src = open(os.path.join(ROOT, "bin", "orbit-ui")).read()
        self.assertEqual(src.count("st.inbox.append("), 1, "an inbox append outside _note_if_answering")


class TestRestartPickUp(Base):
    def setUp(self):
        super().setUp()
        q = self.q
        self.jobs = {"jobs": []}
        self.patch(q, "sched_load", lambda: self.jobs)
        self.patch(q, "sched_save", lambda d: d)
        self.patch(q, "notify", lambda *a, **k: None)

    def cut_off(self, sid, **extra):
        self.q.session_save(sid, [{"role": "system", "content": "s"}], "t",
                            {"running_since": time.time() - 30, **extra})

    def test_it_stops_after_pick_ups_that_were_themselves_cut_off(self):
        self.cut_off("p1", restart_pickups=self.q.RESUME_MAX_TRIES)
        self.assertEqual(self.q.recover_interrupted_sessions(), [("p1", False)])
        self.assertEqual(self.jobs["jobs"], [])

    def test_each_pick_up_is_counted(self):
        self.cut_off("p2")
        self.assertEqual(self.q.recover_interrupted_sessions(), [("p2", True)])
        self.assertEqual(json.load(open(self.q.session_path("p2")))["restart_pickups"], 1)
        self.assertEqual(self.jobs["jobs"][0]["kind"], "restart_resume")

    def test_a_finished_answer_clears_the_count(self):
        st = self.chat(temp=False)
        self.q.session_save(st.sid, st.msgs, "t", {"restart_pickups": 1})
        st.clear_pickups = True
        self.ui.save_session(st)
        self.assertNotIn("restart_pickups", json.load(open(self.q.session_path(st.sid))))

    def test_its_queue_waits_for_the_pick_up(self):
        started = []
        self.patch(self.ui, "start_turn", lambda st, *a, **k: started.append(st.sid))
        st = self.chat(queue=[{"id": "m1", "text": "later", "t": 1}])
        self.ui.PICKUP_WAIT[st.sid] = time.time() + 60
        self.addCleanup(self.ui.PICKUP_WAIT.pop, st.sid, None)
        self.ui._drain()
        self.assertEqual(started, [])
        self.assertEqual(len(st.queue), 1)


class TestFork(Base):
    def test_it_cuts_at_the_message_you_clicked_and_keeps_the_chats_settings(self):
        q = self.q
        msgs = [{"role": "system", "content": "s"},
                {"role": "user", "content": "one"}, {"role": "assistant", "content": "a"},
                {"role": "user", "content": "carry on", "nudge": True},
                {"role": "assistant", "content": "b"},
                {"role": "user", "content": "two"}, {"role": "assistant", "content": "c"}]
        q.session_save("f1", msgs, "orig", {"project": "p9", "model": "harness:claude/sonnet"})
        new = q.session_branch("f1", 1)
        raw = json.load(open(q.session_path(new)))
        self.assertEqual([m["content"] for m in raw["messages"]][-1], "b",
                         "the nudge was counted as your message")
        self.assertEqual((raw.get("project"), raw.get("model")), ("p9", "harness:claude/sonnet"))


class TestRunNow(Base):
    def setUp(self):
        super().setUp()
        self.jobs = {"jobs": [{"id": "j1", "every": "once", "at_ts": time.time() + 86400,
                               "enabled": True, "prompt": "hi", "name": "tomorrow"}]}
        def upd(fn): fn(self.jobs); return self.jobs
        self.patch(self.q, "sched_update", upd)
        self.patch(self.q, "sched_load", lambda: self.jobs)

    def test_trying_a_one_off_leaves_it_scheduled(self):
        self.patch(self.q, "turn", lambda msgs, *a, **k: (msgs.append({"role": "assistant", "content": "ok"}), "ok")[1])
        self.ui.run_job(self.jobs["jobs"][0], manual=True)
        j = self.jobs["jobs"][0]
        self.assertTrue(j["enabled"])
        self.assertFalse(j.get("last_run"))
        self.assertTrue(self.q.sched_due(j, time.time() + 86400 + 5))
        self.assertTrue(j["last_ok"])

    def test_it_cannot_start_twice(self):
        ui = self.ui
        ui.JOBS_INFLIGHT.add("j1"); self.addCleanup(ui.JOBS_INFLIGHT.discard, "j1")
        out = types.SimpleNamespace(code=None)
        class Fake(ui.H):
            def __init__(self): self.path = "/api/schedule/run"; self.headers = {}
            def _body(self): return {"id": "j1"}
            def _send(self, code, b, ctype="application/json", headers=None): out.code = code
        Fake()._post("/api/schedule/run")
        self.assertEqual(out.code, 409)

    def test_a_run_cut_off_shows_no_stale_result(self):
        self.jobs["jobs"][0].update(last_ok=True, last_result="yesterday's answer")
        self.ui._stamp_started("j1")
        j = self.jobs["jobs"][0]
        self.assertIsNone(j["last_ok"])
        self.assertNotIn("yesterday", j["last_result"])


class TestHelpersDoNotReview(unittest.TestCase):
    def test_only_the_answer_itself_reviews(self):
        src = open(os.path.join(ROOT, "bin", "qqcore.py")).read()
        self.assertIn('if not helper and mode and changed:', src)


if __name__ == "__main__":
    unittest.main()
