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
        try: v = q.goal_audit([{"role": "user", "content": "x"}], q.goal_new("x"), model="m")
        finally: q.stream_call = saved
        self.assertEqual((len(calls), v["status"], v["failed"]), (2, "complete", False))


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = load_ui()

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


class TestPush(unittest.TestCase):
    def test_nothing_is_sent_unless_configured(self):
        saved = dict(q.S); self.addCleanup(lambda: (q.S.clear(), q.S.update(saved)))
        q.S["push_ntfy_url"] = ""
        self.assertFalse(q.push_notify("t", "b"))


if __name__ == "__main__":
    unittest.main()
