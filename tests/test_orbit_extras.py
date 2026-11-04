import importlib.machinery, importlib.util, os, sys, threading, time, types, unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "bin"))


class Extras(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        loader = importlib.machinery.SourceFileLoader("orbit_ui_extras_test", os.path.join(ROOT, "bin", "orbit-ui"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        cls.ui = importlib.util.module_from_spec(spec)
        loader.exec_module(cls.ui)

    def setUp(self):
        self.sent = []
        self.ui._notify_after = lambda title, text, sid, mac: self.sent.append((title, text, mac))
        self.old = self.ui.q.S.get("notify_long_min"); self.addCleanup(self._restore)
        self.ui.q.S["notify_long_min"] = 5
        self.st = types.SimpleNamespace(cancel=threading.Event(), temp=False, title="Cassini", sid="s1",
                                        msgs=[{"role": "assistant", "content": "All  done.\nTotals below."}])

    def _restore(self):
        if self.old is None: self.ui.q.S.pop("notify_long_min", None)
        else: self.ui.q.S["notify_long_min"] = self.old

    def test_only_a_long_answer_tells_you(self):
        self.ui._notify_long(self.st, 60, True, None)
        self.assertEqual(self.sent, [])
        self.ui._notify_long(self.st, 400, True, None)
        self.assertEqual(self.sent, [("Answer ready", "Cassini: All done. Totals below.", True)])

    def test_a_stopped_or_temporary_chat_or_zero_minutes_says_nothing(self):
        self.st.cancel.set(); self.ui._notify_long(self.st, 4000, True, None)
        self.st.cancel.clear(); self.st.temp = True; self.ui._notify_long(self.st, 4000, True, None)
        self.st.temp = False; self.ui.q.S["notify_long_min"] = 0; self.ui._notify_long(self.st, 4000, True, None)
        self.assertEqual(self.sent, [])

    def test_a_failed_answer_says_so(self):
        self.ui._notify_long(self.st, 400, False, "limit")
        self.assertEqual(self.sent[0][0], "Answer failed")

    def test_a_long_background_task_ending_tells_you_and_a_short_one_does_not(self):
        self.ui.STATES["s1"] = self.st
        self.addCleanup(self.ui.STATES.pop, "s1", None)
        self.ui._bg_done("s1", {"since": 0, "ended": 60, "status": "completed", "description": "dry run"})
        self.assertEqual(self.sent, [])
        self.ui._bg_done("s1", {"since": 0, "ended": 900, "status": "completed", "description": "dry run"})
        self.assertEqual(self.sent[0][0], "Background task finished")
        self.assertIn("dry run", self.sent[0][1])

    def test_a_waiting_restart_can_be_cancelled(self):
        ui = self.ui
        busy = [True]
        saved = ui.restart_blockers; ui.restart_blockers = lambda: ["x"] if busy[0] else []
        bowed = []; sb = ui._bow_out; ui._bow_out = lambda: bowed.append(1)
        self.addCleanup(lambda: (setattr(ui, "restart_blockers", saved), setattr(ui, "_bow_out", sb),
                                 ui._RESTART_WAITING.clear(), ui.CREW_HOLD.clear(), ui._RESTART_CANCEL.clear()))
        ui._restart_when_idle()
        self.assertTrue(ui._RESTART_WAITING.is_set())
        ui._RESTART_CANCEL.set()
        for _ in range(60):
            if not ui._RESTART_WAITING.is_set(): break
            time.sleep(0.1)
        self.assertFalse(ui._RESTART_WAITING.is_set(), "cancelled")
        self.assertFalse(ui.CREW_HOLD.is_set())
        self.assertEqual(bowed, [])


if __name__ == "__main__":
    unittest.main()


class StopIsNotACrash(unittest.TestCase):
    """After Stop, the chat file must not say 'answering': a restart then picks the chat up again against your wish."""
    def test_save_after_stop_leaves_no_running_flag(self):
        ui = Extras.ui if hasattr(Extras, "ui") else None
        if ui is None:
            loader = importlib.machinery.SourceFileLoader("orbit_ui_extras_test2", os.path.join(ROOT, "bin", "orbit-ui"))
            spec = importlib.util.spec_from_loader(loader.name, loader); ui = importlib.util.module_from_spec(spec); loader.exec_module(ui)
        src = open(os.path.join(ROOT, "bin", "orbit-ui")).read()
        i = src.index('if p == "/api/cancel":'); block = src[i:i + 2600]
        self.assertIn("st.running = False", block)
        self.assertLess(block.index("st.cancel.set()"), block.index("st.running = False"))
        self.assertIn("save_session(st)", block[block.index("st.running = False"):])
