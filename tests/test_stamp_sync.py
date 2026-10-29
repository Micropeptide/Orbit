"""A phone watching a Claude Code chat must see it move when it is continued in a terminal:
the stamp endpoint brings that in first -- but not on every poll."""
import importlib.machinery, importlib.util, os, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin"))


def load_ui():
    loader = importlib.machinery.SourceFileLoader("orbit_ui_stamp_test", os.path.join(ROOT, "bin", "orbit-ui"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class TestStampSync(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = load_ui()

    def setUp(self):
        self.calls = []
        self.saved = self.ui._claude_sync
        self.ui._claude_sync = self.calls.append
        self.addCleanup(setattr, self.ui, "_claude_sync", self.saved)
        self.ui._STAMP_SYNC.clear()

    def test_the_first_poll_syncs_and_the_next_ones_wait(self):
        self.ui._stamp_sync("c1")
        self.ui._stamp_sync("c1")
        self.ui._stamp_sync("c1")
        self.assertEqual(self.calls, ["c1"])

    def test_each_chat_has_its_own_clock(self):
        self.ui._stamp_sync("c1"); self.ui._stamp_sync("c2")
        self.assertEqual(sorted(self.calls), ["c1", "c2"])

    def test_it_syncs_again_after_the_wait(self):
        self.ui._stamp_sync("c1")
        self.ui._STAMP_SYNC["c1"] -= 7
        self.ui._stamp_sync("c1")
        self.assertEqual(self.calls, ["c1", "c1"])


if __name__ == "__main__":
    unittest.main()
