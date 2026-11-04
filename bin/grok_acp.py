"""Grok CLI (xAI's Grok Build, `grok`), driven over ACP -- the Agent Client Protocol it speaks on
`grok agent stdio`: newline-delimited JSON-RPC on stdin/stdout.

One turn = one `grok agent stdio` process: start it, open (or load) a session, send the prompt, read
the updates until the prompt is answered, shut it down. The session lives in Grok's own history
(~/.grok/sessions), so the next turn of the chat loads it and sends only what is new.

  initialize -> session/new | session/load -> session/prompt
  session/update   agent_message_chunk, agent_thought_chunk, tool_call, tool_call_update, plan, usage
  session/request_permission   asks before a tool runs: Orbit answers by the chat's autonomy
  session/cancel   stops the turn

The methods are the published ACP v1 ones (agentclientprotocol.com); `grok agent stdio` is the
documented entry point (docs.x.ai/build/cli/headless-scripting). No file-system or terminal
capability is offered to the agent: it uses its own tools, in the folder of the chat.

Permissions: nobody is there to click in a headless turn, and over ACP Grok decides what to ask by the
person's own settings (it reads Claude's `defaultMode`), so the limit that holds is Grok's OS sandbox, chosen
by the chat's autonomy (see sandbox_profile). Any permission request that does arrive is answered by decide().
  Plan mode (read_only) and ask   read-only sandbox: reads everything, writes only to temp folders
  auto                            workspace sandbox: writes inside the chat's folder
  full                            no sandbox, always-approve
"""
import json, os, queue, re, subprocess, threading, time

CLIENT = {"name": "orbit", "title": "Orbit", "version": "1.0"}
EFFORTS = ("low", "medium", "high", "xhigh", "max")

# ACP tool kinds that only look; the rest change something
LOOKS = ("read", "search", "fetch", "think", "switch_mode")
# commands even Auto does not run unattended
_DESTRUCTIVE = re.compile(
    r"(\brm\s+-[a-z]*[rf][a-z]*\s+(/|~|\$HOME|\*)|\bsudo\b|\bmkfs\b|\bdd\s+if=|:\(\)\s*\{|"
    r"\bcurl\b[^|;]*\|\s*(ba|z)?sh\b|\bwget\b[^|;]*\|\s*(ba|z)?sh\b|\bgit\s+push\b[^;|]*(--force|\s-f\b)|"
    r"\bgit\s+reset\s+--hard\b|\bchmod\s+-R\s+7|>\s*/dev/sd|\bshutdown\b|\breboot\b)", re.I)


class GrokError(RuntimeError):
    """Grok failed in a way worth showing as it is."""


class GrokResumeError(GrokError):
    """The session this chat was in is gone; start again with the whole conversation."""


