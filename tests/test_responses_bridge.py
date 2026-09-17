"""Codex's Responses API answered by other providers (bin/responses_bridge.py and the
gateway's /v1/responses route): requests in the shape Codex sends, streams back in the
shape Codex reads. A stand-in upstream, no network."""
import http.server, json, os, sys, threading, unittest, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin"))
import responses_bridge as RB          # noqa: E402
import harness_gateway as G            # noqa: E402

CODEX_BODY = {
    "model": "deepseek-v4-flash", "instructions": "You are a coding agent.",
    "input": [
        {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "<permissions>workspace-write</permissions>"}]},
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "list the files"}]},
        {"type": "reasoning", "id": "rs_1", "summary": [{"type": "summary_text", "text": "I should run ls"}],
         "content": [{"type": "reasoning_text", "text": "I should run ls"}]},
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Listing them."}]},
        {"type": "function_call", "call_id": "call_1", "name": "exec_command", "arguments": "{\"cmd\": \"ls\"}"},
        {"type": "function_call_output", "call_id": "call_1", "output": "a.txt\nb.txt"},
        {"type": "function_call", "call_id": "call_2", "name": "read_file", "namespace": "mcp__files", "arguments": "{\"path\":\"a.txt\""},
        {"type": "function_call_output", "call_id": "call_2", "output": [{"type": "input_text", "text": "hello"}]},
    ],
    "tools": [
        {"type": "function", "name": "exec_command", "description": "Run a command", "strict": False,
         "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}},
        {"type": "namespace", "name": "mcp__files", "description": "File server", "tools": [
            {"type": "function", "name": "read_file", "description": "Read", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}]},
        {"type": "web_search", "external_web_access": False},
    ],
    "tool_choice": "auto", "parallel_tool_calls": False, "reasoning": {"effort": "medium", "summary": "auto"},
    "store": False, "stream": True, "include": ["reasoning.encrypted_content"], "prompt_cache_key": "t1",
}


def sse_chat(chunks):
    return [("data: " + json.dumps(c) + "\n").encode() for c in chunks] + [b"data: [DONE]\n"]


def events(stream):
    out = []
    for chunk in stream:
        for line in chunk.decode().splitlines():
            if line.startswith("data:"): out.append(json.loads(line[5:]))
    return out


class TestRequests(unittest.TestCase):
    def test_codex_request_as_chat_completions(self):
        out, names = RB.responses_to_chat(CODEX_BODY)
        msgs = out["messages"]
        self.assertEqual(msgs[0]["role"], "system")
        self.assertIn("coding agent", msgs[0]["content"]); self.assertIn("permissions", msgs[0]["content"])
        self.assertEqual(msgs[1], {"role": "user", "content": "list the files"})
        a = msgs[2]
        self.assertEqual((a["role"], a["content"], a["reasoning_content"]), ("assistant", "Listing them.", "I should run ls"))
        self.assertEqual(a["tool_calls"][0]["function"], {"name": "exec_command", "arguments": "{\"cmd\": \"ls\"}"})
        self.assertEqual(msgs[3], {"role": "tool", "tool_call_id": "call_1", "content": "a.txt\nb.txt"})
        flat = msgs[4]["tool_calls"][0]["function"]
        self.assertEqual(flat["name"], "mcp__files__read_file")
        self.assertEqual(json.loads(flat["arguments"]), {"path": "a.txt"})          # repaired
        self.assertEqual(msgs[5]["content"], "hello")
        self.assertEqual([t["function"]["name"] for t in out["tools"]], ["exec_command", "mcp__files__read_file"])
        self.assertEqual(names, {"mcp__files__read_file": ("mcp__files", "read_file")})
        self.assertEqual(out["reasoning_effort"], "medium")
        self.assertTrue(out["stream"])
        self.assertNotIn("store", out); self.assertNotIn("include", out)

    def test_codex_request_as_anthropic_messages(self):
        out, names = RB.responses_to_messages(CODEX_BODY)
        self.assertIn("coding agent", out["system"])
        roles = [m["role"] for m in out["messages"]]
        self.assertEqual(roles, ["user", "assistant", "user", "assistant", "user"])
        a = out["messages"][1]["content"]
        self.assertEqual([b["type"] for b in a], ["text", "tool_use"])
        self.assertEqual(a[1]["input"], {"cmd": "ls"})
        self.assertEqual(out["messages"][3]["content"][0]["name"], "mcp__files__read_file")
        self.assertEqual(out["messages"][4]["content"][0], {"type": "tool_result", "tool_use_id": "call_2", "content": "hello"})
        self.assertEqual({t["name"] for t in out["tools"]}, {"exec_command", "mcp__files__read_file"})

    def test_for_other_responses_providers(self):
        out, names = RB.responses_for_provider(CODEX_BODY)
        self.assertEqual([t["name"] for t in out["tools"]], ["exec_command", "mcp__files__read_file"])
        self.assertTrue(all(t["type"] == "function" for t in out["tools"]))
        call2 = [i for i in out["input"] if i.get("call_id") == "call_2" and i["type"] == "function_call"][0]
        self.assertEqual(call2["name"], "mcp__files__read_file"); self.assertNotIn("namespace", call2)
        for k in ("include", "store", "prompt_cache_key"): self.assertNotIn(k, out)
        openai, _ = RB.responses_for_provider(CODEX_BODY, openai=True)
        self.assertEqual(openai["tools"], CODEX_BODY["tools"])


