"""Cheaper hours (bin/offpeak.py): windows in the provider's timezone, across
midnight, on some days only, what is paid then, and which models they cover."""
import datetime as dt, json, os, shutil, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin"))
import offpeak as O        # noqa: E402

UTC = dt.timezone.utc
POL = {"provider": "testprov", "applies_to": "api", "models": ["deepseek-v4*"], "exclude": ["deepseek-v4-special"],
       "windows": [{"start": "16:30", "end": "00:30", "tz": "UTC", "days": "daily"}],
       "discount": {"input_cache_miss": 0.5, "input_cache_hit": 0.5, "output": 0.25}, "sources": ["https://example.org"]}


class TestOffPeak(unittest.TestCase):
    def test_a_window_across_midnight(self):
        s = O.status(POL, dt.datetime(2026, 9, 17, 23, 0, tzinfo=UTC))
        self.assertTrue(s["active"])
        self.assertEqual(s["fraction"], 0.25)
        self.assertEqual(s["what"], "75% off")
        self.assertEqual(dt.datetime.fromtimestamp(s["ends_at"], UTC), dt.datetime(2026, 9, 18, 0, 30, tzinfo=UTC))
        s = O.status(POL, dt.datetime(2026, 9, 18, 0, 10, tzinfo=UTC))          # after midnight, still inside
        self.assertTrue(s["active"])
        s = O.status(POL, dt.datetime(2026, 9, 18, 9, 0, tzinfo=UTC))
        self.assertFalse(s["active"])
        self.assertEqual(dt.datetime.fromtimestamp(s["starts_at"], UTC), dt.datetime(2026, 9, 18, 16, 30, tzinfo=UTC))

    def test_timezones_days_and_dates(self):
        cn = {**POL, "windows": [{"start": "00:00", "end": "08:00", "tz": "Beijing", "days": "weekdays"}]}
        # 2026-09-17 17:00 UTC = 2026-09-18 01:00 Beijing, a Friday
        self.assertTrue(O.status(cn, dt.datetime(2026, 9, 17, 17, 0, tzinfo=UTC))["active"])
        # 2026-09-19 17:00 UTC = Sunday 01:00 Beijing: not a weekday
        self.assertFalse(O.status(cn, dt.datetime(2026, 9, 19, 17, 0, tzinfo=UTC))["active"])
        self.assertFalse(O.status({**POL, "ends": "2026-01-01"}, dt.datetime(2026, 9, 17, 23, 0, tzinfo=UTC))["active"])
        q = {**POL, "discount": {"quota_multiplier": 0.5}}
        self.assertEqual(O.status(q, dt.datetime(2026, 9, 17, 23, 0, tzinfo=UTC))["what"], "half usage")

    def test_which_models_and_overrides(self):
        tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, tmp, True)
        os.makedirs(os.path.join(tmp, "config"))
        json.dump({"policies": [POL]}, open(os.path.join(tmp, "config", "offpeak.json"), "w"))
        O._CACHE["key"] = None
        now = dt.datetime(2026, 9, 17, 23, 0, tzinfo=UTC)
        self.assertTrue(O.for_model("testprov", "deepseek-v4-flash", tmp, now)["active"])
        self.assertIsNone(O.for_model("testprov", "deepseek-v4-special", tmp, now))
        self.assertIsNone(O.for_model("testprov", "other-model", tmp, now))
        self.assertIsNone(O.for_model("otherprov", "deepseek-v4-flash", tmp, now))    # another provider: not this one's discount
        O._CACHE["key"] = None

    def test_the_researched_deepseek_policy(self):
        O._CACHE["key"] = None
        # Wednesday 2026-09-16, 10:00 Beijing = 02:00 UTC: peak
        st = O.for_model("deepseek", "deepseek-v4.1-flash", None, dt.datetime(2026, 9, 16, 2, 0, tzinfo=UTC))
        self.assertFalse(st["active"])
        self.assertEqual(dt.datetime.fromtimestamp(st["starts_at"], UTC), dt.datetime(2026, 9, 16, 4, 0, tzinfo=UTC))
        # Friday 2026-09-18 19:00 Beijing = 11:00 UTC: off-peak, and it lasts through the weekend to Monday 09:00 Beijing
        st = O.for_model("deepseek", "deepseek-v4-pro", None, dt.datetime(2026, 9, 18, 11, 0, tzinfo=UTC))
        self.assertTrue(st["active"])
        self.assertEqual(dt.datetime.fromtimestamp(st["ends_at"], UTC), dt.datetime(2026, 9, 21, 1, 0, tzinfo=UTC))
        self.assertEqual(st["what"], "50% off")
        # OpenCode Go's DeepSeek models: the same hours, counted against the plan
        st = O.for_model("opencode-go", "deepseek-v4-flash", None, dt.datetime(2026, 9, 16, 2, 0, tzinfo=UTC))
        self.assertFalse(st["active"]); self.assertTrue(st["quota"])
        self.assertIsNone(O.for_model("opencode-go", "kimi-k2.6", None))
        self.assertIsNone(O.for_model("glm", "glm-5.3", None))            # the pay-as-you-go API: no time pricing


if __name__ == "__main__":
    unittest.main()