class Host:
    """One `grok agent stdio` process and the JSON-RPC conversation with it."""

    def __init__(self, argv, env, cwd):
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     env=env, cwd=cwd, text=True, bufsize=1, start_new_session=True)
        self.lock = threading.Lock()
        self.next_id = 0
        self.pending = {}                # id -> [Event, reply]
        self.inbox = queue.Queue()       # ("notify"|"request", method, params, id) and ("exit", ...)
        self.stderr = []
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._read_err, daemon=True).start()

    def alive(self):
        return self.proc.poll() is None

    def _write(self, obj):
        with self.lock:
            try:
                self.proc.stdin.write(json.dumps(obj) + "\n")
                self.proc.stdin.flush()
            except (OSError, ValueError):
                raise GrokError("Grok stopped: " + " ".join(self.stderr[-3:])[:300])

    def notify(self, method, params=None):
        self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def respond(self, rid, result=None, error=None):
        msg = {"jsonrpc": "2.0", "id": rid}
        if error is not None: msg["error"] = error
        else: msg["result"] = result if result is not None else {}
        try: self._write(msg)
        except GrokError: pass

    def send(self, method, params):
        """Send a request without waiting: -> (id, event). The reply is read with reply()."""
        with self.lock:
            self.next_id += 1
            rid = self.next_id
        ev = threading.Event()
        self.pending[rid] = [ev, None]
        self._write({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        return rid, ev

    def reply(self, rid):
        """The result of a finished request; raises GrokError (with .code) for an error reply."""
        got = self.pending.pop(rid, [None, None])[1]
        if got is None:
            raise GrokError("Grok stopped: " + " ".join(self.stderr[-3:])[:300])
        if got.get("error"):
            e = got["error"] if isinstance(got["error"], dict) else {"message": str(got["error"])}
            err = GrokError(str(e.get("message") or e))
            err.code, err.data = e.get("code"), e.get("data")
            raise err
        return got.get("result") or {}

    def request(self, method, params, timeout=60):
        rid, ev = self.send(method, params)
        if not ev.wait(timeout):
            self.pending.pop(rid, None)
            raise GrokError(f"Grok did not answer {method} within {timeout}s")
        return self.reply(rid)

    def _read(self):
        for line in self.proc.stdout:
            try: m = json.loads(line)
            except ValueError: continue            # a log line, not a message
            if not isinstance(m, dict): continue
            method = m.get("method")
            if method is None and "id" in m:
                w = self.pending.get(m["id"])
                if w: w[1] = m; w[0].set()
            elif "id" in m:
                self.inbox.put(("request", method, m.get("params") or {}, m["id"]))
            else:
                self.inbox.put(("notify", method, m.get("params") or {}, None))
        for w in list(self.pending.values()):
            w[0].set()
        self.inbox.put(("exit", None, {}, None))

    def _read_err(self):
        for line in self.proc.stderr:
            self.stderr.append(line.rstrip())
            del self.stderr[:-40]

    def close(self):
        try: self.proc.stdin.close()
        except Exception: pass
        if self.alive():
            try: self.proc.terminate(); self.proc.wait(5)
            except Exception:
                try: self.proc.kill()
                except Exception: pass


def sandbox_profile(autonomy, read_only=False):
    """The OS sandbox Grok runs in for a chat. Over ACP Grok decides what to ask by the person's own settings
    (it reads Claude's `defaultMode`, so a person on auto never gets asked), and there is no way to request
    Ask or Plan mode, so the limit that holds is the kernel's (Seatbelt on a Mac): Plan and Ask can read
    everything and write only to temp folders; Auto writes inside the chat's folder; Full is unsandboxed."""
    if read_only: return "read-only"
    if autonomy == "full": return "off"
    if autonomy == "auto": return "workspace"
    return "read-only"


def host_argv(exe, model=None, effort=None, temp=False, read_only=False, autonomy=None):
    argv = [exe, "--no-auto-update", "agent"]            # a script must not update itself
    if model: argv += ["--model", model]
    if effort in EFFORTS: argv += ["--effort", effort]
    return argv + ["stdio"]


def _auth_problem(text):
    low = str(text or "").lower()
    return any(w in low for w in ("not logged in", "not signed in", "unauthenticated", "no credential", "api key",
                                  "authentication", "auth required", "unauthorized", "sign in", "log in", "login",
                                  "xai_api_key"))


def _text_of(block):
    """The text of one ACP content block (or of a tool call's content list)."""
    if isinstance(block, dict):
        if block.get("type") == "text": return str(block.get("text") or "")
        if block.get("type") == "content": return _text_of(block.get("content"))
        if block.get("type") == "diff": return f"edit {block.get('path') or ''}".strip()
        if block.get("type") == "terminal": return ""
        return ""
    if isinstance(block, list): return "\n".join(t for t in (_text_of(b) for b in block) if t)
    return ""


def _command_of(call):
    """The shell command a tool call carries, if it is one."""
    raw = call.get("rawInput")
    if isinstance(raw, dict):
        for k in ("command", "cmd", "script"):
            if raw.get(k): return " ".join(raw[k]) if isinstance(raw[k], list) else str(raw[k])
    title = str(call.get("title") or "")
    return title if call.get("kind") == "execute" else ""


def decide(call, autonomy, read_only):
    """(allow, why) for one permission request: the tool call ACP describes, the chat's autonomy."""
    kind = str(call.get("kind") or "other")
    if kind in LOOKS: return True, ""
    what = (call.get("title") or kind).strip()
    if read_only: return False, what
    if autonomy == "full": return True, ""
    if autonomy == "auto":
        if kind == "delete": return False, what
        cmd = _command_of(call)
        if cmd and _DESTRUCTIVE.search(cmd): return False, cmd
        return True, ""
    return False, what


def pick_option(options, allow, always=False):
    """The option id to answer a permission request with; None if the agent offers no fitting one."""
    want = ("allow_always", "allow_once") if always else ("allow_once", "allow_always")
    if not allow: want = ("reject_once", "reject_always")
    for kind in want:
        for o in options or []:
            if isinstance(o, dict) and o.get("kind") == kind and o.get("optionId"): return o["optionId"]
    return None


def _tool_line(call):
    """One readable line for a tool call: `⚙ Run ls -la — first line of what it printed`."""
    title = " ".join(str(call.get("title") or call.get("kind") or "tool").split())[:140]
    out = _text_of(call.get("content")).strip().splitlines()
    first = " ".join(out[0].split())[:100] if out else ""
    if call.get("status") == "failed": tail = " — failed" + (f": {first}" if first else "")
    else: tail = f" — {first}" if first else ""
    return f"⚙ {title}{tail}\n"


def run_turn(exe, prompt, cwd, *, model=None, effort=None, resume=None, temp=False, read_only=False, autonomy=None,
             env=None, emit=None, cancel=None, timeout=900, images=()):
    """One turn. -> {"text", "reasoning", "session", "usage": {...}|None, "tools": n, "denied": [..]}.

    resume: a session id from an earlier turn of this chat. If Grok no longer has it,
    GrokResumeError is raised so the caller can send the whole conversation instead."""
    emit = emit or (lambda k, p: None)
    cwd = os.path.abspath(cwd or os.getcwd())
    henv = dict(env or os.environ)
    henv["GROK_SANDBOX"] = sandbox_profile(autonomy, read_only)
    host = Host(host_argv(exe, model, effort, temp, read_only, autonomy), henv, cwd)
    started = time.time()
    try:
        try:
            init = host.request("initialize", {"protocolVersion": 1, "clientInfo": CLIENT, "clientCapabilities": {}}, timeout=60)
        except GrokError as e:
            raise GrokError(f"Could not start Grok: {e}") from None
        caps = init.get("agentCapabilities") or {}
        methods = init.get("authMethods") or []

        def authed(fn):
            """Run `fn`; if Grok says it must be signed in, try the API-key method once (XAI_API_KEY)."""
            try:
                return fn()
            except GrokError as e:
                if getattr(e, "code", None) != -32000 and not _auth_problem(e): raise
                key = (env or os.environ).get("XAI_API_KEY")
                meth = next((m for m in methods if isinstance(m, dict) and "key" in str(m.get("id", "")).lower()), None)
                if key and not meth:
                    raise GrokError("xAI did not accept the API key (" + str(e)[:160] + "). Check the key in Orbit's "
                                    "Settings, or remove it and sign in with `grok login`.") from None
                if not (key and meth):
                    raise GrokError("Grok is not signed in (" + str(e)[:160] + "). Run `grok` in a terminal and sign in "
                                    "(`grok login`), or save an xAI API key in Orbit's Settings.") from None
                host.request("authenticate", {"methodId": meth["id"]}, timeout=30)
                return fn()

        sess = None
        if resume:
            if not caps.get("loadSession"):
                raise GrokResumeError("this Grok cannot load an earlier session")
            try:
                authed(lambda: host.request("session/load", {"sessionId": resume, "cwd": cwd, "mcpServers": []}, timeout=120))
            except GrokError as e:
                raise GrokResumeError(str(e)) from None
            sess = resume
            # loading replays the earlier conversation as updates: that is history, not this answer
            try:
                while True: host.inbox.get_nowait()
            except queue.Empty:
                pass
        else:
            new = {"cwd": cwd, "mcpServers": []}
            if autonomy == "full" and not read_only: new["_meta"] = {"yoloMode": True}      # always-approve for this session
            got = authed(lambda: host.request("session/new", new, timeout=60))
            sess = got.get("sessionId")
            if not sess: raise GrokError("Grok did not open a session.")

        blocks = [{"type": "text", "text": prompt}]
        for img in images or ():
            try:
                import base64, mimetypes
                with open(img, "rb") as f:
                    blocks.append({"type": "image", "mimeType": mimetypes.guess_type(img)[0] or "image/png",
                                   "data": base64.b64encode(f.read()).decode("ascii")})
            except OSError:
                pass
        rid, done_ev = host.send("session/prompt", {"sessionId": sess, "prompt": blocks})

        live, think, calls = [], [], {}
        tools, denied = 0, []
        usage = {"prompt_tokens": 0, "completion_tokens": 0}
        interrupted = None
        while True:
            if cancel is not None and cancel.is_set() and interrupted is None:
                interrupted = time.time()
                try: host.notify("session/cancel", {"sessionId": sess})
                except GrokError: pass
            if interrupted and time.time() - interrupted > 15:
                raise GrokError("Grok did not stop within 15 s")
            if time.time() - started > timeout:
                raise GrokError(f"Grok produced no finished answer within {timeout}s")
            if done_ev.is_set() and host.inbox.empty(): break
            try: kind, method, p, qid = host.inbox.get(timeout=0.3)
            except queue.Empty:
                continue
            if kind == "exit":
                if done_ev.is_set(): break
                if live: break
                raise GrokError("Grok stopped: " + (" ".join(host.stderr[-3:])[:300] or "no output"))
            if p.get("sessionId") not in (None, sess): continue
            if kind == "request":
                if method == "session/request_permission":
                    call = p.get("toolCall") or {}
                    allow, why = decide(call, autonomy, read_only)
                    opt = pick_option(p.get("options"), allow, always=(autonomy == "full"))
                    if not allow and why and why not in denied: denied.append(why)
                    if opt: host.respond(qid, {"outcome": {"outcome": "selected", "optionId": opt}})
                    else: host.respond(qid, {"outcome": {"outcome": "cancelled"}})
                else:                                   # fs/* and terminal/*: none was offered
                    host.respond(qid, error={"code": -32601, "message": f"Orbit does not handle {method}"})
                continue
            if method != "session/update": continue
            u = p.get("update") or {}
            what = u.get("sessionUpdate")
            if what == "agent_message_chunk":
                t = _text_of(u.get("content"))
                if t: live.append(t); emit("content_delta", t)
            elif what == "agent_thought_chunk":
                t = _text_of(u.get("content"))
                if t: think.append(t); emit("thinking_delta", t)
            elif what == "tool_call":
                tools += 1
                calls[u.get("toolCallId")] = dict(u)
                if u.get("status") in ("completed", "failed"):
                    line = _tool_line(u); think.append(line); emit("thinking_delta", line)
                    calls[u.get("toolCallId")]["_shown"] = True
            elif what == "tool_call_update":
                c = calls.setdefault(u.get("toolCallId"), {})
                c.update({k: v for k, v in u.items() if k != "sessionUpdate" and v is not None})
                if c.get("status") in ("completed", "failed") and not c.get("_shown"):
                    c["_shown"] = True
                    line = _tool_line(c); think.append(line); emit("thinking_delta", line)
            elif what == "usage_update":
                pass                                    # the context's size, not this turn's cost
        res = host.reply(rid)
        stop = res.get("stopReason")
        ru = res.get("usage") or (res.get("_meta") or {}).get("usage") or {}
        if isinstance(ru, dict):
            usage["prompt_tokens"] = int(ru.get("inputTokens") or ru.get("input_tokens") or 0)
            usage["completion_tokens"] = int(ru.get("outputTokens") or ru.get("output_tokens") or 0)
        text = "".join(live)
        if stop == "refusal" and not text.strip():
            raise GrokError("Grok declined to answer this.")
        return {"text": text, "reasoning": "".join(think), "session": sess, "tools": tools, "denied": denied,
                "stopped": stop == "cancelled",
                "usage": usage if usage["prompt_tokens"] or usage["completion_tokens"] else None}
    except GrokError as e:
        if _auth_problem(e) and "not signed in" not in str(e):
            raise GrokError("Grok is not signed in (" + str(e)[:160] + "). Run `grok` in a terminal and sign in "
                            "(`grok login`), or save an xAI API key in Orbit's Settings.") from None
        raise
    finally:
        host.close()
