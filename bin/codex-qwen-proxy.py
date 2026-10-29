#!/usr/bin/env python3
"""Small OpenAI Responses -> Chat Completions bridge for Codex + MTPLX.

Codex 0.147+ only accepts Responses API providers.  MTPLX serves the local
Qwen model through Chat Completions, so this process translates the request
and emits the subset of Responses streaming events Codex consumes.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


LOCAL_MODEL = "mtplx-qwen38-27b-optimized-speed"


def codex_model_catalog():
    """Model metadata shape expected by current Codex releases."""
    return {"models": [{
        "slug": LOCAL_MODEL,
        "display_name": "Qwen 3.8 27B (local)",
        "description": "Local Qwen served by MTPLX",
        "default_reasoning_level": "low",
        "supported_reasoning_levels": [
            {"effort": "low", "description": "Use the model's local reasoning mode"}
        ],
        "shell_type": "shell_command",
        "visibility": "list",
        "supported_in_api": True,
        "priority": 1,
        "additional_speed_tiers": [],
        "service_tiers": [{"id": "default", "name": "Local", "description": "Local inference"}],
        "default_service_tier": "default",
        "availability_nux": {"message": "Local Qwen through MTPLX"},
        "model_messages": {
            "instructions_template": (
                "You are Codex, a coding agent using a local Qwen model. Work in the user's "
                "repository, use the supplied tools when needed, and complete the requested task."
            ),
        },
        "include_skills_usage_instructions": False,
        "include_plugin_usage_instructions": False,
        "include_apps_usage_instructions": False,
        "supports_reasoning_summary_parameter": False,
        "default_reasoning_summary": "none",
        "support_verbosity": False,
        "default_verbosity": "low",
        "apply_patch_tool_type": "freeform",
        "web_search_tool_type": "text_and_image",
        "truncation_policy": {"mode": "tokens", "limit": 10000},
        "supports_parallel_tool_calls": True,
        "supports_image_detail_original": False,
        "context_window": 131072,
        "max_context_window": 131072,
        "auto_compact_token_limit": 100000,
        "comp_hash": "local-qwen-v1",
        "effective_context_window_percent": 90,
        "experimental_supported_tools": [],
        "input_modalities": ["text", "image"],
        "supports_search_tool": False,
        "use_responses_lite": False,
        "auto_review_model_override": LOCAL_MODEL,
        "tool_mode": "default",
        "multi_agent_version": "v1",
    }]}


def _text(content):
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return "" if content is None else str(content)
    chunks = []
    for part in content:
        if isinstance(part, str):
            chunks.append(part)
        elif isinstance(part, dict):
            kind = part.get("type", "")
            if kind in ("input_text", "output_text", "text"):
                chunks.append(part.get("text", ""))
            elif kind == "input_image" and part.get("image_url"):
                chunks.append({"type": "image_url", "image_url": {"url": part["image_url"]}})
    if any(isinstance(x, dict) for x in chunks):
        return [{"type": "text", "text": x} if isinstance(x, str) else x for x in chunks]
    return "\n".join(x for x in chunks if x)


def responses_to_chat(body):
    messages = []
    if body.get("instructions"):
        messages.append({"role": "system", "content": body["instructions"]})
    raw_input = body.get("input", [])
    if isinstance(raw_input, str):
        raw_input = [{"role": "user", "content": raw_input}]

    pending_calls = []

    def flush_calls():
        if pending_calls:
            messages.append({"role": "assistant", "content": None,
                             "tool_calls": list(pending_calls)})
            pending_calls.clear()

    for item in raw_input:
        if not isinstance(item, dict):
            continue
        kind = item.get("type", "message")
        if kind == "function_call":
            pending_calls.append({
                "id": item.get("call_id") or item.get("id") or "call_" + uuid.uuid4().hex[:12],
                "type": "function",
                "function": {"name": item.get("name", ""),
                             "arguments": item.get("arguments") or "{}"},
            })
            continue
        flush_calls()
        if kind == "function_call_output":
            messages.append({"role": "tool",
                             "tool_call_id": item.get("call_id", ""),
                             "content": _text(item.get("output"))})
        elif kind == "message" or "role" in item:
            role = item.get("role", "user")
            if role == "developer":
                role = "system"
            messages.append({"role": role, "content": _text(item.get("content"))})
        # Reasoning and provider-only bookkeeping items are intentionally omitted.
    flush_calls()

    tools = []
    for tool in body.get("tools") or []:
        if tool.get("type") != "function":
            continue
        tools.append({"type": "function", "function": {
            "name": tool.get("name", ""),
            "description": tool.get("description", ""),
            "parameters": tool.get("parameters") or {"type": "object", "properties": {}},
        }})

    out = {
        "model": body.get("model"),
        "messages": messages,
        "stream": False,
        "max_tokens": body.get("max_output_tokens") or 16384,
        # This bridge is launched by codex-qwen with reasoning effort "none".
        # Codex currently does not serialize that setting for unknown models,
        # so make the matching MTPLX control explicit here.
        "enable_thinking": False,
    }
    if tools:
        out["tools"] = tools
        choice = body.get("tool_choice", "auto")
        if isinstance(choice, dict) and choice.get("type") == "function":
            choice = {"type": "function", "function": {"name": choice.get("name", "")}}
        if choice in ("auto", "none", "required") or isinstance(choice, dict):
            out["tool_choice"] = choice
        out["parallel_tool_calls"] = body.get("parallel_tool_calls", True)
    return out


def make_response(request_body, completion):
    now = int(time.time())
    response_id = "resp_" + uuid.uuid4().hex
    output = []
    message = ((completion.get("choices") or [{}])[0].get("message") or {})
    content = message.get("content")
    if content:
        output.append({
            "id": "msg_" + uuid.uuid4().hex,
            "type": "message", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": content, "annotations": []}],
        })
    for call in message.get("tool_calls") or []:
        fn = call.get("function") or {}
        output.append({
            "id": "fc_" + uuid.uuid4().hex,
            "type": "function_call", "status": "completed",
            "call_id": call.get("id") or "call_" + uuid.uuid4().hex[:12],
            "name": fn.get("name", ""), "arguments": fn.get("arguments") or "{}",
        })
    usage = completion.get("usage") or {}
    in_tokens = usage.get("prompt_tokens", 0)
    out_tokens = usage.get("completion_tokens", 0)
    return {
        "id": response_id, "object": "response", "created_at": now,
        "status": "completed", "error": None, "incomplete_details": None,
        "instructions": request_body.get("instructions"),
        "model": completion.get("model") or request_body.get("model"),
        "output": output, "parallel_tool_calls": request_body.get("parallel_tool_calls", True),
        "tool_choice": request_body.get("tool_choice", "auto"),
        "tools": request_body.get("tools") or [],
        "usage": {"input_tokens": in_tokens, "input_tokens_details": {"cached_tokens": 0},
                  "output_tokens": out_tokens,
                  "output_tokens_details": {"reasoning_tokens": 0},
                  "total_tokens": usage.get("total_tokens", in_tokens + out_tokens)},
    }


def response_events(response):
    stub = dict(response)
    stub["status"] = "in_progress"
    stub["output"] = []
    yield "response.created", {"type": "response.created", "response": stub, "sequence_number": 0}
    seq = 1
    for index, item in enumerate(response["output"]):
        started = dict(item)
        started["status"] = "in_progress"
        if item["type"] == "message":
            started["content"] = []
        elif item["type"] == "function_call":
            started["arguments"] = ""
        yield "response.output_item.added", {
            "type": "response.output_item.added", "output_index": index,
            "item": started, "sequence_number": seq,
        }
        seq += 1
        if item["type"] == "message":
            text = item["content"][0]["text"]
            part = {"type": "output_text", "text": "", "annotations": []}
            yield "response.content_part.added", {
                "type": "response.content_part.added", "item_id": item["id"],
                "output_index": index, "content_index": 0, "part": part,
                "sequence_number": seq,
            }
            seq += 1
            yield "response.output_text.delta", {
                "type": "response.output_text.delta", "item_id": item["id"],
                "output_index": index, "content_index": 0, "delta": text,
                "logprobs": [], "sequence_number": seq,
            }
            seq += 1
            yield "response.output_text.done", {
                "type": "response.output_text.done", "item_id": item["id"],
                "output_index": index, "content_index": 0, "text": text,
                "logprobs": [], "sequence_number": seq,
            }
            seq += 1
            yield "response.content_part.done", {
                "type": "response.content_part.done", "item_id": item["id"],
                "output_index": index, "content_index": 0,
                "part": item["content"][0], "sequence_number": seq,
            }
            seq += 1
        else:
            args = item["arguments"]
            yield "response.function_call_arguments.delta", {
                "type": "response.function_call_arguments.delta", "item_id": item["id"],
                "output_index": index, "delta": args, "sequence_number": seq,
            }
            seq += 1
            yield "response.function_call_arguments.done", {
                "type": "response.function_call_arguments.done", "item_id": item["id"],
                "output_index": index, "arguments": args, "sequence_number": seq,
            }
            seq += 1
        yield "response.output_item.done", {
            "type": "response.output_item.done", "output_index": index,
            "item": item, "sequence_number": seq,
        }
        seq += 1
    yield "response.completed", {"type": "response.completed", "response": response,
                                 "sequence_number": seq}


class Handler(BaseHTTPRequestHandler):
    server_version = "CodexQwenBridge/1.0"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def _json(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path.rstrip("/")
        if path == "/health":
            return self._json(200, {"ok": True, "service": "codex-qwen-proxy"})
        if path in ("/v1/models", "/models"):
            return self._json(200, codex_model_catalog())
        self._json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        if urlsplit(self.path).path.rstrip("/") not in ("/v1/responses", "/responses"):
            return self._json(404, {"error": {"message": "not found"}})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(size))
            chat = responses_to_chat(body)
            data = json.dumps(chat).encode()
            req = urllib.request.Request(self.server.upstream + "/chat/completions", data=data,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=3600) as result:
                completion = json.load(result)
            response = make_response(body, completion)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            return self._json(exc.code, {"error": {"message": detail}})
        except Exception as exc:
            return self._json(502, {"error": {"message": f"bridge error: {exc}"}})

        if not body.get("stream", False):
            return self._json(200, response)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        for event, payload in response_events(response):
            self.wfile.write(f"event: {event}\ndata: {json.dumps(payload)}\n\n".encode())
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8012)
    parser.add_argument("--upstream", default="http://127.0.0.1:8011/v1")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.upstream = args.upstream.rstrip("/")
    print(f"codex-qwen-proxy listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
