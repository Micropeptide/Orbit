"""The update check: version order, choosing a release from the feed, what a copy is told, and that it only ever reads."""
import json, os, sys, tempfile, shutil, threading, time, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
import updatecheck as U        # noqa: E402

BASE = U.DOWNLOAD_BASE


def rel(version, pre=False, draft=False, prefix=U.TAG_PREFIX, body="Notes.", dmg=True, url=None):
    assets = [{"name": f"Orbit-{version}-arm64.dmg", "browser_download_url": f"{BASE}{prefix}{version}/Orbit-{version}-arm64.dmg", "size": 123},
              {"name": "SHA256SUMS.txt", "browser_download_url": f"{BASE}{prefix}{version}/SHA256SUMS.txt", "size": 9}] if dmg else []
    return {"tag_name": f"{prefix}{version}", "name": f"Orbit {version}", "draft": draft, "prerelease": pre, "body": body,
            "published_at": "2026-10-01T00:00:00Z", "html_url": url or f"https://github.com/{U.REPO}/releases/tag/{prefix}{version}",
            "assets": assets}


class Clock:
    def __init__(self, t=1_000_000.0): self.t = t
    def __call__(self): return self.t


class TestVersions(unittest.TestCase):
    def test_order(self):
        order = ["0.2.2-beta.1", "0.2.2-beta.2", "0.2.2", "0.2.10", "0.10.0", "1.0.0"]
        for a, b in zip(order, order[1:]):
            self.assertEqual(U.compare(a, b), -1, (a, b))
            self.assertEqual(U.compare(b, a), 1)
        self.assertEqual(U.compare("v1.2.3", "1.2.3"), 0)
        self.assertEqual(U.compare("1.2.3+build5", "1.2.3"), 0)

    def test_numbers_compare_as_numbers_not_text(self):
        self.assertTrue(U.is_newer("0.2.10", "0.2.9"))
        self.assertTrue(U.is_newer("0.10.0", "0.9.9"))

    def test_not_a_version(self):
        for bad in ("", None, "latest", "1.2", "1.2.3.4", "01.2.3", "1.2.x", "<script>"):
            self.assertIsNone(U.parse_version(bad), bad)
            self.assertIsNone(U.compare(bad, "1.0.0"))
            self.assertFalse(U.is_newer(bad, "1.0.0"))


class TestPick(unittest.TestCase):
    def test_newest_stable(self):
        got = U.pick([rel("0.2.1"), rel("0.2.3"), rel("0.2.2")])
        self.assertEqual(got["version"], "0.2.3")
        self.assertEqual(got["dmg"]["name"], "Orbit-0.2.3-arm64.dmg")
        self.assertTrue(got["sums"].endswith("SHA256SUMS.txt"))

    def test_drafts_prereleases_and_other_products_are_passed_over(self):
        feed = [rel("0.3.0", draft=True), rel("0.2.9", pre=True), rel("0.2.8-beta.1"), rel("9.9.9", prefix="ios-v"), rel("0.2.2")]
        self.assertEqual(U.pick(feed)["version"], "0.2.2")

    def test_beta_channel_sees_prereleases(self):
        feed = [rel("0.2.2"), rel("0.3.0-beta.1", pre=True)]
        self.assertEqual(U.pick(feed, "beta")["version"], "0.3.0-beta.1")
        self.assertEqual(U.pick(feed, "stable")["version"], "0.2.2")

    def test_nothing_usable(self):
        for feed in ([], None, {}, "x", [None, 3, {}], [rel("0.1.0", draft=True)]):
            self.assertIsNone(U.pick(feed))

    def test_links_that_leave_the_project_are_not_kept(self):
        r = rel("0.2.5", url="https://evil.example/orbit")
        r["assets"][0]["browser_download_url"] = "https://evil.example/Orbit.dmg"
        got = U.pick([r])
        self.assertEqual(got["page"], U.PAGE)
        self.assertIsNone(got["dmg"])

    def test_notes_are_cut(self):
        self.assertEqual(len(U.pick([rel("0.2.5", body="x" * 10_000)])["notes"]), U.NOTES_MAX)

    def test_a_release_with_no_dmg_still_counts(self):
        got = U.pick([rel("0.2.5", dmg=False)])
        self.assertEqual(got["version"], "0.2.5")
        self.assertIsNone(got["dmg"])


