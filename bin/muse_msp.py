"""Muse Code, driven over its own session protocol (`muse serve`, "MSP").

One turn = one `muse serve` process: start it, open (or resume) a session, submit the prompt,
read the notifications until the turn is over, shut it down. Newline-delimited JSON-RPC on
stdio, the same shape Codex's app-server has. Nothing here is guessed: the methods and
notifications are from `muse schema generate-json-schema` (MSP v1, Muse Code 1.4).

  initialize -> initialized -> session/start | session/resume -> turn/start
  item/started, item/delta, item/completed   the reply, its reasoning, tool calls
  session/tokenUsage                          usage;  turn/completed ends the turn

Safety: the OS sandbox stays ON (it is fixed when the host starts, and Orbit never disables it),
so with nobody to answer a prompt the approval mode is "allowAll" *inside that sandbox*. A chat in
plan mode starts the host with writes and shell off. A temporary chat uses memory-only sessions.
"""
import json, os, queue, subprocess, threading, time, uuid

CLIENT = {"name": "orbit", "title": "Orbit", "version": "1.0"}
EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")


class MuseError(RuntimeError):
    """Muse Code failed in a way worth showing as it is."""


class MuseResumeError(MuseError):
    """The session this chat was in is gone; start again with the whole conversation."""


def uuid7():
    """Commands carry UUIDv7 ids (the host refuses anything else)."""
    ms = int(time.time() * 1000)
    r = int.from_bytes(os.urandom(10), "big")
    n = (ms << 80) | (0x7 << 76) | (((r >> 62) & 0xFFF) << 64) | (0x2 << 62) | (r & ((1 << 62) - 1))
    return str(uuid.UUID(int=n))


