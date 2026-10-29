"""The Orbit app's side of account sign-in: PKCE, a one-shot loopback callback, token storage, refresh and sign-out -- against a fake service."""
import base64, hashlib, http.client, json, os, shutil, sys, tempfile, threading, time, unittest, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
import accounts_client as A      # noqa: E402


class FakeService:
    """Just enough of the account service: /token (PKCE), /token/refresh (rotating), DELETE /devices/<id>."""

    def __init__(self):
        self.codes, self.refresh, self.devices, self.log = {}, {}, set(), []
        self.deleted = False
        outer = self
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def _send(self, status, obj):
                b = json.dumps(obj).encode(); self.send_response(status); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
            def _body(self): return json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            def do_POST(self):
                b = self._body(); outer.log.append((self.path, b))
                if self.path == "/token":
                    row = outer.codes.pop(b.get("code"), None)
                    if not row: return self._send(400, {"error": "invalid_grant", "code": "invalid_grant"})
                    ch = base64.urlsafe_b64encode(hashlib.sha256(b.get("code_verifier", "").encode()).digest()).rstrip(b"=").decode()
                    if ch != row["challenge"] or b.get("redirect_uri") != row["redirect_uri"]: return self._send(400, {"error": "invalid_grant", "code": "invalid_grant"})
                    return self._send(200, outer.session("Pat"))
                if self.path == "/token/refresh":
                    dev = outer.refresh.pop(b.get("refresh_token"), None)
                    if not dev: return self._send(401, {"error": "invalid", "code": "invalid_grant"})
                    return self._send(200, outer.session("Pat", dev))
                if self.path == "/proof":
                    if not (self.headers.get("Authorization") or "").startswith("Bearer at_"): return self._send(401, {"error": "no"})
                    return self._send(200, {"token": "proof-for-" + str(b.get("audience"))})
                self._send(404, {})
            def do_GET(self):
                if self.path == "/me/export" and (self.headers.get("Authorization") or "").startswith("Bearer at_"):
                    return self._send(200, {"format": "orbit-account-export/1", "account": {"id": "acc_1", "name": "Pat"}})
                self._send(401, {"error": "no"})
            def do_DELETE(self):
                outer.log.append((self.path, self.headers.get("Authorization")))
                if self.path == "/me":
                    if self._body().get("confirm") != "delete": return self._send(400, {"error": "confirmation_required"})
                    outer.deleted = True; return self._send(200, {"deleted": True})
                dev = self.path.rsplit("/", 1)[-1]
                if dev in outer.devices: outer.devices.discard(dev); return self._send(200, {"ok": True})
                self._send(404, {})
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H); self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def session(self, name, dev=None):
        dev = dev or "dev_" + str(len(self.devices) + 1); self.devices.add(dev)
        rt = "rt_" + os.urandom(6).hex(); self.refresh[rt] = dev
        return {"token_type": "Bearer", "access_token": "at_" + os.urandom(6).hex(), "expires_in": 900, "refresh_token": rt, "device_id": dev, "account": {"id": "acc_1", "name": name, "avatar": None}}

    def issue_code(self, query):
        code = "code" + os.urandom(12).hex()
        self.codes[code] = {"challenge": query["code_challenge"][0], "redirect_uri": query["redirect_uri"][0]}
        return code


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.svc = FakeService(); self.addCleanup(self.svc.srv.shutdown)
        self.t = [1_800_000_000.0]
        self.c = A.AccountClient(self.svc.url, os.path.join(self.tmp, "account.json"), now=lambda: self.t[0])
        self.addCleanup(self.c.cancel)

    def begin(self):
        r = self.c.start("Orbit on a Mac")
        return r, urllib.parse.parse_qs(urllib.parse.urlsplit(r["url"]).query)

    def hit(self, q, code=None, state=None, path="/orbit-callback", host=None):
        port = urllib.parse.urlsplit(q["redirect_uri"][0]).port
        qs = urllib.parse.urlencode({k: v for k, v in (("code", code), ("state", state)) if v})
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", path + "?" + qs, headers={"Host": host} if host else {}); r = c.getresponse(); r.read(); return r.status

    def wait(self, pred, secs=3):
        end = time.time() + secs
        while time.time() < end and not pred(): time.sleep(0.02)
        return pred()


