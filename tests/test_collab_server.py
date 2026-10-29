"""Shared projects over HTTP: the only door members have, and what that door refuses."""
import http.client, json, os, shutil, socket, sys, tempfile, threading, time, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
import collab_policy as P      # noqa: E402
import collab_store as S       # noqa: E402
import collab_server as V      # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.work = os.path.join(self.tmp, "work"); os.makedirs(self.work)
        pol = P.Policy(never=[], home=os.path.join(self.tmp, "home"), sensitive=lambda p: None)
        self.st = S.Store(os.path.join(self.tmp, "collab"), policy=pol)
        p = self.st.create_project("Lab", owner_name="Owner", working_dir=self.work)
        self.pid, self.owner, self.otok = p["project"]["id"], p["member"]["id"], p["token"]
        self.srv = V.make_server(self.st, "127.0.0.1", 0)
        self.port = self.srv.server_address[1]
        self.srv.public_url = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown); self.addCleanup(self.srv.server_close)

    def call(self, method, path, body=None, token=None, headers=None, raw=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Content-Type": "application/json"} if body is not None or raw is not None else {}
        if token: h["Authorization"] = "Bearer " + token
        h.update(headers or {})
        c.request(method, path, body=raw if raw is not None else (json.dumps(body) if body is not None else None), headers=h)
        r = c.getresponse(); data = r.read()
        try: j = json.loads(data)
        except ValueError: j = data
        return r.status, j, dict(r.getheaders())

    def join(self, name="Guest", role="editor"):
        st, inv, _ = self.call("POST", f"/api/collab/p/{self.pid}/invite", {"role": role, "uses": 1}, token=self.otok)
        self.assertEqual(st, 200, inv)
        st, j, _ = self.call("POST", "/api/collab/join", {"p": self.pid, "i": inv["id"], "s": inv["secret"], "name": name})
        self.assertEqual(st, 200, j)
        return j["member"]["id"], j["token"]


class TestBasics(Base):
    def test_proto_is_open_and_says_the_version(self):
        st, j, h = self.call("GET", "/api/collab/proto")
        self.assertEqual((st, j["proto"]), (200, S.PROTO))
        self.assertEqual(h["Cache-Control"], "no-store"); self.assertEqual(h["X-Content-Type-Options"], "nosniff")
        self.assertNotIn("Access-Control-Allow-Origin", h)

    def test_everything_else_needs_a_member_token(self):
        for path in ("/api/collab/projects", f"/api/collab/p/{self.pid}", f"/api/collab/p/{self.pid}/events"):
            self.assertEqual(self.call("GET", path)[0], 401, path)
            self.assertEqual(self.call("GET", path, token="wrong")[0], 401, path)
        self.assertEqual(self.call("POST", f"/api/collab/p/{self.pid}/intent", {"id": "a"})[0], 401)

    def test_only_collab_routes_exist_and_only_get_and_post(self):
        for path in ("/api/chat", "/api/settings", "/api/secrets", "/api/cluster", "/api/collab", "/api/collab/", "/../etc/passwd", "/api/collab/p/../../x"):
            self.assertIn(self.call("GET", path, token=self.otok)[0], (404, 400), path)
        for m in ("PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"):
            self.assertEqual(self.call(m, "/api/collab/proto")[0], 405, m)

    def test_errors_are_json_without_internals(self):
        st, j, _ = self.call("GET", f"/api/collab/p/p_{'0' * 12}", token=self.otok)
        self.assertEqual(st, 401); self.assertEqual(set(j), {"error", "code"}); self.assertNotIn("Traceback", json.dumps(j))

    def test_listing_projects_by_token(self):
        st, j, _ = self.call("GET", "/api/collab/projects", token=self.otok)
        self.assertEqual([p["id"] for p in j["projects"]], [self.pid])


class TestFlow(Base):
    def test_invite_join_chat_and_read(self):
        m, tok = self.join("Ed")
        st, j, _ = self.call("POST", f"/api/collab/p/{self.pid}/intent", {"id": "m1", "type": "msg", "chat": "main", "payload": {"text": "hello"}}, token=tok)
        self.assertEqual(st, 200); self.assertEqual(j["id"], "m1")
        st, j, _ = self.call("GET", f"/api/collab/p/{self.pid}/events?after=0", token=self.otok)
        msgs = [e for e in j["events"] if e["type"] == "msg"]
        self.assertEqual(msgs[0]["author"], m); self.assertEqual(msgs[0]["payload"]["text"], "hello")
        st, j, _ = self.call("GET", f"/api/collab/p/{self.pid}", token=tok)
        self.assertEqual(j["my_grant"]["role"], "editor"); self.assertEqual({x["name"] for x in j["members"]}, {"Owner", "Ed"})

    def test_a_join_link_is_returned_with_the_host_address(self):
        st, inv, _ = self.call("POST", f"/api/collab/p/{self.pid}/invite", {"role": "viewer"}, token=self.otok)
        self.assertIn(self.srv.public_url, inv["link"]); self.assertIn(inv["secret"], inv["link"]); self.assertTrue(inv["app_link"].startswith("orbit://join"))

    def test_editors_cannot_invite_or_change_grants_or_freeze_or_verify(self):
        m, tok = self.join("Ed")
        for method, path, body in (("POST", f"/api/collab/p/{self.pid}/invite", {"role": "viewer"}),
                                   ("POST", f"/api/collab/p/{self.pid}/grants", {"member": self.owner, "grant": {}}),
                                   ("POST", f"/api/collab/p/{self.pid}/members/{self.owner}", {"action": "remove"}),
                                   ("POST", f"/api/collab/p/{self.pid}/panic", {}), ("GET", f"/api/collab/p/{self.pid}/verify", None)):
            self.assertEqual(self.call(method, path, body, token=tok)[0], 403, path)

    def test_nobody_can_invite_above_themselves_over_http(self):
        m, tok = self.join("Admin", role="admin")
        self.assertEqual(self.call("POST", f"/api/collab/p/{self.pid}/invite", {"role": "owner"}, token=tok)[0], 403)
        self.assertEqual(self.call("POST", f"/api/collab/p/{self.pid}/invite", {"role": "editor"}, token=tok)[0], 200)

    def test_grants_and_moderation_over_http(self):
        m, tok = self.join("Ed")
        st, j, _ = self.call("POST", f"/api/collab/p/{self.pid}/grants", {"member": m, "role": "viewer"}, token=self.otok)
        self.assertEqual(st, 200)
        st, j, _ = self.call("POST", f"/api/collab/p/{self.pid}/intent", {"id": "x", "type": "msg", "chat": "main", "payload": {"text": "hi"}}, token=tok)
        self.assertEqual(st, 403)
        self.assertEqual(self.call("POST", f"/api/collab/p/{self.pid}/members/{m}", {"action": "remove"}, token=self.otok)[0], 200)
        self.assertEqual(self.call("GET", f"/api/collab/p/{self.pid}", token=tok)[0], 401)

    def test_verify_and_export(self):
        self.call("POST", f"/api/collab/p/{self.pid}/intent", {"id": "m1", "type": "msg", "chat": "main", "payload": {"text": "# title\nbody"}}, token=self.otok)
        st, j, _ = self.call("GET", f"/api/collab/p/{self.pid}/verify", token=self.otok)
        self.assertTrue(j["ok"])
        st, j, _ = self.call("GET", f"/api/collab/p/{self.pid}/export?format=json", token=self.otok); self.assertTrue(j["events"])
        st, raw, h = self.call("GET", f"/api/collab/p/{self.pid}/export?format=md", token=self.otok)
        self.assertEqual(st, 200); self.assertIn(b"Owner", raw); self.assertIn("text/markdown", h["Content-Type"])

    def test_panic_over_http(self):
        m, tok = self.join("Ed")
        self.assertEqual(self.call("POST", f"/api/collab/p/{self.pid}/panic", {}, token=self.otok)[0], 200)
        st, j, _ = self.call("POST", f"/api/collab/p/{self.pid}/intent", {"id": "x", "type": "msg", "chat": "main", "payload": {"text": "hi"}}, token=tok)
        self.assertEqual(st, 403)


class TestRefusals(Base):
    def test_bodies_must_be_json_and_small(self):
        self.assertEqual(self.call("POST", f"/api/collab/p/{self.pid}/intent", raw="not json", token=self.otok)[0], 400)
        self.assertEqual(self.call("POST", f"/api/collab/p/{self.pid}/intent", raw="[1,2]", token=self.otok)[0], 400)
        self.assertEqual(self.call("POST", f"/api/collab/p/{self.pid}/intent", raw="x" * (V.MAX_BODY + 10), token=self.otok)[0], 413)
        self.assertEqual(self.call("POST", f"/api/collab/p/{self.pid}/intent", raw="{}", token=self.otok, headers={"Content-Type": "text/plain"})[0], 415)
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)                       # a body length that lies
        c.request("POST", f"/api/collab/p/{self.pid}/intent", body=b"{}", headers={"Authorization": "Bearer " + self.otok, "Content-Type": "application/json", "Content-Length": "-5"})
        self.assertEqual(c.getresponse().status, 400)

    def test_chunked_and_doubled_lengths_are_refused_so_nothing_can_be_smuggled(self):
        for extra in ("Transfer-Encoding: chunked\r\n\r\n5\r\nhello\r\n0\r\n\r\n", "Content-Length: 2\r\nContent-Length: 40\r\n\r\n{}"):
            s = socket.create_connection(("127.0.0.1", self.port), timeout=5)
            s.sendall((f"POST /api/collab/p/{self.pid}/intent HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {self.otok}\r\nContent-Type: application/json\r\n{extra}").encode())
            buf = s.recv(4096); s.close()
            self.assertIn(b" 400 ", buf.split(b"\r\n")[0] + b" ", extra[:30])

    def test_a_page_from_another_site_is_refused(self):
        h = {"Origin": "https://evil.example"}
        self.assertEqual(self.call("POST", f"/api/collab/p/{self.pid}/intent", {"id": "m", "type": "msg", "chat": "main", "payload": {"text": "x"}}, token=self.otok, headers=h)[0], 403)
        self.assertEqual(self.call("GET", f"/api/collab/p/{self.pid}", token=self.otok, headers=h)[0], 403)
        same = {"Origin": f"http://127.0.0.1:{self.port}"}
        self.assertEqual(self.call("GET", f"/api/collab/p/{self.pid}", token=self.otok, headers=same)[0], 200)
        self.assertEqual(self.call("GET", f"/api/collab/p/{self.pid}", token=self.otok)[0], 200)          # a native app sends no Origin

    def test_guessing_tokens_gets_you_blocked(self):
        for i in range(V.AUTH_FAILS_PER_MIN):
            self.assertEqual(self.call("GET", f"/api/collab/p/{self.pid}", token="guess%d" % i)[0], 401)
        self.assertEqual(self.call("GET", f"/api/collab/p/{self.pid}", token="guess-more")[0], 429)
        self.assertEqual(self.call("GET", f"/api/collab/p/{self.pid}", token=self.otok)[0], 429)          # even the right one, for a while, from that address

    def test_join_with_a_bad_secret_is_the_same_answer_every_time(self):
        st, inv, _ = self.call("POST", f"/api/collab/p/{self.pid}/invite", {"role": "viewer"}, token=self.otok)
        a = self.call("POST", "/api/collab/join", {"p": self.pid, "i": inv["id"], "s": "wrong", "name": "x"})
        b = self.call("POST", "/api/collab/join", {"p": self.pid, "i": "i_nope", "s": "wrong", "name": "x"})
        c = self.call("POST", "/api/collab/join", {"p": "p_nope", "i": "x", "s": "y", "name": "x"})
        self.assertEqual({a[0], b[0], c[0]}, {401}); self.assertEqual(a[1], b[1]); self.assertEqual(b[1], c[1])

    def test_path_tricks(self):
        for path in (f"/api/collab/p/{self.pid}/../..", f"/api/collab/p/{self.pid}%2f..%2f..", f"/api/collab/p/{self.pid}/events/../../x", "/api/collab/p/%00",
                     f"/api/collab/p/{self.pid}//intent", "/api/collab/p/" + "a" * 5000):
            self.assertIn(self.call("GET", path, token=self.otok)[0], (400, 404), path)


