"""What is left of a shared model: the statement people see, and that the host controls whether they see it."""
import os, sys, tempfile, shutil, unittest, datetime
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
import collab_usage as U       # noqa: E402
import collab_host as CH       # noqa: E402
import collab_policy as P      # noqa: E402

NOW = 1_800_000_000.0
def iso(secs): return datetime.datetime.fromtimestamp(NOW + secs, datetime.timezone.utc).isoformat()


class TestStatement(unittest.TestCase):
    def test_the_tightest_window_decides_and_says_when_it_resets(self):
        r = U.from_windows({"rolling": {"status": "ok", "percent": 40, "resetsAt": iso(3600)}, "weekly": {"status": "ok", "percent": 90, "resetsAt": iso(3 * 86400)}}, NOW)
        self.assertEqual((r["left_pct"], r["window"], r["state"]), (10, "weekly", "low")); self.assertIn("10% left in the week", r["label"]); self.assertIn("in 3 days", r["label"])
        self.assertEqual(U.from_windows({"rolling": {"status": "ok", "percent": 40, "resetsAt": iso(1800)}}, NOW)["label"], "60% left in the 5-hour window, resets in 30 min")

    def test_used_up_and_rate_limited_say_so(self):
        r = U.from_windows({"rolling": {"status": "rate-limited", "percent": 20, "resetsAt": iso(7200)}}, NOW); self.assertEqual((r["left_pct"], r["state"]), (0, "out")); self.assertTrue(r["label"].startswith("used up"))
        self.assertEqual(U.from_windows({"weekly": {"status": "ok", "percent": 130}}, NOW)["left_pct"], 0)

    def test_nothing_known_is_none_and_odd_figures_do_not_crash(self):
        for bad in (None, {}, {"rolling": "x"}, {"rolling": {"percent": "lots"}}, {"rolling": {"percent": None}}): self.assertIsNone(U.from_windows(bad, NOW), bad)
        self.assertEqual(U.from_windows({"rolling": {"percent": 5, "resetsAt": "not a date"}}, NOW)["label"], "95% left in the 5-hour window")

    def test_a_local_model_has_no_limit(self): self.assertTrue(U.unlimited()["unlimited"])

    def test_spend_only_providers(self):
        self.assertIsNone(U.from_spend(None)); self.assertIsNone(U.from_spend({"requests": 0}))
        self.assertEqual(U.from_spend({"requests": 3, "windows": {"day": {"tokens": 1200}}})["label"], "1,200 tokens used lately")
        self.assertEqual(U.from_spend({"requests": 3, "windows": {"day": {"left_pct": 7}}})["state"], "low")


class FakeRemote:
    def bind_addresses(self, mode): return ["127.0.0.1"]
    def reachable_hosts(self, mode, port): return {f"127.0.0.1:{port}"}
    def best_url(self, mode, port): return f"http://127.0.0.1:{port}"


class TestHostDecides(unittest.TestCase):
    def test_usage_is_shown_only_for_models_the_host_switched_on(self):
        tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, tmp, True)
        h = CH.Host(tmp, remote=FakeRemote(), policy=P.Policy(never=[], home=tmp, sensitive=lambda p: None), usage=lambda mid: {"label": "60% left", "left_pct": 60, "state": "ok", "for": mid})
        h.configure(models=[{"handle": "a", "id": "m1", "share_usage": True}, {"handle": "b", "id": "m2"}])
        got = {m["handle"]: m for m in h._models_public()}
        self.assertEqual(got["a"]["usage"]["for"], "m1"); self.assertNotIn("usage", got["b"])
        h.usage = lambda mid: 1 / 0; self.assertIsNone({m["handle"]: m for m in h._models_public()}["a"]["usage"])      # a failing lookup never breaks the project page
        self.assertTrue(h.cfg["models"][0]["share_usage"]); self.assertFalse(h.cfg["models"][1]["share_usage"])


if __name__ == "__main__":
    unittest.main()