class TestSignIn(Base):
    def test_the_url_carries_the_apps_own_pkce_state_and_a_loopback_redirect(self):
        r, q = self.begin()
        self.assertTrue(r["url"].startswith(self.svc.url + "/signin?"))
        self.assertRegex(q["redirect_uri"][0], r"^http://127\.0\.0\.1:\d+/orbit-callback$")
        self.assertEqual(len(q["code_challenge"][0]), 43); self.assertGreaterEqual(len(q["state"][0]), 8)
        self.assertEqual(q["device_name"][0], "Orbit on a Mac")
        self.assertFalse(self.c.status()["signed_in"]); self.assertTrue(self.c.status()["pending"])

    def test_the_full_flow_ends_signed_in_with_tokens_kept_privately(self):
        r, q = self.begin()
        self.assertEqual(self.hit(q, self.svc.issue_code(q), q["state"][0]), 200)
        self.assertTrue(self.wait(lambda: self.c.status()["signed_in"]))
        s = self.c.status()
        self.assertEqual((s["name"], s["id"], s["pending"]), ("Pat", "acc_1", False))
        self.assertNotIn("token", json.dumps(s).lower().replace("signed_in", ""), "status never carries a token")
        path = os.path.join(self.tmp, "account.json")
        self.assertEqual(os.stat(path).st_mode & 0o077, 0)
        self.assertTrue(self.c.access_token().startswith("at_"))

    def test_a_wrong_state_or_a_stranger_cannot_finish_it(self):
        r, q = self.begin(); code = self.svc.issue_code(q)
        self.assertEqual(self.hit(q, code, "x" * 20), 400)
        self.assertEqual(self.hit(q, None, q["state"][0]), 400)
        self.assertEqual(self.hit(q, code, q["state"][0], path="/elsewhere"), 404)
        self.assertEqual(self.hit(q, code, q["state"][0], host="attacker.example"), 400)
        self.assertFalse(self.c.status()["signed_in"])
        self.assertEqual(self.hit(q, code, q["state"][0]), 200)            # the real callback still works after the failed attempts
        self.assertTrue(self.wait(lambda: self.c.status()["signed_in"]))

    def test_the_listener_is_one_shot(self):
        r, q = self.begin(); self.hit(q, self.svc.issue_code(q), q["state"][0])
        self.wait(lambda: self.c.status()["signed_in"])
        with self.assertRaises(OSError): self.hit(q, "x", q["state"][0])

    def test_a_code_for_another_challenge_is_refused_by_the_service(self):
        r, q = self.begin()
        other = {"code_challenge": ["A" * 43], "redirect_uri": q["redirect_uri"]}
        self.hit(q, self.svc.issue_code(other), q["state"][0])
        self.assertTrue(self.wait(lambda: self.c.status().get("error")))
        self.assertFalse(self.c.status()["signed_in"])

    def get(self, r, query):
        port = urllib.parse.urlsplit(r["url"] and urllib.parse.parse_qs(urllib.parse.urlsplit(r["url"]).query)["redirect_uri"][0]).port
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", "/orbit-callback?" + query); resp = c.getresponse(); return resp.status, resp.read().decode()

    def test_an_error_from_the_service_is_explained_not_a_blank_400_and_the_attempt_stays_open_for_a_second_try(self):
        r, q = self.begin(); st = q["state"][0]
        status, page = self.get(r, "error=consent_required&state=" + st)
        self.assertEqual(status, 200)
        self.assertIn("tick", page); self.assertIn("Back to the sign-in page", page)
        self.assertIn("/signin?", page)                                # the way back is this attempt's own sign-in address
        self.assertIn("agreement", self.c.status()["error"])           # the app's own status says why too
        status, page = self.get(r, "error=who_knows&state=" + st)      # an unknown reason: a fixed sentence, nothing reflected
        self.assertEqual(status, 200); self.assertNotIn("who_knows", page)
        self.assertEqual(self.hit(q, self.svc.issue_code(q), st), 200)  # the listener was still there for the second try
        self.assertTrue(self.wait(lambda: self.c.status()["signed_in"]))

    def test_an_error_with_the_wrong_state_or_a_stray_visit_is_refused_with_a_readable_page(self):
        r, q = self.begin()
        for query in ("error=consent_required&state=not-ours-at-all", "error=consent_required", "", "code=abc&state=not-ours-at-all"):
            status, page = self.get(r, query)
            self.assertEqual(status, 400, query); self.assertIn("not the sign-in Orbit is waiting for", page)
        self.assertEqual(self.c.status()["error"], "", "a stranger cannot put a message into the app")
        self.assertTrue(self.c.status()["pending"])

    def test_cancelling_and_starting_again_replaces_the_old_attempt(self):
        r1, q1 = self.begin(); self.c.cancel(); r2, q2 = self.begin()
        with self.assertRaises(OSError): self.hit(q1, "x", q1["state"][0])          # the old listener is gone
        self.assertEqual(self.hit(q2, self.svc.issue_code(q2), q2["state"][0]), 200)

    def test_an_attempt_that_is_never_finished_expires(self):
        r, q = self.begin(); self.t[0] += A.ATTEMPT_S + 1
        self.assertFalse(self.c.status()["pending"])
        self.assertEqual(self.hit(q, self.svc.issue_code(q), q["state"][0]), 400) if self._listening(q) else None
        self.assertFalse(self.c.status()["signed_in"])

    def _listening(self, q):
        try: self.hit(q, "x", "y"); return True
        except OSError: return False


