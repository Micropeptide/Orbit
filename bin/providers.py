"""Where answers come from.

Orbit started out talking to one local server. This module makes the model a choice:
a local MLX model served by MTPLX, or a hosted one (Claude, GPT, anything
OpenAI-shaped) behind an API key you type into Settings.

Three ways in:

  kind "openai"     — /v1/chat/completions. MTPLX, Ollama, LM Studio, OpenAI,
                      OpenRouter, Groq, DeepSeek, and most self-hosted servers.
  kind "anthropic"  — the Messages API through the official SDK, so Claude's
                      thinking blocks and tool calls arrive as themselves rather
                      than squeezed through a compatibility shim.
  kind "cli"        — spawn a coding CLI you are already signed into (claude,
                      codex, opencode, qwen) and read its JSON event stream.
                      No API key, and it bills against that subscription.

Everything above this layer keeps speaking the OpenAI message shape; the
Anthropic adapter translates on the way in and out.
"""
import json, os, urllib.request, urllib.error

# ------------------------------------------------------------------ registry

BUILTIN_PROVIDERS = {
    # base_url empty on purpose: the local server's actual port is only known
    # by qqcore.py (config/settings.json's server.port, which is user-settable
    # and not always 8000), and stream_call() already falls back to its own
    # freshly-computed BASE when a provider's base_url is empty. A hardcoded
    # value here would go stale — and silently 404 against whatever else is
    # running on port 8000 — the moment someone changes the port.
    "local": {"label": "Local · MTPLX", "kind": "openai", "managed": True,
              "base_url": "", "key": "",
              "note": "the model running on this Mac"},
    "anthropic": {"label": "Anthropic · Claude", "kind": "anthropic",
                  "base_url": "", "key": "ANTHROPIC_API_KEY",
                  "keys_url": "https://console.anthropic.com/settings/keys"},
    "openai": {"label": "OpenAI", "kind": "openai",
               "base_url": "https://api.openai.com/v1", "key": "OPENAI_API_KEY",
               "keys_url": "https://platform.openai.com/api-keys"},
    "openrouter": {"label": "OpenRouter", "kind": "openai",
                   "base_url": "https://openrouter.ai/api/v1", "key": "OPENROUTER_API_KEY",
                   "keys_url": "https://openrouter.ai/keys"},
    "ollama": {"label": "Ollama", "kind": "openai",
               "base_url": "http://127.0.0.1:11434/v1", "key": "",
               "note": "another local server, if you run one"},
    "lmstudio": {"label": "LM Studio", "kind": "openai",
                 "base_url": "http://127.0.0.1:1234/v1", "key": ""},
}

# Claude ids change faster than this file does; the Models API is the source of
# truth and "fetch models" replaces this list. It is here so the picker is not
# empty before you have typed a key.
SEED_MODELS = [
    {"provider": "anthropic", "model": "claude-opus-5",   "label": "Claude Opus 5",
     "context": 1000000, "thinking": True},
    {"provider": "anthropic", "model": "claude-sonnet-5", "label": "Claude Sonnet 5",
     "context": 1000000, "thinking": True},
    {"provider": "anthropic", "model": "claude-haiku-4-5", "label": "Claude Haiku 4.5",
     "context": 200000, "thinking": False},
]

# Claude models that take adaptive thinking and output_config.effort. Anything
# else gets neither — sending them to an older model is a 400, not a warning.
ADAPTIVE = ("claude-opus-5", "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6",
            "claude-sonnet-5", "claude-sonnet-4-6", "claude-fable-5", "claude-mythos-5")


# ------------------------------------------------------------------ CLI agents
#
# Borrowed from Guardian, which runs jobs through whichever coding CLI you are
# already signed into rather than through an API key. `claude` and `codex` are
# logged in on this Mac already, so this costs nothing extra to use and no key
# ever gets pasted anywhere.
#
# The trade: these are whole agents, not raw models. They bring their own tools
# and refuse anything needing approval when run non-interactively, and Orbit's
# own tools are not offered to them. Good for asking; not for driving the toolchain.

