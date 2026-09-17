"""Queued messages and many chats answering at once (bin/orbit-ui), with a stand-in
for the model: no model server, nothing written to your chats (temporary chats)."""
import importlib.machinery, importlib.util, os, sys, threading, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "bin"))


def load_ui():
    loader = importlib.machinery.SourceFileLoader("orbit_ui_under_test", os.path.join(ROOT, "bin", "orbit-ui"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class TestQueue(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = ui = load_ui()
        q = cls.q = ui.q
        cls.saved = {k: getattr(q, k) for k in ("turn", "slot_enter", "slot_exit", "maybe_autocompact",
                                                   "ledger_add", "notify")}
        cls.saved_ui = {k: getattr(ui, k) for k in ("autotitle", "_learn_later", "_refresh_system", "_max_parallel")}
        cls.log, cls.gates = [], {}

        def fake_turn(msgs, content, tools, emit=None, cancel=None, sid=None, **kw):
            text = content if isinstance(content, str) else content[0]["text"]
            cls.log.append(("start", sid, text, q.pinned_model(), getattr(q.TURN_CTX, "pin_effort", None)))
            gate = cls.gates.get(text)
            if gate:
                while not gate.wait(0.05):
                    if cancel is not None and cancel.is_set(): break
            else:
                time.sleep(0.05)
            msgs.append({"role": "user", "content": content})
            msgs.append({"role": "assistant", "content": "done: " + text})
            cls.log.append(("end", sid, text))
            return "done"

        q.turn = fake_turn
        q.slot_enter = lambda *a, **k: True
        q.slot_exit = lambda *a, **k: None
        q.maybe_autocompact = lambda msgs, emit=None, sid=None: (msgs, False, 0)
        q.ledger_add = lambda *a, **k: None
        q.notify = lambda *a, **k: None
        ui.autotitle = lambda msgs: None
        ui._learn_later = lambda *a, **k: None
        ui._refresh_system = lambda st: None
        ui._max_parallel = lambda: 3

    @classmethod
    def tearDownClass(cls):
        for k, v in cls.saved.items(): setattr(cls.q, k, v)
        for k, v in cls.saved_ui.items(): setattr(cls.ui, k, v)

    def setUp(self):
        self.log.clear(); self.gates.clear()

    def chat(self, model=None):
        st = self.ui.State()
        st.temp = True                     # never written to disk
        st.model = model
        st.refresh_tools = lambda: None
        st.title = "t"
        self.ui.STATES[st.sid] = st
        self.addCleanup(self.ui.STATES.pop, st.sid, None)
        return st

    def send(self, st, text, effort=None):
        """What /api/chat does: start now if free, else queue."""
        if st.lock.locked() or self.ui._due_items(st) or len(self.ui.running_sids()) >= self.ui._max_parallel():
            self.ui._queue_add(st, text, None, effort)
            self.ui._drain()
            return "queued"
        self.assertTrue(st.lock.acquire(blocking=False))
        self.ui.start_turn(st, text, None, effort)
        return "started"

    def wait(self, cond, secs=5):
        end = time.time() + secs
        while time.time() < end:
            if cond(): return True
            time.sleep(0.02)
        return False

    def starts(self, sid=None):
        return [e[2] for e in self.log if e[0] == "start" and (sid is None or e[1] == sid)]

    def test_messages_wait_their_turn_in_the_order_you_set(self):
        st = self.chat()
        self.gates["first"] = g = threading.Event()
        self.assertEqual(self.send(st, "first"), "started")
        self.assertTrue(self.wait(lambda: self.starts() == ["first"]))
        for t in ("second", "third", "fourth"):
            self.assertEqual(self.send(st, t), "queued")
        # reorder: fourth before second, and edit third
        ids = {it["text"]: it["id"] for it in st.queue}
        st.queue.sort(key=lambda it: [ids["fourth"], ids["second"], ids["third"]].index(it["id"]))
        next(it for it in st.queue if it["text"] == "third")["text"] = "third, edited"
        time.sleep(0.2)
        self.assertEqual(self.starts(), ["first"])          # nothing jumps in while it answers
        g.set()
        self.assertTrue(self.wait(lambda: len([e for e in self.log if e[0] == "end"]) == 4))
        self.assertEqual(self.starts(), ["first", "fourth", "second", "third, edited"])
        self.assertFalse(st.queue)
        self.assertEqual([m["content"] for m in st.msgs if m["role"] == "user"],
                         ["first", "fourth", "second", "third, edited"])

    def test_stop_pauses_the_queue(self):
        st = self.chat()
        self.gates["long"] = threading.Event()
        self.send(st, "long")
        self.assertTrue(self.wait(lambda: self.starts() == ["long"]))
        self.send(st, "after")
        st.cancel.set()
        self.assertTrue(self.wait(lambda: not st.lock.locked()))
        time.sleep(0.3)
        self.assertTrue(st.queue_paused)
        self.assertEqual(self.starts(), ["long"])
        st.queue_paused = False
        self.ui._drain()
        self.assertTrue(self.wait(lambda: self.starts() == ["long", "after"]))

    def test_many_chats_at_once_each_on_its_own_model_and_effort(self):
        gate = threading.Event()
        chats = [self.chat(model=f"model-{i}") for i in range(5)]
        for i, st in enumerate(chats):
            self.gates[f"m{i}"] = gate
            self.send(st, f"m{i}", effort=f"e{i}")
        # three answer at once; the other two wait for a free slot
        self.assertTrue(self.wait(lambda: len(self.starts()) == 3))
        time.sleep(0.2)
        self.assertEqual(len(self.starts()), 3)
        self.assertEqual(sum(len(st.queue) for st in chats), 2)
        gate.set()
        self.assertTrue(self.wait(lambda: len([e for e in self.log if e[0] == "end"]) == 5))
        for e in self.log:
            if e[0] != "start": continue
            i = int(e[2][1:])
            self.assertEqual((e[3], e[4]), (f"model-{i}", f"e{i}"), "a chat ran on another chat's model")

    def test_no_limit_on_remote_chats_but_the_local_model_takes_turns(self):
        ui, q = self.ui, self.q
        ui._max_parallel = self.saved_ui["_max_parallel"]          # the real default: no limit
        saved_local, saved_slot = q.model_is_local, (q.slot_enter, q.slot_exit)
        q.slot_enter, q.slot_exit = self.saved["slot_enter"], self.saved["slot_exit"]
        q.model_is_local = lambda mid=None: str(mid or q.pinned_model() or "").startswith("local:")
        live, peak = {"local": 0, "remote": 0}, {"local": 0, "remote": 0}
        lock = threading.Lock()
        inner = q.turn
        def counting_turn(msgs, content, tools, **kw):
            kind = "local" if str(q.pinned_model()).startswith("local:") else "remote"
            with lock:
                live[kind] += 1; peak[kind] = max(peak[kind], live[kind])
            try: return inner(msgs, content, tools, **kw)
            finally:
                with lock: live[kind] -= 1
        q.turn = counting_turn
        try:
            gate = threading.Event()
            chats = [self.chat(model=f"harness:opencode-go/m{i}") for i in range(12)] + \
                    [self.chat(model="local:qwen") for _ in range(2)]
            for i, st in enumerate(chats):
                self.gates[f"c{i}"] = gate
                self.assertEqual(self.send(st, f"c{i}"), "started")       # nothing refused or queued
            self.assertTrue(self.wait(lambda: peak["remote"] == 12))
            time.sleep(0.3)
            self.assertEqual(peak["local"], 1)                              # the second local chat waits
            gate.set()
            self.assertTrue(self.wait(lambda: len([e for e in self.log if e[0] == "end"]) == 14, 10))
            self.assertEqual(peak["local"], 1)
        finally:
            q.turn, q.model_is_local = inner, saved_local
            q.slot_enter, q.slot_exit = saved_slot
            ui._max_parallel = lambda: 3

    def test_queue_view_hides_attachment_data(self):
        st = self.chat()
        st.lock.acquire()
        try:
            self.ui._queue_add(st, "with a picture", [{"kind": "image", "name": "a.png", "data_url": "data:image/png;base64,AAAA"}])
            view = self.ui._queue_view(st)
            self.assertEqual(view["items"][0]["attachments"], [{"name": "a.png", "kind": "image"}])
            self.assertNotIn("base64", str(view))
        finally:
            st.queue.clear(); st.lock.release()

    def test_a_scheduled_message_goes_out_at_its_time_without_holding_others_back(self):
        ui = self.ui
        st = self.chat()
        ui._queue_add(st, "later", at=time.time() + 0.6)
        # a message scheduled for later does not make new ones queue
        self.assertEqual(self.send(st, "now"), "started")
        self.assertTrue(self.wait(lambda: self.starts() == ["now"]))
        self.assertTrue(self.wait(lambda: not st.lock.locked()))
        ui._drain()
        time.sleep(0.2)
        self.assertEqual(self.starts(), ["now"])                  # not yet
        time.sleep(0.6)
        ui._drain()                                                # what the 15-second ticker does
        self.assertTrue(self.wait(lambda: self.starts() == ["now", "later"]))
        self.assertFalse(st.queue)
        self.assertTrue(self.wait(lambda: not st.lock.locked()))

    def test_a_repeating_message_books_its_next_time(self):
        ui = self.ui
        st = self.chat()
        at = time.time() + 0.3
        st.queue.append({"id": "r1", "text": "daily check", "attachments": [], "effort": None, "t": 0,
                         "at": at, "repeat": "daily"})
        time.sleep(0.4)
        ui._drain()
        self.assertTrue(self.wait(lambda: self.starts() == ["daily check"]))
        self.assertTrue(self.wait(lambda: len(st.queue) == 1))
        nxt = st.queue[0]
        self.assertEqual((nxt["text"], nxt["repeat"]), ("daily check", "daily"))
        self.assertAlmostEqual(nxt["at"] - at, 86400, delta=3700)     # same clock time tomorrow (DST aside)
        self.assertEqual(time.localtime(nxt["at"]).tm_hour, time.localtime(at).tm_hour)
        st.queue.clear()
        self.assertTrue(self.wait(lambda: not st.lock.locked()))

    def test_weekdays_skip_the_weekend_and_long_missed_times_are_not_sent(self):
        ui = self.ui
        fri = time.mktime((2026, 9, 18, 9, 0, 0, 0, 0, -1))          # a Friday, 09:00
        mon = ui._next_time(fri, "weekdays", now=fri + 60)
        self.assertEqual(time.localtime(mon).tm_wday, 0)
        self.assertEqual(time.localtime(mon).tm_hour, 9)
        self.assertEqual(time.localtime(ui._next_time(fri, "weekly", now=fri + 60)).tm_mday, 25)
        st = self.chat()
        old = time.time() - 30 * 3600
        st.queue += [{"id": "o", "text": "one-off", "at": old, "attachments": []},
                     {"id": "r", "text": "repeat", "at": old, "repeat": "daily", "attachments": []}]
        ui._drain()
        time.sleep(0.3)
        self.assertEqual(self.starts(), [])                       # neither goes out a day late
        one, rep = st.queue
        self.assertTrue(one["missed"])
        self.assertGreater(rep["at"], time.time())
        self.assertEqual(rep["skipped"], 1)
        with self.assertRaises(ValueError):
            ui._queue_add(st, "x", at=time.time() + 60, repeat="hourly")
        st.queue.clear()

    def test_stop_does_not_cancel_a_scheduled_message(self):
        ui = self.ui
        st = self.chat()
        self.gates["long2"] = threading.Event()
        self.send(st, "long2")
        self.assertTrue(self.wait(lambda: self.starts() == ["long2"]))
        self.send(st, "waiting")
        ui._queue_add(st, "at nine", at=time.time() + 0.5)
        st.cancel.set()
        self.assertTrue(self.wait(lambda: not st.lock.locked()))
        time.sleep(0.7)
        ui._drain()
        self.assertTrue(self.wait(lambda: self.starts() == ["long2", "at nine"]))
        self.assertTrue(self.wait(lambda: not st.lock.locked()))
        self.assertEqual([it["text"] for it in st.queue], ["waiting"])   # paused ones stay paused
        st.queue.clear()

    def test_a_scheduled_message_can_be_edited_and_given_its_own_model(self):
        ui = self.ui
        st = self.chat(model="model-chat")
        ui._queue_add(st, "report", at=time.time() + 3600)
        iid = st.queue[0]["id"]
        it, err = ui.queue_update(st, iid, {"text": "report, briefly", "repeat": "weekdays", "model": "model-B"})
        self.assertIsNone(err)
        self.assertEqual((it["text"], it["repeat"], it["model"]), ("report, briefly", "weekdays", "model-B"))
        self.assertEqual(ui.queue_update(st, iid, {"at": time.time() - 3600, "repeat": None})[1], "that time has passed")
        it, err = ui.queue_update(st, iid, {"model": ""})
        self.assertNotIn("model", it)
        ui.queue_update(st, iid, {"model": "model-B", "at": time.time() + 0.3, "repeat": None})
        self.assertNotIn("repeat", st.queue[0])
        rows = [r for r in ui.scheduled_messages() if r["sid"] == st.sid]
        self.assertEqual((rows[0]["model"], rows[0]["chat_model"]), ("model-B", "model-chat"))
        time.sleep(0.4); ui._drain()
        self.assertTrue(self.wait(lambda: self.starts() == ["report, briefly"]))
        start = [e for e in self.log if e[0] == "start"][0]
        self.assertEqual(start[3], "model-B")                     # it ran on the model it was scheduled for
        self.assertEqual(st.model, "model-B")                     # and the chat moved to it
        self.assertTrue(self.wait(lambda: not st.lock.locked()))
        # a plain queued message can be given a time, and a scheduled one sent back to the queue
        st.lock.acquire()
        try:
            ui._queue_add(st, "later maybe")
            iid = st.queue[0]["id"]
            ui.queue_update(st, iid, {"at": time.time() + 999})
            self.assertTrue(st.queue[0].get("at"))
            ui.queue_update(st, iid, {"at": None})
            self.assertNotIn("at", st.queue[0])
        finally:
            st.queue.clear(); st.lock.release()

    def test_sending_a_repeating_message_now_into_a_running_answer_keeps_the_series(self):
        ui = self.ui
        st = self.chat()
        st.queue.append({"id": "rep1", "text": "daily digest", "attachments": [], "at": time.time() + 3600, "repeat": "daily"})
        st.lock.acquire()
        try:
            import types
            h = types.SimpleNamespace(sent=None)
            class Fake(ui.H):
                def __init__(self): self.path = "/api/queue"
                def _body(self): return {"sid": st.sid, "op": "now", "id": "rep1"}
                def _send(self, code, body, ctype="application/json"): h.sent = (code, body)
            Fake()._post("/api/queue")
            self.assertIn("interjected", h.sent[1])
            self.assertEqual(len(st.queue), 1)
            self.assertEqual((st.queue[0]["text"], st.queue[0]["repeat"]), ("daily digest", "daily"))
            self.assertGreater(st.queue[0]["at"], time.time() + 3600 * 20)
            self.assertEqual(st.inbox[-1]["text"], "daily digest")
        finally:
            st.queue.clear(); st.inbox.clear(); st.lock.release()


if __name__ == "__main__":
    unittest.main()
