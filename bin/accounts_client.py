"""Orbit's side of account sign-in (the service at orbit.runtianwu.com; see docs/collab/ACCOUNTS.md).

Signing in opens the service's page in the person's browser. The app gives that page its own one-time secret (a PKCE challenge), an unguessable
state, and a loopback address on this Mac to come back to. The page returns there with a one-time code; this module checks the state, trades
the code and its secret for tokens, and keeps the long-lived refresh token in a file only this user can read. The access token (15 minutes)
lives in memory. Nothing here ever shows a token to the page, the log or a status call.

The listener is one-shot: it accepts a single correct callback on 127.0.0.1 and then closes, and an attempt that is never finished expires.
"""
import base64, html, hashlib, hmac, json, os, secrets, threading, time, urllib.error, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_SERVICE = "https://orbit.runtianwu.com"
CALLBACK = "/orbit-callback"
ATTEMPT_S = 900                 # an unfinished sign-in is forgotten after fifteen minutes (an emailed link lasts ten, and mail can be slow)
REFRESH_MARGIN_S = 60           # an access token this close to its end is replaced first
TIMEOUT_S = 15

# What the person sees when the service sends the browser back with ?error=<code> instead of a code. Only these fixed sentences are ever shown.
_ERRORS = {
    "consent_required": "This is the first time this account signs in to Orbit, so Orbit needs your agreement first. Go back to the sign-in page, tick \u201cI have read what is stored and I agree\u201d, then choose it again.",
    "turnstile_required": "The check that you are a person did not pass. Go back to the sign-in page and try again.",
    "access_denied": "The sign-in was cancelled at the provider. Go back to the sign-in page to choose again.",
    "rate_limited": "There have been too many tries. Wait a few minutes, then go back to the sign-in page.",
    "browser_mismatch": "The sign-in finished in a different browser from the one that started it. Go back to the sign-in page and use one browser throughout.",
    "identity_in_use": "That sign-in method already belongs to another Orbit account.",
    "account_gone": "That Orbit account no longer exists.",
}
_GENERIC = "The sign-in did not complete. Go back to the sign-in page and try again."
_STYLE = b"<!doctype html><meta charset=utf-8><title>Orbit</title><body style=\"font:16px -apple-system,sans-serif;max-width:32rem;margin:15vh auto;padding:1rem;line-height:1.5\">"


def _error_page(message, retry_url=None):
    a = f'<p><a href="{html.escape(retry_url, quote=True)}">Back to the sign-in page</a></p>' if retry_url else ""
    return _STYLE + f"<h1>Sign-in needs one more step</h1><p>{html.escape(message)}</p>{a}</body>".encode()


PAGE = (b"<!doctype html><meta charset=utf-8><title>Orbit</title><body style=\"font:16px -apple-system,sans-serif;max-width:30rem;margin:15vh auto;padding:1rem\">"
        b"<h1>You are signed in to Orbit</h1><p>You can close this tab and go back to the app.</p></body>")


def _b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None          # a token request is never forwarded somewhere else


_OPENER = urllib.request.build_opener(_NoRedirect)


