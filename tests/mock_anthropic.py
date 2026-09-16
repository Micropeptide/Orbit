"""A scripted stand-in for the Anthropic Messages API, for testing Orbit's
Claude Code engine without a model.

    python mock_anthropic.py PORT SCRIPT.json LOG.jsonl

SCRIPT is a list of replies to the harness's main requests (the ones that
offer tools), in order. Each reply is a list of blocks:

    {"thinking": "..."}  {"text": "..."}  {"tool_use": {"name": "Write", "input": {...}}}
    {"sleep": 2.5}       -- pause the stream here (to test stopping mid-answer)

Side requests (titles, summaries: no tools offered) get a short text reply.
Every request body is appended to LOG, one JSON object per line.
"""
import http.server, json, sys, threading, time, uuid

PORT, SCRIPT, LOG = int(sys.argv[1]), sys.argv[2], sys.argv[3]
lock = threading.Lock()
state = {"main": 0}


def sse(w, event, data):
    w.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode())
    w.flush()


class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps({"data": [{"id": "mock-model", "type": "model"}]}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        req = json.loads(self.rfile.read(n) or b"{}")
        with lock:
            with open(LOG, "a") as f:
                f.write(json.dumps({"path": self.path, "body": req}) + "\n")
        if "count_tokens" in self.path:
            body = json.dumps({"input_tokens": 100}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        main = bool(req.get("tools"))
        if main:
            with lock:
                script = json.load(open(SCRIPT))
                i = state["main"]
                state["main"] += 1
            blocks = script[i] if i < len(script) else [{"text": "(script exhausted)"}]
        else:
            blocks = [{"text": "Mock title"}]
        if not req.get("stream"):
            content = [{"type": "text", "text": b["text"]} for b in blocks if "text" in b]
            body = json.dumps({"id": "msg_" + uuid.uuid4().hex, "type": "message",
                               "role": "assistant", "model": req.get("model"),
                               "content": content, "stop_reason": "end_turn",
                               "usage": {"input_tokens": 10, "output_tokens": 5}}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.send_header("connection", "close")
        self.end_headers()
        w = self.wfile
        try:
            sse(w, "message_start", {"type": "message_start", "message": {
                "id": "msg_" + uuid.uuid4().hex, "type": "message", "role": "assistant",
                "model": req.get("model"), "content": [], "stop_reason": None,
                "usage": {"input_tokens": 1234, "output_tokens": 1,
                          "cache_read_input_tokens": 1000}}})
            idx, stop = 0, "end_turn"
            for b in blocks:
                if "sleep" in b:
                    time.sleep(float(b["sleep"]))
                    continue
                if "thinking" in b:
                    sse(w, "content_block_start", {"type": "content_block_start", "index": idx,
                        "content_block": {"type": "thinking", "thinking": "", "signature": ""}})
                    for chunk in _chunks(b["thinking"]):
                        sse(w, "content_block_delta", {"type": "content_block_delta", "index": idx,
                            "delta": {"type": "thinking_delta", "thinking": chunk}})
                    sse(w, "content_block_delta", {"type": "content_block_delta", "index": idx,
                        "delta": {"type": "signature_delta", "signature": "sig"}})
                elif "text" in b:
                    sse(w, "content_block_start", {"type": "content_block_start", "index": idx,
                        "content_block": {"type": "text", "text": ""}})
                    for chunk in _chunks(b["text"]):
                        sse(w, "content_block_delta", {"type": "content_block_delta", "index": idx,
                            "delta": {"type": "text_delta", "text": chunk}})
                elif "tool_use" in b:
                    tu = b["tool_use"]
                    sse(w, "content_block_start", {"type": "content_block_start", "index": idx,
                        "content_block": {"type": "tool_use", "id": "toolu_" + uuid.uuid4().hex[:20],
                                          "name": tu["name"], "input": {}}})
                    sse(w, "content_block_delta", {"type": "content_block_delta", "index": idx,
                        "delta": {"type": "input_json_delta",
                                  "partial_json": json.dumps(tu.get("input") or {})}})
                    stop = "tool_use"
                sse(w, "content_block_stop", {"type": "content_block_stop", "index": idx})
                idx += 1
            sse(w, "message_delta", {"type": "message_delta",
                "delta": {"stop_reason": stop, "stop_sequence": None},
                "usage": {"output_tokens": 42}})
            sse(w, "message_stop", {"type": "message_stop"})
        except (BrokenPipeError, ConnectionResetError):
            pass


def _chunks(s, n=12):
    return [s[i:i + n] for i in range(0, len(s), n)] or [""]


class Srv(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    Srv(("127.0.0.1", PORT), H).serve_forever()
