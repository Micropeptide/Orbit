"""Pressing stop keeps the words already on screen.

Cancelling a turn is an ordinary thing to do, not an error, and the paragraph you were
reading when you pressed it is worth keeping -- it is often the reason you pressed it.
Every backend has to agree about that. One of them did not: the Anthropic path closed
the stream and then asked it for the final message, which resumes reading the socket it
had just closed, so the turn ended with "Bad file descriptor" and the text was dropped
on the floor."""
import json, os, sys, threading, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))
import providers


def _events(n=200):
    out = [("message_start", {"type": "message_start", "message": {
                "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5",
                "content": [], "stop_reason": None, "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 1}}}),
           ("content_block_start", {"type": "content_block_start", "index": 0,
                "content_block": {"type": "text", "text": ""}})]
    for i in range(n):
        out.append(("content_block_delta", {"type": "content_block_delta", "index": 0,
                    "delta": {"type": "text_delta", "text": f"chunk{i} "}}))
    out.append(("content_block_stop", {"type": "content_block_stop", "index": 0}))
    out.append(("message_delta", {"type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": n}}))
    out.append(("message_stop", {"type": "message_stop"}))
    return out


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def do_POST(self):
        self.rfile.read(int(self.headers.get("content-length") or 0))
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("transfer-encoding", "chunked")
        self.end_headers()
        try:
            for name, data in _events():
                b = f"event: {name}\ndata: {json.dumps(data)}\n\n".encode()
                self.wfile.write(hex(len(b))[2:].encode() + b"\r\n" + b + b"\r\n")
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n"); self.wfile.flush()
        except Exception:
            pass                      # the client hanging up mid-answer is the point


class _Quiet(ThreadingHTTPServer):
    """The client hanging up mid-answer is what this test does on purpose; the
    server need not print a traceback about it."""
    daemon_threads = True
    def handle_error(self, request, client_address): pass


class _StopAfter:
    """A stop button pressed once a few events have arrived."""
    def __init__(self, after): self.n, self.after = 0, after
    def is_set(self):
        self.n += 1
        return self.n > self.after


class TestCancelKeepsWhatWasWritten(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = _Quiet(("127.0.0.1", 0), _Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close()

    def stream(self, cancel):
        seen = []
        msg = providers.anthropic_stream(
            "claude-opus-5", [{"role": "user", "content": "hi"}], [], "test",
            emit=lambda kind, s: seen.append(s) if kind == "content_delta" else None,
            cancel=cancel, base_url=self.url)
        return msg, "".join(seen)

    def test_stopping_mid_answer_returns_what_was_written(self):
        msg, shown = self.stream(_StopAfter(5))
        self.assertTrue(shown, "nothing reached the screen; the test proves nothing")
        self.assertEqual(msg["content"], shown, "kept text differs from what was shown")

    def test_it_does_not_raise_at_the_reader(self):
        """The failure was a bare httpx ReadError out of a call site with no except."""
        try:
            self.stream(_StopAfter(3))
        except Exception as e:                                  # pragma: no cover
            self.fail(f"cancelling raised {type(e).__name__}: {e}")

    def test_a_turn_nobody_stops_still_finishes_normally(self):
        """The cancel path must not swallow the real ending."""
        msg, shown = self.stream(None)
        self.assertIn("chunk199", msg["content"])
        self.assertEqual(msg["content"], shown)
        self.assertIn("_usage", msg, "usage is only known from the final message")


if __name__ == "__main__":
    unittest.main()
