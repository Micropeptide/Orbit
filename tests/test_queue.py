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
        if st.lock.locked() or st.queue or len(self.ui.running_sids()) >= self.ui._max_parallel():
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


if __name__ == "__main__":
    unittest.main()