class TestPage(Base):
    def test_the_member_page_and_its_two_files_are_served_with_a_strict_policy(self):
        for path, kind in (("/", "text/html"), ("/join", "text/html"), ("/collab.js", "text/javascript"), ("/collab.css", "text/css")):
            st, body, h = self.call("GET", path)
            self.assertEqual(st, 200, path); self.assertIn(kind, h["Content-Type"])
            csp = h["Content-Security-Policy"]
            self.assertIn("default-src 'none'", csp); self.assertIn("script-src 'self'", csp); self.assertNotIn("unsafe-inline", csp); self.assertNotIn("unsafe-eval", csp)
            self.assertEqual(h["X-Frame-Options"], "DENY")

    def test_only_those_files_exist(self):
        for path in ("/collab.html", "/app.js", "/index.html", "/collab.js/..", "/collab.json", "/web/collab.js", "/../web/collab.js", "/collab.js%2f"):
            self.assertIn(self.call("GET", path)[0], (400, 404), path)

    def test_the_page_never_builds_html_from_text(self):
        # a message from anyone is put on the page as text; these calls would turn it into markup, so they must not appear
        js = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "collab.js")).read()
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "setAttribute('style'", "javascript:"):
            self.assertNotIn(bad, js, bad)
        html = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "collab.html")).read()
        self.assertNotIn("<script>", html); self.assertNotIn(" on", html.replace("one", "").replace("on ", ""))   # no inline script or handlers

    def test_project_view_carries_who_i_am_and_what_everyone_can_do(self):
        m, tok = self.join("Ed", role="commenter")
        st, j, _ = self.call("GET", f"/api/collab/p/{self.pid}", token=tok)
        self.assertEqual(j["me"], m); self.assertTrue(j["my_summary"])
        by = {x["name"]: x for x in j["members"]}
        self.assertTrue(any("run any command" in s for s in by["Owner"]["summary"])); self.assertTrue(any("cannot edit files" in s for s in by["Ed"]["summary"]))