class TestStreams(unittest.TestCase):
    def test_chat_stream_to_responses_events(self):
        names = {"mcp__files__read_file": ("mcp__files", "read_file")}
        chunks = [
            {"choices": [{"delta": {"reasoning_content": "think "}}]},
            {"choices": [{"delta": {"reasoning_content": "more"}}]},
            {"choices": [{"delta": {"content": "Hello "}}]},
            {"choices": [{"delta": {"content": "there"}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "exec_command", "arguments": "{\"cmd\":"}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": " \"pwd\"}"}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c2", "function": {"name": "mcp__files__read_file", "arguments": "{\"path\":\"x\"}"}}]}}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
            {"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 20, "prompt_tokens_details": {"cached_tokens": 40}}},
        ]
        evs = events(RB.chat_stream_to_responses(sse_chat(chunks), "m", names))
        kinds = [e["type"] for e in evs]
        self.assertEqual(kinds[0], "response.created")
        self.assertEqual(kinds[-1], "response.completed")
        text = "".join(e["delta"] for e in evs if e["type"] == "response.output_text.delta")
        self.assertEqual(text, "Hello there")
        done = [e["item"] for e in evs if e["type"] == "response.output_item.done"]
        self.assertEqual([i["type"] for i in done], ["reasoning", "message", "function_call", "function_call"])
        self.assertEqual(done[0]["summary"][0]["text"], "think more")
        self.assertEqual((done[2]["call_id"], done[2]["name"], json.loads(done[2]["arguments"])), ("c1", "exec_command", {"cmd": "pwd"}))
        self.assertEqual((done[3]["name"], done[3]["namespace"]), ("read_file", "mcp__files"))       # two calls at index 0, kept apart
        final = evs[-1]["response"]
        self.assertEqual(final["usage"]["input_tokens"], 100)
        self.assertEqual(final["usage"]["input_tokens_details"]["cached_tokens"], 40)
        self.assertEqual(len(final["output"]), 4)
        # and what Codex sends back next time reads the same
        again, _ = RB.responses_to_chat({"input": [{"type": "message", "role": "user", "content": "go"}] + final["output"]})
        self.assertEqual(again["messages"][1]["reasoning_content"], "think more")
        self.assertEqual(len(again["messages"][1]["tool_calls"]), 2)

    def test_messages_stream_to_responses_events(self):
        lines = [("data: " + json.dumps(e) + "\n").encode() for e in [
            {"type": "message_start", "message": {"usage": {"input_tokens": 50, "cache_read_input_tokens": 10}}},
            {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "hmm"}},
            {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "ok"}},
            {"type": "content_block_start", "index": 2, "content_block": {"type": "tool_use", "id": "tu1", "name": "exec_command"}},
            {"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": "{\"cmd\":\"ls\"}"}},
            {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 7}},
            {"type": "message_stop"}]]
        evs = events(RB.messages_stream_to_responses(lines, "m"))
        done = [e["item"] for e in evs if e["type"] == "response.output_item.done"]
        self.assertEqual([i["type"] for i in done], ["reasoning", "message", "function_call"])
        self.assertEqual(done[2]["call_id"], "tu1")
        self.assertEqual(evs[-1]["response"]["usage"]["output_tokens"], 7)
        self.assertEqual(evs[-1]["response"]["usage"]["input_tokens"], 60)

    def test_errors_become_a_failed_response(self):
        evs = events(RB.chat_stream_to_responses(sse_chat([{"error": {"message": "quota"}}]), "m"))
        self.assertEqual(evs[-1]["type"], "response.failed")
        self.assertIn("quota", evs[-1]["response"]["error"]["message"])

    def test_parallel_calls_all_numbered_zero_keep_their_own_arguments(self):
        chunks = [
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "a", "function": {"name": "exec_command", "arguments": "{\"cmd\":"}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": " \"ls\"}"}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "b", "function": {"name": "exec_command", "arguments": "{\"cmd\":"}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": " \"pwd\"}"}}]}}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}]
        done = [e["item"] for e in events(RB.chat_stream_to_responses(sse_chat(chunks), "m")) if e["type"] == "response.output_item.done"]
        self.assertEqual([(i["call_id"], json.loads(i["arguments"])) for i in done],
                         [("a", {"cmd": "ls"}), ("b", {"cmd": "pwd"})])


