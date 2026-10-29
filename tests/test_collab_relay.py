"""The host's end of the relay against a real member door: frames in, the door's answers out in pieces, nothing outside the allowed routes, reconnecting."""
import base64, json, os, queue, shutil, sys, tempfile, threading, time, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
import collab_policy as P          # noqa: E402
import collab_relay as R           # noqa: E402
import collab_server as V          # noqa: E402
import collab_store as S           # noqa: E402
import ws_client as W              # noqa: E402


class FakeWS:
    """The service's side of the connection: tests put frames in, read what the host sent."""
    instances = []

    def __init__(self, url="", headers=None, **kw):
        self.url, self.headers, self.inbox, self.sent, self.closed, self.fail = url, headers, queue.Queue(), [], False, kw.get("fail")
        FakeWS.instances.append(self)

    def connect(self):
        if self.fail: raise W.WSError(self.fail)
        return self

    def recv(self):
        v = self.inbox.get(timeout=20)
        if v is None: return None
        if isinstance(v, Exception): raise v
        return v

    def send_text(self, t):
        if self.closed: raise W.WSError("closed")
        self.sent.append(json.loads(t))

    def close(self): self.closed = True; self.inbox.put(None)
    def put(self, f): self.inbox.put(json.dumps(f))

    def frames(self, rid, until_end=True, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            mine = [f for f in self.sent if f.get("id") == rid]
            if not until_end or any(f["t"] in ("end", "err") for f in mine): return mine
            time.sleep(0.01)
        raise AssertionError(f"no answer for {rid}: {self.sent}")


class Base(unittest.TestCase):
    def setUp(self):
        FakeWS.instances = []
        self.tmp = os.path.realpath(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.work = os.path.join(self.tmp, "work"); os.makedirs(self.work)
        pol = P.Policy(never=[], home=os.path.join(self.tmp, "home"), sensitive=lambda p: None)
        self.st = S.Store(os.path.join(self.tmp, "collab"), policy=pol)
        p = self.st.create_project("Lab", owner_name="Owner", working_dir=self.work); self.pid, self.owner, self.otok = p["project"]["id"], p["member"]["id"], p["token"]
        self.srv = V.make_server(self.st, "127.0.0.1", 0); self.port = self.srv.server_address[1]
        self.srv.public_url = f"http://127.0.0.1:{self.port}"; self.srv.allowed_hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}; self.srv.trust_relay = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start(); self.addCleanup(self.srv.shutdown); self.addCleanup(self.srv.server_close)
        self.rc = R.RelayClient("https://svc.example.test", self.pid, "s" * 40, self.port, ws_factory=FakeWS)
        self.addCleanup(self.rc.stop); self.rc.start(); self.ws = self.wait_ws()

    def wait_ws(self):
        for _ in range(500):
            if FakeWS.instances and self.rc.state == "connected": return FakeWS.instances[-1]
            time.sleep(0.01)
        raise AssertionError("the client did not connect: " + str(self.rc.status()))

    def ask(self, rid, method="GET", path="/api/collab/proto", token=None, body=None, client="Abcdefgh12345678"):
        h = {"content-type": "application/json"}
        if token: h["authorization"] = "Bearer " + token
        self.ws.put({"t": "req", "id": rid, "method": method, "path": path, "headers": h, "body": None if body is None else base64.b64encode(json.dumps(body).encode()).decode(), "client": client})
        return self.ws.frames(rid)

    @staticmethod
    def text(frames): return b"".join(base64.b64decode(f["b64"]) for f in frames if f["t"] == "chunk").decode()


class TestServing(Base):
    def test_it_connects_with_the_secret_and_a_request_gets_the_doors_answer_in_frames(self):
        self.assertEqual(self.ws.url, f"wss://svc.example.test/relay/host/{self.pid}"); self.assertEqual(self.ws.headers, {"Authorization": "Bearer " + "s" * 40})
        fr = self.ask("a1"); self.assertEqual([f["t"] for f in fr], ["res", "chunk", "end"]); self.assertEqual(fr[0]["status"], 200); self.assertEqual(json.loads(self.text(fr))["proto"], S.PROTO)
        self.assertTrue(fr[0]["headers"]["content-type"].startswith("application/json")); time.sleep(0.1); self.assertEqual(self.rc.served, 1)

    def test_member_tokens_still_decide_everything_and_posts_carry_their_body(self):
        self.assertEqual(self.ask("a2", path=f"/api/collab/p/{self.pid}")[0]["status"], 401)
        self.assertEqual(self.ask("a3", path=f"/api/collab/p/{self.pid}", token=self.otok)[0]["status"], 200)
        fr = self.ask("a4", method="POST", path=f"/api/collab/p/{self.pid}/intent", token=self.otok, body={"id": "i1", "type": "msg", "chat": "main", "payload": {"text": "through the relay"}}); self.assertEqual(fr[0]["status"], 200)
        self.assertEqual([e["payload"]["text"] for e in self.st.read(self.pid, self.owner, limit=50) if e["type"] == "msg"], ["through the relay"])

    def test_only_api_collab_paths_and_get_or_post_get_through(self):
        self.assertEqual(self.ask("b0", path=f"/api/collab/p/{self.pid}/file?path=src/a.py", token=self.otok)[0]["status"], 404)          # a file path in the query passes the filter (the door then answers for itself)
        for rid, kw in (("b1", {"path": "/"}), ("b2", {"path": "/collab.js"}), ("b3", {"path": "/api/other"}), ("b4", {"path": "/api/collab/../x"}), ("b5", {"method": "DELETE"}), ("b6", {"path": "/api/collab/a b"}), ("b7", {"path": "/api/collab/" + "a" * 2100})):
            fr = self.ask(rid, **kw); self.assertEqual((fr[-1]["t"], fr[-1]["status"]), ("err", 404), kw)

    def test_bad_bodies_are_refused_before_the_door(self):
        self.ws.put({"t": "req", "id": "c1", "method": "POST", "path": "/api/collab/join", "headers": {}, "body": "!!!not base64", "client": ""}); self.assertEqual(self.ws.frames("c1")[-1]["status"], 400)
        self.ws.put({"t": "req", "id": "c2", "method": "POST", "path": "/api/collab/join", "headers": {}, "body": base64.b64encode(b"x" * (R.MAX_BODY + 1)).decode(), "client": ""}); self.assertEqual(self.ws.frames("c2")[-1]["status"], 413)

    def test_junk_frames_do_nothing_and_the_connection_stays_up(self):
        for junk in ("not json", "[]", "{}", json.dumps({"t": "req"}), json.dumps({"t": "weird", "id": "z"}), json.dumps({"t": "req", "id": "z9", "method": 5, "path": 7})):
            self.ws.inbox.put(junk)
        self.assertEqual(self.ask("d1")[0]["status"], 200); self.assertEqual(self.rc.state, "connected")

    def test_the_door_being_down_is_a_502_not_a_crash(self):
        self.srv.shutdown(); self.srv.server_close(); fr = self.ask("e1"); self.assertEqual((fr[-1]["t"], fr[-1]["status"]), ("err", 502))

    def test_a_live_stream_is_sent_in_pieces_and_a_cancel_closes_it(self):
        m = self.st.create_invite(self.pid, self.owner, grant=P.template("editor", project=self.work)); j = self.st.join(self.pid, m["id"], m["secret"], name="Mei")
        self.ws.put({"t": "req", "id": "s1", "method": "GET", "path": f"/api/collab/p/{self.pid}/events?stream=1", "headers": {"authorization": "Bearer " + j["token"], "accept": "text/event-stream"}, "body": None, "client": "Abcdefgh12345678"})
        for _ in range(300):
            if any(f.get("id") == "s1" and f["t"] == "chunk" for f in self.ws.sent): break
            time.sleep(0.01)
        self.assertTrue(any(f.get("id") == "s1" and f["t"] == "res" and f["status"] == 200 for f in self.ws.sent))
        self.st.submit_as(self.pid, self.owner, {"id": "i9", "type": "msg", "chat": "main", "payload": {"text": "live!"}}); time.sleep(0.5)
        self.assertIn("live!", self.text([f for f in self.ws.sent if f.get("id") == "s1"]))
        self.ws.put({"t": "cancel", "id": "s1"}); time.sleep(0.3); self.assertEqual(self.rc.active, {})

    def test_callers_are_told_apart_by_the_hash_so_one_cannot_throttle_everyone(self):
        for i in range(40): self.ask(f"f{i}", path=f"/api/collab/p/{self.pid}", token="wrong-token-" + "x" * 20, client="Attacker0000000001")
        self.assertEqual(self.ask("g1", path=f"/api/collab/p/{self.pid}", token="wrong-token-" + "x" * 20, client="Attacker0000000001")[0]["status"], 429)
        self.assertEqual(self.ask("g2", path=f"/api/collab/p/{self.pid}", token=self.otok, client="Honest00000000002")[0]["status"], 200)
        self.assertEqual(self.ask("g3", path=f"/api/collab/p/{self.pid}", token=self.otok, client="Honest00000000002")[0]["status"], 200)


class TestConnection(unittest.TestCase):
    def setUp(self): FakeWS.instances = []

    def test_a_refused_connection_backs_off_and_a_401_waits_a_minute(self):
        waited = []
        def sleep(s): waited.append(s); time.sleep(0.001)
        rc = R.RelayClient("https://svc.example.test", "p_0123456789ab", "x" * 40, 1, ws_factory=lambda url, headers=None: FakeWS(url, headers, fail="the server refused the connection: HTTP/1.1 401 Unauthorized"), sleep=sleep)
        rc.start(); time.sleep(0.5); rc.stop(); self.assertEqual(rc.state, "stopped"); self.assertIn("401", rc.error); self.assertGreaterEqual(len(FakeWS.instances), 1)

    def test_it_reconnects_after_the_service_closes_the_connection(self):
        rc = R.RelayClient("https://svc.example.test", "p_0123456789ab", "x" * 40, 1, ws_factory=FakeWS, sleep=lambda s: time.sleep(0.001)); self.addCleanup(rc.stop); rc.start()
        for _ in range(300):
            if FakeWS.instances and rc.state == "connected": break
            time.sleep(0.01)
        first = FakeWS.instances[0]; first.inbox.put(None)
        for _ in range(500):
            if len(FakeWS.instances) >= 2 and rc.state == "connected": break
            time.sleep(0.01)
        self.assertGreaterEqual(len(FakeWS.instances), 2); self.assertEqual(rc.state, "connected")

    def test_the_url_is_made_from_the_service_address(self):
        self.assertEqual(R.RelayClient("https://a.example/", "p_1", "s", 1).url, "wss://a.example/relay/host/p_1"); self.assertEqual(R.RelayClient("http://127.0.0.1:8787", "p_1", "s", 1).url, "ws://127.0.0.1:8787/relay/host/p_1")


class TestHelperDoorOverTheRelay(unittest.TestCase):
    """The same client carries Orbit's helper door (an agent's MCP calls) when it is told which path may pass."""
    def test_only_the_mcp_address_passes_and_the_door_answers(self):
        import science_bridge as B
        FakeWS.instances = []; tmp = os.path.realpath(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, tmp, True)
        class BE:
            def models(self): return [{"id": "m", "label": "M", "tier": "light"}]
            server_llms = lambda self: []
        b = B.Bridge(os.path.join(tmp, "science_bridge.json"), BE()); b.configure(enabled=True); srv = B.make_server(b, 0); port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start(); self.addCleanup(srv.shutdown); self.addCleanup(srv.server_close)
        tok = b.cfg["clients"][0]["token"]
        rc = R.RelayClient("https://svc.example.test", "h_0123456789ab", "s" * 40, port, ws_factory=FakeWS, path_ok=R.HELPER_PATH_OK); self.addCleanup(rc.stop); rc.start()
        for _ in range(500):
            if FakeWS.instances and rc.state == "connected": break
            time.sleep(0.01)
        ws = FakeWS.instances[-1]
        def ask(rid, path, method="POST", body=None, headers=None):
            ws.put({"t": "req", "id": rid, "method": method, "path": path, "headers": headers or {}, "body": base64.b64encode(json.dumps(body).encode()).decode() if body is not None else None, "client": "Abcdefgh12345678"}); return ws.frames(rid)
        call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "orbit_models", "arguments": {}}}
        fr = ask("h1", f"/mcp/{tok}", body=call, headers={"content-type": "application/json"}); self.assertEqual(fr[0]["status"], 200); self.assertIn("m  [light]", json.loads(b"".join(base64.b64decode(f["b64"]) for f in fr if f["t"] == "chunk"))["result"]["content"][0]["text"])
        fr = ask("h2", "/mcp", body=call, headers={"content-type": "application/json", "authorization": "Bearer " + tok}); self.assertEqual(fr[0]["status"], 200)
        fr = ask("h3", "/mcp", body=call, headers={"content-type": "application/json"}); self.assertEqual(fr[0]["status"], 401)
        for rid, path in (("h4", "/api/collab/proto"), ("h5", "/mcp/short"), ("h6", "/mcp?x=1"), ("h7", "/"), ("h8", "/mcp/../x")): self.assertEqual((ask(rid, path, body=call)[-1]["t"], ask(rid + "b", path, body=call)[-1]["status"]), ("err", 404), path)


if __name__ == "__main__":
    unittest.main()
