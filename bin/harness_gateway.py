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
    th = body.get("thinking") if isinstance(body.get("thinking"), dict) else {}
    model = str(body.get("model") or "").lower()
    if model.startswith("deepseek") and th.get("type") in (None, "disabled"):
        # DeepSeek V4 reasons by default: a request that asks for no thinking (a title, a
        # quick note) says so, or it spends hundreds of tokens and ~10 s first. (Measured on
        # OpenCode Go: reasoning_effort "none" -> 1 s, 5 tokens. GLM there rejects a
        # "thinking" field, so it is not sent.)
        out["reasoning_effort"] = "none"
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


def repair_json(raw):
    """Tool arguments as a JSON object string, mended where a model left them broken."""
    raw = (raw or "").strip()
    if not raw: return "{}"
    try:
        v = json.loads(raw)
        return raw if isinstance(v, dict) else json.dumps({"value": v})
    except ValueError:
        pass
    s = raw
    if s.startswith("```"):
        s = re.sub(r"^```[a-z]*\s*|\s*```$", "", s)
    s = re.sub(r",\s*([}\]])", r"\1", s)                       # trailing commas
    # close what was left open (strings, arrays, objects), in order
    stack, in_str, esc = [], False, False
    for ch in s:
        if in_str:
            if esc: esc = False
            elif ch == "\\": esc = True
            elif ch == '"': in_str = False
        elif ch == '"': in_str = True
        elif ch in "{[": stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack: stack.pop()
    s = s + ('"' if in_str else "") + "".join(reversed(stack))
    s = re.sub(r",\s*([}\]])", r"\1", s)
    try:
        v = json.loads(s)
        return json.dumps(v) if isinstance(v, dict) else json.dumps({"value": v})
    except ValueError:
        return "{}"


class _Blocks:
    """Keeps the Messages content blocks of one streamed answer in order."""

    def __init__(self, model):
        self.model, self.idx, self.open = model, -1, None
        self.calls = {}              # upstream call key -> {"id", "name", "args"}, in order of arrival
        self.had_tools = False
        self.ids = {}                # upstream tool index -> the call id it carries now
        self.keys = {}               # upstream tool index -> the call key it maps to now

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

    def flush_tools(self):
        """Tool calls go out whole, once their arguments are complete: parallel calls
        can arrive interleaved, and some models send malformed or truncated JSON,
        which would fail the call in Claude Code."""
        calls, self.calls = self.calls, {}
        self.ids, self.keys = {}, {}
        for c in calls.values():
            yield from self.begin("tool", {"type": "tool_use", "id": c["id"], "name": c["name"], "input": {}})
            yield _sse("content_block_delta", {"type": "content_block_delta", "index": self.idx,
                                               "delta": {"type": "input_json_delta",
                                                         "partial_json": repair_json(c["args"])}})
            yield from self.close()

    def thinking(self, text):
        if self.calls: yield from self.flush_tools()
        if self.open != "thinking":
            yield from self.begin("thinking", {"type": "thinking", "thinking": "", "signature": ""})
        yield _sse("content_block_delta", {"type": "content_block_delta", "index": self.idx,
                                           "delta": {"type": "thinking_delta", "thinking": text}})

    def text(self, text):
        if self.calls: yield from self.flush_tools()
        if self.open != "text":
            yield from self.begin("text", {"type": "text", "text": ""})
        yield _sse("content_block_delta", {"type": "content_block_delta", "index": self.idx,
                                           "delta": {"type": "text_delta", "text": text}})

    def tool(self, index, cid=None, name=None, args=""):
        key = self.keys.get(index, index)
        if cid and index in self.ids and self.ids[index] != cid:
            # some providers number every parallel call 0: a new call id at a used
            # index is a new call, not more arguments for the previous one
            key = (index, cid)
        if cid:
            self.ids[index], self.keys[index] = cid, key
        self.had_tools = True
        if key not in self.calls:
            yield from self.close()
            self.calls[key] = {"id": cid or ("toolu_" + uuid.uuid4().hex[:20]), "name": name or "", "args": ""}
        c = self.calls[key]
        if name and not c["name"]: c["name"] = name
        if args: c["args"] += args
        return
        yield

    def finish(self, stop, usage):
        yield from self.close()
        if self.calls: yield from self.flush_tools()
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
    if b.had_tools and stop == "end_turn": stop = "tool_use"
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
    if b.had_tools and stop == "end_turn": stop = "tool_use"
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


