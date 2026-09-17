"""OpenAI's Responses API, answered by any model: what Orbit's gateway speaks to Codex.

Codex (the CLI and its app-server) talks to a custom model provider only through
the Responses API (`wire_api = "responses"`). This module translates, with no I/O:

- a Responses request -> an OpenAI chat-completions request, or an Anthropic
  Messages request, or a Responses request other providers accept;
- the provider's streamed answer -> Responses stream events (reasoning, text,
  function calls, usage), as Codex expects them.

Codex groups an MCP server's tools as a "namespace" tool. Models behind other APIs
only know flat functions, so a namespaced tool is offered as `<namespace>__<name>`
and a call to it goes back to Codex with its namespace and name restored.
"""
import json, re, time, uuid

from harness_gateway import repair_json, _data_lines


# ------------------------------------------------------------------ tools

def _flat_name(ns, name, taken):
    base = re.sub(r"[^A-Za-z0-9_-]", "_", f"{ns}__{name}")[:64]
    out, i = base, 2
    while out in taken:
        out = f"{base[:60]}_{i}"; i += 1
    return out


def flatten_tools(tools):
    """Responses tools -> ([{"name", "description", "parameters"}], {flat name: (namespace, name)}).
    Built-in tools a non-OpenAI model cannot run (web_search, image_generation…) are left out."""
    out, names, taken = [], {}, set()
    for t in tools or []:
        kind = t.get("type")
        if kind == "function" and t.get("name"):
            taken.add(t["name"])
            out.append({"name": t["name"], "description": t.get("description") or "",
                        "parameters": t.get("parameters") or {"type": "object", "properties": {}}})
        elif kind == "namespace":
            for sub in t.get("tools") or []:
                if sub.get("type", "function") != "function" or not sub.get("name"): continue
                flat = _flat_name(t.get("name") or "ns", sub["name"], taken)
                taken.add(flat)
                names[flat] = (t.get("name"), sub["name"])
                desc = sub.get("description") or ""
                if t.get("description"): desc = f"[{t['name']}: {t['description'][:200]}] {desc}"
                out.append({"name": flat, "description": desc,
                            "parameters": sub.get("parameters") or {"type": "object", "properties": {}}})
        elif kind == "custom" and t.get("name"):
            # a freeform tool (its input is plain text): offered as a function taking that text
            taken.add(t["name"])
            names[t["name"]] = ("__custom__", t["name"])
            out.append({"name": t["name"], "description": (t.get("description") or "") + " (pass the whole input as `input`)",
                        "parameters": {"type": "object", "properties": {"input": {"type": "string"}}, "required": ["input"]}})
    return out, names


def _flat_of(item, names):
    """The flat tool name a Responses function_call item was offered under."""
    ns, name = item.get("namespace"), item.get("name") or ""
    if ns:
        for flat, (n, sub) in names.items():
            if n == ns and sub == name: return flat
        return _flat_name(ns, name, set())
    return name


# ------------------------------------------------------------------ input items

def _parts_text(content, kinds=("input_text", "output_text", "text", "summary_text", "reasoning_text")):
    if isinstance(content, str): return content
    return "".join((p.get("text") or "") for p in content or [] if isinstance(p, dict) and p.get("type") in kinds)


def _output_text(out):
    if isinstance(out, str): return out
    if isinstance(out, dict): return out.get("content") if isinstance(out.get("content"), str) else json.dumps(out)
    if isinstance(out, list):
        bits = []
        for p in out:
            if not isinstance(p, dict): continue
            if p.get("type") in ("input_text", "output_text", "text"): bits.append(p.get("text") or "")
            elif p.get("type") in ("input_image",): bits.append("[image]")
        return "\n".join(bits)
    return str(out or "")