CLI_BACKENDS = {
    "claude-cli": {
        "label": "Claude Code CLI", "bin": "claude",
        "argv": ["--print", "--output-format", "stream-json", "--verbose",
                 "--include-partial-messages"],
        "model_flag": "--model", "system_flag": "--append-system-prompt",
        "models": [("opus", "Claude Opus"), ("sonnet", "Claude Sonnet"),
                   ("haiku", "Claude Haiku")],
        "note": "your Claude subscription — no API key",
    },
    "codex-cli": {
        "label": "Codex CLI", "bin": "codex",
        "argv": ["exec", "--json", "--skip-git-repo-check"],
        "model_flag": "--model", "system_flag": None,
        "models": [("", "Codex (default model)")],
        "note": "your ChatGPT plan — no API key",
    },
    "opencode-cli": {
        "label": "OpenCode CLI", "bin": "opencode",
        "argv": ["run", "--format", "json"],
        "model_flag": "--model", "system_flag": None,
        "models": [("", "OpenCode (default model)")],
    },
    "qwen-cli": {
        "label": "Qwen Code CLI", "bin": "qwen",
        "argv": ["-p"], "model_flag": "-m", "system_flag": None,
        "models": [("", "Qwen Code (default model)")],
    },
}


# launchd gives the UI a much thinner PATH than a login shell, so `codex` and
# `qwen` in /opt/homebrew/bin were invisible to the server while being right
# there in the terminal. Look in the usual places too.
EXTRA_BIN_DIRS = ["~/.local/bin", "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin",
                  "~/.opencode/bin", "~/.bun/bin", "~/.npm-global/bin", "~/bin",
                  "~/.volta/bin", "~/.nvm/versions/node"]

def which(name):
    import shutil
    hit = shutil.which(name)
    if hit: return hit
    for d in EXTRA_BIN_DIRS:
        cand = os.path.join(os.path.expanduser(d), name)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def cli_available(backend):
    return bool(which((CLI_BACKENDS.get(backend) or {}).get("bin") or ""))


def cli_models():
    """One entry per (installed CLI, model route)."""
    out = []
    for bid, b in CLI_BACKENDS.items():
        if not cli_available(bid): continue
        for route, label in b["models"]:
            out.append({"provider": bid, "model": route or "default",
                        "label": f"{label} · CLI", "context": None,
                        "thinking": False, "kind": "cli",
                        "provider_label": b["label"], "ready": True,
                        "note": b.get("note", "")})
    return out


def _transcript(messages):
    """One prompt out of a conversation. A CLI turn has no history of its own,
    so the history goes in the prompt — plainly labelled, nothing invented."""
    system, lines = [], []
    for m in messages:
        role, c = m.get("role"), m.get("content")
        if isinstance(c, list):                       # multimodal: text parts only
            c = " ".join(p.get("text", "") for p in c if p.get("type") == "text")
        c = str(c or "").strip()
        if not c: continue
        if role == "system": system.append(c)
        elif role == "user": lines.append("User: " + c)
        elif role == "assistant": lines.append("Assistant: " + c)
        elif role == "tool": lines.append("Tool result: " + c[:2000])
    body = "\n\n".join(lines[-40:])
    if len(lines) > 1:
        body = ("Here is the conversation so far. Answer the final message.\n\n"
                + body + "\n\nAssistant:")
    return "\n\n".join(system), body


def _cli_text(ev):
    """Pull displayable text out of one streamed event, whatever CLI wrote it."""
    t = ev.get("type")
    # claude --include-partial-messages
    if t == "stream_event":
        d = ((ev.get("event") or {}).get("delta") or {})
        if d.get("type") == "text_delta": return ("delta", d.get("text") or "")
        if d.get("type") == "thinking_delta": return ("think", d.get("thinking") or "")
        return (None, "")
    # claude whole-message events
    if t == "assistant" and isinstance(ev.get("message"), dict):
        return ("whole", "".join(c.get("text", "") for c in ev["message"].get("content", [])
                                 if isinstance(c, dict) and c.get("type") == "text"))
    if t == "result" and isinstance(ev.get("result"), str):
        return ("final", ev["result"])
    # codex
    if t == "item.completed":
        it = ev.get("item") or {}
        if it.get("type") == "agent_message": return ("whole", it.get("text") or "")
        if it.get("type") == "reasoning": return ("think", it.get("text") or "")
    # opencode
    part = ev.get("part")
    if isinstance(part, dict) and isinstance(part.get("text"), str):
        return ("whole", part["text"])
    return (None, "")


