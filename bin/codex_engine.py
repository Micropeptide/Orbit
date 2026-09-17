"""Codex mode: Orbit chats answered by Codex's own agent, as Claude Code mode does for Claude.

A chat on a `codex:<provider>/<model>` model runs through `codex app-server` -- the
JSON-RPC interface Codex's own apps use -- so it gets Codex's tools, sandbox, skills,
plugins, MCP servers and AGENTS.md, while Orbit shows each step and asks you about
what Codex wants approved.

- `codex:chatgpt/<model>` uses the ChatGPT account Codex is signed in to on this Mac
  (`codex login`), exactly as the Codex CLI and app do.
- Any other provider in Orbit's list (OpenCode Go, DeepSeek, Kimi, GLM, OpenRouter…)
  goes through Orbit's gateway, which answers Codex's Responses API in that
  provider's own format with your key -- the key never reaches Codex.

Threads are Codex's own sessions (~/.codex/sessions), so the Codex CLI and app can
pick them up too. One app-server process serves every Codex chat; each chat is a
thread in it. A chat that moves here from Orbit's own agent or Claude Code brings
what was said since Codex last saw it.
"""
import json, os, queue, re, shutil, subprocess, threading, time, uuid

Q = None               # qqcore, bound by qqcore (no import cycle)
BACKEND = "codex"
CHATGPT = "chatgpt"


def _ce():
    return Q.CE


# ------------------------------------------------------------------ install, login, models

def which_codex():
    for p in (shutil.which("codex"), "/opt/homebrew/bin/codex", "/usr/local/bin/codex",
              os.path.expanduser("~/.local/bin/codex")):
        if p and os.path.exists(p): return p
    return None


_LOGIN = {"at": 0, "state": None}


def login_state(max_age=300):
    """'chatgpt', 'api_key' or None (signed out / not installed)."""
    if time.time() - _LOGIN["at"] < max_age and _LOGIN["at"]: return _LOGIN["state"]
    exe, state = which_codex(), None
    if exe:
        try:
            import providers
            r = subprocess.run([exe, "login", "status"], capture_output=True, text=True, timeout=20,
                               env=providers.cli_env(exe))
            out = (r.stdout + r.stderr).lower()
            state = "chatgpt" if "chatgpt" in out else "api_key" if "api key" in out else None
            if "not logged in" in out: state = None
        except Exception:
            state = None
    _LOGIN.update(at=time.time(), state=state)
    return state


def chatgpt_models():
    """The models your Codex account offers (Codex's own cache of them)."""
    try:
        d = json.load(open(os.path.join(os.path.expanduser("~/.codex"), "models_cache.json")))
    except (OSError, ValueError):
        return [{"slug": "gpt-5.6-sol", "display_name": "GPT-5.6-Sol"}]
    return [m for m in d.get("models") or [] if m.get("visibility", "list") == "list" and m.get("supported_in_api", True)]


def parse_id(mid):
    """'codex:opencode-go/deepseek-v4-flash' -> ('opencode-go', 'deepseek-v4-flash')."""
    body = str(mid or "")[len("codex:"):] if str(mid or "").startswith("codex:") else ""
    pid, _, model = body.partition("/")
    return (pid, model) if pid and model else (None, None)


def catalogue(harness_cat):
    """Codex models for the picker: your ChatGPT account's, then every harness model
    whose provider has an API (not the Claude subscription)."""
    out = []
    signed = login_state() == "chatgpt"
    for m in chatgpt_models():
        out.append({"id": f"codex:{CHATGPT}/{m['slug']}", "provider": BACKEND, "model": f"{CHATGPT}/{m['slug']}",
                    "label": m.get("display_name") or m["slug"], "provider_label": "Codex · your ChatGPT account",
                    "kind": BACKEND, "context": m.get("context_window") or 272000, "thinking": True,
                    "ready": signed and bool(which_codex()),
                    "note": "" if signed else "run `codex login` in a terminal"})
    for h in harness_cat or []:
        pid = str(h.get("model") or "").split("/")[0]
        if pid in ("claude",): continue                  # the Claude subscription has no API to call
        out.append({**h, "id": "codex:" + h["model"], "provider": BACKEND, "kind": BACKEND,
                    "provider_label": str(h.get("provider_label") or "").replace("Claude Code · ", "Codex · "),
                    "ready": bool(h.get("ready")) and bool(which_codex()), "note": ""})
    return out


