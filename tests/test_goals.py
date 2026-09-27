"""Goals: a chat keeps working toward what you set until it is done, stuck, over its
budget or stopped -- across answers, whichever engine runs it. The model and the
progress check are stubbed; nothing here calls a model or touches real chats.
"""
import importlib.machinery, importlib.util, json, os, shutil, sys, tempfile, threading, time, types, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "bin"))

import qqcore as q


def load_ui():
    loader = importlib.machinery.SourceFileLoader("orbit_ui_goals", os.path.join(ROOT, "bin", "orbit-ui"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def verdict(status, reason="r", nxt="n"):
    return {"status": status, "reason": reason, "next": nxt, "failed": False}

FAILED = {"status": "", "reason": "no JSON", "next": "", "failed": True}


class TestTheStep(unittest.TestCase):
    def step(self, g, **kw):
        kw.setdefault("messages", [])
        return q.goal_after_answer(g, **kw)

    def test_continue_counts_a_turn_and_keeps_the_next_step(self):
        g = q.goal_new("ship it")
        v, g = self.step(g, audit=verdict("continue", nxt="write the tests"))
        self.assertEqual((v, g["turns_used"], g["note"]), ("continue", 1, "write the tests"))

    def test_complete_settles(self):
        v, g = self.step(q.goal_new("x"), audit=verdict("complete", "all checked"))
        self.assertEqual((v, g["status"], g["reason"]), ("stop", "complete", "all checked"))

    def test_one_blocked_verdict_is_a_snag_three_are_a_stop(self):
        g = q.goal_new("x")
        for i in range(q.GOAL_BLOCKED_STREAK - 1):
            v, g = self.step(g, audit=verdict("blocked"))
            self.assertEqual(v, "continue")
        v, g = self.step(g, audit=verdict("blocked", "needs a login"))
        self.assertEqual((v, g["status"], g["reason"]), ("stop", "blocked", "needs a login"))

    def test_progress_resets_the_blocked_streak(self):
        g = q.goal_new("x")
        _, g = self.step(g, audit=verdict("blocked"))
        _, g = self.step(g, audit=verdict("continue"))
        self.assertEqual(g["blocked_streak"], 0)

    def test_a_check_that_cannot_run_allows_one_blind_turn_then_stops(self):
        g = q.goal_new("x")
        v, g = self.step(g, audit=FAILED)
        self.assertEqual(v, "continue")
        v, g = self.step(g, audit=FAILED)
        self.assertEqual((v, g["status"]), ("stop", "blocked"))

    def test_the_turn_cap_stops_it(self):
        g = q.goal_new("x", max_turns=2)
        for _ in range(2): v, g = self.step(g, audit=verdict("continue"))
        v, g = self.step(g, audit=verdict("continue"))
        self.assertEqual((v, g["status"]), ("stop", "blocked"))

    def test_the_budget_counts_every_answer_and_stops_before_checking(self):
        g = q.goal_new("x", token_budget=1000)
        v, g = self.step(g, usage={"prompt_tokens": 600, "completion_tokens": 500},
                         audit={"status": "boom"})       # never consulted
        self.assertEqual((v, g["status"], g["tokens_used"]), ("stop", "budget", 1100))

    def test_stop_pauses_and_a_failed_answer_pauses(self):
        v, g = self.step(q.goal_new("x"), cancelled=True)
        self.assertEqual((v, g["status"]), ("stop", "paused"))
        v, g = self.step(q.goal_new("x"), failed="network")
        self.assertEqual((v, g["status"]), ("stop", "paused"))

    def test_the_continuation_keeps_the_plan_and_fences_the_objective(self):
        g = q.goal_new("make <<<x>>> work", token_budget=5000)
        g["note"] = "run the tests"
        t = q.build_continuation(g)
        self.assertTrue(t.startswith("Continue"), "turn() would start a fresh plan")
        self.assertIn("run the tests", t); self.assertIn("5,000", t); self.assertIn(q.ORBIT_SAYS, t)

    def test_the_audit_retries_once_on_a_reply_that_is_not_json(self):
        calls = []
        def fake(msgs, tools, **kw):
            calls.append(1)
            return {"content": "hmm" if len(calls) == 1 else '{"status": "complete", "reason": "ok"}'}
        saved = q.stream_call; q.stream_call = fake
        try: v = q._real_goal_audit([{"role": "user", "content": "x"}], q.goal_new("x"), model="m")
        finally: q.stream_call = saved
        self.assertEqual((len(calls), v["status"], v["failed"]), (2, "complete", False))


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = load_ui()
        # this copy of the server never starts a real answer, whatever a stray timer or
        # queue does after a test has finished (the tests that need a start patch over it)
        cls.ui.start_turn = lambda *a, **k: None

    def setUp(self):
        ui = self.ui
        self.tmp = tempfile.mkdtemp(prefix="orbit-goals-"); self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = (q.SESSIONS, ui.QUEUE_INDEX)
        self.addCleanup(lambda: (setattr(q, "SESSIONS", saved[0]), setattr(ui, "QUEUE_INDEX", saved[1])))
        q.SESSIONS = os.path.join(self.tmp, "s"); os.makedirs(q.SESSIONS)
        ui.QUEUE_INDEX = os.path.join(self.tmp, "queues.json")
        q._SESS_CACHE["key"] = None

    def patch(self, obj, name, value):
        old = getattr(obj, name); setattr(obj, name, value); self.addCleanup(setattr, obj, name, old)

    def chat(self):
        st = self.ui.State(); st.temp = False
        st.msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "go"},
                   {"role": "assistant", "content": "working"}]
        self.ui.STATES[st.sid] = st; self.addCleanup(self.ui.STATES.pop, st.sid, None)
        return st

    def call(self, body):
        out = types.SimpleNamespace(code=None, body=None)
        ui = self.ui
        class Fake(ui.H):
            def __init__(self): self.path = "/api/goal"; self.headers = {}
            def _body(self): return body
            def _send(self, code, b, ctype="application/json", headers=None):
                out.code, out.body = code, json.loads(b)
        Fake()._post("/api/goal")
        return out


