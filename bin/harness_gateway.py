"""Orbit's gateway: Claude Code's Messages API, answered by any model.

Claude Code sends Anthropic Messages requests to
    http://127.0.0.1:<port>/h/<provider>/v1/messages
and the gateway, according to the model's format:

- "messages":  forwards the request to the provider as is, adding the key;
- "chat":      translates to OpenAI chat completions and the streamed answer
               back into Messages events (text, thinking, tool use, usage);
- "responses": the same for OpenAI's Responses API.

It listens on loopback only. Keys come from the resolver (Orbit's secrets) and
are never seen by the Claude process. Standard library only.
"""
import http.server, json, re, socket, ssl, threading, time, urllib.error, urllib.parse, urllib.request, uuid

STOP = {"stop": "end_turn", "tool_calls": "tool_use", "function_call": "tool_use", "length": "max_tokens",
        "content_filter": "refusal"}
ERROR_TYPES = {400: "invalid_request_error", 401: "authentication_error", 403: "permission_error",
               404: "not_found_error", 413: "request_too_large", 429: "rate_limit_error",
               500: "api_error", 502: "api_error", 503: "overloaded_error", 529: "overloaded_error"}


# ------------------------------------------------------------------ requests

def _text_of(content):
    if isinstance(content, str): return content
    out = []
    for b in content or []:
        if isinstance(b, dict):
            if b.get("type") == "text": out.append(b.get("text") or "")
            elif b.get("type") == "image": out.append("[image]")
    return "\n".join(out)


def _image_url(b):
    src = b.get("source") or {}
    if src.get("type") == "base64":
        return f"data:{src.get('media_type')};base64,{src.get('data')}"
    return src.get("url") or ""


def to_openai(body):
    """An Anthropic Messages request as an OpenAI chat-completions request."""
    msgs = []
    sys_ = body.get("system")
    if sys_:
        msgs.append({"role": "system", "content": _text_of(sys_) if not isinstance(sys_, str) else sys_})
    for m in body.get("messages") or []:
        role, content = m.get("role"), m.get("content")
        if isinstance(content, str):
            msgs.append({"role": role, "content": content})
            continue
        if role == "assistant":
            text, think, calls = [], [], []
            for b in content or []:
                t = b.get("type")
                if t == "text": text.append(b.get("text") or "")
                elif t in ("thinking", "redacted_thinking"): think.append(b.get("thinking") or "")
                elif t == "tool_use":
                    calls.append({"id": b.get("id"), "type": "function",
                                  "function": {"name": b.get("name"), "arguments": json.dumps(b.get("input") or {})}})
            a = {"role": "assistant", "content": "".join(text) or (None if calls else "")}
            # reasoning models (DeepSeek) want their own reasoning back within a tool loop
            if think: a["reasoning_content"] = "".join(think)
            if calls: a["tool_calls"] = calls
            msgs.append(a)
            continue
        parts, tool_msgs = [], []
        for b in content or []:
            t = b.get("type")
            if t == "tool_result":
                txt = _text_of(b.get("content"))
                if b.get("is_error"): txt = "Error: " + txt
                tool_msgs.append({"role": "tool", "tool_call_id": b.get("tool_use_id"), "content": txt})
            elif t == "text":
                parts.append({"type": "text", "text": b.get("text") or ""})
            elif t == "image":
                parts.append({"type": "image_url", "image_url": {"url": _image_url(b)}})
            elif t == "document":
                parts.append({"type": "text", "text": "[a document was attached; this model cannot read it]"})
        msgs.extend(tool_msgs)                       # tool results follow the call that made them
        if parts:
            if all(p["type"] == "text" for p in parts):
                msgs.append({"role": "user", "content": "\n".join(p["text"] for p in parts)} if len(parts) == 1
                            else {"role": "user", "content": parts})
            else:
                msgs.append({"role": "user", "content": parts})
    out = {"model": body.get("model"), "messages": msgs, "stream": bool(body.get("stream"))}
    if body.get("max_tokens"): out["max_tokens"] = body["max_tokens"]
    for k in ("temperature", "top_p"):
        if body.get(k) is not None: out[k] = body[k]
    if body.get("stop_sequences"): out["stop"] = body["stop_sequences"]
    if body.get("tools"):
        out["tools"] = [{"type": "function", "function": {"name": t.get("name"), "description": t.get("description") or "",
                                                          "parameters": t.get("input_schema") or {"type": "object"}}}
                        for t in body["tools"] if t.get("name")]
        tc = body.get("tool_choice") or {}
        if tc.get("type") == "any": out["tool_choice"] = "required"
        elif tc.get("type") == "tool": out["tool_choice"] = {"type": "function", "function": {"name": tc.get("name")}}
        elif tc.get("type") == "none": out["tool_choice"] = "none"
        else: out["tool_choice"] = "auto"
    if out["stream"]: out["stream_options"] = {"include_usage": True}
    return out