class Host:
    """One `muse serve` process and the JSON-RPC conversation with it."""

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
                raise MuseError("Muse Code stopped: " + " ".join(self.stderr[-3:])[:300])

    def notify(self, method, params=None):
        self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def respond(self, rid, result=None):
        try: self._write({"jsonrpc": "2.0", "id": rid, "result": result if result is not None else {}})
        except MuseError: pass

    def request(self, method, params, timeout=60):
        with self.lock:
            self.next_id += 1
            rid = self.next_id
        ev = threading.Event()
        self.pending[rid] = [ev, None]
        self._write({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        if not ev.wait(timeout):
            self.pending.pop(rid, None)
            raise MuseError(f"Muse Code did not answer {method} within {timeout}s")
        reply = self.pending.pop(rid, [None, None])[1]
        if reply is None:
            raise MuseError("Muse Code stopped: " + " ".join(self.stderr[-3:])[:300])
        if reply.get("error"):
            e = reply["error"] or {}
            raise MuseError(str(e.get("message") or e))
        return reply.get("result") or {}

    def _read(self):
        for line in self.proc.stdout:
            try: m = json.loads(line)
            except ValueError: continue
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


def host_argv(exe, model=None, temp=False, read_only=False, provider=None):
    argv = [exe, "serve"]
    if provider: argv += ["--provider", provider]
    if model: argv += ["--model", model]
    if temp: argv.append("--no-session-log")           # memory-only: no session left on disk
    if read_only: argv += ["--disable-write", "--disable-shell"]
    return argv


def _tool_line(item):
    """One readable line for a finished tool call: `Bash  ls -la`, with the first line of its output."""
    label = ((item.get("displayLabel") or {}).get("done") or (item.get("displayLabel") or {}).get("neutral") or "").strip()
    name = item.get("tool") or "tool"
    arg = ""
    try:
        a = json.loads(item.get("args") or "{}")
        if isinstance(a, dict):
            arg = next((str(a[k]) for k in ("command", "cmd", "path", "file_path", "pattern", "query", "url") if a.get(k)),
                       next((str(v) for v in a.values() if isinstance(v, (str, int, float))), ""))
    except ValueError:
        arg = ""
    head = label or f"{name} {' '.join(arg.split())[:90]}".rstrip()
    out = str(item.get("visibleOutput") or "").strip().splitlines()
    tail = f" — {out[0][:100]}" if out else ""
    if item.get("status") not in (None, "completed", "inProgress"):
        tail = f" — {item.get('status')}" + (f": {str(item.get('failureReason'))[:100]}" if item.get("failureReason") else "")
    return f"⚙ {head}{tail}\n"


def _auth_problem(text):
    low = str(text or "").lower()
    return any(w in low for w in ("not logged in", "not signed in", "unauthenticated", "no credential", "api key",
                                  "authentication", "unauthorized", "sign in", "log in", "login"))


def run_turn(exe, prompt, cwd, *, model=None, effort=None, resume=None, temp=False, read_only=False, env=None,
             emit=None, cancel=None, timeout=900, images=(), provider=None):
    """One turn. -> {"text", "reasoning", "session", "usage": {...}|None, "tools": n}.

    resume: a session id from an earlier turn of this chat. If the host no longer has it,
    MuseResumeError is raised so the caller can send the whole conversation instead."""
    emit = emit or (lambda k, p: None)
    host = Host(host_argv(exe, model, temp, read_only, provider), env or os.environ.copy(), cwd or None)
    started = time.time()
    try:
        try:
            host.request("initialize", {"clientInfo": CLIENT, "capabilities": {"userInputDialogs": False}}, timeout=60)
            host.notify("initialized")
        except MuseError as e:
            raise MuseError(f"Could not start Muse Code: {e}") from None
        mode = "denyUnmatched" if read_only else "allowAll"
        sess = None
        if resume:
            try:
                got = host.request("session/resume", {"commandId": uuid7(), "sessionId": resume, "excludeItems": True}, timeout=60)
                sess = (got.get("session") or {}).get("sessionId") or resume
                host.request("session/setApprovalMode", {"commandId": uuid7(), "sessionId": sess, "mode": mode}, timeout=30)
            except MuseError as e:
                raise MuseResumeError(str(e)) from None
        else:
            p = {"commandId": uuid7(), "workspaceRoot": cwd or os.getcwd(), "approvalMode": mode}
            if model: p["modelId"] = model
            sess = (host.request("session/start", p, timeout=60).get("session") or {}).get("sessionId")
            if not sess: raise MuseError("Muse Code did not open a session.")

        parts = [{"type": "text", "text": prompt}]
        for img in images or ():
            try:
                import base64, mimetypes
                with open(img, "rb") as f:
                    parts.append({"type": "image", "mediaType": mimetypes.guess_type(img)[0] or "image/png",
                                  "base64Data": base64.b64encode(f.read()).decode("ascii")})
            except OSError:
                pass
        tp = {"commandId": uuid7(), "sessionId": sess, "input": parts}
        if effort in EFFORTS: tp["reasoningEffort"] = effort
        turn = host.request("turn/start", tp, timeout=60)
        turn_id = turn.get("turnId")

        live, whole, think, tools = [], {}, [], 0
        usage = {"prompt_tokens": 0, "completion_tokens": 0}
        seen_usage = False
        error, interrupted = None, None
        kinds = {}                                     # item id -> kind, to route deltas
        done = False
        while not done:
            if cancel is not None and cancel.is_set() and interrupted is None:
                interrupted = time.time()
                try: host.request("turn/interrupt", {"commandId": uuid7(), "sessionId": sess, "turnId": turn_id}, timeout=10)
                except MuseError: pass
            if interrupted and time.time() - interrupted > 15:
                raise MuseError("Muse Code did not stop within 15 s")
            if time.time() - started > timeout:
                raise MuseError(f"Muse Code produced no finished answer within {timeout}s")
            try: kind, method, p, rid = host.inbox.get(timeout=0.4)
            except queue.Empty:
                continue
            if kind == "exit":
                if live or whole: break
                raise MuseError("Muse Code stopped: " + (" ".join(host.stderr[-3:])[:300] or "no output"))
            if p.get("sessionId") not in (None, sess): continue
            if kind == "request":
                # nothing should need an answer here (the mode is allowAll inside the sandbox); if something
                # does, it is refused rather than left hanging
                host.respond(rid, {})
                try:
                    if method == "approval/request":
                        no = next((c for c in p.get("availableChoices") or [] if str(c.get("decision", "")).startswith("denied")), None)
                        if no: host.request("approval/decide", {"commandId": uuid7(), "sessionId": sess, "approvalId": p.get("approvalId"),
                                                                  "choiceId": no["choiceId"], "requirementId": p.get("currentRequirementId")}, timeout=15)
                    elif method == "userInput/request":
                        host.request("userInput/answer", {"commandId": uuid7(), "sessionId": sess, "userInputId": p.get("userInputId"),
                                                            "answers": []}, timeout=15)
                except MuseError:
                    pass
                continue
            if method == "item/started":
                it = p.get("item") or {}
                kinds[it.get("itemId")] = it.get("kind")
            elif method == "item/delta":
                k, field, d = kinds.get(p.get("itemId")), str(p.get("field") or ""), p.get("delta") or ""
                if k == "agentMessage" and field == "text" and d:
                    live.append(d); emit("content_delta", d)
                elif k == "reasoning" and d:
                    think.append(d); emit("thinking_delta", d)
            elif method == "item/completed":
                it = p.get("item") or {}
                k = it.get("kind")
                if k == "agentMessage":
                    whole[it.get("itemId")] = it.get("text") or ""
                elif k == "reasoning" and not think:
                    txt = it.get("text") or "\n".join(it.get("summary") or [])
                    if txt: think.append(txt); emit("thinking_delta", txt)
                elif k == "toolCall":
                    tools += 1
                    line = _tool_line(it)
                    think.append(line); emit("thinking_delta", line)
            elif method == "session/tokenUsage":
                u = p.get("usage") or {}
                seen_usage = True
                usage["prompt_tokens"] += int(u.get("inputTokens") or p.get("promptTokens") or 0)
                usage["completion_tokens"] += int(u.get("outputTokens") or 0)
            elif method == "turn/completed":
                if p.get("turnId") not in (None, turn_id): continue
                if p.get("terminal") == "failed":
                    e = p.get("error") or {}
                    error = e.get("message") or p.get("reason") or "the turn failed"
                    if e.get("quota"): error = "Muse allowance used up: " + str(error)
                done = True
        text = "".join(live) if live else "\n\n".join(t for t in whole.values() if t)
        if error and not text.strip():
            if _auth_problem(error):
                raise MuseError("Muse Code is not signed in (" + str(error)[:160] + "). Run `muse` in a terminal and use /login, "
                                "or save a Meta Model API key in Orbit's Settings.")
            raise MuseError(str(error)[:500])
        return {"text": text, "reasoning": "".join(think), "session": sess, "tools": tools,
                "usage": usage if seen_usage and (usage["prompt_tokens"] or usage["completion_tokens"]) else None}
    finally:
        host.close()
