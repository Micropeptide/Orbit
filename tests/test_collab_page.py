"""The member page in a real (headless) browser: it must actually draw. A script error that leaves the page blank passes every other test, so this loads the page with
a live door and a project, and checks what is on the screen."""
import os, shutil, subprocess, sys, tempfile, threading, time, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
import collab_policy as P      # noqa: E402
import collab_store as S       # noqa: E402
import collab_server as V      # noqa: E402

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


@unittest.skipUnless(os.path.exists(CHROME), "needs Google Chrome")
class TestPageDraws(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)
        work = os.path.join(self.tmp, "work"); os.makedirs(work)
        pol = P.Policy(never=[], home=os.path.join(self.tmp, "home"), sensitive=lambda p: None)
        self.st = S.Store(os.path.join(self.tmp, "collab"), policy=pol)
        p = self.st.create_project("Pollen notebook", owner_name="Owner", working_dir=work); self.pid, self.owner = p["project"]["id"], p["member"]["id"]
        inv = self.st.create_invite(self.pid, self.owner, grant=P.template("editor", project=work)); self.mei = self.st.join(self.pid, inv["id"], inv["secret"], name="Mei")["member"]["id"]
        self.st.submit_as(self.pid, self.mei, {"id": "i1", "type": "msg", "chat": "main", "payload": {"text": "hello <b>there</b> pollen"}})
        self.st.append_system(self.pid, "turn_changes", {"turn": "t", "model": "qwen", "asked_by": self.mei, "asked_by_name": "Mei", "created": ["a.txt"], "modified": [], "deleted": [], "more": 0, "truncated": False, "undoable": 1}, chat="main")
        self.st.append_system(self.pid, "approval_request", {"request": "r_1", "turn": "t", "tool": "run_shell", "args_summary": "rm x", "touches": [], "requested_by": self.mei, "reason": "deletes", "need": 1, "flags": []}, chat="main")
        self.st.attach_message(self.pid, self.mei, "main", {"id": "a_0123456789ab", "name": "figure one.png", "size": 2048}, "see the figure")
        self.st.append_system(self.pid, "file_upload", {"by": self.mei, "target": "dir", "path": "data/new.csv", "size": 1234, "sha": "abc"}, chat=None)
        self.dev = self.st.add_device_for(self.pid, self.owner, "browser")
        self.srv = V.make_server(self.st, "127.0.0.1", 0); self.port = self.srv.server_address[1]; self.srv.public_url = f"http://127.0.0.1:{self.port}"; self.srv.models_provider = lambda: [{"handle": "qwen", "label": "Qwen", "payer": "the host", "usage": {"label": "no limit (runs on this Mac)", "left_pct": None, "state": "ok"}}, {"handle": "opus", "label": "Opus", "payer": "the host", "usage": {"label": "62% left in the 5-hour window, resets in 2 h", "left_pct": 62, "state": "ok"}}]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start(); self.addCleanup(self.srv.shutdown); self.addCleanup(self.srv.server_close)

    def dump(self, url):
        r = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", f"--user-data-dir={self.tmp}/profile", "--virtual-time-budget=6000", "--dump-dom", url],
                           capture_output=True, text=True, timeout=60)
        return r.stdout

    def test_the_project_page_draws_with_chats_people_messages_and_an_approval_card(self):
        dom = self.dump(f"http://127.0.0.1:{self.port}/#p={self.pid}&t={self.dev['token']}&n=Owner")
        for needle in ("Pollen notebook", "New chat", "Search", "Files", "Mei", "pollen", "created a.txt", "Needs an answer", "figure one.png", "2.0 KB", "put data/new.csv into the project folder"):
            self.assertIn(needle, dom, needle)
        self.assertIn("type @ to ask a model", dom); self.assertIn(">@qwen<", dom); self.assertIn(">@opus<", dom)        # the composer and its shortcuts name the models people may ask
        self.assertNotIn("<b>there</b>", dom)                                  # a member's text is shown as text, never as markup
        self.assertIn("&lt;b&gt;there&lt;/b&gt;", dom)

    def test_the_page_shows_what_is_left_of_each_model_a_chat_header_and_message_actions(self):
        dom = self.dump(f"http://127.0.0.1:{self.port}/#p={self.pid}&t={self.dev['token']}&n=Owner")
        for needle in ("62% left in the 5-hour window, resets in 2 h", "no limit (runs on this Mac)", "# Main", 'aria-label="Message actions"', 'aria-label="Chats"', "Models"):
            self.assertIn(needle, dom, needle)

    def test_markdown_becomes_safe_elements_and_never_a_script_link(self):
        self.st.submit_as(self.pid, self.mei, {"id": "md1", "type": "msg", "chat": "main", "payload": {"text": "**bold** and `code` see [site](https://example.org/x) and [bad](javascript:alert(1))\n\n```py\nprint(1)\n```\n\n- one\n- two"}})
        dom = self.dump(f"http://127.0.0.1:{self.port}/#p={self.pid}&t={self.dev['token']}&n=Owner")
        for needle in ("<strong>bold</strong>", "<code>code</code>", 'href="https://example.org/x"', 'rel="noopener noreferrer"', 'class="codeblock"', "print(1)", "<li>one</li>"):
            self.assertIn(needle, dom, needle)
        self.assertNotIn('href="javascript:', dom)

    def test_a_long_history_opens_on_its_end_and_offers_the_earlier_part(self):
        import unittest.mock
        with unittest.mock.patch.object(S, "RATE_PER_MIN", 10 ** 6):
            for i in range(330): self.st.submit_as(self.pid, self.mei, {"id": f"bulk{i}", "type": "msg", "chat": "main", "payload": {"text": f"bulk message {i}"}})
        dom = self.dump(f"http://127.0.0.1:{self.port}/#p={self.pid}&t={self.dev['token']}&n=Owner")
        self.assertIn("bulk message 329", dom); self.assertNotIn(">bulk message 3<", dom); self.assertIn("Load earlier messages", dom)

    def test_a_host_that_does_not_answer_gives_a_readable_error_with_a_retry_not_a_blank_page(self):
        import http.server, json as _json
        web = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def do_GET(self):
                if self.path.startswith("/api/"):
                    b = _json.dumps({"error": "The host\u2019s Orbit is not sharing right now."}).encode(); self.send_response(503); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
                name = {"/": "collab.html", "/collab.js": "collab.js", "/collab.css": "collab.css"}.get(self.path.split("#")[0])
                if not name: self.send_response(404); self.end_headers(); return
                b = open(os.path.join(web, name), "rb").read(); self.send_response(200); self.send_header("Content-Type", "text/html" if name.endswith("html") else "text/javascript" if name.endswith("js") else "text/css"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start(); self.addCleanup(srv.server_close); self.addCleanup(srv.shutdown)
        dom = self.dump(f"http://127.0.0.1:{srv.server_address[1]}/#p={self.pid}&t=abc&n=X")
        for needle in ("Cannot reach the project", "not sharing right now", "Try again", "Reload the page"):
            self.assertIn(needle, dom, needle)

    def test_a_visitor_without_a_session_sees_the_how_to_join_note_not_a_blank_page(self):
        dom = self.dump(f"http://127.0.0.1:{self.port}/")
        self.assertIn("Open an invitation link to join a project", dom)


if __name__ == "__main__":
    unittest.main()