def to_responses(body):
    """An Anthropic Messages request as an OpenAI Responses request."""
    items = []
    for m in body.get("messages") or []:
        role, content = m.get("role"), m.get("content")
        if isinstance(content, str):
            items.append({"role": role, "content": [{"type": "input_text" if role == "user" else "output_text",
                                                     "text": content}]})
            continue
        parts = []
        for b in content or []:
            t = b.get("type")
            if t == "text":
                parts.append({"type": "input_text" if role == "user" else "output_text", "text": b.get("text") or ""})
            elif t == "image" and role == "user":
                parts.append({"type": "input_image", "image_url": _image_url(b)})
            elif t == "tool_use":
                if parts: items.append({"role": role, "content": parts}); parts = []
                items.append({"type": "function_call", "call_id": b.get("id"), "name": b.get("name"),
                              "arguments": json.dumps(b.get("input") or {})})
            elif t == "tool_result":
                items.append({"type": "function_call_output", "call_id": b.get("tool_use_id"),
                              "output": _text_of(b.get("content"))})
        if parts: items.append({"role": role, "content": parts})
    out = {"model": body.get("model"), "input": items, "stream": bool(body.get("stream"))}
    if body.get("system"): out["instructions"] = _text_of(body["system"]) if not isinstance(body["system"], str) else body["system"]
    if body.get("max_tokens"): out["max_output_tokens"] = body["max_tokens"]
    if body.get("tools"):
        out["tools"] = [{"type": "function", "name": t.get("name"), "description": t.get("description") or "",
                         "parameters": t.get("input_schema") or {"type": "object"}} for t in body["tools"] if t.get("name")]
    return out


# ------------------------------------------------------------------ answers

def _sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


def _usage(u):
    u = u or {}
    cached = ((u.get("prompt_tokens_details") or u.get("input_tokens_details") or {}).get("cached_tokens")) or 0
    prompt = u.get("prompt_tokens", u.get("input_tokens")) or 0
    return {"input_tokens": max(0, prompt - cached), "output_tokens": u.get("completion_tokens", u.get("output_tokens")) or 0,
            "cache_read_input_tokens": cached, "cache_creation_input_tokens": 0}


class _Blocks:
    """Keeps the Messages content blocks of one streamed answer in order."""

    def __init__(self, model):
        self.model, self.idx, self.open = model, -1, None
        self.tools = {}              # upstream tool index -> our block index

    def start(self):
        yield _sse("message_start", {"type": "message_start", "message": {
            "id": "msg_" + uuid.uuid4().hex, "type": "message", "role": "assistant", "model": self.model,
            "content": [], "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0}}})

    def close(self):
        if self.open is None: return
        if self.open == "thinking":
            yield _sse("content_block_delta", {"type": "content_block_delta", "index": self.idx,
                                               "delta": {"type": "signature_delta", "signature": ""}})
        yield _sse("content_block_stop", {"type": "content_block_stop", "index": self.idx})
        self.open = None

    def begin(self, kind, block):
        yield from self.close()
        self.idx += 1
        self.open = kind
        yield _sse("content_block_start", {"type": "content_block_start", "index": self.idx, "content_block": block})

    def thinking(self, text):
        if self.open != "thinking":
            yield from self.begin("thinking", {"type": "thinking", "thinking": "", "signature": ""})
        yield _sse("content_block_delta", {"type": "content_block_delta", "index": self.idx,
                                           "delta": {"type": "thinking_delta", "thinking": text}})

    def text(self, text):
        if self.open != "text":
            yield from self.begin("text", {"type": "text", "text": ""})
        yield _sse("content_block_delta", {"type": "content_block_delta", "index": self.idx,
                                           "delta": {"type": "text_delta", "text": text}})

    def tool(self, key, cid=None, name=None, args=""):
        if key not in self.tools:
            yield from self.begin("tool", {"type": "tool_use", "id": cid or ("toolu_" + uuid.uuid4().hex[:20]),
                                           "name": name or "", "input": {}})
            self.tools[key] = self.idx
        if args:
            yield _sse("content_block_delta", {"type": "content_block_delta", "index": self.tools[key],
                                               "delta": {"type": "input_json_delta", "partial_json": args}})

    def finish(self, stop, usage):
        yield from self.close()
        yield _sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None},
                                     "usage": usage})
        yield _sse("message_stop", {"type": "message_stop"})


