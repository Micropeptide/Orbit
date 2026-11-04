"""Talk to Claude Code's control channel without a chat answering.

Its controls (MCP status and sign-in, reloading plugins) are requests sent on a running session's stdin. A chat only has one
while an answer runs, so for the rest of the time Orbit starts a Claude Code of its own that has no message to answer, asks, and
closes it. Nothing is sent to a model, so it costs nothing. Sign-ins it completes are kept by Claude Code itself (in your
Claude folder) and every later session uses them.
"""
import json
import os
import subprocess
import threading
import time
import uuid

_BASE = ["--print", "--output-format", "stream-json", "--verbose", "--input-format", "stream-json"]


class Ctl:
    def __init__(self, exe, env=None, cwd=None, extra=()):
        self.proc = subprocess.Popen([exe] + _BASE + list(extra), cwd=cwd if cwd and os.path.isdir(cwd) else None, env=env,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     start_new_session=True)
        self.replies, self.cv, self.err = {}, threading.Condition(), []
        self.born = time.time()
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._read_err, daemon=True).start()
        self.request("initialize", timeout=20)

    def _read(self):
        for raw in self.proc.stdout:
            try: ev = json.loads(raw)
            except ValueError: continue
            if ev.get("type") != "control_response": continue
            r = ev.get("response") or {}
            with self.cv:
                self.replies.setdefault(r.get("request_id"), []).append(r)
                self.cv.notify_all()
        with self.cv:
            self.replies["__eof__"] = [{}]
            self.cv.notify_all()

    def _read_err(self):
        for raw in self.proc.stderr:
            self.err.append(raw.decode("utf-8", "replace").rstrip())
            del self.err[:-20]

    def send(self, subtype, **params):
        rid = "orbit-ctl-" + uuid.uuid4().hex[:8]
        line = json.dumps({"type": "control_request", "request_id": rid, "request": {"subtype": subtype, **params}}) + "\n"
        try:
            self.proc.stdin.write(line.encode()); self.proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            return None
        return rid

    def wait(self, rid, timeout=15, nth=0):
        """The nth reply to a request (a sign-in answers twice: the address to open, then that it finished)."""
        end = time.time() + timeout
        with self.cv:
            while True:
                got = self.replies.get(rid) or []
                if len(got) > nth: return got[nth]
                if "__eof__" in self.replies or time.time() >= end: return None
                self.cv.wait(0.3)

    def request(self, subtype, timeout=15, **params):
        """The reply's payload, or {"error": ...}."""
        rid = self.send(subtype, **params)
        if rid is None: return {"error": "Claude Code has closed"}
        r = self.wait(rid, timeout)
        return _payload(r)

    def close(self):
        try: self.proc.stdin.close()
        except Exception: pass
        try: self.proc.wait(timeout=5)
        except Exception:
            try: os.killpg(os.getpgid(self.proc.pid), 15)
            except Exception: pass


def _payload(r):
    if r is None: return {"error": "no reply from Claude Code"}
    if r.get("subtype") == "error": return {"error": str(r.get("error") or "Claude Code refused")}
    return r.get("response") if isinstance(r.get("response"), dict) else {}


def once(exe, env, cwd, subtype, timeout=20, **params):
    """One control request on a short-lived Claude Code."""
    try: c = Ctl(exe, env, cwd)
    except OSError as e: return {"error": f"Claude Code could not be started: {e}"}
    try: return c.request(subtype, timeout=timeout, **params)
    finally: c.close()


def mcp_servers(exe, env, cwd, settle=8):
    """[{name, status, ...}] for the servers Claude Code would start with, once they have had a moment to connect."""
    try: c = Ctl(exe, env, cwd)
    except OSError as e: return {"error": f"Claude Code could not be started: {e}"}
    try:
        end = time.time() + settle
        while True:
            r = c.request("mcp_status", timeout=15)
            if r.get("error"): return r
            servers = r.get("mcpServers") or []
            if not any(str(s.get("status")) == "pending" for s in servers) or time.time() >= end:
                return {"servers": servers}
            time.sleep(1)
    finally:
        c.close()


# sign-ins in progress: server name -> {ctl, rid, at}. The browser comes back to Claude Code's own local address, so the
# process that asked has to stay up until it does (or until ten minutes pass).
AUTH = {}
_LOCK = threading.Lock()
KEEP_S = 600


def _reap():
    now = time.time()
    for name, a in list(AUTH.items()):
        if now - a["at"] > KEEP_S or a["ctl"].proc.poll() is not None:
            AUTH.pop(name, None)
            threading.Thread(target=a["ctl"].close, daemon=True).start()


def auth_start(exe, env, cwd, server):
    """Begin signing in to one MCP server: {"url": the address to open} (or {"error"}), the session kept while you do."""
    with _LOCK:
        _reap()
        old = AUTH.pop(server, None)
    if old: threading.Thread(target=old["ctl"].close, daemon=True).start()
    try: c = Ctl(exe, env, cwd)
    except OSError as e: return {"error": f"Claude Code could not be started: {e}"}
    rid = c.send("mcp_authenticate", serverName=server)
    r = c.wait(rid, 25) if rid else None
    out = _payload(r)
    url = out.get("authUrl") or out.get("url") or out.get("authorizationUrl")
    if out.get("error") or not url:
        c.close()
        return {"error": out.get("error") or "this server gave no address to sign in at (it may not need signing in)"} if not url else out
    with _LOCK: AUTH[server] = {"ctl": c, "rid": rid, "at": time.time()}
    return {"url": url, "waiting": bool(out.get("callbackExpected", True))}


def auth_state(server):
    """Whether the sign-in Orbit started has finished: {"state": waiting|done|none, ...}."""
    with _LOCK: a = AUTH.get(server)
    if not a: return {"state": "none"}
    later = a["ctl"].wait(a["rid"], 0.1, nth=1)
    if later is None:
        if a["ctl"].proc.poll() is not None: return {"state": "none"}
        return {"state": "waiting"}
    with _LOCK: AUTH.pop(server, None)
    threading.Thread(target=a["ctl"].close, daemon=True).start()
    out = _payload(later)
    return {"state": "done"} if not out.get("error") else {"state": "failed", "error": out["error"]}


def auth_callback(exe, env, cwd, server, callback_url):
    """Hand Claude Code the address the browser ended up at, for a sign-in whose redirect did not reach it."""
    with _LOCK: a = AUTH.get(server)
    if a: return a["ctl"].request("mcp_oauth_callback_url", timeout=30, serverName=server, callbackUrl=callback_url)
    return once(exe, env, cwd, "mcp_oauth_callback_url", 30, serverName=server, callbackUrl=callback_url)


def auth_clear(exe, env, cwd, server):
    return once(exe, env, cwd, "mcp_clear_auth", 15, serverName=server)
