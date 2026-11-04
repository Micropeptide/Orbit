import os, sys, tempfile, textwrap, time, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))
import claude_ctl as C

FAKE = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json, sys, time
    def out(o): sys.stdout.write(json.dumps(o) + "\\n"); sys.stdout.flush()
    for line in sys.stdin:
        ev = json.loads(line); r = ev["request"]; rid = ev["request_id"]; sub = r["subtype"]
        ok = lambda body: out({"type": "control_response", "response": {"subtype": "success", "request_id": rid, "response": body}})
        if sub == "initialize": ok({})
        elif sub == "mcp_status": ok({"mcpServers": [{"name": "a", "status": "connected"}, {"name": "wp", "status": "needs-auth"}]})
        elif sub == "mcp_authenticate":
            ok({"authUrl": "https://example.org/login?server=" + r["serverName"], "callbackExpected": True})
            time.sleep(0.6); ok({})                      # the browser came back: finished
        elif sub == "mcp_oauth_callback_url": ok({"accepted": r["callbackUrl"]})
        else: out({"type": "control_response", "response": {"subtype": "error", "request_id": rid, "error": "unknown " + sub}})
''')


class Ctl(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.exe = os.path.join(self.d, "claude")
        open(self.exe, "w").write(FAKE); os.chmod(self.exe, 0o755)
        self.addCleanup(C.AUTH.clear)

    def test_servers_and_their_status(self):
        r = C.mcp_servers(self.exe, None, self.d, settle=1)
        self.assertEqual([(s["name"], s["status"]) for s in r["servers"]], [("a", "connected"), ("wp", "needs-auth")])

    def test_sign_in_gives_an_address_then_reports_done(self):
        r = C.auth_start(self.exe, None, self.d, "wp")
        self.assertEqual(r["url"], "https://example.org/login?server=wp")
        self.assertEqual(C.auth_state("wp")["state"], "waiting")
        time.sleep(1.2)
        self.assertEqual(C.auth_state("wp")["state"], "done")
        self.assertEqual(C.auth_state("wp")["state"], "none")

    def test_a_pasted_address_is_handed_over_and_errors_are_plain(self):
        self.assertEqual(C.auth_callback(self.exe, None, self.d, "wp", "http://localhost:1/cb?code=x")["accepted"], "http://localhost:1/cb?code=x")
        self.assertIn("unknown", C.auth_clear(self.exe, None, self.d, "wp")["error"])

    def test_a_missing_claude_is_an_error_not_a_crash(self):
        self.assertIn("error", C.mcp_servers("/nonexistent/claude", None, self.d))


if __name__ == "__main__":
    unittest.main()