def _data_lines(lines):
    for raw in lines:
        line = raw.decode("utf-8", "replace").strip() if isinstance(raw, bytes) else str(raw).strip()
        if not line.startswith("data:"): continue
        data = line[5:].strip()
        if data == "[DONE]": return
        try: yield json.loads(data)
        except ValueError: continue


def stream_to_anthropic(lines, model):
    """OpenAI chat-completions stream lines -> Messages SSE bytes."""
    b = _Blocks(model)
    yield from b.start()
    stop, usage = "end_turn", {"input_tokens": 0, "output_tokens": 0}
    for ch in _data_lines(lines):
        if ch.get("usage"): usage = _usage(ch["usage"])
        if ch.get("error"):
            yield from b.text(f"\n[model error: {ch['error'].get('message') if isinstance(ch['error'], dict) else ch['error']}]")
        for c in ch.get("choices") or []:
            d = c.get("delta") or {}
            r = d.get("reasoning_content") or d.get("reasoning")
            if r: yield from b.thinking(r)
            if d.get("content"): yield from b.text(d["content"])
            for tc in d.get("tool_calls") or []:
                fn = tc.get("function") or {}
                yield from b.tool(tc.get("index", 0), tc.get("id"), fn.get("name"), fn.get("arguments") or "")
            if c.get("finish_reason"): stop = STOP.get(c["finish_reason"], "end_turn")
    if b.tools and stop == "end_turn": stop = "tool_use"
    yield from b.finish(stop, usage)


def responses_stream_to_anthropic(lines, model):
    """OpenAI Responses stream lines -> Messages SSE bytes."""
    b = _Blocks(model)
    yield from b.start()
    stop, usage = "end_turn", {"input_tokens": 0, "output_tokens": 0}
    for ev in _data_lines(lines):
        t = ev.get("type") or ""
        if t in ("response.reasoning_summary_text.delta", "response.reasoning_text.delta"):
            yield from b.thinking(ev.get("delta") or "")
        elif t == "response.output_text.delta":
            yield from b.text(ev.get("delta") or "")
        elif t == "response.output_item.added" and (ev.get("item") or {}).get("type") == "function_call":
            it = ev["item"]
            yield from b.tool(it.get("id") or ev.get("output_index"), it.get("call_id"), it.get("name"), it.get("arguments") or "")
        elif t == "response.function_call_arguments.delta":
            yield from b.tool(ev.get("item_id") or ev.get("output_index"), args=ev.get("delta") or "")
        elif t in ("response.completed", "response.incomplete"):
            resp = ev.get("response") or {}
            usage = _usage(resp.get("usage"))
            if t == "response.incomplete": stop = "max_tokens"
        elif t in ("response.failed", "error"):
            msg = ((ev.get("response") or {}).get("error") or ev.get("error") or {})
            yield from b.text(f"\n[model error: {msg.get('message') if isinstance(msg, dict) else msg}]")
    if b.tools and stop == "end_turn": stop = "tool_use"
    yield from b.finish(stop, usage)