class TestGatewayRoute(unittest.TestCase):
    def test_codex_through_the_gateway_to_a_chat_provider(self):
        seen = {}
        class Up(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_POST(self):
                seen["path"] = self.path
                seen["auth"] = self.headers.get("authorization")
                seen["session"] = self.headers.get("x-opencode-session")
                seen["body"] = json.loads(self.rfile.read(int(self.headers["content-length"])))
                self.send_response(200); self.send_header("content-type", "text/event-stream"); self.end_headers()
                for c in [{"choices": [{"delta": {"content": "hi from upstream"}}]},
                          {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 3, "completion_tokens": 4}}]:
                    self.wfile.write(("data: " + json.dumps(c) + "\n\n").encode())
                self.wfile.write(b"data: [DONE]\n\n")
        up = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Up)
        threading.Thread(target=up.serve_forever, daemon=True).start()
        self.addCleanup(up.shutdown)
        usage = []
        route = {"format": "chat", "base": f"http://127.0.0.1:{up.server_port}/v1", "api_key": "sk-upstream"}
        gw = G.serve(0, lambda pid, model: route if pid == "prov" else None, token="orbit-tok",
                     hooks={"usage": lambda *a: usage.append(a)})
        self.addCleanup(gw.shutdown)
        url = f"http://127.0.0.1:{gw.server_port}/h/prov/v1/responses"
        body = json.dumps(CODEX_BODY).encode()
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(urllib.request.Request(url, data=body, headers={"content-type": "application/json"}))
        self.assertEqual(cm.exception.code, 401)
        req = urllib.request.Request(url, data=body, headers={"content-type": "application/json", "authorization": "Bearer orbit-tok",
                                                              "session-id": "thread-123"})
        evs = events([urllib.request.urlopen(req).read()])
        self.assertEqual(seen["path"], "/v1/chat/completions")
        self.assertEqual(seen["auth"], "Bearer sk-upstream")
        self.assertEqual(seen["session"], "thread-123")
        self.assertEqual(evs[-1]["type"], "response.completed")
        self.assertEqual("".join(e["delta"] for e in evs if e["type"] == "response.output_text.delta"), "hi from upstream")
        self.assertEqual(usage[0][3]["output_tokens"], 4)
        models = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{gw.server_port}/h/prov/v1/models?client_version=1").read())
        self.assertEqual(models, {"models": []})


if __name__ == "__main__":
    unittest.main()