class TestStream(Base):
    def open_stream(self, token, path=None, headers=None):
        s = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        extra = "".join(f"{k}: {v}\r\n" for k, v in (headers or {}).items())
        s.sendall((f"GET {path or f'/api/collab/p/{self.pid}/events?stream=1'} HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer {token}\r\nAccept: text/event-stream\r\n{extra}\r\n").encode())
        self.addCleanup(s.close)
        return s

    def read_until(self, s, needle, secs=5):
        buf, end = b"", time.time() + secs
        while time.time() < end and needle not in buf:
            try: buf += s.recv(4096)
            except socket.timeout: pass
        return buf

    def test_events_stream_and_resume_by_id(self):
        s = self.open_stream(self.otok)
        buf = self.read_until(s, b"event: msg" if False else b"id: 1")
        self.assertIn(b"text/event-stream", buf); self.assertIn(b"id: 1", buf)
        self.call("POST", f"/api/collab/p/{self.pid}/intent", {"id": "m1", "type": "msg", "chat": "main", "payload": {"text": "live one"}}, token=self.otok)
        self.assertIn(b"live one", self.read_until(s, b"live one"))
        s2 = self.open_stream(self.otok, headers={"Last-Event-ID": "2"})
        got = self.read_until(s2, b"data:", 3)
        self.assertNotIn(b"\"type\":\"project\"", got)

    def test_a_removed_member_loses_the_stream(self):
        m, tok = self.join("Ed")
        s = self.open_stream(tok); self.read_until(s, b"id: 1")
        self.call("POST", f"/api/collab/p/{self.pid}/members/{m}", {"action": "remove"}, token=self.otok)
        end, closed = time.time() + 8, False
        while time.time() < end:
            try:
                if s.recv(4096) == b"": closed = True; break
            except socket.timeout: pass
            except OSError: closed = True; break
        self.assertTrue(closed)

    def test_private_chat_text_never_reaches_the_stream_of_others(self):
        m, tok = self.join("Ed"); n, ntok = self.join("Nosy")
        self.st.create_chat(self.pid, m, "secret", visibility={"mode": "members", "members": [m]})
        s = self.open_stream(ntok); self.read_until(s, b"id: 1")
        self.call("POST", f"/api/collab/p/{self.pid}/intent", {"id": "p1", "type": "msg", "chat": "secret", "payload": {"text": "top secret words"}}, token=tok)
        self.call("POST", f"/api/collab/p/{self.pid}/intent", {"id": "p2", "type": "msg", "chat": "main", "payload": {"text": "public words"}}, token=tok)
        buf = self.read_until(s, b"public words")
        self.assertIn(b"public words", buf); self.assertNotIn(b"top secret", buf)

    def test_a_member_cannot_hold_many_streams_and_the_newest_page_wins(self):
        socks = [self.open_stream(self.otok) for _ in range(V.STREAMS_PER_MEMBER)]
        for s in socks: self.assertIn(b"200", self.read_until(s, b"200"))
        extra = self.open_stream(self.otok)
        self.assertIn(b"200", self.read_until(extra, b"200"))                         # the newcomer is let in ...
        socks[0].settimeout(3); closed = False; end = time.time() + 5
        while time.time() < end:                                                       # ... and the oldest stream is the one that ends
            try:
                if socks[0].recv(4096) == b"": closed = True; break
            except socket.timeout: pass
            except OSError: closed = True; break
        self.assertTrue(closed)