def complete_to_anthropic(obj, model):
    """A whole (non-streamed) chat completion as a Messages response."""
    c = (obj.get("choices") or [{}])[0]
    m = c.get("message") or {}
    content = []
    if m.get("reasoning_content") or m.get("reasoning"):
        content.append({"type": "thinking", "thinking": m.get("reasoning_content") or m.get("reasoning"), "signature": ""})
    if m.get("content"):
        content.append({"type": "text", "text": m["content"]})
    for tc in m.get("tool_calls") or []:
        fn = tc.get("function") or {}
        try: args = json.loads(fn.get("arguments") or "{}")
        except ValueError: args = {"_raw": fn.get("arguments")}
        content.append({"type": "tool_use", "id": tc.get("id") or ("toolu_" + uuid.uuid4().hex[:20]),
                        "name": fn.get("name"), "input": args})
    stop = STOP.get(c.get("finish_reason") or "stop", "end_turn")
    if any(x["type"] == "tool_use" for x in content): stop = "tool_use"
    return {"id": "msg_" + uuid.uuid4().hex, "type": "message", "role": "assistant", "model": model,
            "content": content, "stop_reason": stop, "stop_sequence": None, "usage": _usage(obj.get("usage"))}


def responses_complete_to_anthropic(obj, model):
    content = []
    for it in obj.get("output") or []:
        if it.get("type") == "reasoning":
            txt = "".join(s.get("text", "") for s in it.get("summary") or [])
            if txt: content.append({"type": "thinking", "thinking": txt, "signature": ""})
        elif it.get("type") == "message":
            txt = "".join(p.get("text", "") for p in it.get("content") or [] if p.get("type") == "output_text")
            if txt: content.append({"type": "text", "text": txt})
        elif it.get("type") == "function_call":
            try: args = json.loads(it.get("arguments") or "{}")
            except ValueError: args = {}
            content.append({"type": "tool_use", "id": it.get("call_id"), "name": it.get("name"), "input": args})
    stop = "tool_use" if any(x["type"] == "tool_use" for x in content) else "end_turn"
    return {"id": "msg_" + uuid.uuid4().hex, "type": "message", "role": "assistant", "model": model,
            "content": content, "stop_reason": stop, "stop_sequence": None, "usage": _usage(obj.get("usage"))}