def cli_stream(backend, model, messages, emit=None, cancel=None, timeout=900,
               cwd=None, extra_args=None):
    """Run one turn through a CLI agent and stream what it says."""
    import signal, subprocess, threading
    emit = emit or (lambda k, p: None)
    b = CLI_BACKENDS.get(backend)
    if not b: raise RuntimeError(f"unknown CLI backend {backend}")
    exe = which(b["bin"])
    if not exe: raise RuntimeError(f"{b['bin']} is not installed or not on PATH")

    system, prompt = _transcript(messages)
    argv = [exe, *b["argv"]]
    if model and model != "default" and b.get("model_flag"):
        argv += [b["model_flag"], model]
    if system and b.get("system_flag"):
        argv += [b["system_flag"], system[:6000]]
    argv += list(extra_args or [])
    argv.append(prompt if (system and b.get("system_flag")) else
                ((system + "\n\n" + prompt) if system else prompt))

    proc = subprocess.Popen(argv, cwd=cwd or None, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            start_new_session=True)   # own group, so cancel kills children

    killed = {"why": None}
    def stop(why):
        killed["why"] = why
        try: os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            try: proc.terminate()
            except Exception: pass

    timer = threading.Timer(timeout, lambda: stop("timeout"))
    timer.daemon = True; timer.start()
    if cancel is not None:
        def watch():
            while proc.poll() is None:
                if cancel.wait(0.4): stop("cancelled"); return
        threading.Thread(target=watch, daemon=True).start()

    live, whole, final, think = [], [], None, []
    try:
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if not line: continue
            try: ev = json.loads(line)
            except ValueError:
                continue                       # progress chatter, not an event
            if not isinstance(ev, dict): continue
            kind, text = _cli_text(ev)
            if not text: continue
            if kind == "delta":
                live.append(text); emit("content_delta", text)
            elif kind == "think":
                think.append(text); emit("thinking_delta", text)
            elif kind == "whole":
                if not live:                   # no token stream from this CLI
                    emit("content_delta", text)
                whole.append(text)
            elif kind == "final":
                final = text
    finally:
        timer.cancel()
        try: proc.stdout.close()
        except Exception: pass
        err = b""
        try: err = proc.stderr.read() or b""
        except Exception: pass
        try: proc.stderr.close()
        except Exception: pass
        rc = proc.wait()

    text = final or ("".join(live) if live else "\n\n".join(whole))

    # A signed-out CLI exits 0 and prints its complaint as the answer, which then
    # gets saved as though the model had said it. Surface it as the failure it is.
    low = text.strip().lower()
    for marker, fix in (
        ("failed to authenticate", "sign in again"),
        ("oauth session expired", "sign in again"),
        ("not logged in", "sign in"),
        ("please run `claude login`", "sign in"),
        ("authentication_error", "check the credentials"),
    ):
        if low.startswith(marker) or (marker in low and len(low) < 300):
            raise RuntimeError(
                f"{b['bin']} is not signed in ({text.strip()[:120]}). "
                f"Open a terminal, run `{b['bin']}`, {fix}, then try again.")
    if killed["why"] == "timeout" and not text:
        raise RuntimeError(f"{b['bin']} produced nothing within {timeout}s")
    if not text and rc not in (0, None):
        tail = err.decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(f"{b['bin']} exited {rc}: " + (tail[-1][:300] if tail else "no output"))
    msg = {"role": "assistant", "content": text}
    if think: msg["reasoning_content"] = "".join(think)
    return msg


def _path(root):  return os.path.join(root, "config", "models.json")


def load(root):
    """Registry as stored, with built-in providers filled in."""
    try:
        cfg = json.load(open(_path(root)))
    except Exception:
        cfg = {}
    provs = dict(BUILTIN_PROVIDERS)
    for pid, p in (cfg.get("providers") or {}).items():
        provs[pid] = {**provs.get(pid, {}), **p}
    return {"default": cfg.get("default") or "", "providers": provs,
            "models": cfg.get("models") or [], "hidden": cfg.get("hidden") or []}


def save(root, cfg):
    keep = {"default": cfg.get("default") or "",
            "models": cfg.get("models") or [],
            "hidden": cfg.get("hidden") or [],
            # only store what differs from the built-ins
            "providers": {k: v for k, v in (cfg.get("providers") or {}).items()
                          if k not in BUILTIN_PROVIDERS or v != BUILTIN_PROVIDERS[k]}}
    tmp = _path(root) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(keep, f, indent=1)
    os.replace(tmp, _path(root))
    return keep