class TestFiles(Base):
    def base(self, tok): return f"/api/collab/p/{self.pid}"

    def setUp(self):
        super().setUp()
        for rel, t in (("README.md", "hello"), ("src/a.py", "print(1)\n")):
            os.makedirs(os.path.dirname(os.path.join(self.work, rel)), exist_ok=True); open(os.path.join(self.work, rel), "w").write(t)

    def test_list_download_and_the_headers_that_keep_a_download_a_download(self):
        m, tok = self.join("Mei"); st, j, _ = self.call("GET", self.base(tok) + "/files", token=tok); self.assertEqual((st, sorted(e["name"] for e in j["entries"])), (200, ["README.md", "src"]))
        st, data, h = self.call("GET", self.base(tok) + "/file?path=src/a.py", token=tok); self.assertEqual((st, data), (200, b"print(1)\n"))
        self.assertTrue(h["Content-Disposition"].startswith("attachment;")); self.assertEqual(h["X-Content-Type-Options"], "nosniff"); self.assertIn("sandbox", h["Content-Security-Policy"]); self.assertEqual(h["Content-Type"], "application/octet-stream")
        for path in ("../x", "src/../../x", ".git/config", "nope.txt", ""): self.assertIn(self.call("GET", self.base(tok) + "/file?path=" + path, token=tok)[0], (400, 403, 404), path)
        self.assertEqual(self.call("GET", self.base(tok) + "/file?path=README.md")[0], 401)

    def test_a_member_without_the_switch_is_refused_and_a_viewer_can_still_get_generated_files(self):
        v, vtok = self.join("Vee", role="viewer"); self.assertEqual(self.call("GET", self.base(vtok) + "/files", token=vtok)[0], 403); self.assertEqual(self.call("GET", self.base(vtok) + "/file?path=README.md", token=vtok)[0], 403)
        self.st.append_system(self.pid, "turn_changes", {"turn": "t", "model": "qwen", "asked_by": self.owner, "asked_by_name": "Owner", "created": ["README.md"], "modified": [], "deleted": [], "more": 0, "truncated": False, "undoable": 0}, chat="main")
        st, j, _ = self.call("GET", self.base(vtok) + "/generated", token=vtok); self.assertEqual([f["path"] for f in j["files"]], ["README.md"])
        self.assertEqual(self.call("GET", self.base(vtok) + "/file?path=README.md", token=vtok)[:2], (200, b"hello")); self.assertEqual(self.call("GET", self.base(vtok) + "/file?path=src/a.py", token=vtok)[0], 403)

    def piece(self, tok, uid, n, data, ctype="application/octet-stream"):
        return self.call("POST", self.base(tok) + f"/upload/{uid}/chunk?n={n}", raw=data, token=tok, headers={"Content-Type": ctype})

    def test_an_upload_in_pieces_to_the_project_folder_and_to_the_chat(self):
        m, tok = self.join("Mei"); data = os.urandom(450_000)
        st, u, _ = self.call("POST", self.base(tok) + "/upload", {"name": "data.bin", "size": len(data), "target": "dir", "dir": "src"}, token=tok); self.assertEqual(st, 200); uid = u["id"]
        self.assertEqual(self.piece(tok, uid, 0, data[:400_000])[0], 200); self.assertEqual(self.piece(tok, uid, 1, data[400_000:])[0], 200)
        st, r, _ = self.call("POST", self.base(tok) + f"/upload/{uid}/finish", {}, token=tok); self.assertEqual((st, r["path"]), (200, "src/data.bin")); self.assertEqual(open(os.path.join(self.work, "src", "data.bin"), "rb").read(), data)
        st, u, _ = self.call("POST", self.base(tok) + "/upload", {"name": "fig.png", "size": 5, "target": "chat", "chat": "main", "text": "look"}, token=tok); self.piece(tok, u["id"], 0, b"abcde")
        st, r, _ = self.call("POST", self.base(tok) + f"/upload/{u['id']}/finish", {}, token=tok); self.assertEqual(st, 200)
        k, ktok = self.join("Kai", role="viewer"); st, got, h = self.call("GET", self.base(ktok) + f"/attachment/{r['attachment']}", token=ktok); self.assertEqual((st, got), (200, b"abcde"))
        msgs = [e for e in self.call("GET", self.base(ktok) + "/events", token=ktok)[1]["events"] if e["type"] == "msg"]; self.assertEqual(msgs[-1]["payload"]["attachments"][0]["name"], "fig.png")

    def test_pieces_must_be_octet_streams_of_the_right_size_and_order(self):
        m, tok = self.join("Mei"); uid = self.call("POST", self.base(tok) + "/upload", {"name": "x.bin", "size": 10, "target": "dir"}, token=tok)[1]["id"]
        self.assertEqual(self.piece(tok, uid, 0, b"abc", "application/json")[0], 415); self.assertEqual(self.piece(tok, uid, 0, b"x" * 500_000)[0], 413); self.assertEqual(self.piece(tok, uid, 1, b"abc")[0], 409)
        self.assertEqual(self.call("POST", self.base(tok) + f"/upload/{uid}/chunk?n=0", raw=b"", token=tok, headers={"Content-Type": "application/octet-stream"})[0], 400)
        self.assertEqual(self.piece(tok, uid, "x", b"abc")[0], 409); self.assertEqual(self.piece(tok, "u_000000000000", 0, b"abc")[0], 404)
        self.assertEqual(self.call("POST", self.base(tok) + f"/upload/{uid}/abort", {}, token=tok)[0], 200); self.assertEqual(self.piece(tok, uid, 0, b"abc")[0], 404)

    def test_editing_text_over_the_door(self):
        m, tok = self.join("Mei"); st, t, _ = self.call("GET", self.base(tok) + "/filetext?path=README.md", token=tok); self.assertEqual((st, t["content"]), (200, "hello"))
        self.assertEqual(self.call("POST", self.base(tok) + "/filetext", {"path": "README.md", "content": "hello world", "sha": t["sha"]}, token=tok)[0], 200); self.assertEqual(open(os.path.join(self.work, "README.md")).read(), "hello world")
        self.assertEqual(self.call("POST", self.base(tok) + "/filetext", {"path": "README.md", "content": "again", "sha": t["sha"]}, token=tok)[0], 409)
        c, ctok = self.join("Cee", role="commenter"); self.assertEqual(self.call("GET", self.base(ctok) + "/filetext?path=README.md", token=ctok)[0], 403)

    def test_everything_is_on_the_record_with_a_name(self):
        m, tok = self.join("Mei"); uid = self.call("POST", self.base(tok) + "/upload", {"name": "n.txt", "size": 2, "target": "dir"}, token=tok)[1]["id"]; self.piece(tok, uid, 0, b"hi"); self.call("POST", self.base(tok) + f"/upload/{uid}/finish", {}, token=tok)
        types = [e["type"] for e in self.st.read(self.pid, self.owner, limit=100)]; self.assertIn("file_upload", types); self.assertTrue(self.st.verify(self.pid)["ok"])
        for t in ("file_upload", "file_edit"):
            self.assertEqual(self.call("POST", self.base(tok) + "/intent", {"id": "z" + t, "type": t, "chat": "main", "payload": {}}, token=tok)[0], 403)