def _walk(body):
    """Yield ("system", text) / ("user", parts) / ("assistant", text) / ("call", item) /
    ("result", item) / ("reasoning", text) from a Responses request, in order."""
    if body.get("instructions"): yield "system", str(body["instructions"])
    items = body.get("input")
    if isinstance(items, str):
        yield "user", [{"type": "input_text", "text": items}]
        return
    for it in items or []:
        if not isinstance(it, dict): continue
        kind = it.get("type") or ("message" if it.get("role") else None)
        if kind == "message":
            role = it.get("role")
            c = it.get("content")
            if role in ("system", "developer"): yield "system", _parts_text(c)
            elif role == "assistant": yield "assistant", _parts_text(c)
            else: yield "user", ([{"type": "input_text", "text": c}] if isinstance(c, str) else list(c or []))
        elif kind in ("function_call", "custom_tool_call", "local_shell_call"):
            yield "call", it
        elif kind in ("function_call_output", "custom_tool_call_output", "local_shell_call_output"):
            yield "result", it
        elif kind == "reasoning":
            txt = _parts_text(it.get("content")) or _parts_text(it.get("summary"))
            if txt: yield "reasoning", txt


def _call_args(item):
    if item.get("type") == "custom_tool_call":
        return json.dumps({"input": item.get("input") or ""})
    return repair_json(item.get("arguments") or "{}")


# ------------------------------------------------------------------ -> chat completions

def responses_to_chat(body):
    tools, names = flatten_tools(body.get("tools"))
    msgs, system, pending_reasoning = [], [], ""
    for kind, v in _walk(body):
        if kind == "system":
            if v.strip(): system.append(v)
        elif kind == "user":
            parts = []
            for p in v:
                t = p.get("type")
                if t in ("input_text", "text", "output_text"): parts.append({"type": "text", "text": p.get("text") or ""})
                elif t == "input_image":
                    url = p.get("image_url") or (p.get("image") or {}).get("url") or ""
                    if url: parts.append({"type": "image_url", "image_url": {"url": url}})
                elif t == "input_file":
                    parts.append({"type": "text", "text": f"[file attached: {p.get('filename') or 'file'}]"})
            if not parts: continue
            msgs.append({"role": "user", "content": parts[0]["text"] if len(parts) == 1 and parts[0]["type"] == "text" else parts})
        elif kind == "reasoning":
            pending_reasoning += v
        elif kind == "assistant":
            m = {"role": "assistant", "content": v}
            if pending_reasoning: m["reasoning_content"], pending_reasoning = pending_reasoning, ""
            msgs.append(m)
        elif kind == "call":
            last = msgs[-1] if msgs else None
            if not (last and last["role"] == "assistant"):
                last = {"role": "assistant", "content": None, "tool_calls": []}
                msgs.append(last)
            last.setdefault("tool_calls", [])
            if last.get("content") == "": last["content"] = None
            if pending_reasoning: last["reasoning_content"], pending_reasoning = pending_reasoning, ""
            last["tool_calls"].append({"id": v.get("call_id") or v.get("id") or "call_" + uuid.uuid4().hex[:16],
                                       "type": "function",
                                       "function": {"name": _flat_of(v, names), "arguments": _call_args(v)}})
        elif kind == "result":
            msgs.append({"role": "tool", "tool_call_id": v.get("call_id"), "content": _output_text(v.get("output"))})
    if system: msgs.insert(0, {"role": "system", "content": "\n\n".join(system)})
    out = {"model": body.get("model"), "messages": msgs, "stream": True, "stream_options": {"include_usage": True}}
    if tools:
        out["tools"] = [{"type": "function", "function": t} for t in tools]
        tc = body.get("tool_choice")
        if isinstance(tc, dict) and tc.get("name"):
            out["tool_choice"] = {"type": "function", "function": {"name": tc["name"]}}
        elif tc in ("auto", "none", "required"):
            out["tool_choice"] = tc
        if body.get("parallel_tool_calls") is not None:
            out["parallel_tool_calls"] = bool(body["parallel_tool_calls"])
    if body.get("max_output_tokens"): out["max_tokens"] = body["max_output_tokens"]
    for k in ("temperature", "top_p"):
        if body.get(k) is not None: out[k] = body[k]
    fmt = (body.get("text") or {}).get("format") if isinstance(body.get("text"), dict) else None
    if isinstance(fmt, dict) and fmt.get("type") == "json_schema":
        out["response_format"] = {"type": "json_schema", "json_schema": {
            "name": fmt.get("name") or "output", "schema": fmt.get("schema") or {}, "strict": bool(fmt.get("strict"))}}
    effort = ((body.get("reasoning") or {}).get("effort") or "").lower()
    model = str(body.get("model") or "").lower()
    if model.startswith("deepseek") and effort:
        # DeepSeek V4 takes reasoning_effort; others (GLM on OpenCode Go) reject unknown fields
        out["reasoning_effort"] = "none" if effort in ("none", "minimal") else ("high" if effort in ("xhigh", "max", "ultra") else effort)
    return out, names