class TestTheDriver(Server):
    def test_a_continue_verdict_queues_the_next_answer_and_starts_it(self):
        ui = self.ui
        started = []
        self.patch(ui, "start_turn", lambda st, text, *a, **k: started.append(text))
        self.patch(q, "goal_audit", lambda msgs, g, model=None: verdict("continue", nxt="next bit"))
        st = self.chat(); st.goal = q.goal_new("finish the report")
        ui._goal_step(st, False, None, {"prompt_tokens": 10, "completion_tokens": 5})
        self.assertEqual(len(started), 1)
        self.assertTrue(started[0].startswith("Continue working toward the goal"))
        self.assertEqual((st.goal["turns_used"], st.goal["tokens_used"]), (1, 15))
        saved = json.load(open(q.session_path(st.sid)))
        self.assertEqual(saved["goal"]["status"], "active")

    def test_done_settles_and_says_so(self):
        ui = self.ui
        said = []
        self.patch(q, "notify", lambda t, b: said.append(t))
        self.patch(q, "goal_audit", lambda msgs, g, model=None: verdict("complete", "tests pass"))
        st = self.chat(); st.goal = q.goal_new("x")
        ui._goal_step(st, False, None, None)
        self.assertEqual(st.goal["status"], "complete")
        self.assertEqual(said, ["Goal done"])
        self.assertEqual(st.queue, [])

    def test_your_queued_messages_go_first(self):
        ui = self.ui
        self.patch(q, "goal_audit", lambda *a, **k: self.fail("checked before your messages ran"))
        st = self.chat(); st.goal = q.goal_new("x")
        st.queue = [{"id": "m", "text": "mine", "t": 1}]
        self.patch(ui, "start_turn", lambda *a, **k: None)
        ui._goal_step(st, False, None, None)
        self.assertEqual([i["id"] for i in st.queue], ["m"])

    def test_stop_pauses_the_goal(self):
        ui = self.ui
        st = self.chat(); st.goal = q.goal_new("x")
        ui._goal_step(st, True, None, None)
        self.assertEqual(st.goal["status"], "paused")


