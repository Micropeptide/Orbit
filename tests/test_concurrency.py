"""Two things at once: several prompts waiting, two devices answering, a window reading
an answer while it is being written. Each of these raced, and the loser was a prompt
nobody could answer, an answer that went to the wrong request, or a view that stopped.
"""
import importlib.machinery, importlib.util, json, os, queue, sys, threading, types, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "bin"))


def load_ui():
    loader = importlib.machinery.SourceFileLoader("orbit_ui_concurrency", os.path.join(ROOT, "bin", "orbit-ui"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = load_ui()

    def state(self):
        st = self.ui.State()
        st.temp = True
        return st


class TestSeveralPromptsAtOnce(Base):
    """One slot held the pending approval. A second overwrote the first, and answering the
    first deleted the second -- which then waited out its 15 minutes, unseen, and was denied."""

    def test_answering_one_leaves_the_other_showing(self):
        ui, st, Q = self.ui, self.state(), queue.Queue()
        ui._pending_put(st, "approval", {"id": "a1", "name": "first"})
        ui._pending_put(st, "approval", {"id": "a2", "name": "second"})
        self.assertEqual(st.live["approval"]["id"], "a1", "the oldest is the one shown")
        self.assertEqual(set(st.live["approvals"]), {"a1", "a2"})
        ui._pending_done(st, "approval", "a1", {"allow": True}, Q)
        self.assertEqual(st.live["approval"]["id"], "a2", "the second vanished with the first")
        ui._pending_done(st, "approval", "a2", {"allow": False}, Q)
        self.assertNotIn("approval", st.live)

    def test_every_window_is_told_it_was_answered(self):
        ui, st, Q = self.ui, self.state(), queue.Queue()
        ui._pending_put(st, "approval", {"id": "a9"})
        ui._pending_done(st, "approval", "a9", {"allow": True, "expired": False}, Q)
        k, p = Q.get_nowait()
        self.assertEqual((k, p["id"], p["allow"]), ("approval_resolved", "a9", True))

    def test_questions_queue_the_same_way(self):
        ui, st, Q = self.ui, self.state(), queue.Queue()
        ui._pending_put(st, "question", {"id": "q1"}); ui._pending_put(st, "question", {"id": "q2"})
        ui._pending_done(st, "question", "q1", {}, Q)
        self.assertEqual(st.live["question"]["id"], "q2")


class TestIdsNeverCollide(Base):
    def test_under_many_threads(self):
        """`seq[0] += 1` from a thread per prompt could hand two prompts the same id."""
        ids, lock = [], threading.Lock()
        def take():
            got = [self.ui._prompt_id("ap") for _ in range(300)]
            with lock: ids.extend(got)
        ts = [threading.Thread(target=take) for _ in range(8)]
        for t in ts: t.start()
        for t in ts: t.join()
        self.assertEqual(len(ids), len(set(ids)))


class TestTheFirstAnswerIsTheAnswer(Base):
    """The Mac and the phone both show the card. A Deny and an Allow a moment apart both
    succeeded, and which one counted depended on thread timing."""

    def call(self, path, body):
        out = types.SimpleNamespace(code=None, body=None)
        ui = self.ui
        class Fake(ui.H):
            def __init__(self): self.path = path; self.headers = {}
            def _body(self): return body
            def _send(self, code, b, ctype="application/json", headers=None):
                out.code, out.body = code, json.loads(b)
        Fake()._post(path)
        return out

    def test_a_second_answer_is_refused(self):
        ev = threading.Event()
        self.ui.PENDING["apX"] = {"event": ev, "allow": False}
        self.addCleanup(self.ui.PENDING.pop, "apX", None)
        first = self.call("/api/approve", {"id": "apX", "allow": False})
        second = self.call("/api/approve", {"id": "apX", "allow": True})
        self.assertEqual(first.code, 200)
        self.assertEqual(second.code, 409)
        self.assertFalse(self.ui.PENDING["apX"]["allow"], "the later answer overwrote the first")

    def test_and_for_questions(self):
        self.ui.PENDING["qaX"] = {"event": threading.Event(), "answer": None}
        self.addCleanup(self.ui.PENDING.pop, "qaX", None)
        self.assertEqual(self.call("/api/answer", {"id": "qaX", "answer": "A"}).code, 200)
        self.assertEqual(self.call("/api/answer", {"id": "qaX", "answer": "B"}).code, 409)
        self.assertEqual(self.ui.PENDING["qaX"]["answer"], "A")


class TestReadingAnAnswerWhileItIsWritten(Base):
    def test_the_view_is_a_copy(self):
        """Nested, not just top level: the view handed back the answer's own dicts, which
        went on growing after it was taken. (A string would look stable either way.)"""
        ui, st = self.ui, self.state()
        ui._live_record(st, "bgtask", {"id": 1, "kind": "shell", "status": "running"})
        view = ui._live_view(st)
        ui._live_record(st, "bgtask", {"id": 2, "kind": "shell", "status": "running"})
        self.assertEqual(len(view["bgtasks"]), 1, "the view kept changing after it was taken")

    def test_no_dictionary_changed_size_during_iteration(self):
        """The failure was a 500 from /api/live -- the route serialises the view while the
        answer adds background tasks and tool results to dicts inside it -- and the web
        page stops following an answer after one failed poll."""
        ui, st = self.ui, self.state()
        done, errors = threading.Event(), []
        def write():                                   # a bounded answer, so reads stay cheap
            for i in range(400):
                ui._live_record(st, "bgtask", {"id": i, "kind": "shell", "status": "running"})
                ui._live_record(st, "tool_start", {"name": "t", "args": {}, "id": f"c{i}"})
                ui._live_record(st, "tool_result", {"id": f"c{i}", "ok": True, "secs": 0.1})
            done.set()
        def read():
            while not done.is_set():
                try: json.dumps(ui._live_view(st))          # what the route does with it
                except Exception as e:
                    errors.append(e); return
        readers = [threading.Thread(target=read) for _ in range(3)]
        for r in readers: r.start()
        w = threading.Thread(target=write); w.start()
        w.join(30); done.set()
        for r in readers: r.join(30)
        self.assertEqual(errors, [])


class TestConnectionsAreLetGo(Base):
    def test_idle_keep_alive_has_a_limit(self):
        self.assertTrue(self.ui.H.timeout and self.ui.H.timeout <= 300)

    def test_dead_peers_are_noticed(self):
        self.assertIn("SO_KEEPALIVE", open(os.path.join(ROOT, "bin", "orbit-ui")).read())


class TestAnotherDevicesNewChatLeavesYoursAlone(Base):
    def test_a_temporary_chat_stays_reachable_and_unerased(self):
        ui = self.ui
        erased, saved_S, saved_erase = [], ui.S, ui.erase_temp_traces
        ui.erase_temp_traces = lambda st: erased.append(st.sid)
        self.addCleanup(lambda: (setattr(ui, "S", saved_S), setattr(ui, "erase_temp_traces", saved_erase)))
        mine = ui.State(); mine.temp = True
        mine.msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "private"}]
        ui.S = mine
        ui.fresh_state(leaving=False)                    # the phone pressed New
        self.addCleanup(ui.STATES.pop, mine.sid, None)
        self.assertEqual(erased, [], "the Mac's temporary chat was erased")
        self.assertIs(ui.STATES.get(mine.sid), mine, "and dropped from memory")

    def test_leaving_it_yourself_still_cleans_up(self):
        ui = self.ui
        erased, saved_S, saved_erase = [], ui.S, ui.erase_temp_traces
        ui.erase_temp_traces = lambda st: erased.append(st.sid)
        self.addCleanup(lambda: (setattr(ui, "S", saved_S), setattr(ui, "erase_temp_traces", saved_erase)))
        mine = ui.State(); mine.temp = True
        ui.S = mine
        ui.fresh_state(leaving=True)
        self.assertEqual(erased, [mine.sid])


if __name__ == "__main__":
    unittest.main()
