"""The host's end of the relay: one outbound WebSocket to the Orbit service per published project. Members' requests arrive on it as frames; each is made to this Mac's own
member door (127.0.0.1) and the answer is sent back in pieces. Nothing listens for the outside: the connection is made from here, and the door's own checks (member tokens,
the permission engine, the allowlist of routes) still decide everything. The service never sees more than passes through it. See accounts/worker/src/relay.js for the frames."""
import base64, http.client, json, re, threading, time, urllib.parse

import ws_client as W

PATH_OK = re.compile(r"^/api/collab/[A-Za-z0-9_\-./]*(\?[A-Za-z0-9_\-.%&=+:,~*!'()@/]*)?$")
REQ_HEADERS = ("authorization", "content-type", "last-event-id", "accept")
RES_HEADERS = ("content-type", "cache-control", "content-disposition", "retry-after", "www-authenticate")
CHUNK = 192_000                 # bytes per frame before base64, under the 1 MiB message limit
MAX_STREAM_S = 55               # a live stream is ended after this long; the page reconnects with Last-Event-ID
MAX_BODY = 650_000
HELPER_PATH_OK = re.compile(r"^/mcp(/[A-Za-z0-9_\-]{20,80})?$")        # Orbit's helper door for other agents: only its one MCP address
MAX_CONCURRENT = 48
PING_EVERY_S = 25
BACKOFF = (1, 2, 5, 10, 20, 40, 60)


class RelayClient:
    def __init__(self, service, pid, secret, door_port, ws_factory=W.WSClient, sleep=time.sleep, now=time.time, path_ok=None):
        base = service.rstrip("/").replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        self.url = f"{base}/relay/host/{pid}"
        self.pid, self.secret, self.door_port, self.ws_factory, self.sleep, self.now = pid, secret, door_port, ws_factory, sleep, now
        self.path_ok = path_ok or PATH_OK            # which paths of the local door may be reached through this connection
        self.stop_event, self.thread, self.ws = threading.Event(), None, None
        self.state, self.error, self.since, self.served = "stopped", "", 0.0, 0
        self.active, self.lock = {}, threading.Lock()                # request id -> the local connection, so a cancel can close it
        self.slots = threading.BoundedSemaphore(MAX_CONCURRENT)

    # -- the connection
    def start(self):
        if self.thread and self.thread.is_alive(): return
        self.stop_event.clear(); self.state = "connecting"; self.thread = threading.Thread(target=self._run, daemon=True, name=f"relay-{self.pid}"); self.thread.start()

    def stop(self):
        self.stop_event.set(); self.state = "stopped"
        ws = self.ws
        if ws is not None:
            try: ws.close()
            except Exception: pass
        with self.lock:
            for c in list(self.active.values()):
                try: c.close()
                except Exception: pass

    def status(self):
        return {"state": self.state, "error": self.error, "since": self.since, "served": self.served}

    def _run(self):
        fails = 0
        while not self.stop_event.is_set():
            ws = None
            try:
                self.state = "connecting"
                ws = self.ws_factory(self.url, headers={"Authorization": "Bearer " + self.secret}); ws.connect(); self.ws = ws
                self.state, self.error, self.since, fails = "connected", "", self.now(), 0
                pinger = threading.Thread(target=self._ping, args=(ws,), daemon=True); pinger.start()
                while not self.stop_event.is_set():
                    msg = ws.recv()
                    if msg is None: break
                    self._frame(ws, msg)
                self.error = "the service closed the connection"
            except (W.WSError, OSError, ValueError) as e:
                self.error = str(e)[:160]
            finally:
                if ws is not None:
                    try: ws.close()
                    except Exception: pass
                self.ws = None
            if self.stop_event.is_set(): break
            self.state = "error" if self.error else "connecting"
            wait = BACKOFF[min(fails, len(BACKOFF) - 1)]; fails += 1
            if "401" in self.error: wait = 60                       # the secret was replaced or the project unpublished: do not hammer
            for _ in range(int(wait * 10)):
                if self.stop_event.is_set(): break
                self.sleep(0.1)
        self.state = "stopped"

    def _ping(self, ws):
        while not self.stop_event.wait(PING_EVERY_S):
            try:
                if ws.closed: return
                ws.send_text('{"t":"ping"}')
            except W.WSError: return

    # -- one frame
    def _frame(self, ws, text):
        try: f = json.loads(text)
        except ValueError: return
        if not isinstance(f, dict) or not isinstance(f.get("id"), str) and f.get("t") != "ping": return
        if f.get("t") == "cancel":
            with self.lock: c = self.active.pop(f["id"], None)
            if c is not None:
                try: c.close()
                except Exception: pass
        elif f.get("t") == "req":
            if not self.slots.acquire(blocking=False): return self._send(ws, {"t": "err", "id": f["id"], "status": 503, "msg": "the host is busy"})
            threading.Thread(target=self._serve, args=(ws, f), daemon=True).start()

    def _send(self, ws, obj):
        try: ws.send_text(json.dumps(obj, separators=(",", ":")))
        except W.WSError: pass

    def _serve(self, ws, f):
        rid = f["id"]
        try:
            method, path = f.get("method"), f.get("path")
            if method not in ("GET", "POST") or not isinstance(path, str) or len(path) > 2000 or not self.path_ok.match(path) or ".." in path.split("?")[0].split("/"):
                return self._send(ws, {"t": "err", "id": rid, "status": 404, "msg": "not found"})
            body = None
            if method == "POST":
                try: body = base64.b64decode(f.get("body") or "", validate=True)
                except Exception: return self._send(ws, {"t": "err", "id": rid, "status": 400, "msg": "bad body"})
                if len(body) > MAX_BODY: return self._send(ws, {"t": "err", "id": rid, "status": 413, "msg": "too large"})
            headers = {k: str(v) for k, v in (f.get("headers") or {}).items() if k in REQ_HEADERS and isinstance(v, str) and "\r" not in v and "\n" not in v}
            client = f.get("client") if isinstance(f.get("client"), str) and re.fullmatch(r"[A-Za-z0-9_\-]{8,32}", f["client"]) else ""
            if client: headers["X-Orbit-Relay-Client"] = client
            headers["Host"] = f"127.0.0.1:{self.door_port}"
            conn = http.client.HTTPConnection("127.0.0.1", self.door_port, timeout=MAX_STREAM_S + 80 if self.path_ok is HELPER_PATH_OK else MAX_STREAM_S + 10)
            with self.lock: self.active[rid] = conn
            conn.request(method, path, body=body, headers=headers)
            r = conn.getresponse()
            self._send(ws, {"t": "res", "id": rid, "status": r.status, "headers": {k: v for k, v in ((h, r.getheader(h)) for h in RES_HEADERS) if v}})
            end = self.now() + MAX_STREAM_S
            while self.now() < end:
                data = r.read1(CHUNK) if hasattr(r, "read1") else r.read(CHUNK)
                if not data: break
                self._send(ws, {"t": "chunk", "id": rid, "b64": base64.b64encode(data).decode()})
            self._send(ws, {"t": "end", "id": rid})
            self.served += 1
        except (OSError, http.client.HTTPException):
            if not self.stop_event.is_set(): self._send(ws, {"t": "err", "id": rid, "status": 502, "msg": "this Mac's door did not answer"})
        finally:
            with self.lock: c = self.active.pop(rid, None)
            if c is not None:
                try: c.close()
                except Exception: pass
            self.slots.release()