class TestNewChats(Base):
    def new(self, tok, **body): return self.call("POST", f"/api/collab/p/{self.pid}/chats", body, token=tok)

    def test_a_member_starts_a_shared_chat_everyone_can_see(self):
        m, tok = self.join("Mei"); k, ktok = self.join("Kai"); st, j, _ = self.new(tok, name="Figures"); self.assertEqual(st, 200)
        for t in (tok, ktok, self.otok): self.assertIn(j["chat"], [c["id"] for c in self.call("GET", f"/api/collab/p/{self.pid}", token=t)[1]["chats"]])

    def test_a_private_chat_is_seen_only_by_the_people_chosen(self):
        m, tok = self.join("Mei"); k, ktok = self.join("Kai"); l, ltok = self.join("Lea")
        st, j, _ = self.new(tok, name="Secret", private=True, members=[k]); self.assertEqual(st, 200)
        ids = lambda t: [c["id"] for c in self.call("GET", f"/api/collab/p/{self.pid}", token=t)[1]["chats"]]
        self.assertIn(j["chat"], ids(tok)); self.assertIn(j["chat"], ids(ktok)); self.assertNotIn(j["chat"], ids(ltok))
        self.assertEqual(self.call("POST", f"/api/collab/p/{self.pid}/intent", {"id": "x1", "type": "msg", "chat": j["chat"], "payload": {"text": "hi"}}, token=ltok)[0] in (403, 404), True)

    def test_bad_requests_and_limits(self):
        m, tok = self.join("Mei", role="viewer")
        self.assertIn(self.new(tok, name="x")[0], (403,))                                         # a reader cannot start chats
        n, ntok = self.join("Ned"); 
        for body in ({"private": True}, {"private": True, "members": "x"}, {"private": True, "members": ["m_nobody"]}, {"name": 5}, {"private": True, "members": [None]}):
            self.assertEqual(self.new(ntok, **body)[0], 400, body)
        import collab_store as S2
        for i in range(S2.MAX_CHATS): self.st.create_chat(self.pid, self.owner, f"x{i}") if i < S2.MAX_CHATS - 1 else None
        self.assertEqual(self.new(ntok, name="one too many")[0], 413)