class TestCurrentVersion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_env_wins_then_the_desktop_package_then_a_version_file(self):
        self.assertIsNone(U.current_version(self.tmp, {}))
        open(os.path.join(self.tmp, "VERSION"), "w").write("0.1.5\n")
        self.assertEqual(U.current_version(self.tmp, {}), "0.1.5")
        os.makedirs(os.path.join(self.tmp, "desktop"))
        json.dump({"version": "0.2.2"}, open(os.path.join(self.tmp, "desktop", "package.json"), "w"))
        self.assertEqual(U.current_version(self.tmp, {}), "0.2.2")
        self.assertEqual(U.current_version(self.tmp, {"ORBIT_VERSION": "v0.3.0"}), "0.3.0")
        self.assertEqual(U.current_version(self.tmp, {"ORBIT_VERSION": "junk"}), "0.2.2")

    def test_install_kind(self):
        self.assertEqual(U.install_kind("/Users/x/Orbit", {}), "source")
        self.assertEqual(U.install_kind("/Applications/Orbit.app/Contents/Resources/orbit", {}), "app")
        self.assertEqual(U.install_kind("/anywhere", {"ORBIT_PACKAGED": "1"}), "app")


class TestUpdates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = os.path.join(self.tmp, "config", "update-check.json")
        self.clock, self.calls, self.feed = Clock(), [], [rel("0.2.5")]
        self.env = {"ORBIT_VERSION": "0.2.2"}

    def make(self, fetch=None):
        def default():
            self.calls.append(1)
            if isinstance(self.feed, Exception): raise self.feed
            return self.feed
        return U.Updates(self.path, self.tmp, fetch=fetch or default, now=self.clock, env=self.env)

    def test_a_newer_release_is_reported(self):
        s = self.make().check()
        self.assertTrue(s["newer"]); self.assertEqual(s["latest"]["version"], "0.2.5"); self.assertEqual(s["current"], "0.2.2")
        self.assertEqual(s["error"], ""); self.assertTrue(s["checked"])

    def test_the_same_or_an_older_release_is_not_news(self):
        for v in ("0.2.2", "0.2.1"):
            self.feed = [rel(v)]; self.clock.t += 100
            self.assertFalse(self.make().check()["newer"], v)

    def test_unknown_current_version_never_claims_news(self):
        self.env = {}
        self.assertFalse(self.make().check()["newer"])

    def test_an_error_keeps_the_last_good_answer(self):
        u = self.make(); u.check()
        self.feed = OSError("offline"); self.clock.t += 100
        s = u.check()
        self.assertTrue(s["newer"]); self.assertIn("Could not reach", s["error"])
        self.feed = [rel("0.2.6")]; self.clock.t += 100
        s = u.check()
        self.assertEqual(s["latest"]["version"], "0.2.6"); self.assertEqual(s["error"], "")

    def test_rate_limit_and_garbage_are_told_plainly(self):
        self.feed = Exception("HTTP Error 403: rate limit exceeded")
        self.assertIn("limiting", self.make().check()["error"])
        self.feed = ValueError("bad json"); self.clock.t += 100
        self.assertIn("not understood", self.make().check()["error"])

    def test_a_check_right_after_another_does_not_ask_again(self):
        u = self.make(); u.check(); u.check(); u.check()
        self.assertEqual(len(self.calls), 1)
        self.clock.t += U.MIN_GAP_S + 1; u.check()
        self.assertEqual(len(self.calls), 2)

    def test_off_means_no_automatic_check_but_a_manual_one_works(self):
        u = self.make(); u.configure(mode="off")
        self.assertFalse(u.due()); self.assertIsNone(u.status()["next_check"])
        u.status(kick=True); time.sleep(0.05)
        self.assertEqual(self.calls, [])
        u.check(force=False); self.assertEqual(self.calls, [])
        u.check(force=True); self.assertEqual(len(self.calls), 1)

    def test_due_after_the_interval(self):
        u = self.make(); u.check()
        self.assertFalse(u.due())
        self.clock.t += 24 * 3600 - 1; self.assertFalse(u.due())
        self.clock.t += 2; self.assertTrue(u.due())
        u.configure(every_h=1); self.clock.t += 0; self.assertTrue(u.due())

    def test_kick_checks_in_the_background_and_does_not_wait(self):
        gate, started = threading.Event(), threading.Event()
        def slow():
            started.set(); gate.wait(5); return [rel("0.2.5")]
        u = self.make(fetch=slow)
        t0 = time.time(); s = u.status(kick=True)
        self.assertLess(time.time() - t0, 1.0)
        self.assertTrue(started.wait(2)); self.assertTrue(u.status()["checking"]); self.assertFalse(s["newer"])
        gate.set()
        for _ in range(100):
            if not u.status()["checking"]: break
            time.sleep(0.02)
        self.assertTrue(u.status()["newer"])

    def test_only_one_check_runs_at_a_time(self):
        gate, n = threading.Event(), []
        def slow():
            n.append(1); gate.wait(5); return [rel("0.2.5")]
        u = self.make(fetch=slow)
        t = threading.Thread(target=u.check); t.start()
        while not n: time.sleep(0.01)
        u.check(); gate.set(); t.join(5)
        self.assertEqual(len(n), 1)

    def test_skipping_a_version_quietens_it_until_a_newer_one(self):
        u = self.make(); u.check()
        s = u.skip()
        self.assertTrue(s["newer"]); self.assertTrue(s["skipped"])
        self.feed = [rel("0.2.6")]; self.clock.t += 100
        s = u.check()
        self.assertTrue(s["newer"]); self.assertFalse(s["skipped"])

    def test_settings_are_checked_and_kept_across_restarts(self):
        u = self.make()
        u.configure(mode="nonsense", every_h=5, channel="weird", skipped="not-a-version")
        p = u.status()["prefs"]
        self.assertEqual((p["mode"], p["every_h"], p["channel"], p["skipped"]), ("notify", 24, "stable", ""))
        u.configure(mode="off", every_h=168, channel="beta"); u.check()
        again = self.make().status()
        self.assertEqual((again["prefs"]["mode"], again["prefs"]["every_h"], again["prefs"]["channel"]), ("off", 168, "beta"))
        self.assertEqual(again["latest"]["version"], "0.2.5")

    def test_a_damaged_file_does_not_break_it(self):
        os.makedirs(os.path.dirname(self.path)); open(self.path, "w").write("{not json")
        self.assertEqual(self.make().status()["prefs"], U.DEFAULTS)
        json.dump({"prefs": "x", "latest": "y", "tried": "z", "checked": [1], "error": None}, open(self.path, "w"))
        s = self.make().status()
        self.assertEqual(s["prefs"], U.DEFAULTS); self.assertIsNone(s["latest"]); self.assertEqual(s["error"], "")
        json.dump([1, 2], open(self.path, "w"))
        self.assertEqual(self.make().status()["prefs"], U.DEFAULTS)

    def test_the_request_carries_nothing_about_the_person(self):
        seen = {}
        class R:
            def read(self, n): return b"[]"
            def __enter__(self): return self
            def __exit__(self, *a): pass
        orig = U.urllib.request.urlopen
        U.urllib.request.urlopen = lambda req, timeout=0: (seen.update(url=req.full_url, headers=dict(req.header_items()), data=req.data), R())[1]
        self.addCleanup(setattr, U.urllib.request, "urlopen", orig)
        U.fetch_feed()
        self.assertEqual(seen["url"], U.FEED); self.assertIsNone(seen["data"])
        self.assertEqual(set(k.lower() for k in seen["headers"]), {"user-agent", "accept"})
        self.assertEqual(seen["headers"]["User-agent"], "Orbit-update-check")