class TestTheRoute(Server):
    def test_set_pause_resume_clear(self):
        ui = self.ui
        started = []
        self.patch(ui, "start_turn", lambda st, text, *a, **k: started.append(text))
        st = self.chat()
        r = self.call({"sid": st.sid, "op": "set", "objective": "get the build green", "token_budget": 50000})
        self.assertEqual((r.code, r.body["goal"]["status"]), (200, "paused"))
        r = self.call({"sid": st.sid, "op": "resume"})
        self.assertTrue(r.body["started"]); self.assertEqual(len(started), 1)
        self.assertEqual(st.goal["status"], "active")
        r = self.call({"sid": st.sid, "op": "pause"})
        self.assertEqual(st.goal["status"], "paused")
        r = self.call({"sid": st.sid, "op": "edit", "objective": "get the build green on CI"})
        self.assertEqual(st.goal["objective"], "get the build green on CI")
        self.assertEqual(st.goal["token_budget"], 50000, "an edit kept the budget")
        self.call({"sid": st.sid, "op": "clear"})
        self.assertIsNone(st.goal)
        self.assertNotIn("goal", json.load(open(q.session_path(st.sid))))

    def test_resuming_past_the_budget_needs_a_bigger_one(self):
        st = self.chat(); st.goal = q.goal_new("x", token_budget=100); st.goal.update(tokens_used=150, status="budget")
        self.assertEqual(self.call({"sid": st.sid, "op": "resume"}).code, 409)
        self.patch(self.ui, "start_turn", lambda *a, **k: None)
        self.assertEqual(self.call({"sid": st.sid, "op": "resume", "token_budget": 1000}).code, 200)

    def test_the_chat_list_shows_it(self):
        st = self.chat(); st.goal = q.goal_new("x"); self.ui.save_session(st)
        q._SESS_CACHE["key"] = None
        row = next(r for r in q.session_list() if r["id"] == st.sid)
        self.assertEqual(row["goal"], "active")


class TestTasksUntilDone(Server):
    def setUp(self):
        super().setUp()
        self.jobs = {"jobs": [{"id": "j1", "every": "daily", "at": "02:00", "enabled": True,
                               "prompt": "run the test suite and fix what fails", "name": "nightly",
                               "until_done": True}]}
        def upd(fn): fn(self.jobs); return self.jobs
        self.patch(q, "sched_update", upd)
        self.patch(q, "sched_load", lambda: self.jobs)
        self.patch(q, "notify", lambda *a, **k: None)
        self.patch(q, "turn", lambda msgs, *a, **k: (msgs.append({"role": "assistant", "content": "all green"}), "all green")[1])

    def test_it_stops_repeating_once_met(self):
        self.patch(q, "goal_audit", lambda msgs, g, model=None: verdict("complete", "every test passes"))
        self.ui.run_job(self.jobs["jobs"][0])
        j = self.jobs["jobs"][0]
        self.assertFalse(j["enabled"])
        self.assertTrue(j["last_result"].startswith("Done — every test passes"))

    def test_and_keeps_going_until_then(self):
        self.patch(q, "goal_audit", lambda msgs, g, model=None: verdict("continue", "two tests still fail"))
        self.ui.run_job(self.jobs["jobs"][0])
        self.assertTrue(self.jobs["jobs"][0]["enabled"])


class TestPush(unittest.TestCase):
    def test_nothing_is_sent_unless_configured(self):
        saved = dict(q.S); self.addCleanup(lambda: (q.S.clear(), q.S.update(saved)))
        q.S["push_ntfy_url"] = ""
        self.assertFalse(q.push_notify("t", "b"))


class TestTokensAreWhatIsNew(unittest.TestCase):
    def test_cached_prompt_is_not_spending(self):
        """A one-word answer in a Claude Code chat counted 43,000 tokens: its long
        opening is re-sent, cached, on every turn."""
        self.assertEqual(q.goal_tokens({"prompt_tokens": 43000, "cached_tokens": 42500, "completion_tokens": 5}), 505)
        self.assertEqual(q.goal_tokens({"prompt_tokens": 100, "completion_tokens": 20}), 120)
        g = q.goal_new("x", token_budget=10000)
        _, g = q.goal_after_answer(g, messages=[], usage={"prompt_tokens": 43000, "cached_tokens": 42900,
                                                         "completion_tokens": 3}, audit=verdict("continue"))
        self.assertEqual((g["status"], g["tokens_used"]), ("active", 103))


class TestHistory(unittest.TestCase):
    def test_each_check_and_stop_is_kept(self):
        g = q.goal_new("x")
        _, g = q.goal_after_answer(g, messages=[], audit=verdict("continue", "half done"))
        _, g = q.goal_after_answer(g, messages=[], audit=verdict("complete", "all checked"))
        self.assertEqual([h["verdict"] for h in g["history"]], ["set", "continue", "complete"])
        self.assertEqual(g["history"][-1]["reason"], "all checked")


