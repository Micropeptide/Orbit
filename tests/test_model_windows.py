"""Model windows that keep themselves up to date.

Claude Opus was listed at 200k, written into the code, while the Opus that "opus" meant had
1M. The Claude subscription's models are aliases for the newest of each family, so their
windows come from models.dev's newest; a window the engine reported in use beats any list;
your own setting beats both. Every test runs on a temporary Orbit folder.
"""
import json, os, shutil, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))

import harness as H


DEV = {"anthropic": {"models": {
    "claude-opus-4-8":  {"name": "Claude Opus 4.8", "family": "claude-opus", "release_date": "2026-03-01",
                         "limit": {"context": 1000000}},
    "claude-opus-5-5":  {"name": "Claude Opus 5.5", "family": "claude-opus", "release_date": "2026-09-22",
                         "limit": {"context": 1000000}},
    "claude-sonnet-4-5": {"name": "Claude Sonnet 4.5", "family": "claude-sonnet", "release_date": "2025-09-29",
                          "limit": {"context": 200000}},
    "claude-sonnet-5-5": {"name": "Claude Sonnet 5.5", "family": "claude-sonnet", "release_date": "2026-09-22",
                          "limit": {"context": 1000000}},
    "claude-haiku-4-5": {"name": "Claude Haiku 4.5", "family": "claude-haiku", "release_date": "2025-10-01",
                         "limit": {"context": 200000}},
}}}


class Root(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="orbit-windows-")
        self.addCleanup(shutil.rmtree, self.root, True)
        os.makedirs(os.path.join(self.root, "config"))
        saved = H._learned_path                     # this test's own, not the run's shared one
        H._learned_path = lambda root: os.path.join(root, "config", "learned-windows.json")
        self.addCleanup(setattr, H, "_learned_path", saved)

    def dev(self, d=DEV):
        json.dump(d, open(os.path.join(self.root, "config", "models-dev.json"), "w"))

    def claude(self):
        return {m["id"]: m for m in H.providers(self.root)["claude"]["models"]}


class TestTheSubscriptionsAliases(Root):
    def test_each_alias_takes_its_newest_models_window(self):
        self.dev()
        m = self.claude()
        self.assertEqual((m["opus"]["context"], m["sonnet"]["context"], m["haiku"]["context"]),
                         (1000000, 1000000, 200000))
        self.assertIn("Opus 5.5", m["opus"]["label"])           # and says which model that is now

    def test_the_1m_variants_go_when_the_alias_is_1m_already(self):
        self.dev()
        m = self.claude()
        self.assertNotIn("opus[1m]", m)
        self.assertNotIn("sonnet[1m]", m)

    def test_without_the_catalogue_the_built_in_sizes_stand(self):
        self.assertEqual(self.claude()["opus"]["context"], 200000)


class TestLearnedFromUse(Root):
    def test_a_window_the_engine_reported_beats_the_lists(self):
        self.dev()
        H.learn_window(self.root, "claude/haiku", 400000)
        self.assertEqual(self.claude()["haiku"]["context"], 400000)

    def test_your_own_setting_beats_everything(self):
        self.dev()
        H.learn_window(self.root, "claude/opus", 1000000)
        cfg = H.load(self.root); cfg["contexts"]["claude/opus"] = 500000; H.save(self.root, cfg)
        self.assertEqual(self.claude()["opus"]["context"], 500000)

    def test_nonsense_is_not_learned(self):
        for w in (0, -5, "big", 10**9):
            H.learn_window(self.root, "claude/opus", w)
        self.assertEqual(H.learned_windows(self.root), {})


class TestClaudeCodeTeachesIt(Root):
    def test_a_reported_window_is_kept_for_the_model(self):
        import qqcore as q, claude_engine as CE
        saved = q.ROOT; q.ROOT = self.root; self.addCleanup(setattr, q, "ROOT", saved)
        self.addCleanup(q.SESSION_WINDOW.pop, "w1", None)
        CE.note_context_window("w1", {"modelUsage": {"claude-opus-5-5": {"contextWindow": 1000000}}},
                               model_hint="harness:claude/opus")
        self.assertEqual(H.learned_windows(self.root), {"claude/opus": 1000000})


if __name__ == "__main__":
    unittest.main()