class TestMyLimits(Base):
    def test_a_member_sees_their_limits_and_use(self):
        m, tok = self.join("Mei", role="editor"); self.assertEqual(self.call("GET", f"/api/collab/p/{self.pid}", token=tok)[1]["my_limits"], [])
        g = P.template("editor", project=self.work); g["budget"] = {"turns_per_hour": 3}
        self.st.set_grant(self.pid, self.owner, m, g)
        self.assertEqual(self.call("GET", f"/api/collab/p/{self.pid}", token=tok)[1]["my_limits"], [{"per": "hour", "limit": 3, "used": 0}])


class TestPresence(Base):
    def test_who_has_the_project_open_is_listed(self):
        m, tok = self.join("Mei")
        self.assertEqual(self.call("GET", f"/api/collab/p/{self.pid}", token=tok)[1]["online"], [])
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10); c.request("GET", f"/api/collab/p/{self.pid}/events?stream=1", headers={"Authorization": "Bearer " + tok, "Accept": "text/event-stream"})
        r = c.getresponse(); self.assertEqual(r.status, 200)
        for _ in range(50):
            if self.call("GET", f"/api/collab/p/{self.pid}", token=self.otok)[1]["online"] == [m]: break
            time.sleep(0.05)
        self.assertEqual(self.call("GET", f"/api/collab/p/{self.pid}", token=self.otok)[1]["online"], [m])
        c.close()