# Fields every Anthropic-compatible vendor accepts. Claude Code also sends
# Anthropic-only ones (context_management, output_config, adaptive thinking…)
# that other vendors may reject.
PASSTHROUGH_KEYS = ("model", "messages", "system", "max_tokens", "metadata", "stop_sequences", "stream",
                    "temperature", "top_k", "top_p", "tools", "tool_choice", "thinking")


def _drop_unsigned_thinking(messages):
    """Thinking written by another vendor's model carries no Anthropic signature, and
    Anthropic rejects such blocks: a chat that moved to Claude drops them (the answers
    and tool calls they led to stay)."""
    out = []
    for m in messages or []:
        c = m.get("content") if isinstance(m, dict) else None
        if m.get("role") == "assistant" and isinstance(c, list):
            kept = [b for b in c if not (isinstance(b, dict) and b.get("type") == "thinking" and not b.get("signature"))]
            if len(kept) != len(c):
                m = {**m, "content": kept or [{"type": "text", "text": " "}]}
        out.append(m)
    return out


def passthrough_body(body, strict=True):
    if not strict:
        return {**body, "messages": _drop_unsigned_thinking(body.get("messages"))} if body.get("messages") else body
    out = {k: v for k, v in body.items() if k in PASSTHROUGH_KEYS}
    th = out.get("thinking")
    if isinstance(th, dict) and th.get("type") not in ("enabled", "disabled"):
        mt = int(out.get("max_tokens") or 32000)
        out["thinking"] = {"type": "enabled", "budget_tokens": max(1024, min(16000, mt - 1024))} \
            if mt > 2048 else {"type": "disabled"}
    return out


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


class UpstreamError(Exception):
    """An error reply from the provider, already read."""
    def __init__(self, code, raw):
        super().__init__(f"upstream {code}")
        self.code, self.raw = code, raw


def _error_message(raw):
    msg = raw
    try:
        j = json.loads(raw)
        err = j.get("error") if isinstance(j, dict) else None
        msg = (err.get("message") if isinstance(err, dict) else err) or j.get("message") or raw
    except (ValueError, AttributeError):
        pass
    return str(msg)


class _UsageTap:
    """Reads token usage out of the Anthropic-format stream going back to Claude Code."""
    def __init__(self):
        self.buf, self.usage = b"", {}

    def _take(self, u):
        for k, v in (u or {}).items():
            if isinstance(v, int): self.usage[k] = max(self.usage.get(k, 0), v)

    def feed(self, chunk):
        self.buf += chunk
        *lines, self.buf = self.buf.split(b"\n")
        for line in lines:
            if not line.startswith(b"data:") or b"usage" not in line: continue
            try: ev = json.loads(line[5:])
            except ValueError: continue
            self._take((ev.get("message") or {}).get("usage") if ev.get("type") == "message_start" else ev.get("usage"))

    def whole(self, obj):
        self._take((obj or {}).get("usage"))