def model_id(provider, model):  return f"{provider}:{model}"


def catalogue(root, local_model=None, secrets=None):
    """Every model you can pick right now, newest config first.

    The local server contributes whatever it is actually serving, so the picker
    never offers a local model that is not there.
    """
    cfg = load(root)
    out, seen = [], set()

    def add(m):
        mid = model_id(m["provider"], m["model"])
        if mid in seen or mid in cfg["hidden"]: return
        seen.add(mid)
        prov = cfg["providers"].get(m["provider"]) or {}
        if m["provider"] in CLI_BACKENDS:
            out.append({**m, "id": mid}); return
        need = prov.get("key")
        out.append({**m, "id": mid, "kind": prov.get("kind", "openai"),
                    "provider_label": prov.get("label", m["provider"]),
                    "ready": (not need) or bool((secrets or {}).get(need) or os.environ.get(need))})

    if local_model:
        add({"provider": "local", "model": local_model, "label": local_model,
             "context": None, "thinking": True})
    for m in cli_models():
        add(m)
    for m in cfg["models"]:
        add(m)
    for m in SEED_MODELS:
        add(m)
    return out


def resolve(root, mid, local_model=None, secrets=None):
    """A model id to everything needed to call it. Falls back to the local model."""
    cfg = load(root)
    cat = catalogue(root, local_model, secrets)
    pick = next((m for m in cat if m["id"] == mid), None)
    if pick is None and cfg["default"]:
        pick = next((m for m in cat if m["id"] == cfg["default"]), None)
    if pick is None:
        pick = next((m for m in cat if m["provider"] == "local"), None)
    if pick is None:
        return None
    if pick["provider"] in CLI_BACKENDS:
        b = CLI_BACKENDS[pick["provider"]]
        return {**pick, "provider_cfg": {"kind": "cli", "backend": pick["provider"],
                                         "label": b["label"], "api_key": ""}}
    prov = dict(cfg["providers"].get(pick["provider"]) or {})
    key_name = prov.get("key") or ""
    prov["api_key"] = (secrets or {}).get(key_name) or os.environ.get(key_name) or ""
    return {**pick, "provider_cfg": prov}


# ------------------------------------------------------------------ discovery

