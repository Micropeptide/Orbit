"""The shared project inside Orbit: its page and calls are served from Orbit's own address (so they work from the phone too) with the owner's sign-in added by Orbit."""
import http.client, json, os, shutil, sys, tempfile, threading, time, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
import collab_host as CH           # noqa: E402
import collab_policy as P          # noqa: E402


class FakeRemote:
    def bind_addresses(self, mode): return ["127.0.0.1"]
    def reachable_hosts(self, mode, port): return {f"127.0.0.1:{port}"}
    def best_url(self, mode, port): return f"http://127.0.0.1:{port}"


class TestSharedInOrbit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.machinery, importlib.util
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_loader("qqui_shr", importlib.machinery.SourceFileLoader("qqui_shr", os.path.join(root, "bin", "orbit-ui")))
        cls.ui = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.ui)

    def setUp(self):
        ui = self.ui
        self.tmp = os.path.realpath(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.work = os.path.join(self.tmp, "work"); os.makedirs(self.work)
        pol = P.Policy(never=[], home=os.path.join(self.tmp, "home"), sensitive=lambda p: None)
        self.host = CH.Host(self.tmp, remote=FakeRemote(), policy=pol); self.addCleanup(self.host.stop); self.addCleanup(self.host._stop_engine)
        self.host.configure(port=0, enabled=True); self.pid = self.host.create_project("Lab", "Me", self.work)["project"]["id"]
        self.old = (ui.COLLAB_HOST, dict(ui._SHARED_TOK)); ui.COLLAB_HOST = self.host; ui._SHARED_TOK.clear(); self.addCleanup(lambda: (setattr(ui, "COLLAB_HOST", self.old[0]), ui._SHARED_TOK.update(self.old[1])))
        self.srv = ui.Srv(("127.0.0.1", 0), ui.H); self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start(); self.addCleanup(self.srv.shutdown); self.addCleanup(self.srv.server_close)

    def get(self, path, method="GET", body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": f"127.0.0.1:{self.ui.PORT}"}; h.update(headers or {})
        c.request(method, path, body=body, headers=h); r = c.getresponse(); return r.status, r.read(), dict(r.getheaders())

    def test_the_page_comes_from_orbit_with_the_projects_base_path_and_a_strict_policy(self):
        st, data, h = self.get(f"/shared/{self.pid}/"); html = data.decode()
        self.assertEqual(st, 200); self.assertIn(f'<meta name="orbit-base" content="/shared/{self.pid}">', html); self.assertIn(f'src="/shared/{self.pid}/collab.js"', html); self.assertIn("script-src 'self'", h["Content-Security-Policy"])
        self.assertEqual(self.get(f"/shared/{self.pid}/collab.js")[0], 200); self.assertIn("orbit-base", self.get(f"/shared/{self.pid}/collab.js")[1].decode()); self.assertEqual(self.get(f"/shared/{self.pid}/collab.css")[0], 200)
        for p in ("/shared/p_000000000000/", "/shared/not-a-project/", "/shared/", f"/shared/{self.pid}/other"): self.assertEqual(self.get(p)[0], 404, p)

    def test_calls_are_passed_to_the_door_with_the_owners_sign_in_not_the_pages(self):
        st, data, h = self.get(f"/shared/{self.pid}/api/collab/p/{self.pid}", headers={"Authorization": "Bearer orbit-embedded"})
        self.assertEqual(st, 200); self.assertEqual(json.loads(data)["me"], self.host._store().project_view_admin(self.pid)["owner"])         # the owner, whatever the page sent
        self.assertEqual(self.get(f"/shared/{self.pid}/api/collab/proto")[0], 200)
        st, data, _ = self.get(f"/shared/{self.pid}/api/collab/p/{self.pid}/intent", "POST", json.dumps({"id": "i1", "type": "msg", "chat": "main", "payload": {"text": "from inside Orbit"}}), {"Content-Type": "application/json"}); self.assertEqual(st, 200, data)
        ev = self.get(f"/shared/{self.pid}/api/collab/p/{self.pid}/events")[1]; self.assertIn("from inside Orbit", ev.decode())

    def test_a_forgotten_sign_in_is_made_again_once_and_other_paths_are_not_passed_on(self):
        self.get(f"/shared/{self.pid}/api/collab/p/{self.pid}"); self.ui._SHARED_TOK[self.pid] = "stale-token-" + "x" * 30
        self.assertEqual(self.get(f"/shared/{self.pid}/api/collab/p/{self.pid}")[0], 200)
        for p in (f"/shared/{self.pid}/api/other", f"/shared/{self.pid}/api/collab/../x", f"/shared/{self.pid}/me"): self.assertEqual(self.get(p)[0], 404, p)
        self.assertEqual(self.get(f"/shared/{self.pid}/api/collab/proto", "DELETE")[0] in (404, 405, 501), True)

    def test_a_page_that_closes_leaves_no_stream_open_on_the_door(self):
        import socket
        door = self.host.servers[0]
        for i in range(6):                                                           # more reloads than the door allows streams at once
            c = socket.create_connection(("127.0.0.1", self.port), timeout=10)
            c.sendall((f"GET /shared/{self.pid}/api/collab/p/{self.pid}/events?stream=1 HTTP/1.1\r\nHost: 127.0.0.1:{self.ui.PORT}\r\nAccept: text/event-stream\r\n\r\n").encode())
            head = c.recv(4096); self.assertIn(b" 200 ", head.split(b"\r\n")[0], (i, head[:200])); c.close()
            for _ in range(60):                                                      # the proxy notices within a couple of seconds, not at the door's next heartbeat
                if sum(door.streams.values()) == 0: break
                time.sleep(0.1)
            self.assertEqual(sum(door.streams.values()), 0, i)
        for _ in range(60):
            if sum(door.streams.values()) == 0: break
            time.sleep(0.1)
        self.assertEqual(sum(door.streams.values()), 0)

    def _off_machine(self):
        """Pretend the next calls come from paired phones (a forwarded request is not you at the machine): token full-tok is a full device, chat-tok one limited to chats."""
        ui = self.ui
        class FakeDevices:
            def token_device(self, root, tok): return {"full-tok": "d_full", "chat-tok": "d_chat"}.get(tok)
            def touch_device(self, root, did): pass
            def device_scope(self, root, did): return {"d_full": "full", "d_chat": "chat"}.get(did, "full")
            def tunnel_config(self): return {}
        old = (ui.REMOTE, ui.remote_mode); ui.REMOTE = FakeDevices(); ui.remote_mode = lambda: "tailscale"
        self.addCleanup(lambda: (setattr(ui, "REMOTE", old[0]), setattr(ui, "remote_mode", old[1])))

    def test_a_paired_phone_reaches_the_shared_page_with_its_token_as_a_header_or_the_cookie_the_app_sets(self):
        self._off_machine(); fwd = {"X-Forwarded-For": "100.64.0.9"}
        self.assertEqual(self.get(f"/shared/{self.pid}/", headers=fwd)[0], 401)                                  # no token: refused
        self.assertEqual(self.get(f"/shared/{self.pid}/", headers=dict(fwd, Authorization="Bearer wrong"))[0], 401)
        self.assertEqual(self.get(f"/shared/{self.pid}/", headers=dict(fwd, Authorization="Bearer full-tok"))[0], 200)
        # a web view cannot add a header to the page's own requests, so the app plants the cookie and every request after carries it
        self.assertEqual(self.get(f"/shared/{self.pid}/collab.js", headers=dict(fwd, Cookie="orbit_token=full-tok"))[0], 200)
        st, data, _ = self.get(f"/shared/{self.pid}/api/collab/p/{self.pid}", headers=dict(fwd, Cookie="orbit_token=full-tok"))
        self.assertEqual(st, 200); self.assertEqual(json.loads(data)["me"], self.host._store().project_view_admin(self.pid)["owner"])
        st, _, _ = self.get(f"/shared/{self.pid}/api/collab/p/{self.pid}/intent", "POST", json.dumps({"id": "i9", "type": "msg", "chat": "main", "payload": {"text": "from the phone"}}), dict(fwd, Cookie="orbit_token=full-tok", **{"Content-Type": "application/json"}))
        self.assertEqual(st, 200)

    def test_a_phone_that_may_only_use_chats_cannot_open_a_shared_project_as_its_owner(self):
        self._off_machine(); fwd = {"X-Forwarded-For": "100.64.0.9", "Authorization": "Bearer chat-tok"}
        for path in (f"/shared/{self.pid}/", f"/shared/{self.pid}/api/collab/p/{self.pid}", f"/shared/{self.pid}/api/collab/proto"):
            self.assertEqual(self.get(path, headers=fwd)[0], 403, path)
        st, _, _ = self.get(f"/shared/{self.pid}/api/collab/p/{self.pid}/intent", "POST", json.dumps({"id": "i8", "type": "msg", "chat": "main", "payload": {"text": "x"}}), dict(fwd, **{"Content-Type": "application/json"}))
        self.assertEqual(st, 403)
        self.assertEqual(self.get(f"/shared/{self.pid}/", headers=dict(fwd, Authorization="Bearer full-tok"))[0], 200)       # a full device still can
        ev = self.get(f"/shared/{self.pid}/api/collab/p/{self.pid}/events", headers={"X-Forwarded-For": "100.64.0.9", "Authorization": "Bearer full-tok"})[1]
        self.assertNotIn("x", [e.get("payload", {}).get("text") for e in json.loads(ev)["events"]])                          # the refused post never reached the project

    def test_files_stream_through_and_a_door_that_is_off_is_a_503(self):
        open(os.path.join(self.work, "a.txt"), "w").write("file text")
        st, data, h = self.get(f"/shared/{self.pid}/api/collab/p/{self.pid}/file?path=a.txt"); self.assertEqual((st, data), (200, b"file text")); self.assertTrue(h["Content-Disposition"].startswith("attachment"))
        self.host.stop(); self.assertEqual(self.get(f"/shared/{self.pid}/api/collab/proto")[0], 503)


if __name__ == "__main__":
    unittest.main()