def make_handler(resolver, log=None, token=None, hooks=None):
    hooks = hooks or {}

    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            if re.match(r"^/h/[A-Za-z0-9_.-]+/v1/models(\?.*)?$", self.path):
                # Codex asks for model metadata; with none it uses its defaults
                data = b'{"models": []}'
                self.send_response(200); self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data))); self.end_headers(); self.wfile.write(data)
                return
            if self.path.rstrip("/") in ("", "/health"):
                data = json.dumps({"ok": True, "stats": STATS}).encode()
                self.send_response(200); self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data))); self.end_headers(); self.wfile.write(data)
                return
            _error(self, 404, "not found")

        def do_POST(self):
            m = re.match(r"^/h/([A-Za-z0-9_.-]+)/v1/(messages(/count_tokens)?|responses)(\?.*)?$", self.path)
            if not m:
                self.close_connection = True
                return _error(self, 404, f"unknown path {self.path}")
            provider, counting = m.group(1), bool(m.group(3))
            self.inbound = "responses" if m.group(2) == "responses" else "messages"
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
                return _error(self, 401, f"No API key for {provider}. Add it in Orbit → Settings → Models & keys.")
            STATS["requests"] += 1
            STATS["by_provider"][provider] = STATS["by_provider"].get(provider, 0) + 1
            STATS["last"] = {"provider": provider, "model": model, "t": time.time(), "format": route["format"]}
            self.provider, self.account, self.tap = provider, None, _UsageTap()
            self.session = session_id(self.headers, body)
            self.close_connection = True
            cap = route.get("max_output")
            if cap and int(body.get("max_tokens") or 0) > int(cap):
                body["max_tokens"] = int(cap)            # a model's own output limit, not Claude's default
            if self.inbound == "responses" and cap and int(body.get("max_output_tokens") or 0) > int(cap):
                body["max_output_tokens"] = int(cap)
            try:
                if self.inbound == "responses":
                    return self._responses(route, body)
                if route["format"] == "messages":
                    return self._passthrough(route, body)
                return self._translate(route, body)
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as e:
                STATS["errors"] += 1
                try: _error(self, 502, f"Orbit gateway: {type(e).__name__}: {e}")
                except Exception: pass
            finally:
                if self.tap.usage and hooks.get("usage"):
                    try: hooks["usage"](provider, self.account, model, dict(self.tap.usage))
                    except Exception: pass

        def _upstream(self, route, path, payload, extra_headers=None):
            """POST to the provider. With several accounts, one whose quota is used up
            is marked and the next is tried."""
            accounts = route.get("accounts") or [{"id": route.get("account") or "", "api_key": route.get("api_key") or ""}]
            data = json.dumps(payload).encode()
            for n, acct in enumerate(accounts):
                self.account = acct.get("id") or ""
                try:
                    return self._post(route, path, data, acct.get("api_key") or "", extra_headers)
                except urllib.error.HTTPError as e:
                    try: raw = e.read().decode("utf-8", "replace")
                    except Exception: raw = ""
                    block = _quota_block(e.code, raw, e.headers.get("retry-after") if e.headers else None)
                    if block is not None:
                        # remembered even with one account, so Settings can say when it resets
                        if hooks.get("exhausted"):
                            try: hooks["exhausted"](self.provider, self.account, _error_message(raw), block)
                            except Exception: pass
                    if block is not None and len(accounts) > 1:
                        if log: log(f"{self.provider} account {self.account}: used up ({e.code}); "
                                    + ("trying the next" if n + 1 < len(accounts) else "no accounts left"))
                        if n + 1 < len(accounts): continue
                    raise UpstreamError(e.code, raw)

        def _post(self, route, path, data, key, extra_headers=None):
            base = route["base"].rstrip("/")
            headers = {"content-type": "application/json", "accept": "text/event-stream, application/json",
                       "user-agent": "orbit/1.0",
                       "x-opencode-client": "orbit",
                       # one id per conversation, for routing and prompt caching (OpenCode Go requires it)
                       "x-opencode-session": getattr(self, "session", "") or "orbit",
                       "x-claude-code-session-id": getattr(self, "session", "") or "orbit"}
            if key:
                headers["authorization"] = "Bearer " + key
                headers["x-api-key"] = key
            headers.update(extra_headers or {})
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
            msg = _error_message(e.raw)
            if log: log(f"upstream {e.code}: {msg[:300]}")
            return _error(self, e.code, f"upstream {e.code}: {msg[:1500]}")

        def _passthrough(self, route, body):
            extra = {}
            for h in ("anthropic-version", "anthropic-beta"):
                if self.headers.get(h): extra[h] = self.headers[h]
            extra.setdefault("anthropic-version", "2023-06-01")
            try:
                r = self._upstream(route, "/messages", passthrough_body(body, route.get("strict", True)), extra)
            except UpstreamError as e:
                return self._relay_error(e)
            self.send_response(r.status)
            self.send_header("content-type", r.headers.get("content-type") or "application/json")
            self.send_header("connection", "close")
            self.end_headers()
            sse = "event-stream" in (r.headers.get("content-type") or "")
            whole = b""
            while True:
                chunk = r.read1(65536) if hasattr(r, "read1") else r.read(65536)
                if not chunk: break
                if sse: self.tap.feed(chunk)
                elif len(whole) < 4_000_000: whole += chunk
                self.wfile.write(chunk); self.wfile.flush()
            if not sse:
                try: self.tap.whole(json.loads(whole))
                except ValueError: pass

        def _responses(self, route, body):
            """Codex's Responses request, answered by this provider in its own format."""
            import responses_bridge as RB
            fmt, model = route["format"], body.get("model") or ""
            if fmt == "chat":
                payload, names = RB.responses_to_chat(body)
                path, conv = "/chat/completions", RB.chat_stream_to_responses
                extra = None
            elif fmt == "messages":
                payload, names = RB.responses_to_messages(body, int(route.get("max_output") or 32000))
                payload = passthrough_body(payload, route.get("strict", True))
                path, conv = "/messages", RB.messages_stream_to_responses
                extra = {"anthropic-version": "2023-06-01"}
            else:
                openai = "api.openai.com" in (route.get("base") or "")
                payload, names = RB.responses_for_provider(body, openai=openai)
                payload["stream"] = True
                path, conv, extra = "/responses", None, None
            payload.update(route.get("extra_body") or {})
            try:
                r = self._upstream(route, path, payload, extra)
            except UpstreamError as e:
                STATS["errors"] += 1
                msg = _error_message(e.raw)
                if log: log(f"upstream {e.code}: {msg[:300]}")
                data = json.dumps({"error": {"message": f"upstream {e.code}: {msg[:1500]}",
                                             "type": ERROR_TYPES.get(e.code, "api_error"), "code": e.code}}).encode()
                self.send_response(e.code); self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                if e.code == 429: self.send_header("retry-after", "20")
                self.end_headers(); self.wfile.write(data)
                return
            lines = iter(r.readline, b"")
            stream = conv(lines, model, names) if conv else RB.responses_stream_restore(lines, names)
            if not body.get("stream", True):
                obj = RB.collect(stream)
                self._tap_responses(obj)
                data = json.dumps(obj).encode()
                self.send_response(200); self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data))); self.end_headers(); self.wfile.write(data)
                return
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("cache-control", "no-cache")
            self.send_header("connection", "close")
            self.end_headers()
            for out in stream:
                if b"response.completed" in out or b"response.incomplete" in out:
                    for line in out.decode("utf-8", "replace").splitlines():
                        if line.startswith("data:"):
                            try: self._tap_responses(json.loads(line[5:]).get("response"))
                            except ValueError: pass
                self.wfile.write(out); self.wfile.flush()

        def _tap_responses(self, resp):
            u = (resp or {}).get("usage") or {}
            cached = (u.get("input_tokens_details") or {}).get("cached_tokens") or 0
            self.tap.whole({"usage": {"input_tokens": max(0, (u.get("input_tokens") or 0) - cached),
                                      "output_tokens": u.get("output_tokens") or 0,
                                      "cache_read_input_tokens": cached}})

        def _translate(self, route, body):
            responses = route["format"] == "responses"
            payload = to_responses(body) if responses else to_openai(body)
            payload.update(route.get("extra_body") or {})
            try:
                r = self._upstream(route, "/responses" if responses else "/chat/completions", payload)
            except UpstreamError as e:
                return self._relay_error(e)
            model = body.get("model") or ""
            if not body.get("stream"):
                obj = json.loads(r.read() or b"{}")
                out = responses_complete_to_anthropic(obj, model) if responses else complete_to_anthropic(obj, model)
                self.tap.whole(out)
                data = json.dumps(out).encode()
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
                self.tap.feed(out)
                self.wfile.write(out); self.wfile.flush()

    return H


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        import sys
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            return                       # a client that hung up: not an error worth a traceback
        super().handle_error(request, client_address)


