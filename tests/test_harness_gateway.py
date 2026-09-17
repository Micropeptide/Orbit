"""Orbit's Anthropic <-> OpenAI gateway (bin/harness_gateway.py)."""
import http.server, json, os, sys, threading, time, unittest, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin"))
import harness_gateway as G           # noqa: E402


def sse_events(raw):
    out = []
    for block in raw.decode().split("\n\n"):
        ev = dict(l.split(": ", 1) for l in block.splitlines() if ": " in l)
        if "data" in ev: out.append((ev.get("event"), json.loads(ev["data"])))
    return out


class Upstream(http.server.BaseHTTPRequestHandler):
    """A scripted OpenAI chat-completions (and Anthropic passthrough) server."""
    script = []
    seen = []
    def log_message(self, *a): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        Upstream.seen.append({"path": self.path, "body": body, "headers": dict(self.headers)})
        reply = Upstream.script.pop(0)
        if reply.get("status"):
            data = json.dumps(reply["error"]).encode()
            self.send_response(reply["status"]); self.send_header("content-length", str(len(data)))
            self.end_headers(); self.wfile.write(data); return
        if "raw" in reply:
            data = reply["raw"].encode()
            self.send_response(200); self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(data))); self.end_headers(); self.wfile.write(data); return
        if not body.get("stream"):
            data = json.dumps(reply["json"]).encode()
            self.send_response(200); self.send_header("content-length", str(len(data)))
            self.end_headers(); self.wfile.write(data); return
        self.send_response(200); self.send_header("content-type", "text/event-stream"); self.end_headers()
        for ch in reply["chunks"]:
            self.wfile.write(f"data: {json.dumps(ch)}\n\n".encode()); self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")


def delta(**d):
    return {"id": "c1", "choices": [{"index": 0, "delta": d, "finish_reason": None}]}