class AccountClient:
    def __init__(self, service=DEFAULT_SERVICE, path=None, now=time.time):
        u = urllib.parse.urlsplit(service or "")
        loop = u.hostname in ("127.0.0.1", "localhost", "::1")
        if not u.hostname or u.username or u.password or u.path not in ("", "/") or not (u.scheme == "https" or (u.scheme == "http" and loop)):
            raise ValueError("the account service must be an https address (or loopback for testing)")
        self.service = f"{u.scheme}://{u.netloc}"
        self.path, self.now = path, now
        self.lock = threading.RLock()
        self._pending, self._error = None, ""
        self._session = self._load()
        self._access = None                                      # (token, expires_at), memory only

    # -------------------------------------------------------------------------------------------------- storage
    def _load(self):
        try: d = json.load(open(self.path, encoding="utf-8")) if self.path else None
        except (OSError, ValueError): return None
        ok = isinstance(d, dict) and isinstance(d.get("refresh_token"), str) and isinstance(d.get("device_id"), str) and isinstance(d.get("account"), dict) and d.get("service") == self.service
        return {k: d[k] for k in ("refresh_token", "device_id", "account", "service")} if ok else None

    def _save(self):
        if not self.path: return
        if self._session is None:
            try: os.unlink(self.path)
            except OSError: pass
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f: json.dump(self._session, f)
        os.replace(tmp, self.path)

    # -------------------------------------------------------------------------------------------------- talking to the service
    def _call(self, method, path, body=None, bearer=None):
        """-> (status, json). A network failure is (None, None): the caller decides what that means."""
        data = json.dumps(body).encode() if body is not None else None
        h = {"Content-Type": "application/json", "User-Agent": "Orbit-account"}
        if bearer: h["Authorization"] = "Bearer " + bearer
        try:
            r = _OPENER.open(urllib.request.Request(self.service + path, data=data, method=method, headers=h), timeout=TIMEOUT_S)
            status, raw = r.status, r.read(200_000)
        except urllib.error.HTTPError as e: status, raw = e.code, e.read(200_000)
        except (urllib.error.URLError, OSError, ValueError): return None, None
        try: return status, json.loads(raw or b"{}")
        except ValueError: return status, {}

    # -------------------------------------------------------------------------------------------------- sign in
    def start(self, device_name="Orbit"):
        """Open a one-shot listener and return {url, port}: the caller opens the url in a browser."""
        with self.lock:
            # A sign-in already waiting keeps its address: pressing Sign in again must not close the listener that a link
            # already emailed (or already open in a browser) points to. Cancel is how to start over.
            if self._pending and self._pending.get("url") and self.now() - self._pending["started"] <= ATTEMPT_S:
                return {"url": self._pending["url"], "port": self._pending["port"]}
            self.cancel()
            verifier, state = secrets.token_urlsafe(48), secrets.token_urlsafe(18)
            outer = self

            class H(BaseHTTPRequestHandler):
                protocol_version = "HTTP/1.0"
                def log_message(self, *a): pass
                def _out(self, code, body=b"", ctype="text/plain"):
                    self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store"); self.send_header("Referrer-Policy", "no-referrer"); self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
                    self.end_headers(); self.wfile.write(body)
                def do_GET(self):
                    u = urllib.parse.urlsplit(self.path)
                    port = self.server.server_address[1]
                    if u.path != CALLBACK: return self._out(404)
                    if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"): return self._out(400)     # a rebound name is not us
                    q = urllib.parse.parse_qs(u.query)
                    code, st = (q.get("code") or [""])[0], (q.get("state") or [""])[0]
                    right = bool(st) and hmac.compare_digest(st.encode(), state.encode())
                    err = (q.get("error") or [""])[0]
                    if right and err and not code:           # the service sent the person back with a reason: say it, and keep waiting for a second try
                        msg = _ERRORS.get(err, _GENERIC)
                        with outer.lock:
                            if outer._pending: outer._error = msg
                        return self._out(200, _error_page(msg, retry.get("url")), "text/html; charset=utf-8")
                    if not code or not right:                # nothing is spent on a wrong guess
                        return self._out(400, _error_page("This is not the sign-in Orbit is waiting for. Go back to Orbit and press Sign in.", None), "text/html; charset=utf-8")
                    self._out(200, PAGE, "text/html; charset=utf-8")
                    threading.Thread(target=outer._finish, args=(code, verifier, redirect, self.server), daemon=True).start()

            retry = {}                                       # filled once the address is known: where "back to the sign-in page" goes
            srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
            srv.daemon_threads = True
            redirect = f"http://127.0.0.1:{srv.server_address[1]}{CALLBACK}"
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            q = urllib.parse.urlencode({"redirect_uri": redirect, "state": state, "code_challenge": _b64u(hashlib.sha256(verifier.encode()).digest()),
                                        "device_name": str(device_name or "Orbit")[:60]})
            url, port = f"{self.service}/signin?{q}", srv.server_address[1]
            retry["url"] = url
            self._pending, self._error = {"server": srv, "started": self.now(), "done": False, "url": url, "port": port}, ""
            return {"url": url, "port": port}

    def _close(self, srv):
        try: srv.shutdown(); srv.server_close()
        except Exception: pass

    def _finish(self, code, verifier, redirect, srv):
        threading.Thread(target=self._close, args=(srv,), daemon=True).start()               # one shot: whatever happens next, no second callback
        status, d = self._call("POST", "/token", {"grant_type": "authorization_code", "code": code, "code_verifier": verifier, "redirect_uri": redirect})
        with self.lock:
            self._pending = None
            if status == 200 and isinstance(d, dict) and d.get("refresh_token") and d.get("access_token"):
                acc = d.get("account") or {}
                self._session = {"refresh_token": d["refresh_token"], "device_id": str(d.get("device_id") or ""), "service": self.service,
                                 "account": {"id": str(acc.get("id") or ""), "name": str(acc.get("name") or "")[:80], "avatar": acc.get("avatar")}}
                self._access = (d["access_token"], self.now() + int(d.get("expires_in") or 900))
                self._error = ""; self._save()
            else:
                self._error = "The sign-in could not be completed. Try again." if status else "The account service could not be reached."

    def cancel(self):
        with self.lock:
            if self._pending: self._close(self._pending["server"]); self._pending = None

    # -------------------------------------------------------------------------------------------------- state
    def status(self):
        with self.lock:
            if self._pending and self.now() - self._pending["started"] > ATTEMPT_S: self.cancel()
            s = self._session
            return {"signed_in": bool(s), "name": (s or {}).get("account", {}).get("name"), "id": (s or {}).get("account", {}).get("id"),
                    "pending": bool(self._pending), "error": self._error, "service": self.service}

    def access_token(self):
        """A valid access token, refreshed if it is about to end; None when signed out or when the service cannot be reached right now."""
        with self.lock:
            if not self._session: return None
            if self._access and self._access[1] - REFRESH_MARGIN_S > self.now(): return self._access[0]
            status, d = self._call("POST", "/token/refresh", {"refresh_token": self._session["refresh_token"]})
            if status is None: return None                                                    # offline: not the same as signed out
            if status == 200 and isinstance(d, dict) and d.get("access_token") and d.get("refresh_token"):
                self._session["refresh_token"] = d["refresh_token"]
                self._access = (d["access_token"], self.now() + int(d.get("expires_in") or 900)); self._save()
                return d["access_token"]
            self._session, self._access = None, None; self._save()                            # refused: the session is over (and a retry would only repeat it)
            return None

    def join_proof(self, audience):
        """A two-minute token made for ONE host (its address is the audience), to show that this signed-in account is joining. None when signed out, offline or refused.
        The access token itself is never sent to a host."""
        tok = self.access_token()
        if not tok: return None
        status, d = self._call("POST", "/proof", {"audience": audience}, bearer=tok)
        return d.get("token") if status == 200 and isinstance(d, dict) and isinstance(d.get("token"), str) else None

    def export_data(self):
        """Everything the service stores about this account (GET /me/export), as a dict. Raises RuntimeError with a sentence for the person when it cannot."""
        tok = self.access_token()
        if not tok: raise RuntimeError("Sign in first (or the Orbit service cannot be reached right now).")
        status, d = self._call("GET", "/me/export", bearer=tok)
        if status is None: raise RuntimeError("The Orbit service cannot be reached right now.")
        if status != 200 or not isinstance(d, dict): raise RuntimeError(f"The service refused ({status}).")
        return d

    def delete_account(self):
        """Delete the account and everything stored with it on the service (DELETE /me), then forget the session here. Raises RuntimeError when it cannot."""
        tok = self.access_token()
        if not tok: raise RuntimeError("Sign in first (or the Orbit service cannot be reached right now).")
        status, d = self._call("DELETE", "/me", {"confirm": "delete"}, bearer=tok)
        if status is None: raise RuntimeError("The Orbit service cannot be reached right now: nothing was deleted.")
        if status != 200: raise RuntimeError(f"The service refused ({status}): nothing was deleted.")
        with self.lock:
            self._session, self._access, self._error = None, None, ""
            self._save()

    def sign_out(self):
        """End this device on the service (best effort) and forget everything here."""
        with self.lock:
            s = self._session
            tok = self.access_token() if s else None
            if s and tok: self._call("DELETE", "/devices/" + urllib.parse.quote(s["device_id"], safe=""), bearer=tok)
            self._session, self._access, self._error = None, None, ""
            self._save()