def _same(a, b):
    import hmac
    return hmac.compare_digest(str(a or ""), str(b or ""))


def session_id(headers, body):
    """A stable id for the conversation a request belongs to. OpenCode Go refuses
    requests without one (x-opencode-session); Claude Code sends its own session
    header, and anything else (Orbit's own calls) gets one derived from how the
    conversation starts, which stays the same as it grows."""
    for h in ("x-opencode-session", "x-claude-code-session-id", "x-session-id", "session-id", "session_id",
              "thread-id", "conversation_id", "conversation-id"):
        v = (headers.get(h) or "").strip()
        if v: return v[:128]
    uid = str(((body or {}).get("metadata") or {}).get("user_id") or "")
    m = re.search(r"session_([0-9a-f-]{16,})", uid)
    if m: return m.group(1)
    import hashlib
    if (body or {}).get("prompt_cache_key"): return str(body["prompt_cache_key"])[:128]
    first = next((x for x in (body or {}).get("messages") or (body or {}).get("input") or []
                  if isinstance(x, dict) and x.get("role") == "user"), {})
    seed = json.dumps([(body or {}).get("system") or (body or {}).get("instructions"), first.get("content")],
                      sort_keys=True, default=str)
    h = hashlib.sha256(seed.encode("utf-8", "replace")).hexdigest()
    return f"orbit-{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def _quota_block(status, raw, retry_after=None):
    try:
        import harness_usage
        return harness_usage.quota_block(status, raw, retry_after)
    except ImportError:
        return 3600 if status == 402 else None


def serve(port, resolver, log=None, token=None, hooks=None):
    """Start the gateway in a background thread on 127.0.0.1:<port> (0 = any free port).
    With a token, requests must carry it (Authorization: Bearer or x-api-key).
    hooks: "usage"(provider, account, model, usage) after each answer,
           "exhausted"(provider, account, message) when an account's quota is used up."""
    srv = Server(("127.0.0.1", int(port)), make_handler(resolver, log, token, hooks))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