# ------------------------------------------------------------------ -> Anthropic Messages

def _image_block(url):
    m = re.match(r"^data:([^;]+);base64,(.*)$", url or "", re.S)
    if m: return {"type": "image", "source": {"type": "base64", "media_type": m.group(1), "data": m.group(2)}}
    return {"type": "image", "source": {"type": "url", "url": url}}


def responses_to_messages(body, max_tokens=32000):
    tools, names = flatten_tools(body.get("tools"))
    msgs, system = [], []

    def push(role, blocks):
        if msgs and msgs[-1]["role"] == role:
            msgs[-1]["content"].extend(blocks)
        else:
            msgs.append({"role": role, "content": list(blocks)})

    for kind, v in _walk(body):
        if kind == "system":
            if v.strip(): system.append(v)
        elif kind == "user":
            blocks = []
            for p in v:
                t = p.get("type")
                if t in ("input_text", "text", "output_text"):
                    if p.get("text"): blocks.append({"type": "text", "text": p["text"]})
                elif t == "input_image":
                    blocks.append(_image_block(p.get("image_url") or ""))
            if blocks: push("user", blocks)
        elif kind == "assistant":
            if v: push("assistant", [{"type": "text", "text": v}])
        elif kind == "call":
            try: args = json.loads(_call_args(v))
            except ValueError: args = {}
            push("assistant", [{"type": "tool_use", "id": v.get("call_id") or "toolu_" + uuid.uuid4().hex[:20],
                                "name": _flat_of(v, names), "input": args}])
        elif kind == "result":
            push("user", [{"type": "tool_result", "tool_use_id": v.get("call_id"), "content": _output_text(v.get("output")) or " "}])
    if msgs and msgs[0]["role"] != "user":
        msgs.insert(0, {"role": "user", "content": [{"type": "text", "text": "(continuing)"}]})
    out = {"model": body.get("model"), "messages": msgs, "stream": True,
           "max_tokens": int(body.get("max_output_tokens") or max_tokens)}
    if system: out["system"] = "\n\n".join(system)
    if tools:
        out["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools]
        tc = body.get("tool_choice")
        if isinstance(tc, dict) and tc.get("name"): out["tool_choice"] = {"type": "tool", "name": tc["name"]}
        elif tc == "required": out["tool_choice"] = {"type": "any"}
        elif tc == "none": out["tool_choice"] = {"type": "none"}
    for k in ("temperature", "top_p"):
        if body.get(k) is not None: out[k] = body[k]
    return out, names


# ------------------------------------------------------------------ -> Responses (other providers)

def responses_for_provider(body, openai=False):
    """A Responses request an OpenAI-compatible provider that is not OpenAI accepts:
    namespaces flattened, built-in tools and OpenAI-only fields left out."""
    out = {k: v for k, v in body.items() if k not in ("client_metadata", "prompt_cache_key", "include", "store", "service_tier")}
    names = {}
    if openai:
        out["store"] = body.get("store", False)
        if body.get("include"): out["include"] = body["include"]
        return out, names
    tools, names = flatten_tools(body.get("tools"))
    if tools: out["tools"] = [{"type": "function", **t} for t in tools]
    else: out.pop("tools", None)
    if isinstance(body.get("input"), list):
        items = []
        for it in body["input"]:
            if isinstance(it, dict) and it.get("type") == "function_call" and it.get("namespace"):
                it = {**{k: v for k, v in it.items() if k != "namespace"}, "name": _flat_of(it, names)}
            if isinstance(it, dict) and it.get("type") == "reasoning" and it.get("encrypted_content") \
                    and not it.get("summary") and not it.get("content"):
                continue                   # another provider's sealed reasoning means nothing here
            items.append(it)
        out["input"] = items
    return out, names


# ------------------------------------------------------------------ streaming back

def _ev(kind, **data):
    data["type"] = kind
    return f"event: {kind}\ndata: {json.dumps(data)}\n\n".encode()


class ResponseStream:
    """Builds the Responses events of one answer: reasoning, then text, then function calls."""

    def __init__(self, model, names=None):
        self.model, self.names = model, names or {}
        self.id = "resp_" + uuid.uuid4().hex
        self.output, self.index = [], -1
        self.reason = None            # {"id", "text"} while reasoning streams
        self.msg = None               # {"id", "text"} while text streams
        self.calls = {}               # key -> {"call_id", "name", "args"}
        self.usage = {"input_tokens": 0, "output_tokens": 0, "cached": 0, "reasoning": 0}
        self.seq = 0

    def _resp(self, status, **extra):
        u = self.usage
        return {"id": self.id, "object": "response", "created_at": int(time.time()), "model": self.model,
                "status": status, "output": self.output,
                "usage": {"input_tokens": u["input_tokens"], "input_tokens_details": {"cached_tokens": u["cached"]},
                          "output_tokens": u["output_tokens"], "output_tokens_details": {"reasoning_tokens": u["reasoning"]},
                          "total_tokens": u["input_tokens"] + u["output_tokens"]}, **extra}

    def start(self):
        yield _ev("response.created", response=self._resp("in_progress", output=[]))
        yield _ev("response.in_progress", response=self._resp("in_progress", output=[]))

    def _close_reason(self):
        if not self.reason: return
        r, self.reason = self.reason, None
        item = {"type": "reasoning", "id": r["id"], "summary": [{"type": "summary_text", "text": r["text"]}],
                "content": [{"type": "reasoning_text", "text": r["text"]}]}
        yield _ev("response.reasoning_summary_text.done", item_id=r["id"], output_index=r["index"], summary_index=0, text=r["text"])
        yield _ev("response.output_item.done", output_index=r["index"], item=item)
        self.output.append(item)

    def _close_msg(self):
        if not self.msg: return
        m, self.msg = self.msg, None
        part = {"type": "output_text", "text": m["text"], "annotations": []}
        yield _ev("response.output_text.done", item_id=m["id"], output_index=m["index"], content_index=0, text=m["text"])
        yield _ev("response.content_part.done", item_id=m["id"], output_index=m["index"], content_index=0, part=part)
        item = {"type": "message", "id": m["id"], "role": "assistant", "status": "completed", "content": [part]}
        yield _ev("response.output_item.done", output_index=m["index"], item=item)
        self.output.append(item)

    def reasoning(self, text):
        if not text: return
        yield from self._close_msg()
        if not self.reason:
            self.index += 1
            self.reason = {"id": "rs_" + uuid.uuid4().hex[:24], "text": "", "index": self.index}
            yield _ev("response.output_item.added", output_index=self.index,
                      item={"type": "reasoning", "id": self.reason["id"], "summary": []})
            yield _ev("response.reasoning_summary_part.added", item_id=self.reason["id"], output_index=self.index,
                      summary_index=0, part={"type": "summary_text", "text": ""})
        self.reason["text"] += text
        yield _ev("response.reasoning_summary_text.delta", item_id=self.reason["id"], output_index=self.reason["index"],
                  summary_index=0, delta=text)

    def text(self, text):
        if not text: return
        yield from self._close_reason()
        if not self.msg:
            self.index += 1
            self.msg = {"id": "msg_" + uuid.uuid4().hex[:24], "text": "", "index": self.index}
            yield _ev("response.output_item.added", output_index=self.index,
                      item={"type": "message", "id": self.msg["id"], "role": "assistant", "status": "in_progress", "content": []})
            yield _ev("response.content_part.added", item_id=self.msg["id"], output_index=self.index, content_index=0,
                      part={"type": "output_text", "text": "", "annotations": []})
        self.msg["text"] += text
        yield _ev("response.output_text.delta", item_id=self.msg["id"], output_index=self.msg["index"],
                  content_index=0, delta=text)

    def tool(self, key, call_id=None, name=None, args=""):
        c = self.calls.setdefault(key, {"call_id": call_id, "name": name or "", "args": ""})
        if call_id and not c["call_id"]: c["call_id"] = call_id
        if name and not c["name"]: c["name"] = name
        c["args"] += args or ""
        return
        yield

    def _calls(self):
        yield from self._close_reason()
        yield from self._close_msg()
        calls, self.calls = self.calls, {}
        for c in calls.values():
            if not c["name"]: continue
            self.index += 1
            ns = self.names.get(c["name"])
            args = repair_json(c["args"])
            if ns and ns[0] == "__custom__":
                try: inp = json.loads(args).get("input", "")
                except (ValueError, AttributeError): inp = c["args"]
                item = {"type": "custom_tool_call", "id": "ctc_" + uuid.uuid4().hex[:24], "status": "completed",
                        "call_id": c["call_id"] or "call_" + uuid.uuid4().hex[:20], "name": ns[1], "input": inp}
            else:
                item = {"type": "function_call", "id": "fc_" + uuid.uuid4().hex[:24], "status": "completed",
                        "call_id": c["call_id"] or "call_" + uuid.uuid4().hex[:20],
                        "name": ns[1] if ns else c["name"], "arguments": args}
                if ns: item["namespace"] = ns[0]
            yield _ev("response.output_item.added", output_index=self.index, item={**item, "status": "in_progress",
                      **({"arguments": ""} if item["type"] == "function_call" else {})})
            if item["type"] == "function_call":
                yield _ev("response.function_call_arguments.delta", item_id=item["id"], output_index=self.index, delta=args)
                yield _ev("response.function_call_arguments.done", item_id=item["id"], output_index=self.index, arguments=args)
            yield _ev("response.output_item.done", output_index=self.index, item=item)
            self.output.append(item)

    def finish(self, incomplete=False):
        yield from self._calls()
        if incomplete:
            yield _ev("response.incomplete", response=self._resp("incomplete", incomplete_details={"reason": "max_output_tokens"}))
        else:
            yield _ev("response.completed", response=self._resp("completed"))

    def fail(self, message, code="server_error"):
        yield from self._close_reason()
        yield from self._close_msg()
        yield _ev("response.failed", response=self._resp("failed", error={"code": code, "message": str(message)[:2000]}))


def chat_stream_to_responses(lines, model, names=None):
    """OpenAI chat-completions stream lines -> Responses SSE bytes."""
    rs = ResponseStream(model, names)
    yield from rs.start()
    incomplete = False
    keys, ids = {}, {}          # upstream tool index -> the call it continues now, and that call's id
    for ch in _data_lines(lines):
        if ch.get("error"):
            err = ch["error"]
            yield from rs.fail(err.get("message") if isinstance(err, dict) else err)
            return
        u = ch.get("usage")
        if u:
            rs.usage.update(input_tokens=u.get("prompt_tokens") or 0, output_tokens=u.get("completion_tokens") or 0,
                            cached=(u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0,
                            reasoning=(u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)
        for c in ch.get("choices") or []:
            d = c.get("delta") or {}
            r = d.get("reasoning_content") or d.get("reasoning")
            if r: yield from rs.reasoning(r)
            if d.get("content"): yield from rs.text(d["content"])
            for tc in d.get("tool_calls") or []:
                fn = tc.get("function") or {}
                idx = tc.get("index", 0)
                key = keys.get(idx, idx)
                if tc.get("id") and ids.get(idx) and ids[idx] != tc["id"]:
                    key = (idx, tc["id"])          # some providers number every parallel call 0
                if tc.get("id"):
                    ids[idx], keys[idx] = tc["id"], key
                yield from rs.tool(key, tc.get("id"), fn.get("name"), fn.get("arguments") or "")
            if c.get("finish_reason") == "length": incomplete = True
    yield from rs.finish(incomplete)


def messages_stream_to_responses(lines, model, names=None):
    """Anthropic Messages stream lines -> Responses SSE bytes."""
    rs = ResponseStream(model, names)
    yield from rs.start()
    blocks, incomplete = {}, False
    for ev in _data_lines(lines):
        t = ev.get("type")
        if t == "message_start":
            u = (ev.get("message") or {}).get("usage") or {}
            rs.usage["input_tokens"] = (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0)
            rs.usage["cached"] = u.get("cache_read_input_tokens") or 0
        elif t == "content_block_start":
            b = ev.get("content_block") or {}
            blocks[ev.get("index")] = b.get("type")
            if b.get("type") == "tool_use":
                yield from rs.tool(ev.get("index"), b.get("id"), b.get("name"), "")
            elif b.get("type") == "text" and b.get("text"):
                yield from rs.text(b["text"])
        elif t == "content_block_delta":
            d = ev.get("delta") or {}
            if d.get("type") == "text_delta": yield from rs.text(d.get("text") or "")
            elif d.get("type") == "thinking_delta": yield from rs.reasoning(d.get("thinking") or "")
            elif d.get("type") == "input_json_delta": yield from rs.tool(ev.get("index"), args=d.get("partial_json") or "")
        elif t == "message_delta":
            u = ev.get("usage") or {}
            if u.get("output_tokens") is not None: rs.usage["output_tokens"] = u["output_tokens"]
            if (ev.get("delta") or {}).get("stop_reason") == "max_tokens": incomplete = True
        elif t == "error":
            err = ev.get("error") or {}
            yield from rs.fail(err.get("message") if isinstance(err, dict) else err)
            return
    yield from rs.finish(incomplete)


def responses_stream_restore(lines, names):
    """A Responses stream from a provider that got flattened tool names: calls go
    back to Codex with their namespace and name."""
    for raw in lines:
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        if names and line.startswith("data:") and "function_call" in line:
            try:
                ev = json.loads(line[5:])
                it = ev.get("item")
                if isinstance(it, dict) and it.get("type") == "function_call" and it.get("name") in names:
                    ns, name = names[it["name"]]
                    it["name"] = name
                    if ns != "__custom__": it["namespace"] = ns
                    line = "data: " + json.dumps(ev) + "\n"
            except ValueError:
                pass
        yield line.encode() if not line.endswith("\n") else line.encode()


def collect(stream):
    """The final response object of a Responses event stream (for a non-streamed request)."""
    last = None
    for chunk in stream:
        for line in chunk.decode("utf-8", "replace").splitlines():
            if not line.startswith("data:"): continue
            try: ev = json.loads(line[5:])
            except ValueError: continue
            if ev.get("type") in ("response.completed", "response.incomplete", "response.failed"):
                last = ev.get("response")
    return last or {"status": "failed", "error": {"message": "no answer"}}