def resolve(mid, harness_resolve):
    """The spec of a codex: model, or None."""
    pid, model = parse_id(mid)
    if not pid: return None
    if pid == CHATGPT:
        info = next((m for m in chatgpt_models() if m.get("slug") == model), {})
        return {"id": mid, "provider": BACKEND, "model": f"{pid}/{model}", "label": info.get("display_name") or model,
                "provider_label": "Codex · your ChatGPT account", "kind": BACKEND, "context": info.get("context_window") or 272000,
                "thinking": True, "ready": login_state() == "chatgpt", "codex": {"provider": pid, "model": model}}
    h = harness_resolve("harness:" + pid + "/" + model)
    if not h: return None
    return {**h, "id": mid, "provider": BACKEND, "kind": BACKEND,
            "provider_label": str(h.get("provider_label") or "").replace("Claude Code · ", "Codex · "),
            "codex": {"provider": pid, "model": model}, "harness": h}


def is_engine(spec):
    return (spec or {}).get("provider") == BACKEND


# ------------------------------------------------------------------ the app-server

class CodexError(Exception):
    pass


class AppServer:
    """One `codex app-server` process: JSON-RPC over stdio, events routed to the
    thread (chat) they belong to."""

    def __init__(self, exe, env):
        self.exe, self.env = exe, env
        self.proc = None
        self.lock = threading.Lock()
        self.next_id = 0
        self.pending = {}            # id -> [Event, reply]
        self.threads = {}            # thread id -> Queue of ("notify"|"request", method, params, id)
        self.stderr = []
        self.rate_limits = None

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        self.proc = subprocess.Popen([self.exe, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True, bufsize=1, env=self.env,
                                     cwd=os.path.expanduser("~"), start_new_session=True)
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._read_err, daemon=True).start()
        self.request("initialize", {"clientInfo": {"name": "orbit", "title": "Orbit", "version": "1.0"}}, timeout=60)
        self.notify("initialized", {})

    def _write(self, obj):
        with self.lock:
            if not self.alive(): raise CodexError("Codex stopped")
            try:
                self.proc.stdin.write(json.dumps(obj) + "\n")
                self.proc.stdin.flush()
            except (OSError, ValueError) as e:            # it died between the check and the write
                raise CodexError(f"Codex stopped ({type(e).__name__})")

    def notify(self, method, params):
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def respond(self, rid, result=None, error=None):
        msg = {"jsonrpc": "2.0", "id": rid}
        if error: msg["error"] = {"code": -32000, "message": str(error)}
        else: msg["result"] = result if result is not None else {}
        try: self._write(msg)
        except CodexError: pass

    def request(self, method, params, timeout=120):
        with self.lock:
            self.next_id += 1
            rid = self.next_id
        ev = threading.Event()
        self.pending[rid] = [ev, None]
        try:
            self._write({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        except CodexError:
            self.pending.pop(rid, None); raise
        if not ev.wait(timeout):
            self.pending.pop(rid, None)
            raise CodexError(f"Codex did not answer {method} within {timeout}s")
        reply = self.pending.pop(rid, [None, None])[1]
        if reply is None:                                  # woken because Codex exited
            raise CodexError("Codex stopped: " + " ".join(self.stderr[-3:])[:300])
        if reply.get("error"):
            raise CodexError(str((reply["error"] or {}).get("message") or reply["error"]))
        return reply.get("result") or {}

    def subscribe(self, thread_id):
        qq = self.threads.get(thread_id)
        if qq is None: qq = self.threads[thread_id] = queue.Queue()
        return qq

    def unsubscribe(self, thread_id):
        self.threads.pop(thread_id, None)

    def _read(self):
        for line in self.proc.stdout:
            try: m = json.loads(line)
            except ValueError: continue
            if not isinstance(m, dict): continue
            method, params = m.get("method"), m.get("params") or {}
            if method is None and "id" in m:
                w = self.pending.get(m["id"])
                if w: w[1] = m; w[0].set()
                continue
            if method == "account/rateLimits/updated":
                self.rate_limits = params.get("rateLimits")
            tid = params.get("threadId") or (params.get("thread") or {}).get("id")
            qq = self.threads.get(tid) if tid else None
            if "id" in m:                                        # a request from Codex
                if qq is not None: qq.put(("request", method, params, m["id"]))
                else: self.respond(m["id"], error="no Orbit chat is waiting on this")
            elif qq is not None:
                qq.put(("notify", method, params, None))
        for w in list(self.pending.values()):
            w[0].set()
        for qq in list(self.threads.values()):
            qq.put(("exit", None, {}, None))

    def _read_err(self):
        for line in self.proc.stderr:
            self.stderr.append(line.rstrip())
            del self.stderr[:-60]

    def close(self):
        if self.alive():
            try: self.proc.terminate(); self.proc.wait(5)
            except Exception:
                try: self.proc.kill()
                except Exception: pass


_SERVER = {"srv": None, "sig": None}
_SERVER_LOCK = threading.Lock()


def server():
    """The shared app-server, started (or restarted) as needed."""
    exe = which_codex()
    if not exe: raise CodexError("Codex is not installed (no `codex` on PATH). Install it with `brew install codex`.")
    import providers
    env = providers.cli_env(exe)
    env["ORBIT_GATEWAY_TOKEN"] = _ce().gateway_token()
    sig = (exe, env["ORBIT_GATEWAY_TOKEN"])
    with _SERVER_LOCK:
        srv = _SERVER["srv"]
        if srv is None or not srv.alive() or _SERVER["sig"] != sig:
            if srv is not None: srv.close()
            srv = AppServer(exe, env)
            srv.start()
            _SERVER.update(srv=srv, sig=sig)
        return srv


def shutdown():
    with _SERVER_LOCK:
        if _SERVER["srv"]: _SERVER["srv"].close()
        _SERVER["srv"] = None


# ------------------------------------------------------------------ chats

def marker_of(messages):
    """This chat's Codex thread: {"thread", "cwd", "model", "provider", "owner"}. A chat
    opened from a Codex session (agent marker) continues that same thread."""
    for m in reversed(messages or []):
        if not isinstance(m, dict): continue
        if isinstance(m.get("codex"), dict) and m["codex"].get("thread"): return m["codex"]
        a = m.get("agent")
        if isinstance(a, dict) and a.get("source") == "codex" and a.get("id"):
            return {"thread": a["id"], "cwd": a.get("cwd"), "provider": None, "imported": True}
    return None


def gap_messages(messages, thread):
    """What was said in this chat since Codex last saw it (all of it, for a new thread)."""
    last = -1
    for i, m in enumerate(messages):
        if isinstance(m, dict) and ((m.get("codex") or {}).get("thread") == thread or m.get("codex_thread") == thread
                                    or ((m.get("agent") or {}).get("id") == thread)):
            last = i
    return [m for m in messages[last + 1:] if isinstance(m, dict) and m.get("role") in ("user", "assistant", "tool")
            and not m.get("nudge")]


PERMISSIONS = {
    # Orbit / Claude permission mode -> (Codex approval policy, sandbox)
    "plan": ("on-request", "read-only"),
    "bypassPermissions": ("never", "danger-full-access"),
    "dontAsk": ("never", "workspace-write"),
    "acceptEdits": ("on-request", "workspace-write"),
    "auto": ("on-request", "workspace-write"),
    "manual": ("untrusted", "workspace-write"),
    "default": ("untrusted", "workspace-write"),
}
EFFORTS = ("minimal", "low", "medium", "high", "xhigh")


def provider_config(spec):
    """(modelProvider, config) for a thread, and the model name Codex should ask for."""
    c = spec.get("codex") or {}
    pid, model = c.get("provider"), c.get("model")
    if pid == CHATGPT:
        return None, {}, model
    key = f"orbit-{pid}"
    cfg = {"model_providers": {key: {"name": f"Orbit · {spec.get('provider_label') or pid}".replace("Codex · ", ""),
                                     "base_url": f"http://127.0.0.1:{_ce().gateway_port()}/h/{pid}/v1",
                                     "wire_api": "responses", "env_key": "ORBIT_GATEWAY_TOKEN",
                                     "stream_idle_timeout_ms": 600000}}}
    ctx = int(spec.get("context") or 0)
    if ctx:
        cfg["model_context_window"] = ctx
        cfg["model_auto_compact_token_limit"] = int(ctx * 0.8)
    return key, cfg, model


def _text_of(content):
    if isinstance(content, str): return content
    return " ".join(x.get("text", "") for x in content or [] if isinstance(x, dict) and x.get("type") == "text")


def _inputs(user_content, prior):
    parts = []
    text = _text_of(user_content)
    if prior:
        text = ("[Earlier in this conversation, before you (Codex) joined or while another model answered — "
                "for context; don't redo what is done]\n" + prior + "\n\n[The message to answer now]\n" + text)
    parts.append({"type": "text", "text": text})
    if isinstance(user_content, list):
        for x in user_content:
            url = (x.get("image_url") or {}).get("url") if isinstance(x, dict) and x.get("type") == "image_url" else None
            if url: parts.append({"type": "image", "url": url})
    return parts


def _cwd_for(sid, project, mk):
    ce = _ce()
    prefs = ce.chat_prefs(sid) if sid else {}
    if mk and mk.get("cwd") and os.path.isdir(mk["cwd"]): return mk["cwd"], prefs
    folder = None
    try: folder = Q.project_folder(project) if project else None
    except Exception: folder = None
    cwd = prefs.get("cwd") or folder or (ce.cfg().get("default_dir") or "").strip() or Q.WORKSPACE
    return (cwd if os.path.isdir(cwd) else Q.WORKSPACE), prefs


RUNS = {}          # chat id -> {"thread", "turn", "srv"} while it answers


def run_turn(messages, user_content, tools, emit=None, approve=None, cancel=None, inbox=None,
             interrupt=None, sid=None, checkpoint=None, project=None, max_minutes=None,
             read_only=None, **_):
    """One answer through Codex. Same contract as qqcore.turn()."""
    q = Q
    ce = _ce()
    emit = emit or (lambda k, p: None)
    cancel = cancel or q.CANCEL
    T = q.TURN_CTX
    T.sid, T.project, T.read_only = sid, project, bool(read_only)
    T.changes = []
    spec = q.current_model() or {}
    label = "Codex · " + (spec.get("label") or (spec.get("codex") or {}).get("model") or "")
    emit("model", {"id": spec.get("id"), "label": label, "provider": "Codex"})

    def fail(msg):
        messages.append({"role": "user", "content": user_content, "t": time.time()})
        emit("error", msg); emit("done", None)
        return ""

    c = spec.get("codex") or {}
    if not which_codex():
        return fail("Codex is not installed (no `codex` on PATH). Install it (`brew install codex`), or pick another model.")
    if c.get("provider") == CHATGPT and login_state(max_age=30) != "chatgpt":
        return fail("Codex is not signed in to a ChatGPT account on this Mac. In a terminal run `codex login`, "
                    "then send this again — or pick a Codex model from another provider.")
    if c.get("provider") != CHATGPT:
        h = spec.get("harness") or {}
        if not (h.get("provider_cfg") or {}).get("api_key") and not (h.get("provider_cfg") or {}).get("local"):
            return fail(f"No API key for {spec.get('provider_label') or c.get('provider')}. "
                        "Add it in Settings → Models & keys.")
    try:
        srv = server()
    except Exception as e:
        return fail(f"Codex could not start: {e}")

    mk = dict(marker_of(messages) or {})
    cwd, prefs = _cwd_for(sid, project, mk)
    provider_key, config, model = provider_config(spec)
    mode = "plan" if read_only else (prefs.get("permission_mode") or ce.cfg().get("permission_mode") or "auto")
    policy, sandbox = PERMISSIONS.get(mode, PERMISSIONS["auto"])
    if prefs.get("add_dirs") and sandbox == "workspace-write":
        config = {**config, "sandbox_workspace_write": {"writable_roots": list(prefs["add_dirs"])}}
    dev = ""
    try: dev = "\n\n".join(ce._system_parts(project))
    except Exception: pass

    thread = None
    same_provider = mk.get("thread") and (mk.get("imported") or mk.get("provider") == (provider_key or CHATGPT))
    # a chat branched from another shares its markers: its own thread starts here, with
    # the conversation as it is now (the parent's thread holds messages cut from this one)
    mine = not mk.get("owner") or not sid or mk.get("owner") == sid
    busy = mk.get("thread") in srv.threads
    fresh = getattr(T, "codex_fresh", False)          # a fallback retry: the failed attempt is in the old thread
    T.codex_fresh = False
    if same_provider and mine and not busy and not fresh:
        try:
            r = srv.request("thread/resume", {"threadId": mk["thread"], "cwd": cwd, "model": model,
                                              "modelProvider": provider_key, "config": config or None,
                                              "approvalPolicy": policy, "sandbox": sandbox}, timeout=120)
            thread = (r.get("thread") or {}).get("id") or mk["thread"]
        except CodexError as e:
            emit("notice", {"msg": f"could not continue Codex's thread ({str(e)[:160]}) — starting a new one with the conversation so far"})
            thread = None
    if not thread:
        try:
            r = srv.request("thread/start", {"cwd": cwd, "model": model, "modelProvider": provider_key,
                                             "config": config or None, "approvalPolicy": policy, "sandbox": sandbox,
                                             "developerInstructions": dev or None, "serviceName": "orbit"}, timeout=180)
        except CodexError as e:
            return fail(f"Codex could not start a thread: {e}")
        thread = (r.get("thread") or {}).get("id")
        if not thread: return fail("Codex did not start a thread")
    gap = gap_messages(messages, thread)
    prior = ce._prior_transcript(gap) if gap else ""

    old_mk = marker_of(messages) or {}
    prev_total = list((old_mk.get("usage_total") or {}).get(thread) or [0, 0]) if old_mk.get("thread") == thread else [0, 0]
    if sid: q.LAST_TURN.pop(sid, None)
    mk = {"thread": thread, "cwd": cwd, "model": spec.get("id"), "provider": provider_key or CHATGPT, "owner": sid}
    messages.append({"role": "user", "content": user_content, "t": time.time(), "codex": dict(mk)})
    umsg = messages[-1]
    _remember_thread(thread, sid)

    qq = srv.subscribe(thread)
    effort = str(getattr(T, "effort", None) or q.pinned_effort() or "").lower()
    params = {"threadId": thread, "input": _inputs(user_content, prior), "model": model}
    if effort in EFFORTS: params["effort"] = effort
    elif effort in ("max", "ultra"): params["effort"] = "xhigh"
    try:
        r = srv.request("turn/start", params, timeout=180)
    except CodexError as e:
        srv.unsubscribe(thread)
        emit("error", f"Codex could not start the answer: {e}"); emit("done", None)
        return ""
    turn_id = (r.get("turn") or {}).get("id")
    RUNS[sid or thread] = {"thread": thread, "turn": turn_id, "srv": srv}

    t0 = time.time()
    cur = None                        # the assistant step being written
    items = {}                        # item id -> {"kind", "t", "name", "args", "out"}
    final_text, error, status = "", None, None
    usage = {}
    interrupted = False
    last_ckpt = time.time()

    def step():
        nonlocal cur
        if cur is None:
            cur = {"role": "assistant", "content": "", "model": label, "t": time.time(), "codex_thread": thread}
            messages.append(cur)
        return cur

    def tool_start(iid, name, args):
        a = step()
        a.setdefault("tool_calls", []).append({"id": iid, "type": "function",
                                               "function": {"name": name, "arguments": json.dumps(args)}})
        items[iid] = {"name": name, "args": args, "t": time.time(), "out": ""}
        emit("tool", {"name": name, "args": args, "id": iid, "t": time.time()})

    def tool_done(iid, ok, output, extra=None):
        nonlocal cur
        it = items.get(iid) or {"name": "tool", "args": {}, "t": time.time(), "out": ""}
        secs = round(time.time() - it["t"], 2)
        text = str(output if output is not None else it["out"] or "")
        p = {"name": it["name"], "id": iid, "ok": ok, "secs": secs, "output": text[:4000]}
        if extra: p.update(extra)
        emit("tool_result", p)
        messages.append({"role": "tool", "tool_call_id": iid, "name": it["name"], "t": time.time(), "ok": ok,
                         "secs": secs, "content": text[:60000], "codex_thread": thread})

    def answer(rid, method, p):
        """Codex asks for approval, or for your input."""
        if method in ("item/commandExecution/requestApproval", "execCommandApproval"):
            cmd = p.get("command") or " ".join(p.get("command") or [])
            reason = "Codex wants to run a command" + (f": {p['reason']}" if p.get("reason") else "")
            if read_only:
                return srv.respond(rid, {"decision": "decline"})
            ok, always = _ask(approve, "run_command", {"command": cmd, "cwd": p.get("cwd") or cwd}, reason, "shell")
            return srv.respond(rid, {"decision": ("acceptForSession" if always else "accept") if ok else "decline"})
        if method in ("item/fileChange/requestApproval", "applyPatchApproval"):
            it = items.get(p.get("itemId")) or {}
            files = (it.get("args") or {}).get("files") or []
            reason = "Codex wants to change files" + (f": {p['reason']}" if p.get("reason") else "")
            if read_only:
                return srv.respond(rid, {"decision": "decline"})
            ok, always = _ask(approve, "write_file", {"path": files[0] if files else cwd, "files": files,
                                                      "diff": (it.get("args") or {}).get("diff", "")[:6000]}, reason, "apply_patch")
            return srv.respond(rid, {"decision": ("acceptForSession" if always else "accept") if ok else "decline"})
        if method == "item/permissions/requestApproval":
            reason = "Codex asks for more access" + (f": {p['reason']}" if p.get("reason") else "")
            ok, _always = (False, False) if read_only else _ask(approve, "permissions", {"permissions": p.get("permissions"),
                                                                                          "cwd": p.get("cwd")}, reason, "permissions")
            return srv.respond(rid, {"permissions": p.get("permissions") if ok else {}, "scope": "turn"})
        if method == "item/tool/requestUserInput":
            return srv.respond(rid, {"answers": {}})
        if method == "mcpServer/elicitation/request":
            return srv.respond(rid, {"action": "decline"})
        return srv.respond(rid, error=f"Orbit does not handle {method}")

    try:
        while True:
            if interrupted and time.time() - interrupted > 30:
                error = error or "Codex did not stop within 30 s; Orbit let go of the answer"
                break
            if cancel.is_set() and not interrupted:
                interrupted = time.time()
                try: srv.request("turn/interrupt", {"threadId": thread, "turnId": turn_id}, timeout=20)
                except CodexError: pass
            if max_minutes and not interrupted and (time.time() - t0) / 60 > float(max_minutes):
                emit("round_limit", {"rounds": len(items), "reason": "time", "pending": []})
                cancel.set()
            while inbox and not interrupted:
                note = inbox.popleft()
                text = note.get("text", "") if isinstance(note, dict) else str(note)
                try:
                    srv.request("turn/steer", {"threadId": thread, "expectedTurnId": turn_id,
                                               "input": [{"type": "text", "text": text}]}, timeout=30)
                    messages.append({"role": "user", "content": text, "t": time.time(), "interjection": True,
                                     "codex": dict(mk)})
                    emit("interjection", {"text": text})
                except CodexError as e:
                    emit("notice", {"msg": f"your note could not reach Codex mid-answer: {str(e)[:160]}"})
            if interrupt is not None: interrupt.clear()
            try:
                kind, method, p, rid = qq.get(timeout=0.5)
            except queue.Empty:
                if not srv.alive():
                    error = "Codex stopped unexpectedly: " + " ".join(srv.stderr[-3:])[:400]
                    break
                continue
            if kind == "exit":
                error = error or ("Codex stopped: " + " ".join(srv.stderr[-3:])[:400])
                break
            if kind == "request":
                threading.Thread(target=answer, args=(rid, method, p), daemon=True).start()
                continue
            if p.get("turnId") and turn_id and p["turnId"] != turn_id and method not in ("turn/completed",):
                continue
            if method == "item/agentMessage/delta":
                a = step()
                a["content"] += p.get("delta") or ""
                emit("content_delta", p.get("delta") or "")
            elif method in ("item/reasoning/summaryTextDelta", "item/reasoning/textDelta"):
                a = step()
                a["reasoning_content"] = (a.get("reasoning_content") or "") + (p.get("delta") or "")
                emit("thinking_delta", p.get("delta") or "")
            elif method == "item/started":
                it = p.get("item") or {}
                t = it.get("type")
                if t == "commandExecution":
                    tool_start(it["id"], "shell", {"command": it.get("command"), "cwd": it.get("cwd")})
                elif t == "fileChange":
                    ch = it.get("changes") or []
                    tool_start(it["id"], "apply_patch", {"path": ch[0]["path"] if ch else "",
                                                         "files": [x.get("path") for x in ch],
                                                         "diff": "\n".join(x.get("diff") or "" for x in ch)[:20000]})
                elif t == "mcpToolCall":
                    tool_start(it["id"], f"{it.get('server')}.{it.get('tool')}", it.get("arguments") or {})
                elif t == "dynamicToolCall":
                    tool_start(it["id"], f"{it.get('namespace') or ''}.{it.get('tool')}".lstrip("."), it.get("arguments") or {})
                elif t == "webSearch":
                    tool_start(it["id"], "web_search", {"query": it.get("query")})
                elif t in ("agentMessage", "reasoning"):
                    # what it says after running tools is the next step
                    if cur is not None and cur.get("tool_calls"): cur = None
                    step()
            elif method in ("item/commandExecution/outputDelta", "item/fileChange/outputDelta"):
                it = items.get(p.get("itemId"))
                if it is not None: it["out"] += p.get("delta") or ""
            elif method == "item/completed":
                it = p.get("item") or {}
                t = it.get("type")
                if t == "commandExecution":
                    ok = it.get("status") == "completed" and it.get("exitCode") in (0, None)
                    out = it.get("aggregatedOutput")
                    if out is None: out = (items.get(it["id"]) or {}).get("out") or ""
                    if it.get("exitCode") not in (0, None): out = f"(exit {it.get('exitCode')})\n" + out
                    tool_done(it["id"], ok, out)
                elif t == "fileChange":
                    ok = it.get("status") == "completed"
                    ch = it.get("changes") or []
                    for x in ch:
                        if x.get("path"):
                            path = x["path"] if os.path.isabs(x["path"]) else os.path.join(cwd, x["path"])
                            if not any(y.get("path") == path for y in T.changes):
                                T.changes.append({"path": path, "snap": None,
                                                  "created": (x.get("kind") or {}).get("type") == "add"})
                    diff = "\n".join(x.get("diff") or "" for x in ch)
                    tool_done(it["id"], ok, diff or it.get("status"),
                              {"diff": {"path": ch[0]["path"] if ch else "", "diff": diff[:20000],
                                        "added": diff.count("\n+"), "removed": diff.count("\n-")}} if diff else None)
                elif t == "mcpToolCall":
                    res = it.get("result")
                    out = json.dumps(res)[:60000] if res is not None and not isinstance(res, str) else (res or it.get("error") or "")
                    tool_done(it["id"], not it.get("error") and it.get("status") != "failed", out)
                elif t == "dynamicToolCall":
                    tool_done(it["id"], bool(it.get("success")), json.dumps(it.get("contentItems") or [])[:60000])
                elif t == "webSearch":
                    tool_done(it["id"], True, json.dumps(it.get("results") or it.get("action") or "")[:20000])
                elif t == "agentMessage":
                    a = step()
                    if it.get("text") and not a["content"]:
                        a["content"] = it["text"]
                        emit("content_delta", it["text"])
                    final_text = it.get("text") or a["content"] or final_text
                elif t == "contextCompaction":
                    emit("notice", {"msg": "Codex compacted the conversation to make room"})
            elif method == "turn/plan/updated":
                steps = p.get("plan") or []
                txt = "\n".join(f"[{'x' if s.get('status') == 'completed' else ' '}] {s.get('step')}" for s in steps)
                if txt:
                    try: q.PLANS[sid or "_"] = {"steps": [{"text": s.get("step"), "done": s.get("status") == "completed"} for s in steps],
                                                "updated": time.time()}
                    except Exception: pass
                    emit("tool_result", {"name": "plan", "output": txt})
            elif method == "thread/tokenUsage/updated":
                tu = p.get("tokenUsage") or {}
                usage = tu.get("total") or usage
                mk["usage_total"] = {thread: [int((usage or {}).get("inputTokens") or 0), int((usage or {}).get("outputTokens") or 0)]}
                last = tu.get("last") or {}
                mk["ctx"] = int(last.get("inputTokens") or 0)
                mk["ctx_max"] = int(tu.get("modelContextWindow") or 0)
                umsg["codex"] = dict(mk)
                if sid and mk["ctx"]:
                    try: q.SESSION_TOKENS[sid] = mk["ctx"]
                    except Exception: pass
            elif method == "error":
                err = p.get("error") or {}
                msg = err.get("message") if isinstance(err, dict) else str(err)
                if p.get("willRetry"):
                    emit("retry", {"attempt": None, "of": None, "wait": 0, "error": str(msg)[:300], "kind": "transient"})
                else:
                    error = msg
            elif method == "warning":
                msg = str(p.get("message") or "")
                if "metadata" not in msg: emit("notice", {"msg": msg[:300]})
            elif method == "turn/completed":
                turn = p.get("turn") or {}
                if turn.get("id") and turn_id and turn["id"] != turn_id: continue
                status = turn.get("status")
                if turn.get("error"):
                    e = turn["error"]
                    error = error or (e.get("message") if isinstance(e, dict) else str(e))
                break
            if checkpoint and time.time() - last_ckpt > 15:
                last_ckpt = time.time()
                try: checkpoint()
                except Exception: pass
    finally:
        srv.unsubscribe(thread)
        RUNS.pop(sid or thread, None)
        # a tool call that never reported back still gets an answer, or the next
        # model this chat moves to is sent a call with no result
        answered_ids = {m.get("tool_call_id") for m in messages if m.get("role") == "tool"}
        for iid in list(items):
            if iid not in answered_ids:
                it = items[iid]
                messages.append({"role": "tool", "tool_call_id": iid, "name": it["name"], "t": time.time(), "ok": False,
                                 "content": "(no result: the answer stopped before this finished)", "codex_thread": thread})

    # an empty step (nothing said, no tools) is not worth keeping
    if cur is not None and not cur.get("content") and not cur.get("tool_calls") and not cur.get("reasoning_content"):
        try: messages.remove(cur)
        except ValueError: pass
    rec = {}
    if usage:
        # the thread's totals so far, less where they stood before this answer
        rec = {"prompt_tokens": max(0, int(usage.get("inputTokens") or 0) - prev_total[0]),
               "completion_tokens": max(0, int(usage.get("outputTokens") or 0) - prev_total[1])}
        for m in reversed(messages):
            if m.get("role") == "assistant" and m.get("codex_thread") == thread:
                m["usage"], m["secs"] = rec, round(time.time() - t0, 1)
                break
    umsg["codex"] = dict(mk)
    if sid:
        try: q.LAST_TURN[sid] = {"secs": round(time.time() - t0, 1), "usage": rec, "tool_runs": len(items),
                                  "rounds": len(items), "changes": [x["path"] for x in T.changes], "t": time.time()}
        except Exception: pass
    answered = bool(final_text) or any(m.get("role") == "assistant" and m.get("codex_thread") == thread and m.get("content")
                                       for m in messages[messages.index(umsg):])
    if error and not interrupted and (status != "completed" or not answered):
        emit("error", f"Codex: {str(error)[:1200]}")
    emit("done", None)
    if checkpoint:
        try: checkpoint()
        except Exception: pass
    if interrupted:
        return (final_text or "") + "\n\n_(stopped)_"
    return final_text


def _ask(approve, fn, args, reason, tool):
    """(allowed, always) from Orbit's approval prompt."""
    if not approve: return False, False
    try:
        said = _ce()._call_approve(approve, fn, args, reason, {"codex": True, "tool": tool})
    except Exception:
        return False, False
    if isinstance(said, dict): return bool(said.get("allow")), bool(said.get("always"))
    if isinstance(said, tuple): return bool(said[0]), False
    return bool(said), False


# ------------------------------------------------------------------ threads Orbit owns

def _threads_path():
    d = os.path.join(Q.CONFIG, "codex")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "threads.json")


_THREADS_LOCK = threading.Lock()


def _remember_thread(thread, sid):
    """Which Orbit chat a Codex thread belongs to, so the sidebar's Codex section does
    not list it a second time."""
    if not sid: return
    with _THREADS_LOCK:
        try: d = json.load(open(_threads_path()))
        except (OSError, ValueError): d = {}
        if d.get(thread) == sid: return
        d[thread] = sid
        tmp = _threads_path() + f".{threading.get_ident()}.tmp"
        json.dump(d, open(tmp, "w")); os.replace(tmp, _threads_path())


def owned_threads():
    try: return json.load(open(_threads_path()))
    except (OSError, ValueError, TypeError): return {}


def info():
    """For Settings: installed, signed in, models, rate limits."""
    exe = which_codex()
    srv = _SERVER.get("srv")
    ver = None
    if exe:
        try:
            import providers
            ver = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10,
                                 env=providers.cli_env(exe)).stdout.strip()
        except Exception: pass
    return {"installed": bool(exe), "version": ver, "login": login_state(max_age=60),
            "models": [{"id": f"codex:{CHATGPT}/{m['slug']}", "label": m.get("display_name") or m["slug"]} for m in chatgpt_models()],
            "rate_limits": srv.rate_limits if srv else None, "running": bool(srv and srv.alive()),
            "chats_answering": len(RUNS)}
