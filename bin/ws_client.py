"""A small WebSocket client (RFC 6455) on the standard library: connect over ws/wss with request headers, send and receive text messages, answer pings.
Only what the relay connection needs: no extensions, no compression, text and control frames, fragmented messages put back together."""
import base64, hashlib, os, socket, ssl, struct, threading, urllib.parse

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_MESSAGE = 4_000_000


class WSError(Exception):
    pass


class WSClient:
    def __init__(self, url, headers=None, timeout=20, sock_factory=None):
        u = urllib.parse.urlsplit(url)
        if u.scheme not in ("ws", "wss") or not u.hostname: raise WSError("not a websocket address")
        self.scheme, self.host, self.port = u.scheme, u.hostname, u.port or (443 if u.scheme == "wss" else 80)
        self.path = (u.path or "/") + (("?" + u.query) if u.query else "")
        self.headers, self.timeout, self.sock_factory = dict(headers or {}), timeout, sock_factory
        self.sock, self.buf, self.lock, self.closed = None, b"", threading.Lock(), False

    # -- connecting
    def connect(self):
        raw = self.sock_factory(self.host, self.port) if self.sock_factory else socket.create_connection((self.host, self.port), timeout=self.timeout)
        if self.scheme == "wss": raw = ssl.create_default_context().wrap_socket(raw, server_hostname=self.host)
        raw.settimeout(self.timeout); self.sock = raw
        key = base64.b64encode(os.urandom(16)).decode()
        host = self.host + ("" if self.port in (80, 443) else f":{self.port}")
        lines = [f"GET {self.path} HTTP/1.1", f"Host: {host}", "Upgrade: websocket", "Connection: Upgrade", f"Sec-WebSocket-Key: {key}", "Sec-WebSocket-Version: 13"]
        for k, v in self.headers.items():
            if "\r" in k + str(v) or "\n" in k + str(v): raise WSError("bad header")
            lines.append(f"{k}: {v}")
        self.sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            c = self.sock.recv(4096)
            if not c: raise WSError("the server closed the connection during the handshake")
            head += c
            if len(head) > 65536: raise WSError("the handshake answer is too long")
        head, _, self.buf = head.partition(b"\r\n\r\n")
        text = head.decode("latin-1").split("\r\n")
        if len(text[0].split()) < 2 or text[0].split()[1] != "101": raise WSError("the server refused the connection: " + text[0][:80])
        h = {l.split(":", 1)[0].strip().lower(): l.split(":", 1)[1].strip() for l in text[1:] if ":" in l}
        want = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
        if h.get("sec-websocket-accept") != want: raise WSError("the server's handshake answer was wrong")
        return self

    # -- frames
    def _read(self, n):
        while len(self.buf) < n:
            c = self.sock.recv(65536)
            if not c: raise WSError("the connection closed")
            self.buf += c
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _send_frame(self, opcode, payload=b""):
        if self.closed: raise WSError("the connection is closed")
        hdr = bytes([0x80 | opcode]); n = len(payload)
        hdr += bytes([0x80 | n]) if n < 126 else (bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536 else bytes([0x80 | 127]) + struct.pack(">Q", n))
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload)) if n < 4096 else (int.from_bytes(payload, "big") ^ int.from_bytes((mask * (n // 4 + 1))[:n], "big")).to_bytes(n, "big")
        with self.lock:
            try: self.sock.sendall(hdr + mask + masked)
            except OSError as e: raise WSError(str(e))

    def send_text(self, text): self._send_frame(0x1, text.encode("utf-8"))
    def ping(self): self._send_frame(0x9, b"")

    def recv(self):
        """-> a text message (str), or None when the server closed. Pings are answered; pongs are ignored."""
        msg, kind = b"", None
        while True:
            b1, b2 = self._read(2)
            fin, op, n = b1 & 0x80, b1 & 0x0F, b2 & 0x7F
            if b2 & 0x80: raise WSError("a server must not mask its frames")
            if n == 126: n = struct.unpack(">H", self._read(2))[0]
            elif n == 127: n = struct.unpack(">Q", self._read(8))[0]
            if n > MAX_MESSAGE: raise WSError("a message was too large")
            data = self._read(n) if n else b""
            if op == 0x8: self.closed = True; return None
            if op == 0x9: self._send_frame(0xA, data); continue
            if op == 0xA: continue
            if op in (0x1, 0x2): kind, msg = op, data
            elif op == 0x0:
                if kind is None: raise WSError("an unexpected continuation")
                msg += data
            else: raise WSError("an unknown frame type")
            if len(msg) > MAX_MESSAGE: raise WSError("a message was too large")
            if fin: return msg.decode("utf-8", "replace") if kind == 0x1 else msg.decode("latin-1")

    def close(self):
        try:
            if not self.closed: self._send_frame(0x8, struct.pack(">H", 1000))
        except WSError: pass
        self.closed = True
        try: self.sock.close()
        except Exception: pass