class TestSearch(Base):
    def post(self, tok, text, chat="main"):
        st, j, _ = self.call("POST", f"/api/collab/p/{self.pid}/intent", {"id": "i%d" % time.time_ns(), "type": "msg", "chat": chat, "payload": {"text": text}}, token=tok); self.assertEqual(st, 200, j); return j

    def find(self, tok, q): return self.call("GET", f"/api/collab/p/{self.pid}/search?q={q}", token=tok)

    def test_finds_all_the_words_in_any_case_newest_first(self):
        m, tok = self.join("Mei"); self.post(tok, "The Pollen methylation plan"); self.post(tok, "lunch?"); self.post(tok, "more POLLEN data and methylation")
        st, j, _ = self.find(tok, "pollen%20METHYLATION"); self.assertEqual(st, 200)
        self.assertEqual([e["payload"]["text"] for e in j["results"]], ["more POLLEN data and methylation", "The Pollen methylation plan"])
        self.assertEqual(self.find(tok, "nothing%20like%20this")[1]["results"], [])

    def test_bad_queries_and_strangers_are_refused(self):
        m, tok = self.join("Mei")
        for q in ("", "%20%20", "x" * 300): self.assertEqual(self.find(tok, q)[0], 400, q)
        self.assertEqual(self.find(None, "hi")[0], 401); self.assertEqual(self.find("junk", "hi")[0], 401)

    def test_a_chat_the_member_cannot_see_is_never_searched(self):
        m, tok = self.join("Mei"); k, ktok = self.join("Kai")
        self.st.create_chat(self.pid, self.owner, "secret", name="Private", visibility={"mode": "members", "members": [self.owner, m]})
        self.post(tok, "the hidden budget number", chat="secret")
        self.assertEqual(len(self.find(tok, "hidden")[1]["results"]), 1); self.assertEqual(self.find(ktok, "hidden")[1]["results"], [])

    def test_deleted_messages_are_not_found(self):
        m, tok = self.join("Mei"); j = self.post(tok, "oops wrong thing")
        eid = next(e["id"] for e in self.st.read(self.pid, self.owner, limit=100) if e["seq"] == j["seq"])
        self.assertEqual(self.call("POST", f"/api/collab/p/{self.pid}/intent", {"id": "d1", "type": "delete", "chat": "main", "payload": {"target": eid}}, token=tok)[0], 200)
        self.assertEqual(self.find(tok, "oops")[1]["results"], [])


