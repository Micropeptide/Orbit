"""The WebSocket client against a small local server written independently from it: the handshake, masking, pings, fragments, big messages, close and refusals."""
import base64, hashlib, os, socket, struct, sys, threading, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
import ws_client as W              # noqa: E402

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class Server:
    """Accepts one connection, does the handshake (or refuses), then runs `script(conn, server)`; records what the client sent."""
    def __init__(self, script=None, refuse=None, bad_accept=False):
        self.sock = socket.socket(); self.sock.bind(("127.0.0.1", 0)); self.sock.listen(1); self.port = self.sock.getsockname()[1]
        self.script, self.refuse, self.bad_accept, self.request, self.frames, self.buf = script, refuse, bad_accept, "", [], b""
        self.t = threading.Thread(target=self.run, daemon=True); self.t.start()

    def read(self, c, n):
        while len(self.buf) < n:
            d = c.recv(65536)
            if not d: raise EOFError
            self.buf += d
        out, self.buf = self.buf[:n], self.buf[n:]; return out

    def read_frame(self, c):
        b1, b2 = self.read(c, 2); n = b2 & 0x7F
        assert b2 & 0x80, "the client must mask its frames"
        if n == 126: n = struct.unpack(">H", self.read(c, 2))[0]
        elif n == 127: n = struct.unpack(">Q", self.read(c, 8))[0]
        mask = self.read(c, 4); data = bytes(b ^ mask[i % 4] for i, b in enumerate(self.read(c, n))); return b1 & 0x0F, bool(b1 & 0x80), data

    @staticmethod
    def frame(op, payload=b"", fin=True):
        n = len(payload); h = bytes([(0x80 if fin else 0) | op]) + (bytes([n]) if n < 126 else bytes([126]) + struct.pack(">H", n) if n < 65536 else bytes([127]) + struct.pack(">Q", n)); return h + payload

    def run(self):
        c, _ = self.sock.accept(); head = b""
        while b"\r\n\r\n" not in head: head += c.recv(4096)
        self.request = head.decode("latin-1"); key = [l.split(":", 1)[1].strip() for l in self.request.split("\r\n") if l.lower().startswith("sec-websocket-key")][0]
        if self.refuse: c.sendall(f"HTTP/1.1 {self.refuse}\r\nContent-Length: 0\r\n\r\n".encode()); c.close(); return
        acc = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode() if not self.bad_accept else "wrong"
        c.sendall(f"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {acc}\r\n\r\n".encode())
        try:
            if self.script: self.script(c, self)
        except Exception: pass
        finally: c.close()


def connect(srv, **kw): return W.WSClient(f"ws://127.0.0.1:{srv.port}/relay/host/p_1?x=1", headers={"Authorization": "Bearer s3cret"}, **kw).connect()


class TestWS(unittest.TestCase):
    def test_handshake_sends_the_path_and_headers_and_text_both_ways_is_masked(self):
        def script(c, s):
            op, fin, data = s.read_frame(c); s.frames.append((op, data)); c.sendall(s.frame(1, b"hello " + data))
        s = Server(script); ws = connect(s); ws.send_text("grüß"); self.assertEqual(ws.recv(), "hello grüß".encode().decode()); s.t.join(2)
        self.assertIn("GET /relay/host/p_1?x=1 HTTP/1.1", s.request); self.assertIn("Authorization: Bearer s3cret", s.request); self.assertEqual(s.frames, [(1, "grüß".encode())])

    def test_pings_are_answered_fragments_are_joined_and_pongs_ignored(self):
        got = []
        def script(c, s):
            c.sendall(s.frame(9, b"hi")); op, _, data = s.read_frame(c); got.append((op, data))
            c.sendall(s.frame(0xA, b"x") + s.frame(1, b"frag", fin=False) + s.frame(0, b"men", fin=False) + s.frame(0, b"ted", fin=True))
        s = Server(script); ws = connect(s); self.assertEqual(ws.recv(), "fragmented"); s.t.join(2); self.assertEqual(got, [(0xA, b"hi")])

    def test_large_messages_in_both_directions(self):
        big = "x" * 300_000; seen = []
        def script(c, s):
            op, fin, data = s.read_frame(c); seen.append(len(data)); c.sendall(s.frame(1, data))
        s = Server(script); ws = connect(s); ws.send_text(big); self.assertEqual(ws.recv(), big); s.t.join(2); self.assertEqual(seen, [300_000])

    def test_a_close_from_the_server_returns_none_and_sending_after_close_fails(self):
        s = Server(lambda c, s: c.sendall(s.frame(8, struct.pack(">H", 1000)))); ws = connect(s); self.assertIsNone(ws.recv())
        with self.assertRaises(W.WSError): ws.send_text("x")

    def test_refusals_are_errors(self):
        with self.assertRaises(W.WSError) as cm: connect(Server(refuse="401 Unauthorized"))
        self.assertIn("401", str(cm.exception))
        with self.assertRaises(W.WSError): connect(Server(bad_accept=True))
        for bad in ("http://x", "ws://", "", "wss:///x"):
            with self.assertRaises(W.WSError): W.WSClient(bad)
        with self.assertRaises(W.WSError): W.WSClient("ws://127.0.0.1:1/", headers={"A": "b\r\nX: y"}, sock_factory=lambda h, p: socket.socket()).connect()

    def test_a_dropped_connection_and_a_masked_server_frame_are_errors(self):
        s = Server(lambda c, s: None); ws = connect(s); s.t.join(2)
        with self.assertRaises(W.WSError): ws.recv()
        s2 = Server(lambda c, s: c.sendall(bytes([0x81, 0x80 | 1]) + b"\0\0\0\0x")); ws2 = connect(s2)
        with self.assertRaises(W.WSError): ws2.recv()

    def test_messages_over_the_limit_are_refused(self):
        s = Server(lambda c, s: c.sendall(bytes([0x81, 127]) + struct.pack(">Q", W.MAX_MESSAGE + 1))); ws = connect(s)
        with self.assertRaises(W.WSError): ws.recv()


if __name__ == "__main__":
    unittest.main()