class TestTranslate(unittest.TestCase):
    def test_request_with_a_tool_loop(self):
        body = {
            "model": "deepseek-v4-pro", "max_tokens": 4000, "stream": True,
            "system": [{"type": "text", "text": "You are Claude Code."}],
            "tools": [{"name": "Read", "description": "read", "input_schema": {"type": "object"}}],
            "tool_choice": {"type": "auto"},
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "read a.txt"},
                                             {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAA"}}]},
                {"role": "assistant", "content": [{"type": "thinking", "thinking": "I should read it", "signature": "s"},
                                                  {"type": "text", "text": "Reading."},
                                                  {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "a.txt"}}]},
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "hello"}]},
                                             {"type": "text", "text": "and?"}]},
            ]}
        o = G.to_openai(body)
        self.assertEqual(o["messages"][0], {"role": "system", "content": "You are Claude Code."})
        self.assertEqual(o["messages"][1]["content"][1]["image_url"]["url"], "data:image/png;base64,AAA")
        a = o["messages"][2]
        self.assertEqual(a["content"], "Reading.")
        self.assertEqual(a["reasoning_content"], "I should read it")
        self.assertEqual(a["tool_calls"][0]["function"], {"name": "Read", "arguments": '{"file_path": "a.txt"}'})
        self.assertEqual(o["messages"][3], {"role": "tool", "tool_call_id": "t1", "content": "hello"})
        self.assertEqual(o["messages"][4]["role"], "user")
        self.assertEqual(o["tools"][0]["function"]["name"], "Read")
        self.assertEqual(o["tool_choice"], "auto")
        self.assertTrue(o["stream"]); self.assertEqual(o["stream_options"], {"include_usage": True})

    def test_streamed_thinking_text_and_two_tools(self):
        chunks = [delta(role="assistant"), delta(reasoning_content="Let me "), delta(reasoning_content="think."),
                  delta(content="Doing it."),
                  delta(tool_calls=[{"index": 0, "id": "call_a", "type": "function", "function": {"name": "Read", "arguments": ""}}]),
                  delta(tool_calls=[{"index": 0, "function": {"arguments": "{\"file_path\":"}}]),
                  delta(tool_calls=[{"index": 0, "function": {"arguments": " \"a\"}"}}]),
                  delta(tool_calls=[{"index": 1, "id": "call_b", "type": "function", "function": {"name": "Bash", "arguments": "{}"}}]),
                  {"id": "c1", "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
                  {"id": "c1", "choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                                                         "prompt_tokens_details": {"cached_tokens": 60}}}]
        lines = [f"data: {json.dumps(c)}".encode() for c in chunks] + [b"data: [DONE]"]
        evs = sse_events(b"".join(G.stream_to_anthropic(iter(lines), "deepseek-v4-pro")))
        kinds = [e for e, _ in evs]
        self.assertEqual(kinds[0], "message_start")
        starts = [d["content_block"] for e, d in evs if e == "content_block_start"]
        self.assertEqual([s["type"] for s in starts], ["thinking", "text", "tool_use", "tool_use"])
        self.assertEqual((starts[2]["id"], starts[2]["name"]), ("call_a", "Read"))
        args = "".join(d["delta"]["partial_json"] for e, d in evs
                       if e == "content_block_delta" and d["delta"]["type"] == "input_json_delta" and d["index"] == 2)
        self.assertEqual(json.loads(args), {"file_path": "a"})
        md = next(d for e, d in evs if e == "message_delta")
        self.assertEqual(md["delta"]["stop_reason"], "tool_use")
        self.assertEqual(md["usage"]["output_tokens"], 20)
        self.assertEqual(md["usage"]["input_tokens"], 40)
        self.assertEqual(md["usage"]["cache_read_input_tokens"], 60)
        self.assertEqual(kinds[-1], "message_stop")
        # every started block is stopped
        self.assertEqual(kinds.count("content_block_start"), kinds.count("content_block_stop"))

    def test_whole_completion(self):
        obj = {"id": "x", "choices": [{"message": {"content": "hi", "reasoning_content": "hm",
                                                   "tool_calls": [{"id": "c", "function": {"name": "Read", "arguments": "{\"a\":1}"}}]},
                                       "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 5, "completion_tokens": 2}}
        m = G.complete_to_anthropic(obj, "m")
        self.assertEqual([b["type"] for b in m["content"]], ["thinking", "text", "tool_use"])
        self.assertEqual(m["content"][2]["input"], {"a": 1})
        self.assertEqual(m["stop_reason"], "tool_use")


class TestResponses(unittest.TestCase):
    def test_request_and_stream(self):
        body = {"model": "gpt-5.6-luna", "max_tokens": 100, "stream": True, "system": "sys",
                "tools": [{"name": "Bash", "input_schema": {"type": "object"}}],
                "messages": [{"role": "user", "content": "run ls"},
                             {"role": "assistant", "content": [{"type": "tool_use", "id": "c1", "name": "Bash", "input": {"command": "ls"}}]},
                             {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "a.txt"}]}]}
        r = G.to_responses(body)
        self.assertEqual(r["instructions"], "sys")
        self.assertEqual([i.get("type") or i.get("role") for i in r["input"]], ["user", "function_call", "function_call_output"])
        self.assertEqual(r["tools"][0]["name"], "Bash"); self.assertEqual(r["max_output_tokens"], 100)
        evs = [{"type": "response.reasoning_summary_text.delta", "delta": "hmm"},
               {"type": "response.output_text.delta", "delta": "Here."},
               {"type": "response.output_item.added", "output_index": 2, "item": {"type": "function_call", "id": "fc1", "call_id": "call_9", "name": "Read", "arguments": ""}},
               {"type": "response.function_call_arguments.delta", "item_id": "fc1", "delta": "{\"file_path\": \"a\"}"},
               {"type": "response.completed", "response": {"usage": {"input_tokens": 50, "output_tokens": 7}}}]
        out = sse_events(b"".join(G.responses_stream_to_anthropic(iter([f"data: {json.dumps(e)}".encode() for e in evs]), "gpt")))
        starts = [d["content_block"]["type"] for e, d in out if e == "content_block_start"]
        self.assertEqual(starts, ["thinking", "text", "tool_use"])
        md = next(d for e, d in out if e == "message_delta")
        self.assertEqual((md["delta"]["stop_reason"], md["usage"]["output_tokens"]), ("tool_use", 7))


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.up = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        threading.Thread(target=cls.up.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{cls.up.server_address[1]}/v1"
        def resolver(provider, model):
            if provider != "p": return None
            fmt = "messages" if model.startswith("claude") else "chat"
            return {"base": base, "format": fmt, "api_key": "sk-upstream"}
        cls.gw = G.serve(0, resolver)
        cls.url = f"http://127.0.0.1:{cls.gw.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.gw.shutdown(); cls.up.shutdown()

    def post(self, path, body, headers=None):
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode(),
                                     headers={"content-type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_chat_model_is_translated_and_keyed(self):
        Upstream.seen.clear()
        Upstream.script = [{"chunks": [delta(content="Hello"), {"id": "c", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}]}]
        code, raw = self.post("/h/p/v1/messages", {"model": "deepseek-v4-pro", "max_tokens": 10, "stream": True,
                                                   "messages": [{"role": "user", "content": "hi"}]},
                              {"x-api-key": "from-claude-ignored"})
        self.assertEqual(code, 200)
        text = "".join(d["delta"].get("text", "") for e, d in sse_events(raw) if e == "content_block_delta")
        self.assertEqual(text, "Hello")
        s = Upstream.seen[-1]
        self.assertEqual(s["path"], "/v1/chat/completions")
        self.assertEqual(s["headers"].get("Authorization"), "Bearer sk-upstream")
        self.assertEqual(s["body"]["model"], "deepseek-v4-pro")

    def test_messages_model_passes_through_with_the_key(self):
        Upstream.seen.clear()
        Upstream.script = [{"raw": "event: message_stop\ndata: {\"type\":\"message_stop\"}\n\n"}]
        code, raw = self.post("/h/p/v1/messages", {"model": "claude-x", "max_tokens": 5, "stream": True,
                                                   "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(code, 200)
        self.assertIn(b"message_stop", raw)
        s = Upstream.seen[-1]
        self.assertEqual(s["path"], "/v1/messages")
        self.assertEqual(s["headers"].get("X-Api-Key") or s["headers"].get("x-api-key"), "sk-upstream")

    def test_upstream_errors_keep_their_meaning(self):
        Upstream.script = [{"status": 429, "error": {"error": {"message": "slow down"}}}]
        code, raw = self.post("/h/p/v1/messages", {"model": "deepseek-v4-pro", "max_tokens": 5, "stream": True,
                                                   "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(code, 429)
        err = json.loads(raw)
        self.assertEqual(err["error"]["type"], "rate_limit_error")
        self.assertIn("slow down", err["error"]["message"])

    def test_unknown_provider_and_token_count(self):
        code, raw = self.post("/h/nope/v1/messages", {"model": "x", "messages": []})
        self.assertEqual(code, 404)
        code, raw = self.post("/h/p/v1/messages/count_tokens", {"model": "x", "messages": [{"role": "user", "content": "a" * 400}]})
        self.assertEqual(code, 200)
        self.assertGreater(json.loads(raw)["input_tokens"], 50)

    def test_loopback_only(self):
        self.assertEqual(self.gw.server_address[0], "127.0.0.1")

    def test_a_token_keeps_other_programs_out(self):
        gw = G.serve(0, lambda p, m: {"base": "http://127.0.0.1:1/v1", "format": "chat", "api_key": "k"}, token="tok-123")
        self.addCleanup(gw.shutdown)
        url = f"http://127.0.0.1:{gw.server_address[1]}/h/p/v1/messages"
        body = json.dumps({"model": "m", "max_tokens": 5, "messages": [{"role": "user", "content": "hi"}]}).encode()
        for headers, want in (({}, 401), ({"authorization": "Bearer wrong"}, 401)):
            req = urllib.request.Request(url, data=body, headers={"content-type": "application/json", **headers})
            try:
                urllib.request.urlopen(req, timeout=5); code = 200
            except urllib.error.HTTPError as e:
                code = e.code
            self.assertEqual(code, want, headers)
        # the right token gets past the check (the upstream here is unreachable: 502)
        req = urllib.request.Request(url, data=body, headers={"content-type": "application/json", "x-api-key": "tok-123"})
        try:
            urllib.request.urlopen(req, timeout=10); code = 200
        except urllib.error.HTTPError as e:
            code = e.code
        self.assertEqual(code, 502)


if __name__ == "__main__":
    unittest.main()