if __name__ == "__main__":
    unittest.main()


class TestRoute(unittest.TestCase):
    """The /api/update route: what the page and the phone are told, through the real server module."""

    @classmethod
    def setUpClass(cls):
        import importlib.machinery, importlib.util
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_loader("qqui_upd", importlib.machinery.SourceFileLoader("qqui_upd", os.path.join(root, "bin", "orbit-ui")))
        cls.ui = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.ui)

    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.upd = U.Updates(os.path.join(self.tmp, "u.json"), self.tmp, fetch=lambda: [rel("0.2.9")], now=Clock(), env={"ORBIT_VERSION": "0.2.2"})
        self.orig = self.ui.UPDATES
        self.ui.UPDATES = self.upd
        self.addCleanup(setattr, self.ui, "UPDATES", self.orig)

    def call(self, **d):
        code, body = self.ui._update_route(d)
        return code, json.loads(body)

    def test_status_check_config_skip(self):
        self.upd.configure(mode="off")                  # a status call starts a check by itself when one is due; not wanted here
        code, s = self.call(op="status"); self.assertEqual(code, 200); self.assertFalse(s["newer"])
        code, s = self.call(op="check"); self.assertTrue(s["newer"]); self.assertEqual(s["latest"]["version"], "0.2.9")
        code, s = self.call(op="config", mode="off", every_h=168); self.assertEqual((s["prefs"]["mode"], s["prefs"]["every_h"]), ("off", 168))
        code, s = self.call(op="skip", version="0.2.9"); self.assertTrue(s["skipped"])

    def test_unknown_op_and_junk_are_refused_or_ignored(self):
        self.assertEqual(self.call(op="install")[0], 400)
        code, s = self.call(op="config", mode="rm -rf", every_h="soon", channel=None)
        self.assertEqual(code, 200); self.assertEqual(s["prefs"]["mode"], "notify")

    def test_it_is_an_admin_route_so_a_chat_only_phone_cannot_change_it(self):
        import re
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "orbit-ui")).read()
        self.assertIn('"/api/update"', re.search(r"ADMIN_PREFIXES = \((.*?)\)\n", src, re.S).group(1))