def estimate_tokens(body):
    return max(1, len(json.dumps({k: body.get(k) for k in ("system", "messages", "tools")})) // 4)


# ------------------------------------------------------------------ the server

STATS = {"requests": 0, "errors": 0, "by_provider": {}, "last": None}


def _error(handler, status, message, etype=None):
    data = json.dumps({"type": "error", "error": {"type": etype or ERROR_TYPES.get(status, "api_error"),
                                                  "message": message}}).encode()
    handler.send_response(status)
    handler.send_header("content-type", "application/json")
    handler.send_header("content-length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _opener(proxy):
    handlers = [urllib.request.ProxyHandler({"http": proxy, "https": proxy} if proxy else {})]
    return urllib.request.build_opener(*handlers)


def make_handler(resolver, log=None, token=None):
    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.rstrip("/") in ("", "/health"):
                data = json.dumps({"ok": True, "stats": STATS}).encode()
                self.send_response(200); self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data))); self.end_headers(); self.wfile.write(data)
                return
            _error(self, 404, "not found")

        def do_POST(self):
            m = re.match(r"^/h/([A-Za-z0-9_.-]+)/v1/messages(/count_tokens)?(\?.*)?$", self.path)
            if not m:
                self.close_connection = True
                return _error(self, 404, f"unknown path {self.path}")
            provider, counting = m.group(1), bool(m.group(2))
            if token:
                # only Orbit's own Claude runs may spend your keys: they carry this token
                got = (self.headers.get("authorization") or "").removeprefix("Bearer ").strip() \
                    or (self.headers.get("x-api-key") or "").strip()
                if not _same(got, token):
                    self.close_connection = True
                    return _error(self, 401, "Orbit's gateway needs Orbit's token (this request did not come from Orbit).")
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
            except ValueError:
                self.close_connection = True
                return _error(self, 400, "request body is not JSON")
            if counting:
                data = json.dumps({"input_tokens": estimate_tokens(body)}).encode()
                self.send_response(200); self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data))); self.end_headers(); self.wfile.write(data)
                return
            model = body.get("model") or ""
            route = resolver(provider, model)
            if not route:
                self.close_connection = True
                return _error(self, 404, f"Orbit has no harness provider '{provider}' (model {model}).", "not_found_error")
            if not route.get("api_key") and route.get("key_required", True):
                self.close_connection = True
                return _error(self, 401, f"No API key for {provider}. Add it in Orbit → Settings → Claude Code → Models.")
            STATS["requests"] += 1
            STATS["by_provider"][provider] = STATS["by_provider"].get(provider, 0) + 1
            STATS["last"] = {"provider": provider, "model": model, "t": time.time(), "format": route["format"]}
            self.close_connection = True
            try:
                if route["format"] == "messages":
                    return self._passthrough(route, body)
                return self._translate(route, body)
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as e:
                STATS["errors"] += 1
                try: _error(self, 502, f"Orbit gateway: {type(e).__name__}: {e}")
                except Exception: pass

        def _upstream(self, route, path, payload, extra_headers=None):
            base = route["base"].rstrip("/")
            headers = {"content-type": "application/json", "accept": "text/event-stream, application/json",
                       "user-agent": "orbit-harness-gateway/1"}
            key = route.get("api_key") or ""
            if key:
                headers["authorization"] = "Bearer " + key
                headers["x-api-key"] = key
            headers.update(extra_headers or {})
            data = json.dumps(payload).encode()
            for attempt in range(3):
                req = urllib.request.Request(base + path, data=data, headers=headers, method="POST")
                try:
                    return _opener(route.get("proxy")).open(req, timeout=float(route.get("timeout") or 900))
                except urllib.error.HTTPError as e:
                    # a brief upstream hiccup is retried here; anything else goes back to Claude Code
                    if e.code not in (502, 503, 504) or attempt == 2: raise
                except (urllib.error.URLError, ConnectionError, TimeoutError, socket.timeout):
                    if attempt == 2: raise
                time.sleep(1.5 * (attempt + 1))

        def _relay_error(self, e):
            STATS["errors"] += 1
            try: raw = e.read().decode("utf-8", "replace")
            except Exception: raw = ""
            msg = raw
            try:
                j = json.loads(raw)
                err = j.get("error") if isinstance(j, dict) else None
                msg = (err.get("message") if isinstance(err, dict) else err) or j.get("message") or raw
            except ValueError:
                pass
            if log: log(f"upstream {e.code}: {str(msg)[:300]}")
            return _error(self, e.code, f"upstream {e.code}: {str(msg)[:1500]}")

        def _passthrough(self, route, body):
            extra = {}
            for h in ("anthropic-version", "anthropic-beta"):
                if self.headers.get(h): extra[h] = self.headers[h]
            extra.setdefault("anthropic-version", "2023-06-01")
            try:
                r = self._upstream(route, "/messages", body, extra)
            except urllib.error.HTTPError as e:
                return self._relay_error(e)
            self.send_response(r.status)
            self.send_header("content-type", r.headers.get("content-type") or "application/json")
            self.send_header("connection", "close")
            self.end_headers()
            while True:
                chunk = r.read1(65536) if hasattr(r, "read1") else r.read(65536)
                if not chunk: break
                self.wfile.write(chunk); self.wfile.flush()

        def _translate(self, route, body):
            responses = route["format"] == "responses"
            payload = to_responses(body) if responses else to_openai(body)
            payload.update(route.get("extra_body") or {})
            try:
                r = self._upstream(route, "/responses" if responses else "/chat/completions", payload)
            except urllib.error.HTTPError as e:
                return self._relay_error(e)
            model = body.get("model") or ""
            if not body.get("stream"):
                obj = json.loads(r.read() or b"{}")
                data = json.dumps(responses_complete_to_anthropic(obj, model) if responses
                                  else complete_to_anthropic(obj, model)).encode()
                self.send_response(200); self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data))); self.end_headers(); self.wfile.write(data)
                return
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("cache-control", "no-cache")
            self.send_header("connection", "close")
            self.end_headers()
            conv = responses_stream_to_anthropic if responses else stream_to_anthropic
            for out in conv(iter(r.readline, b""), model):
                self.wfile.write(out); self.wfile.flush()

    return H


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _same(a, b):
    import hmac
    return hmac.compare_digest(str(a or ""), str(b or ""))


def serve(port, resolver, log=None, token=None):
    """Start the gateway in a background thread on 127.0.0.1:<port> (0 = any free port).
    With a token, requests must carry it (Authorization: Bearer or x-api-key)."""
    srv = Server(("127.0.0.1", int(port)), make_handler(resolver, log, token))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
