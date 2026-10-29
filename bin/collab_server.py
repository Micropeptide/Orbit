"""Shared projects: the one door members have. Its own small HTTP server, with an allowlist of routes and nothing else behind it.

Orbit's main server can do anything a person at this Mac can do; a member of someone else's project must never be able to reach any of it.
So members do not talk to that server. They talk to this one, which knows only /api/collab/... and answers JSON and one event stream.
No pages, no files, no cookies, no CORS: a token in an Authorization header is the only way in, so there is nothing for another website
to ride on. The store (collab_store.py) decides what each member may do; this module only authenticates, shapes and limits.

    srv = make_server(store, host, port); srv.public_url = "https://my-mac.example"; threading.Thread(target=srv.serve_forever).start()
"""
import collections, json, os, re, select, socket, sys, threading, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import collab_accounts as CA
import collab_policy as P
import collab_store as S
import collab_local as L
import collab_share as SH

MAX_BODY = 256_000
AUTH_FAILS_PER_MIN = 10
STREAMS_PER_MEMBER = 6
STREAMS_TOTAL = 200
POLL_S, HEARTBEAT_S = 0.4, 15.0
PID, MID, IID = r"(p_[0-9a-f]{12})", r"(m_[0-9a-f]{10})", r"(i_[0-9a-f]{10})"
UID, AID = r"(u_[0-9a-f]{12})", r"(a_[0-9a-f]{12})"
ROUTES = [                                                    # (method, pattern, handler name, needs a token)
    ("GET", r"/api/collab/proto", "proto", False),
    ("GET", r"/api/collab/projects", "projects", True),
    ("POST", r"/api/collab/join", "join", False),
    ("POST", rf"/api/collab/p/{PID}/signin", "signin", False),
    ("GET", rf"/api/collab/p/{PID}", "project", True),
    ("GET", rf"/api/collab/p/{PID}/events", "events", True),
    ("POST", rf"/api/collab/p/{PID}/intent", "intent", True),
    ("POST", rf"/api/collab/p/{PID}/invite", "invite", True),
    ("GET", rf"/api/collab/p/{PID}/invites", "invites", True),
    ("POST", rf"/api/collab/p/{PID}/invites/{IID}/revoke", "revoke_invite", True),
    ("POST", rf"/api/collab/p/{PID}/grants", "grants", True),
    ("POST", rf"/api/collab/p/{PID}/members/{MID}", "member", True),
    ("POST", rf"/api/collab/p/{PID}/panic", "panic", True),
    ("POST", rf"/api/collab/p/{PID}/resume", "resume", True),
    ("GET", rf"/api/collab/p/{PID}/verify", "verify", True),
    ("GET", rf"/api/collab/p/{PID}/search", "search", True),
    ("GET", rf"/api/collab/p/{PID}/files", "files", True),
    ("GET", rf"/api/collab/p/{PID}/file", "file", True),
    ("GET", rf"/api/collab/p/{PID}/generated", "generated", True),
    ("GET", rf"/api/collab/p/{PID}/attachment/{AID}", "attachment", True),
    ("GET", rf"/api/collab/p/{PID}/filetext", "filetext_get", True),
    ("POST", rf"/api/collab/p/{PID}/filetext", "filetext_put", True),
    ("POST", rf"/api/collab/p/{PID}/upload", "upload_begin", True),
    ("POST", rf"/api/collab/p/{PID}/upload/{UID}/chunk", "upload_chunk", True),
    ("POST", rf"/api/collab/p/{PID}/upload/{UID}/finish", "upload_finish", True),
    ("POST", rf"/api/collab/p/{PID}/upload/{UID}/abort", "upload_abort", True),
    ("POST", rf"/api/collab/p/{PID}/chats", "new_chat", True),
    ("GET", rf"/api/collab/p/{PID}/export", "export", True),
]
ROUTES += [("GET", r"/", "page", False), ("GET", r"/join", "page", False), ("GET", r"/collab\.(js|css)", "asset", False)]
WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "web")
CSP = "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
COMPILED = [(m, re.compile("^" + p + "$"), h, auth) for m, p, h, auth in ROUTES]


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    # The default backlog is 5: a burst of members (or one page opening a handful of connections at once) had some of them
    # reset at connect. The per-member and total stream limits are what bound the load, not the accept queue.
    request_queue_size = 128

    def __init__(self, addr, handler, store):
        super().__init__(addr, handler)
        self.store, self.public_url = store, None
        self.trust_relay = False                 # when the host's own relay client is the only thing that reaches this door from 127.0.0.1, its caller hash names the caller
        self.share = SH.FileShare(store, store.policy)
        self.models_provider = None              # set by the host: the models people may ask, [{handle, label, payer}]
        self.accounts = None                    # an object with verify(token) -> claims, set by the host when it can check Orbit account tokens
        self.relay_audience = None              # relay_audience(pid) -> the join-proof audience of that project's page on the Orbit service, or None when it is not published there
        self.proofs = CA.ProofLedger()          # join proofs already used here: each works once
        self.allowed_hosts, self.allowed_origins = None, set()
        self.stopping = threading.Event()
        self.lock = threading.Lock()
        self.fails = collections.defaultdict(collections.deque)
        self.streams = collections.Counter(); self.stream_stops = {}
        self.polled = {}                         # (project, member) -> when they last asked for events by plain request: a page that cannot hold a stream open is still here

    def shutdown(self):
        self.stopping.set()
        super().shutdown()