def fetch_models(provider_cfg, api_key="", timeout=20):
    """Ask a provider what it serves. Both wire formats answer GET /models."""
    kind = provider_cfg.get("kind", "openai")
    base = (provider_cfg.get("base_url") or "").rstrip("/")
    if kind == "anthropic":
        base = base or "https://api.anthropic.com/v1"
        req = urllib.request.Request(base + "/models", headers={
            "x-api-key": api_key, "anthropic-version": "2023-06-01"})
    else:
        if not base: return {"error": "no base URL for this provider"}
        req = urllib.request.Request(base + "/models")
        if api_key: req.add_header("Authorization", "Bearer " + api_key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        body = ""
        try: body = e.read().decode()[:200]
        except Exception: pass
        return {"error": f"HTTP {e.code}: {body or e.reason}"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    rows = []
    for m in d.get("data") or []:
        mid = m.get("id")
        if not mid: continue
        rows.append({"model": mid,
                     "label": m.get("display_name") or mid,
                     "context": m.get("max_input_tokens"),
                     "thinking": bool(kind == "anthropic" and mid.startswith(ADAPTIVE))})
    return {"models": rows}


# ------------------------------------------------------------------ Anthropic

def _to_anthropic(messages):
    """OpenAI-shaped history -> (system text, Anthropic messages)."""
    system, out = [], []
    for m in messages:
        role = m.get("role")
        if role == "system":
            if m.get("content"): system.append(str(m["content"]))
            continue
        if role == "tool":
            out.append({"role": "user", "content": [{
                "type": "tool_result",
                "tool_use_id": m.get("tool_call_id") or "",
                "content": str(m.get("content") or "")[:100000]}]})
            continue
        if role == "assistant":
            blocks = []
            if m.get("content"):
                blocks.append({"type": "text", "text": str(m["content"])})
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                try: args = json.loads(fn.get("arguments") or "{}")
                except ValueError: args = {}
                blocks.append({"type": "tool_use", "id": tc.get("id") or "",
                               "name": fn.get("name") or "", "input": args})
            if blocks: out.append({"role": "assistant", "content": blocks})
            continue
        # user — may be plain text or the multimodal list Orbit builds for uploads
        c = m.get("content")
        if isinstance(c, list):
            blocks = []
            for part in c:
                if part.get("type") == "text":
                    blocks.append({"type": "text", "text": part.get("text") or ""})
                elif part.get("type") == "image_url":
                    url = ((part.get("image_url") or {}).get("url") or "")
                    if url.startswith("data:") and ";base64," in url:
                        head, b64 = url.split(";base64,", 1)
                        blocks.append({"type": "image", "source": {
                            "type": "base64", "media_type": head[5:], "data": b64}})
            out.append({"role": "user", "content": blocks or [{"type": "text", "text": ""}]})
        else:
            out.append({"role": "user", "content": str(c or "")})

    # The API rejects two turns of the same role in a row; the tool loop can produce
    # that when a tool result follows a plain user message.
    merged = []
    for m in out:
        if merged and merged[-1]["role"] == m["role"]:
            a, b = merged[-1]["content"], m["content"]
            a = a if isinstance(a, list) else [{"type": "text", "text": str(a)}]
            b = b if isinstance(b, list) else [{"type": "text", "text": str(b)}]
            merged[-1]["content"] = a + b
        else:
            merged.append(dict(m))
    return "\n\n".join(system), merged


def _tools_for_anthropic(tools):
    out = []
    for t in tools or []:
        fn = t.get("function") or {}
        if not fn.get("name"): continue
        out.append({"name": fn["name"],
                    "description": (fn.get("description") or "")[:1024],
                    "input_schema": fn.get("parameters") or
                                    {"type": "object", "properties": {}}})
    return out


def anthropic_stream(model, messages, tools, api_key, think=True, effort="medium",
                     emit=None, cancel=None, max_tokens=32000, base_url=""):
    """One Claude turn, returned in the OpenAI shape the rest of Orbit speaks."""
    import anthropic

    emit = emit or (lambda k, p: None)
    client = anthropic.Anthropic(api_key=api_key, **({"base_url": base_url} if base_url else {}))
    system, msgs = _to_anthropic(messages)
    kw = {"model": model, "max_tokens": max_tokens, "messages": msgs}
    if system: kw["system"] = system
    at = _tools_for_anthropic(tools)
    if at: kw["tools"] = at
    if model.startswith(ADAPTIVE):
        # adaptive thinking replaces the old fixed budget; display must be asked
        # for or the blocks stream back empty
        if think: kw["thinking"] = {"type": "adaptive", "display": "summarized"}
        eff = effort if effort in ("low", "medium", "high", "xhigh", "max") else "medium"
        kw["output_config"] = {"effort": eff}

    text, thinking, calls = [], [], []
    with client.messages.stream(**kw) as stream:
        for ev in stream:
            if cancel is not None and cancel.is_set():
                stream.close()
                break
            if ev.type == "content_block_delta":
                d = ev.delta
                if d.type == "thinking_delta":
                    thinking.append(d.thinking); emit("thinking_delta", d.thinking)
                elif d.type == "text_delta":
                    text.append(d.text); emit("content_delta", d.text)
        final = stream.get_final_message()

    if getattr(final, "stop_reason", None) == "refusal":
        det = getattr(final, "stop_details", None)
        why = getattr(det, "category", None) or "unspecified"
        raise RuntimeError(f"Claude declined this request (category: {why}). "
                           "Nothing was generated.")

    for b in final.content:
        if b.type == "tool_use":
            calls.append({"id": b.id, "type": "function",
                          "function": {"name": b.name,
                                       "arguments": json.dumps(b.input or {})}})
    msg = {"role": "assistant", "content": "".join(text)}
    if thinking: msg["reasoning_content"] = "".join(thinking)
    if calls: msg["tool_calls"] = calls
    usage = getattr(final, "usage", None)
    if usage is not None:
        msg["_usage"] = {"prompt_tokens": getattr(usage, "input_tokens", 0),
                         "completion_tokens": getattr(usage, "output_tokens", 0)}
    return msg