class TestSession(Base):
    def sign_in(self):
        r, q = self.begin(); self.hit(q, self.svc.issue_code(q), q["state"][0]); self.assertTrue(self.wait(lambda: self.c.status()["signed_in"]))

    def test_the_access_token_is_refreshed_when_it_is_about_to_expire(self):
        self.sign_in(); first = self.c.access_token()
        self.assertEqual(self.c.access_token(), first)
        self.t[0] += 900 - A.REFRESH_MARGIN_S + 5
        second = self.c.access_token(); self.assertNotEqual(second, first)
        self.assertEqual(len([1 for p, _ in self.svc.log if p == "/token/refresh"]), 1)

    def test_a_join_proof_is_asked_for_one_host_and_never_the_access_token(self):
        self.assertIsNone(self.c.join_proof("https://host.example"))                      # signed out: nothing to show
        self.sign_in(); at = self.c.access_token()
        self.assertEqual(self.c.join_proof("https://host.example"), "proof-for-https://host.example")
        self.assertNotEqual(self.c.join_proof("https://host.example"), at)

    def test_it_survives_a_restart_and_uses_the_stored_refresh_token(self):
        self.sign_in()
        c2 = A.AccountClient(self.svc.url, os.path.join(self.tmp, "account.json"), now=lambda: self.t[0]); self.addCleanup(c2.cancel)
        self.assertTrue(c2.status()["signed_in"]); self.assertEqual(c2.status()["name"], "Pat")
        self.assertTrue(c2.access_token().startswith("at_"))

    def test_a_rejected_refresh_signs_out_instead_of_looping(self):
        self.sign_in(); self.svc.refresh.clear(); self.t[0] += 2000
        self.assertIsNone(self.c.access_token())
        self.assertFalse(self.c.status()["signed_in"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "account.json")))

    def test_pressing_sign_in_again_keeps_the_waiting_attempt_so_an_emailed_link_still_lands(self):
        r1, q1 = self.begin()
        r2 = self.c.start("Orbit on a Mac")
        self.assertEqual((r1["url"], r1["port"]), (r2["url"], r2["port"]), "same listener, same address")
        self.hit(q1, self.svc.issue_code(q1), q1["state"][0])          # the first link's callback still arrives
        self.assertTrue(self.wait(lambda: self.c.status()["signed_in"]))
        self.c.sign_out()
        r3, _ = self.begin()                                           # a finished attempt is not reused
        self.assertNotEqual(r3["port"], r1["port"])

    def test_cancel_is_how_to_start_over_and_a_stale_attempt_is_not_reused(self):
        r1, _ = self.begin(); self.c.cancel()
        r2, _ = self.begin(); self.assertNotEqual(r1["port"], r2["port"])
        self.t[0] += A.ATTEMPT_S + 1
        r3 = self.c.start("Orbit on a Mac"); self.assertNotEqual(r2["port"], r3["port"])

    def test_the_service_being_unreachable_keeps_the_session(self):
        self.sign_in(); self.svc.srv.shutdown(); self.svc.srv.server_close(); self.t[0] += 2000
        self.assertIsNone(self.c.access_token())
        self.assertTrue(self.c.status()["signed_in"], "offline is not signed out")

    def test_sign_out_ends_the_device_on_the_service_and_forgets_everything(self):
        self.sign_in(); dev = list(self.svc.devices)[0]
        self.c.sign_out()
        self.assertNotIn(dev, self.svc.devices)
        self.assertFalse(self.c.status()["signed_in"]); self.assertFalse(os.path.exists(os.path.join(self.tmp, "account.json")))
        self.assertIsNone(self.c.access_token())

    def test_sign_out_works_even_when_the_service_cannot_be_reached(self):
        self.sign_in(); self.svc.srv.shutdown(); self.svc.srv.server_close()
        self.c.sign_out(); self.assertFalse(self.c.status()["signed_in"])

    def test_the_account_can_be_exported_and_deleted_from_the_app(self):
        with self.assertRaises(RuntimeError): self.c.export_data()           # signed out: a sentence, not a crash
        with self.assertRaises(RuntimeError): self.c.delete_account()
        self.sign_in()
        self.assertEqual(self.c.export_data()["format"], "orbit-account-export/1")
        self.assertFalse(self.svc.deleted)
        self.c.delete_account()
        self.assertTrue(self.svc.deleted)                                   # the service was told, with the confirmation word
        self.assertFalse(self.c.status()["signed_in"]); self.assertFalse(os.path.exists(os.path.join(self.tmp, "account.json")))

    def test_nothing_is_forgotten_here_when_the_service_cannot_delete_the_account(self):
        self.sign_in(); self.svc.srv.shutdown(); self.svc.srv.server_close()
        with self.assertRaises(RuntimeError) as cm: self.c.delete_account()
        self.assertIn("nothing was deleted", str(cm.exception))
        self.assertTrue(self.c.status()["signed_in"], "a deletion that did not happen must not sign the person out")

    def test_a_damaged_file_means_signed_out(self):
        open(os.path.join(self.tmp, "account.json"), "w").write("{broken")
        c2 = A.AccountClient(self.svc.url, os.path.join(self.tmp, "account.json")); self.addCleanup(c2.cancel)
        self.assertFalse(c2.status()["signed_in"])