def invite_links(base, pid, inv):
    """The two forms of a join link: a page address for a browser and orbit:// for the app."""
    base = base.rstrip("/")
    qs = f"p={pid}&i={inv['id']}&s={inv['secret']}"
    return {"link": f"{base}/join?{qs}", "app_link": f"orbit://join?host={urllib.parse.quote(base, safe='')}&{qs}"}


def make_server(store, host="127.0.0.1", port=0):
    return Server((host, port), Handler, store)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 30
    server_version, sys_version = "Orbit", ""

    def log_message(self, *a): pass                                   # no log of paths (an invite secret travels in one)

    # ------------------------------------------------------------------------------------------------ plumbing
    def _send(self, status, body, ctype="application/json; charset=utf-8", extra=None, close=False):
        sc = getattr(self, "_scrub_ctx", None)
        if sc and isinstance(body, (dict, list)): body = self.server.store.scrub_for(sc[0], sc[1], body)      # nothing a member is sent names a folder of the host's Mac
        data = body if isinstance(body, bytes) else (json.dumps(body, separators=(",", ":")).encode("utf-8") if not isinstance(body, str) else body.encode("utf-8"))
        self.send_response(status)
        self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store"); self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items(): self.send_header(k, v)
        if close: self.send_header("Connection", "close"); self.close_connection = True
        self.end_headers()
        if self.command != "HEAD": self.wfile.write(data)

    def _error(self, status, code, message, **kw):
        self._send(status, {"error": message, "code": code}, **kw)

    def _ip(self):
        """Who is calling, for the throttle: the address, or for a call that came through the relay a keyed hash the service made of the caller's address."""
        ip = self.client_address[0]
        if self.server.trust_relay and ip == "127.0.0.1":
            c = self.headers.get("X-Orbit-Relay-Client") or ""
            if re.fullmatch(r"[A-Za-z0-9_\-]{8,32}", c): return "relay:" + c
        return ip

    def _fail(self):
        with self.server.lock: self.server.fails[self._ip()].append(time.time())

    def _blocked(self):
        ip, now = self._ip(), time.time()
        with self.server.lock:
            dq = self.server.fails[ip]
            while dq and now - dq[0] >= 60: dq.popleft()
            return len(dq) >= AUTH_FAILS_PER_MIN

    def _origin_ok(self):
        o = self.headers.get("Origin")
        host = self.headers.get("Host", "")
        if self.server.allowed_hosts is not None and host not in self.server.allowed_hosts: return False
        if not o: return True                                          # a native app sends none
        if o in self.server.allowed_origins: return True
        try: return urllib.parse.urlsplit(o).netloc == host and bool(host)
        except ValueError: return False

    def _body(self):
        if self.headers.get("Transfer-Encoding"): raise S.CollabError("bad_input", "chunked bodies are not accepted; send a Content-Length")
        if len(self.headers.get_all("Content-Length") or []) > 1: raise S.CollabError("bad_input", "more than one Content-Length")
        n = self.headers.get("Content-Length")
        try: n = int(n) if n is not None else 0
        except ValueError: n = -1
        if n < 0: raise S.CollabError("bad_input", "bad Content-Length")
        if n > MAX_BODY:
            left = min(n, 2_000_000)
            while left > 0:
                chunk = self.rfile.read(min(65536, left))
                if not chunk: break
                left -= len(chunk)
            raise S.CollabError("too_large", "that request is too large")
        if self.command == "POST" and not (self.headers.get("Content-Type", "").lower().startswith("application/json")):
            raise _Unsupported()
        raw = self.rfile.read(n) if n else b""
        if not raw: return {}
        try: d = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError): raise S.CollabError("bad_input", "the body is not valid JSON")
        if not isinstance(d, dict): raise S.CollabError("bad_input", "the body must be a JSON object")
        return d

    def _raw_body(self, limit):
        """The bytes of an upload piece: a plain Content-Length body of a known size."""
        if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length") or []) != 1: raise S.CollabError("bad_input", "send one Content-Length")
        try: n = int(self.headers.get("Content-Length"))
        except (TypeError, ValueError): n = -1
        if n > limit:
            left = min(n, 2_000_000)                                      # read what is being sent so the sender gets the refusal instead of a reset connection
            while left > 0:
                chunk = self.rfile.read(min(65536, left))
                if not chunk: break
                left -= len(chunk)
        if n < 1 or n > limit: raise S.CollabError("too_large" if n > limit else "bad_input", f"a piece is 1 to {limit} bytes")
        if not self.headers.get("Content-Type", "").lower().startswith("application/octet-stream"): raise _Unsupported()
        raw = self.rfile.read(n)
        if len(raw) != n: raise S.CollabError("bad_input", "the piece was cut short")
        return raw

    def _send_file(self, path, name, size):
        ascii_name = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:100] or "file"
        self.send_response(200); self.send_header("Content-Type", "application/octet-stream"); self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition", f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{urllib.parse.quote(name, safe='')}")
        for k, v in (("X-Content-Type-Options", "nosniff"), ("Content-Security-Policy", "sandbox; default-src 'none'"), ("Cache-Control", "no-store"), ("Cross-Origin-Resource-Policy", "same-origin")): self.send_header(k, v)
        self.end_headers()
        sent = 0
        with open(path, "rb") as f:
            while sent < size:
                b = f.read(min(65536, size - sent))
                if not b: break
                self.wfile.write(b); sent += len(b)

    def _token(self):
        a = self.headers.get("Authorization", "")
        return a[7:].strip() if a[:7].lower() == "bearer " else ""

    # ------------------------------------------------------------------------------------------------ dispatch
    def _dispatch(self):
        self._scrub_ctx = None
        try:
            sp = urllib.parse.urlsplit(self.path)
            path = sp.path
            if "%" in path or ".." in path or "//" in path or "\x00" in path or len(path) > 300: return self._error(404, "not_found", "no such route")
            hit, wrong = None, False
            for method, rx, name, auth in COMPILED:
                m = rx.match(path)
                if m:
                    if method == self.command: hit = (name, auth, m.groups()); break
                    wrong = True
            if hit is None:
                return self._error(405, "method", "method not allowed", extra={"Allow": "GET, POST"}) if wrong else self._error(404, "not_found", "no such route")
            if not self._origin_ok(): return self._error(403, "origin", "this page is not allowed to use shared projects")
            name, auth, args = hit
            query = urllib.parse.parse_qs(sp.query)
            who = None
            if auth:
                if self._blocked(): return self._error(429, "rate_limited", "too many wrong tokens from this address; wait a minute", extra={"Retry-After": "60"})
                tok = self._token()
                pid = args[0] if args else None
                who = self.server.store.authenticate(pid, tok) if pid else None
                if pid is None:                                       # /projects: any project accepts the token
                    who = {"id": None} if self.server.store.projects_for(tok) else None
                if not who: self._fail(); return self._error(401, "unauthorized", "invalid token")
                if pid and who.get("id"): self._scrub_ctx = (pid, who["id"])
            elif name in ("join", "signin") and self._blocked(): return self._error(429, "rate_limited", "too many tries from this address; wait a minute", extra={"Retry-After": "60"})
            body = (self._raw_body(SH.CHUNK + 1000) if name == "upload_chunk" else self._body()) if self.command == "POST" else {}
            getattr(self, "h_" + name)(who, args, query, body)
        except S.CollabError as e:
            self._error(e.status, e.code, str(e), close=(e.code in ("too_large", "bad_input") and self.command == "POST"))
        except _Unsupported:
            self._error(415, "content_type", "send application/json")
        except (BrokenPipeError, ConnectionError): pass
        except Exception as e:                                         # nothing of ours leaks to a member
            print(f"[collab] {type(e).__name__}: {e}", file=sys.stderr)
            try: self._error(500, "internal", "something went wrong on the host")
            except Exception: pass

    def do_GET(self): self._dispatch()
    def do_POST(self): self._dispatch()
    def _no(self): self._error(405, "method", "method not allowed", extra={"Allow": "GET, POST"})
    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_HEAD = do_TRACE = do_CONNECT = _no

    # ------------------------------------------------------------------------------------------------ handlers
    def _static(self, name, ctype):
        try: data = open(os.path.join(WEB, name), "rb").read()
        except OSError: return self._error(404, "not_found", "no such page")
        self._send(200, data, ctype=ctype, extra={"Content-Security-Policy": CSP, "X-Frame-Options": "DENY", "Cross-Origin-Resource-Policy": "same-origin"})

    def h_page(self, who, args, q, body): self._static("collab.html", "text/html; charset=utf-8")

    def h_asset(self, who, args, q, body):
        ext = args[0]; self._static("collab." + ext, "text/javascript; charset=utf-8" if ext == "js" else "text/css; charset=utf-8")

    def h_proto(self, who, args, q, body): self._send(200, {"proto": S.PROTO, "app": "Orbit shared projects"})

    def h_projects(self, who, args, q, body): self._send(200, {"projects": self.server.store.projects_for(self._token())})

    def _audiences(self, pid=None):
        """A join proof is made for one host's address; this host accepts one made for any address it answers to. For a project published through the Orbit service it also
        accepts one made for that project's page there (and only that project's: `pid` is the project the request is about)."""
        srv, out = self.server, []
        if srv.public_url:
            u = urllib.parse.urlsplit(srv.public_url)
            if u.scheme and u.netloc: out.append(f"orbit-join:{u.scheme}://{u.netloc}")
        for h in sorted(srv.allowed_hosts or ()):
            for scheme in ("https", "http"):
                a = f"orbit-join:{scheme}://{h}"
                if a not in out: out.append(a)
        if isinstance(pid, str) and S.PID_RE.match(pid) and srv.relay_audience:
            try: a = srv.relay_audience(pid)
            except Exception: a = None
            if isinstance(a, str) and a and a not in out: out.append(a)
        return out

    def _account(self, body, pid=None):
        """The account a request proves, from a token the host checks itself: -> (account, jti, claims), or (None, None, None) when the request carries no proof. A bare `account` field in the body is never believed.
        The proof is single use: `jti` is held in the server's ledger until the caller calls `_release(jti)` (nothing was issued) or lets it stand (a token was)."""
        tok = body.get("account_token")
        if not tok: return None, None, None
        acc = self.server.accounts
        if acc is None: raise S.CollabError("bad_input", "this host cannot check Orbit accounts")
        auds = self._audiences(pid)
        if not auds: self._fail(); raise S.CollabError("unauthorized", "that sign-in could not be checked")          # never fall back to accepting an ordinary access token
        try: claims = acc.verify(tok, audiences=auds)
        except Exception:
            self._fail(); raise S.CollabError("unauthorized", "that sign-in could not be checked")
        jti = claims.get("jti")
        if not self.server.proofs.reserve(jti, claims.get("exp")):
            self._fail(); raise S.CollabError("unauthorized", "that sign-in was already used or cannot be accepted; sign in again")
        return {"provider": "orbit", "sub": str(claims["sub"])[:100]}, jti, claims

    def _release(self, jti):
        if jti: self.server.proofs.release(jti)

    def h_join(self, who, args, q, body):
        pid = body.get("p")
        account, jti, _ = self._account(body, pid)
        try:
            j = self.server.store.join(pid, body.get("i"), body.get("s"), name=body.get("name") or "Guest", account=account)
        except S.CollabError as e:
            self._release(jti)
            if e.code == "unauthorized": self._fail()
            raise
        except Exception:
            self._release(jti); raise
        self._send(200, dict(j, project=pid))

    def h_signin(self, who, args, q, body):
        account, jti, claims = self._account(body, args[0])
        if not account: raise S.CollabError("unauthorized", "sign in with your Orbit account")
        name = body.get("name") if isinstance(body.get("name"), str) and body.get("name").strip() else (claims.get("name") if isinstance(claims.get("name"), str) else None)
        try: j = self.server.store.sign_in(args[0], account, name=name)
        except S.CollabError as e:
            self._release(jti)
            if e.code in ("unauthorized", "not_a_member"): self._fail()
            raise
        except Exception:
            self._release(jti); raise
        self._send(200, dict(j, project=args[0]))

    def h_new_chat(self, who, args, q, body):
        import secrets as _sec
        if "name" in body and not isinstance(body["name"], str): raise S.CollabError("bad_input", "the name must be text")
        cid = "c" + _sec.token_hex(5); vis = None
        if body.get("private") is True:
            ms = body.get("members")
            if not isinstance(ms, list) or not all(isinstance(m, str) for m in ms): raise S.CollabError("bad_input", "choose who can see a private chat")
            vis = {"mode": "members", "members": ms}
        self.server.store.create_chat(args[0], who["id"], cid, name=body.get("name") if isinstance(body.get("name"), str) else None, visibility=vis)
        self._send(200, {"chat": cid})

    # -- files (see collab_share.py: each part behind its own switch in the member's grant)
    def _q1(self, q, key, default=""): return (q.get(key) or [default])[0]

    def h_files(self, who, args, q, body): self._send(200, self.server.share.list_dir(args[0], who["id"], self._q1(q, "path")))
    def h_file(self, who, args, q, body): self._send_file(*self.server.share.open_file(args[0], who["id"], self._q1(q, "path")))
    def h_generated(self, who, args, q, body): self._send(200, self.server.share.generated(args[0], who["id"]))
    def h_attachment(self, who, args, q, body): self._send_file(*self.server.share.open_attachment(args[0], who["id"], args[1]))
    def h_filetext_get(self, who, args, q, body): self._scrub_ctx = None; self._send(200, self.server.share.read_text(args[0], who["id"], self._q1(q, "path")))
    def h_filetext_put(self, who, args, q, body): self._send(200, self.server.share.write_text(args[0], who["id"], body.get("path"), body.get("content"), body.get("sha")))

    def h_upload_begin(self, who, args, q, body):
        self._send(200, self.server.share.begin_upload(args[0], who["id"], body.get("name"), body.get("size"), body.get("target"), body.get("dir") or "", body.get("chat") or "main", body.get("text") or ""))

    def h_upload_chunk(self, who, args, q, body):
        try: n = int(self._q1(q, "n", "-1"))
        except ValueError: n = -1
        self._send(200, self.server.share.chunk(args[0], who["id"], args[1], n, body))

    def h_upload_finish(self, who, args, q, body): self._send(200, self.server.share.finish_upload(args[0], who["id"], args[1]))
    def h_upload_abort(self, who, args, q, body): self._send(200, self.server.share.abort_upload(args[0], who["id"], args[1]))

    def h_search(self, who, args, q, body):
        found = self.server.store.search(args[0], who["id"], (q.get("q") or [""])[0], (q.get("limit") or [50])[0])
        self._send(200, {"results": found})

    def h_project(self, who, args, q, body):
        pv = dict(self.server.store.project_view(args[0], who["id"]))
        if who["id"] != pv["owner"]: pv["working_dir"] = "the project folder"      # a member is told where the models work, not where that is on the host's Mac
        try: pv["models"] = list(self.server.models_provider() or []) if self.server.models_provider else []
        except Exception: pv["models"] = []
        st, now = self.server.store, time.time(); b = st.effective_grant(args[0], [who["id"]]).get("budget") or {}
        pv["my_limits"] = [{"per": per, "limit": b[k], "used": st.turns_started(args[0], who["id"], now - win)} for k, per, win in (("turns_per_hour", "hour", 3600), ("turns_per_day", "day", 86400)) if k in b]
        with self.server.lock:
            pv["online"] = sorted({m for (p, m), n in self.server.streams.items() if p == args[0] and n > 0} | {m for (p, m), t in self.server.polled.items() if p == args[0] and time.time() - t < 15})       # who has the project open right now
        self._send(200, pv)

    def h_events(self, who, args, q, body):
        pid, st = args[0], self.server.store
        last = self.headers.get("Last-Event-ID") or (q.get("after") or ["0"])[0]
        try: after = max(int(last), 0)
        except ValueError: after = 0
        if "text/event-stream" in self.headers.get("Accept", "") or (q.get("stream") or [""])[0] == "1":
            return self._stream(pid, who, after)
        with self.server.lock:
            self.server.polled[(pid, who["id"])] = time.time()
            if len(self.server.polled) > 2000: self.server.polled = {k: t for k, t in self.server.polled.items() if time.time() - t < 15}
        if (q.get("tail") or [""])[0] or (q.get("before") or [""])[0]:          # the end of a long chat (or the page before a seq): no need to replay it all
            ev, more, head = st.read_tail(pid, who["id"], before=(q.get("before") or [None])[0], limit=(q.get("limit") or [300])[0])
            return self._send(200, {"events": ev, "next": head, "head": head, "more_before": more})
        ev = st.read(pid, who["id"], after=after, limit=(q.get("limit") or [200])[0])
        self._send(200, {"events": ev, "next": ev[-1]["seq"] if ev else after})

    def _stream(self, pid, who, after):
        srv, key = self.server, (pid, who["id"])
        stop = threading.Event()
        with srv.lock:
            if sum(srv.streams.values()) >= STREAMS_TOTAL: return self._error(429, "rate_limited", "too many open streams", close=True)
            mine = srv.stream_stops.setdefault(key, [])
            while len(mine) >= STREAMS_PER_MEMBER: mine.pop(0).set()        # the newest page wins: an old tab that was left open is let go, not the person who just arrived
            mine.append(stop); srv.streams[key] += 1
        try:
            self.send_response(200)
            for k, v in (("Content-Type", "text/event-stream; charset=utf-8"), ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"),
                         ("Connection", "close"), ("X-Accel-Buffering", "no")): self.send_header(k, v)
            self.end_headers(); self.close_connection = True
            tok, last_beat = self._token(), time.time()
            while not srv.stopping.is_set() and not stop.is_set():
                if not srv.store.authenticate(pid, tok): break          # removed, or the token was revoked: the stream ends
                try: batch = srv.store.read(pid, who["id"], after=after, limit=200)
                except S.CollabError: break
                for e in batch:
                    self.wfile.write(f"id: {e['seq']}\nevent: {e['type']}\ndata: {json.dumps(e, separators=(',', ':'))}\n\n".encode("utf-8"))
                    after = e["seq"]
                if batch: self.wfile.flush(); last_beat = time.time()
                elif time.time() - last_beat >= HEARTBEAT_S: self.wfile.write(b": keepalive\n\n"); self.wfile.flush(); last_beat = time.time()
                time.sleep(POLL_S)
                try:                                                    # has the other end gone? (a page that closed must not hold one of the few streams until the next heartbeat)
                    if select.select([self.connection], [], [], 0)[0] and not self.connection.recv(1, socket.MSG_PEEK): break
                except OSError: break
        except (BrokenPipeError, ConnectionError, OSError): pass
        finally:
            with srv.lock:
                srv.streams[key] -= 1
                if srv.streams[key] <= 0: del srv.streams[key]
                lst = srv.stream_stops.get(key) or []
                if stop in lst: lst.remove(stop)
                if not lst: srv.stream_stops.pop(key, None)

    def h_intent(self, who, args, q, body):
        self._send(200, self.server.store.submit(args[0], self._token(), body))

    def _grant_from(self, body, pid, key="grant"):
        if isinstance(body.get(key), dict): return body[key]
        role = body.get("role")
        if not isinstance(role, str) or role not in P.ROLES: raise S.CollabError("bad_input", "give a role or a grant")
        return P.template(role, project=self.server.store.project_view(pid, body["_me"])["working_dir"])

    def h_invite(self, who, args, q, body):
        pid, st = args[0], self.server.store
        body = dict(body, _me=who["id"])
        inv = st.create_invite(pid, who["id"], grant=self._grant_from(body, pid), expires_in=body.get("expires_in"), uses=body.get("uses", 1), account_required=bool(body.get("account_required")))
        base = self.server.public_url or f"http://{self.headers.get('Host', '')}"
        self._send(200, dict(inv, **invite_links(base, pid, inv)))

    def h_invites(self, who, args, q, body): self._send(200, {"invites": self.server.store.list_invites(args[0], who["id"])})

    def h_revoke_invite(self, who, args, q, body):
        self.server.store.revoke_invite(args[0], who["id"], args[1]); self._send(200, {"ok": True})

    def h_grants(self, who, args, q, body):
        pid = args[0]; body = dict(body, _me=who["id"])
        self.server.store.set_grant(pid, who["id"], body.get("member"), self._grant_from(body, pid)); self._send(200, {"ok": True})

    def h_member(self, who, args, q, body):
        pid, mid, act, st = args[0], args[1], body.get("action"), self.server.store
        if act == "remove": st.remove_member(pid, who["id"], mid)
        elif act in ("mute", "unmute"): st.set_member_state(pid, who["id"], mid, "muted" if act == "mute" else "active")
        else: raise S.CollabError("bad_input", "action must be remove, mute or unmute")
        self._send(200, {"ok": True})

    def h_panic(self, who, args, q, body): self.server.store.panic(args[0], who["id"]); self._send(200, {"ok": True})
    def h_resume(self, who, args, q, body): self.server.store.resume(args[0], who["id"]); self._send(200, {"ok": True})

    def _owner_only(self, who, pid):
        if self.server.store.project_view(pid, who["id"])["owner"] != who["id"]: raise S.CollabError("forbidden", "only the owner can do that")

    def h_verify(self, who, args, q, body):
        self._owner_only(who, args[0]); self._send(200, self.server.store.verify(args[0]))

    def h_export(self, who, args, q, body):
        pid, st = args[0], self.server.store
        fmt, chat = (q.get("format") or ["json"])[0], (q.get("chat") or [None])[0]
        view = st.project_view(pid, who["id"]); names = st.member_names(pid)
        if chat:
            if fmt not in ("orbit", "md", "json"): raise S.CollabError("bad_input", "format must be orbit, md or json")
            ev = st.export_events(pid, who["id"], chat)
            cname = next((c["name"] for c in view["chats"] if c["id"] == chat), chat)
            if fmt == "orbit":
                return self._send(200, L.shared_chat_payload(view["name"], chat, cname, ev, names, names.get(who["id"], "a member"), time.time()),
                                  extra={"Content-Disposition": 'attachment; filename="chat.orbit-chat.json"'})
        else:
            if fmt not in ("md", "json"): raise S.CollabError("bad_input", "format must be json or md")
            if who["id"] != view["owner"] and not view.get("allow_export", True): raise S.CollabError("forbidden", "the owner has turned off saving copies of chats here")
            ev = st.read(pid, who["id"], after=0, limit=10_000)
        if fmt == "json": return self._send(200, {"events": ev}, extra={"Content-Disposition": 'attachment; filename="project.json"'})
        lines = []
        for e in ev:
            if e["type"] != "msg": continue
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(e["ts"]))
            text = "(deleted)" if e["payload"].get("deleted") else e["payload"].get("text", "")
            lines.append(f"**{names.get(e['author'], e['author'])}** ({when}): {text}\n")
        self._send(200, "\n".join(lines), ctype="text/markdown; charset=utf-8", extra={"Content-Disposition": 'attachment; filename="project.md"'})


class _Unsupported(Exception): pass
