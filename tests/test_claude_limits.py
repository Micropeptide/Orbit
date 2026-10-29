"""The plan usage Claude Code reports for each account: kept from every answer, shown in words,
and in the shape Orbit already uses for other providers' allowances."""
import os, shutil, sys, tempfile, time, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin"))

import claude_limits as CL                 # noqa: E402

NOW = 1_800_000_000.0
EVENT = {"status": "allowed_warning", "resetsAt": NOW + 3 * 86400, "rateLimitType": "seven_day", "utilization": 0.79,
         "overageStatus": "rejected", "isUsingOverage": False,
         "unifiedWindows": {"five_hour": {"utilization": 0.4, "resetsAt": NOW + 4 * 3600},
                            "seven_day": {"utilization": 0.79, "resetsAt": NOW + 3 * 86400}}}
OVERAGE = {"status": "allowed", "resetsAt": NOW + 5 * 86400, "rateLimitType": "overage", "overageStatus": "allowed",
           "isUsingOverage": False, "overageInUse": True}


class TestPlanUsage(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="orbit-limits-")
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_the_figures_in_a_report_are_kept_as_percent_used(self):
        CL.note(self.root, "main", EVENT, now=NOW)
        v = CL.view(self.root, "main", now=NOW + 60)
        self.assertEqual({w["key"]: w["used"] for w in v["windows"]}, {"five_hour": 40.0, "seven_day": 79.0})
        self.assertFalse(v["usage_based"])

    def test_they_read_in_words(self):
        CL.note(self.root, "main", EVENT, now=NOW)
        line = CL.summary(CL.view(self.root, "main", now=NOW))
        self.assertIn("5 hours: 40% used", line); self.assertIn("week: 79% used", line); self.assertIn("resets", line)

    def test_an_account_billed_by_use_says_it_has_no_window(self):
        CL.note(self.root, "hhmi", OVERAGE, now=NOW)
        v = CL.view(self.root, "hhmi", now=NOW)
        self.assertTrue(v["usage_based"]); self.assertEqual(v["windows"], [])
        self.assertIn("usage-based", CL.summary(v))
        self.assertIsNone(CL.live(self.root, "hhmi"))

    def test_a_window_that_has_since_reset_is_not_shown_as_still_full(self):
        CL.note(self.root, "main", EVENT, now=NOW)
        v = CL.view(self.root, "main", now=NOW + 5 * 3600)          # the 5-hour window reset an hour ago
        five = next(w for w in v["windows"] if w["key"] == "five_hour")
        self.assertEqual((five["used"], five["stale"]), (0.0, True))
        self.assertEqual(next(w for w in v["windows"] if w["key"] == "seven_day")["used"], 79.0)

    def test_a_later_report_with_one_window_keeps_the_other(self):
        CL.note(self.root, "main", EVENT, now=NOW)
        CL.note(self.root, "main", {"status": "allowed", "rateLimitType": "five_hour", "utilization": 0.5,
                                    "resetsAt": NOW + 3600}, now=NOW + 10)
        v = CL.view(self.root, "main", now=NOW + 20)
        self.assertEqual({w["key"]: w["used"] for w in v["windows"]}, {"five_hour": 50.0, "seven_day": 79.0})

    def test_the_shape_orbit_already_shows_for_other_allowances(self):
        CL.note(self.root, "main", EVENT, now=time.time())
        live = CL.live(self.root, "main")
        self.assertEqual((live["rolling"]["percent"], live["weekly"]["percent"]), (40.0, 79.0))
        self.assertTrue(live["rolling"]["resetsAt"].endswith("Z"))
        self.assertEqual(live["rolling"]["status"], "ok")

    def test_the_months_spend_counts_each_run_once(self):
        CL.note(self.root, "hhmi", OVERAGE, now=NOW)
        CL.add_cost(self.root, "hhmi", "s1", 0.40, now=NOW)            # a session that began here
        CL.add_cost(self.root, "hhmi", "s1", 0.55, now=NOW + 60)       # its running total grew by 0.15
        CL.add_cost(self.root, "hhmi", "s2", 3.00, resumed=True, now=NOW + 90)   # old session: only counted from now
        CL.add_cost(self.root, "hhmi", "s2", 3.25, resumed=True, now=NOW + 120)
        v = CL.view(self.root, "hhmi", now=NOW + 200)
        self.assertAlmostEqual(v["spend"]["usd"], 0.40 + 0.15 + 0.25, places=4)
        self.assertIn("this month through Orbit", CL.summary(v))
        self.assertIn("usage-based", CL.summary(v))

    def test_a_new_month_starts_the_count_again(self):
        CL.add_cost(self.root, "hhmi", "s1", 1.0, now=NOW)
        later = NOW + 40 * 86400
        CL.note(self.root, "hhmi", OVERAGE, now=later)
        self.assertEqual(CL.view(self.root, "hhmi", now=later)["spend"]["usd"], 0.0)

    def test_a_usage_based_plans_monthly_credits_from_a_full_login(self):
        # exactly what `get_usage` answers for a usage-based enterprise login
        CL.note_usage(self.root, "hhmi", {"five_hour": None, "seven_day": None, "extra_usage": {
            "is_enabled": True, "monthly_limit": 2500, "used_credits": 501, "utilization": 20.04, "currency": "USD",
            "decimal_places": 2, "spend_limit_reached": False}}, now=NOW)
        v = CL.view(self.root, "hhmi", now=NOW)
        self.assertEqual((v["credits"]["used"], v["credits"]["limit"], v["credits"]["pct"]), (5.01, 25.0, 20.04))
        self.assertTrue(v["usage_based"])
        line = CL.summary(v)
        self.assertIn("$5.01 of $25.00 used", line); self.assertIn("20.04%", line)
        live = CL.live(self.root, "hhmi")                      # and in the shape the provider line reads
        self.assertEqual(live["monthly"]["percent"], 20.04)

    def test_a_plan_with_windows_from_a_full_login(self):
        import datetime
        iso = lambda t: datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        CL.note_usage(self.root, "main", {"five_hour": {"utilization": 41, "resets_at": iso(NOW + 4 * 3600)},
                                          "seven_day": {"utilization": 79, "resets_at": iso(NOW + 3 * 86400)},
                                          "extra_usage": {"is_enabled": False}}, now=NOW)
        v = CL.view(self.root, "main", now=NOW)
        self.assertEqual({w["key"]: w["used"] for w in v["windows"]}, {"five_hour": 41.0, "seven_day": 79.0})
        self.assertIsNone(v["credits"])

    def test_an_account_nothing_is_known_about(self):
        self.assertIsNone(CL.view(self.root, "nobody"))
        self.assertEqual(CL.summary(None), "no figures yet")


if __name__ == "__main__":
    unittest.main()