class TestSafety(unittest.TestCase):
    def test_only_https_services_or_loopback_are_accepted(self):
        for bad in ("http://evil.example", "ftp://x", "javascript:x", "", "https://"):
            with self.assertRaises(ValueError): A.AccountClient(bad, "/tmp/x.json")
        A.AccountClient("https://orbit.example.test", "/tmp/x.json").cancel(); A.AccountClient("http://127.0.0.1:9", "/tmp/x.json").cancel()


if __name__ == "__main__":
    unittest.main()


class TestRoute(Base):
    """/api/account through the real server module: tokens never come out of it."""

    @classmethod
    def setUpClass(cls):
        import importlib.machinery, importlib.util
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_loader("qqui_acct", importlib.machinery.SourceFileLoader("qqui_acct", os.path.join(root, "bin", "orbit-ui")))
        cls.ui = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.ui)

    def setUp(self):
        super().setUp()
        self.orig, self.orig_open = self.ui.ACCOUNT, self.ui._open_in_chrome
        self.opened = []
        self.ui.ACCOUNT = self.c; self.ui._open_in_chrome = lambda url: (self.opened.append(url), True)[1]
        self.addCleanup(setattr, self.ui, "ACCOUNT", self.orig); self.addCleanup(setattr, self.ui, "_open_in_chrome", self.orig_open)

    def call(self, **d):
        code, body = self.ui._account_route(d); return code, json.loads(body)

    def test_start_opens_the_page_and_sign_in_completes(self):
        code, r = self.call(op="start"); self.assertEqual((code, r["opened"]), (200, True)); self.assertEqual(self.opened, [r["url"]])
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(r["url"]).query)
        self.assertTrue(self.call(op="status")[1]["pending"])
        self.hit(q, self.svc.issue_code(q), q["state"][0])
        self.assertTrue(self.wait(lambda: self.call(op="status")[1]["signed_in"]))
        s = self.call(op="status")[1]
        self.assertEqual(s["name"], "Pat"); self.assertNotIn("at_", json.dumps(s)); self.assertNotIn("rt_", json.dumps(s))
        self.assertFalse(self.call(op="signout")[1]["signed_in"])

    def test_cancel_and_unknown_ops(self):
        self.call(op="start"); self.assertFalse(self.call(op="cancel")[1]["pending"])
        self.assertEqual(self.call(op="nope")[0], 400)

    def test_it_is_an_admin_route(self):
        import re
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "orbit-ui")).read()
        self.assertIn('"/api/account"', re.search(r"ADMIN_PREFIXES = \((.*?)\)\n", src, re.S).group(1))