class TestWhatLooksUnfinished(unittest.TestCase):
    def test_signals(self):
        wr = q.work_remaining
        self.assertTrue(wr("Done: a\nVerified: b\nRemaining: the docs"))
        self.assertTrue(wr("Remaining:\n- tests\n- docs"))
        self.assertTrue(wr("ok", plan_steps=[{"text": "a", "done": False}]))
        self.assertTrue(wr("ok", hit_limit="time"))
        self.assertTrue(wr("The migration is not yet finished."))

    def test_not_offered_when_done_optional_or_asking_you(self):
        wr = q.work_remaining
        self.assertEqual(wr("Done.\n\nRemaining: nothing"), "")
        self.assertEqual(wr("All done. Next steps you could take: add docs."), "")
        self.assertEqual(wr("Remaining: the deploy. Which server should it go to?"), "")
        self.assertEqual(wr("ok", plan_steps=[{"text": "a", "done": True}]), "")


class TestTheOffer(Server):
    def answered(self, text_answer):
        st = self.chat()
        st.msgs = [{"role": "system", "content": "s"},
                   {"role": "user", "content": "migrate every table to the new schema"},
                   {"role": "assistant", "content": text_answer}]
        return st

    def test_offered_then_taken_when_nobody_answers(self):
        ui = self.ui
        started = []
        self.patch(ui, "start_turn", lambda st, text, *a, **k: started.append(text))
        saved = dict(q.S); self.addCleanup(lambda: (q.S.clear(), q.S.update(saved)))
        q.S["goal_offer_wait_s"] = 0.2
        events = []
        st = self.answered("Done: three tables.\nRemaining: the other nine tables")
        ui._maybe_offer_goal(st, "migrate every table to the new schema", lambda k, p: events.append((k, p)))
        self.assertEqual(events[0][0], "goal_offer")
        self.assertIn("nine tables", events[0][1]["why"])
        end = time.time() + 5
        while (st.goal is None or not started) and time.time() < end: time.sleep(0.05)
        self.assertEqual(st.goal["objective"], "migrate every table to the new schema")
        self.assertIn("on its own", st.goal["reason"])
        self.assertEqual(len(started), 1, "the next answer did not start")

    def test_a_no_or_a_new_message_withdraws_it(self):
        ui = self.ui
        saved = dict(q.S); self.addCleanup(lambda: (q.S.clear(), q.S.update(saved)))
        q.S["goal_offer_wait_s"] = 0.2
        st = self.answered("Remaining: the other nine tables")
        ui._maybe_offer_goal(st, "migrate every table", lambda k, p: None)
        r = self.call({"sid": st.sid, "op": "decline"})
        self.assertEqual(r.code, 200); self.assertIsNone(st.goal_offer)
        time.sleep(0.4)
        self.assertIsNone(st.goal, "a declined offer was taken anyway")

    def test_accepting_starts_it_and_a_finished_answer_offers_nothing(self):
        ui = self.ui
        started = []
        self.patch(ui, "start_turn", lambda st, text, *a, **k: started.append(text))
        saved = dict(q.S); self.addCleanup(lambda: (q.S.clear(), q.S.update(saved)))
        q.S["goal_offer_wait_s"] = 0
        st = self.answered("Remaining: two files")
        ui._maybe_offer_goal(st, "tidy the repo", lambda k, p: None)
        r = self.call({"sid": st.sid, "op": "accept"})
        self.assertTrue(r.body["started"]); self.assertEqual(st.goal["status"], "active")
        st2 = self.answered("All done. Remaining: nothing")
        ui._maybe_offer_goal(st2, "tidy the repo", lambda k, p: self.fail("offered for finished work"))
        self.assertIsNone(st2.goal_offer)

    def test_the_objective_is_the_request_not_continue(self):
        st = self.answered("x")
        self.assertEqual(self.ui._goal_objective(st, "continue"), "migrate every table to the new schema")


class TestPushTitles(unittest.TestCase):
    def test_a_title_outside_latin1_is_encoded_not_mangled(self):
        sent = []
        class R:
            def read(self): return b""
        saved_open, saved = q.urllib.request.urlopen, dict(q.S)
        def fake(req, timeout=None): sent.append(req); return R()
        q.urllib.request.urlopen = fake
        self.addCleanup(lambda: (setattr(q.urllib.request, "urlopen", saved_open), q.S.clear(), q.S.update(saved)))
        q.S["push_ntfy_url"] = "https://ntfy.example/topic"
        saved_thread = q.threading.Thread
        class Now:
            def __init__(self, target=None, daemon=None): self.t = target
            def start(self): self.t()
        q.threading.Thread = Now; self.addCleanup(setattr, q.threading, "Thread", saved_thread)
        self.assertTrue(q.push_notify("Goal done — 論文", "x"))
        t = sent[0].get_header("Title")
        self.assertTrue(t.startswith("=?UTF-8?B?"), t)


if __name__ == "__main__":
    unittest.main()