if __name__ == "__main__":
    unittest.main()


class TestSavingACopy(Base):
    def test_a_member_saves_the_chat_as_an_orbit_file(self):
        m, tok = self.join("Ed")
        self.call("POST", f"/api/collab/p/{self.pid}/intent", {"id": "m1", "type": "msg", "chat": "main", "payload": {"text": "hello there"}}, token=tok)
        st, j, h = self.call("GET", f"/api/collab/p/{self.pid}/export?format=orbit&chat=main", token=tok)
        self.assertEqual(st, 200); self.assertEqual((j["format"], j["version"], j["project"]), ("orbit-shared-chat", 1, "Lab"))
        self.assertEqual([(x["author"], x["text"]) for x in j["messages"]], [("Ed", "hello there")]); self.assertIn("attachment", h["Content-Disposition"])

    def test_the_owner_can_turn_it_off_for_members_but_not_for_themselves(self):
        m, tok = self.join("Ed")
        self.st.set_allow_export(self.pid, self.owner, False)
        for path in (f"/api/collab/p/{self.pid}/export?format=orbit&chat=main", f"/api/collab/p/{self.pid}/export?format=md", f"/api/collab/p/{self.pid}/export?format=json"):
            self.assertEqual(self.call("GET", path, token=tok)[0], 403, path)
        self.assertEqual(self.call("GET", f"/api/collab/p/{self.pid}/export?format=orbit&chat=main", token=self.otok)[0], 200)

    def test_only_chats_you_can_read_and_known_formats(self):
        m, tok = self.join("Ed"); n, ntok = self.join("Nosy")
        self.st.create_chat(self.pid, m, "secret", visibility={"mode": "members", "members": [m]})
        self.assertEqual(self.call("GET", f"/api/collab/p/{self.pid}/export?format=orbit&chat=secret", token=ntok)[0], 404)
        self.assertEqual(self.call("GET", f"/api/collab/p/{self.pid}/export?format=orbit&chat=secret", token=tok)[0], 200)
        self.assertEqual(self.call("GET", f"/api/collab/p/{self.pid}/export?format=xml&chat=main", token=tok)[0], 400)
        self.assertEqual(self.call("GET", f"/api/collab/p/{self.pid}/export?format=orbit&chat=nope", token=tok)[0], 404)
