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
import io, json, os, queue, re, shutil, subprocess, threading, time, uuid

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

    def __init__(self, exe, env, spawn=None, host=None):
        self.exe, self.env, self.spawn, self.host = exe, env, spawn, host
        self.proc = None
        self.inp = self.out = None
        self.forward_port = None      # on an SSH host: the tunnel's port there, back to Orbit's gateway
        self.home = None
        self.used = time.time()
        self.lock = threading.Lock()
        self.next_id = 0
        self.pending = {}            # id -> [Event, reply]
        self.threads = {}            # thread id -> Queue of ("notify"|"request", method, params, id)
        self.stderr = []
        self.rate_limits = None

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        if self.spawn:
            self.proc = self.spawn()               # over SSH, on another machine
        else:
            self.proc = subprocess.Popen([self.exe, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, env=self.env,
                                         cwd=os.path.expanduser("~"), start_new_session=True)
        self.inp = io.TextIOWrapper(self.proc.stdin, encoding="utf-8", line_buffering=True, write_through=True)
        self.out = io.TextIOWrapper(self.proc.stdout, encoding="utf-8", errors="replace")
        self.err = io.TextIOWrapper(self.proc.stderr, encoding="utf-8", errors="replace")
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._read_err, daemon=True).start()
        self.request("initialize", {"clientInfo": {"name": "orbit", "title": "Orbit", "version": "1.0"}}, timeout=60)
        self.notify("initialized", {})

    def _write(self, obj):
        with self.lock:
            if not self.alive(): raise CodexError("Codex stopped")
            try:
                self.inp.write(json.dumps(obj) + "\n")
                self.inp.flush()
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
        for line in self.out:
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
        for line in self.err:
            self.stderr.append(line.rstrip())
            del self.stderr[:-60]

    def close(self):
        if self.inp is not None:
            try: self.inp.close()                  # on a host, the watchdog there ends Codex when SSH goes
            except Exception: pass
        if self.alive():
            try: self.proc.terminate(); self.proc.wait(5)
            except Exception:
                try: self.proc.kill()
                except Exception: pass


_SERVERS = {}            # "" (this Mac) or an SSH host -> {"srv", "sig"}
_SERVER_LOCK = threading.Lock()
_SERVER = {}             # kept for callers that read the local one


def server(host=None, emit=None):
    """The app-server for this Mac or an SSH host, started (or restarted) as needed.
    On a host, Codex runs there under the SSH watchdog, and reaches Orbit's gateway
    through a reverse tunnel; one connection serves every chat on that host."""
    key = host or ""
    tok = _ce().gateway_token()
    if not host:
        exe = which_codex()
        if not exe: raise CodexError("Codex is not installed (no `codex` on PATH). Install it with `brew install codex`.")
        import providers
        env = providers.cli_env(exe)
        env["ORBIT_GATEWAY_TOKEN"] = tok
        sig, spawn, info = (exe, tok), None, {}
    else:
        info = remote_codex(host, emit)
        exe = info["codex"]
        sig = (host, exe, tok)
        env = {}
        import ssh_remote
        # Codex's state database (an index of its sessions) on the node's own disk: a home
        # folder on network storage, shared by several login nodes, fails to open it
        user = os.path.basename((info.get("home") or "").rstrip("/")) or "user"
        sqlite_home = f"/tmp/orbit-codex-{re.sub(r'[^A-Za-z0-9_.-]', '_', user)}"
        ssh_remote.run(host, f"mkdir -p -m 700 {sqlite_home}", timeout=45)
        def spawn(exe=exe, host=host):
            port = ssh_remote.pick_port()
            p = ssh_remote.popen(host, exe, "~", ["app-server"],
                                 {"ORBIT_GATEWAY_TOKEN": tok, "CODEX_SQLITE_HOME": sqlite_home},
                                 forward=(port, _ce().gateway_port()))
            p.orbit_port = port
            return p
    with _SERVER_LOCK:
        cur = _SERVERS.get(key) or {}
        srv = cur.get("srv")
        if srv is None or not srv.alive() or cur.get("sig") != sig:
            if srv is not None: srv.close()
            srv = AppServer(exe, env, spawn=spawn, host=host)
            srv.start()
            if host:
                srv.forward_port = getattr(srv.proc, "orbit_port", None)
                srv.home = info.get("home")
            _SERVERS[key] = {"srv": srv, "sig": sig}
            if not host: _SERVER["srv"] = srv
            _start_reaper()
        srv.used = time.time()
        return srv


def remote_codex(host, emit=None):
    """Codex on an SSH host: found, or installed there (the official Linux build of this
    Mac's version, in ~/.local/bin) when `codex_remote_install` is on."""
    import ssh_remote
    info = ssh_remote.probe(host, max_age=1800)
    if not info.get("ok"):
        ssh_remote._PROBES.pop(host, None)
        raise CodexError(f"Could not reach {host}: {info.get('error') or 'SSH failed'}")
    ver = local_version()
    have = info.get("codex_version") or ""
    if info.get("codex") and not _older(have, ver): return info
    if not cfg().get("remote_install", True):
        if info.get("codex"): return info                 # an older Codex there, and you install it yourself
        raise CodexError(f"Codex is not installed on {host}. Install it there (or turn on installing it for you in Settings → Codex).")
    if emit: emit("notice", {"msg": (f"Codex {have} on {host} is older than this Mac's {ver}; " if have else "")
                             + f"installing Codex {ver} there (~/.local/bin/codex) — once, about a minute"})
    path, err = ssh_remote.install_codex(host, ver, os.path.join(Q.ROOT, "cache", "codex-linux"), info.get("arch") or "x86_64")
    ssh_remote._PROBES.pop(host, None)
    if err: raise CodexError(f"Could not install Codex on {host}: {err}")
    info = ssh_remote.probe(host, refresh=True)
    if not info.get("codex") or _older(info.get("codex_version") or "", ver):
        # the newest one wins on the probe; point at what was just installed if the other is still found first
        info = dict(info, codex=path, codex_version=ver)
    return info


def _older(a, b):
    """Is version a older than version b? (unknown versions are not older)"""
    try:
        return tuple(int(x) for x in re.findall(r"\d+", a)[:3]) < tuple(int(x) for x in re.findall(r"\d+", b)[:3])
    except (TypeError, ValueError):
        return False


def local_version():
    exe = which_codex()
    try:
        import providers
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10, env=providers.cli_env(exe)).stdout
        m = re.search(r"(\d+\.\d+\.\d+)", out)
        return m.group(1) if m else None
    except Exception:
        return None


_REAPER = {"on": False}


def _start_reaper():
    """Codex left idle on an SSH host is closed (login nodes limit processes); the next
    message starts it again. `remote_keep_alive_min`, as for Claude Code."""
    if _REAPER["on"]: return
    _REAPER["on"] = True
    def loop():
        while True:
            time.sleep(60)
            try: reap_idle()
            except Exception: pass
    threading.Thread(target=loop, daemon=True).start()


def reap_idle(now=None):
    now = now or time.time()
    try: keep = float(cfg().get("remote_keep_alive_min") or 30) * 60
    except (TypeError, ValueError): keep = 1800
    with _SERVER_LOCK:
        for key, cur in list(_SERVERS.items()):
            srv = cur["srv"]
            if not key or srv.threads: continue                 # this Mac's stays; a busy one stays
            if not srv.alive() or now - srv.used > keep:
                srv.close(); _SERVERS.pop(key, None)


def shutdown():
    with _SERVER_LOCK:
        for cur in _SERVERS.values():
            try: cur["srv"].close()
            except Exception: pass
        _SERVERS.clear()
        _SERVER.clear()


# ------------------------------------------------------------------ chats

def marker_of(messages):
    """This chat's Codex thread: {"thread", "cwd", "model", "provider", "owner"}. A chat
    opened from a Codex session (agent marker) continues that same thread."""
    for m in reversed(messages or []):
        if not isinstance(m, dict): continue
        if isinstance(m.get("codex"), dict) and m["codex"].get("thread"): return m["codex"]
        a = m.get("agent")
        if isinstance(a, dict) and a.get("source") == "codex" and a.get("id"):
            return {"thread": a["id"], "cwd": a.get("cwd"), "provider": None, "imported": True,
                    "rewound": bool(a.get("rewound"))}
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
    # Orbit / Claude permission mode -> (Codex approval policy, sandbox, who reviews what Codex asks)
    "plan": ("on-request", "read-only", "user"),
    "bypassPermissions": ("never", "danger-full-access", "user"),
    "dontAsk": ("never", "workspace-write", "user"),
    "acceptEdits": ("on-request", "workspace-write", "user"),
    # Auto: Codex's own automatic review decides what it asks, as Claude Code's Auto does
    "auto": ("on-request", "workspace-write", "auto_review"),
    "manual": ("untrusted", "workspace-write", "user"),
    "default": ("untrusted", "workspace-write", "user"),
}


def permissions(mode, sandbox_works=True):
    """(approval policy, sandbox, reviewer) for a chat's permission mode. Where Codex's
    sandbox cannot start (a Linux host without bubblewrap), commands run unsandboxed:
    Auto then has the automatic reviewer judge each command, the other modes ask you."""
    policy, sandbox, reviewer = PERMISSIONS.get(mode, PERMISSIONS["auto"])
    if not sandbox_works and sandbox != "danger-full-access":
        if sandbox == "read-only": return "untrusted", "danger-full-access", reviewer
        if mode == "dontAsk": return "never", "danger-full-access", reviewer
        return "untrusted", "danger-full-access", reviewer
    return policy, sandbox, reviewer
EFFORTS = ("minimal", "low", "medium", "high", "xhigh")


def provider_config(spec, port=None):
    """(modelProvider, config) for a thread, and the model name Codex should ask for.
    port: where Orbit's gateway is reached from where Codex runs (a tunnel on an SSH host)."""
    c = spec.get("codex") or {}
    pid, model = c.get("provider"), c.get("model")
    if pid == CHATGPT:
        return None, {}, model
    key = f"orbit-{pid}"
    cfg = {"model_providers": {key: {"name": f"Orbit · {spec.get('provider_label') or pid}".replace("Codex · ", ""),
                                     "base_url": f"http://127.0.0.1:{port or _ce().gateway_port()}/h/{pid}/v1",
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


def host_for(sid, mk, prefs=None):
    """Where a Codex chat runs: the host its thread started on, the one chosen for the
    chat, or for a new chat the default machine (None = this Mac)."""
    prefs = prefs if prefs is not None else (_ce().chat_prefs(sid) if sid else {})
    if mk and mk.get("thread") and not mk.get("imported"): return mk.get("host") or None
    if "host" in prefs: return prefs.get("host") or None
    return cfg().get("default_host") or None


def _remote_cwd(host, prefs, mk, home):
    cwd = (mk or {}).get("cwd") if (mk or {}).get("host") == host else None
    cwd = cwd or prefs.get("cwd") or _ce().default_remote_dir(host) or "~"
    if home and (cwd == "~" or cwd.startswith("~/")): cwd = home + cwd[1:]
    return cwd


def _cwd_for(sid, project, mk):
    ce = _ce()
    prefs = ce.chat_prefs(sid) if sid else {}
    if mk and mk.get("cwd") and not mk.get("host") and os.path.isdir(mk["cwd"]): return mk["cwd"], prefs
    folder = None
    try: folder = Q.project_folder(project) if project else None
    except Exception: folder = None
    cwd = prefs.get("cwd") or folder or (cfg().get("default_dir") or "").strip() or Q.WORKSPACE
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
    mk = dict(marker_of(messages) or {})
    prefs0 = ce.chat_prefs(sid) if sid else {}
    host = host_for(sid, mk, prefs0)
    if not which_codex():
        return fail("Codex is not installed (no `codex` on PATH). Install it (`brew install codex`), or pick another model.")
    if not host and c.get("provider") == CHATGPT and login_state(max_age=30) != "chatgpt":
        return fail("Codex is not signed in to a ChatGPT account on this Mac. In a terminal run `codex login`, "
                    "then send this again — or pick a Codex model from another provider.")
    if c.get("provider") != CHATGPT:
        h = spec.get("harness") or {}
        pc = h.get("provider_cfg") or {}
        if not pc.get("api_key") and not pc.get("local") and not pc.get("keyless"):
            return fail(f"No API key for {spec.get('provider_label') or c.get('provider')}. "
                        "Add it in Settings → Models & keys.")
    if host: emit("status", {"msg": f"starting Codex on {host}"})
    try:
        srv = server(host, emit)
    except Exception as e:
        return fail(f"Codex could not start{' on ' + host if host else ''}: {e}")
    if host and c.get("provider") == CHATGPT:
        import ssh_remote
        st = str((ssh_remote._PROBES.get(host) or {}).get("codex_login") or "")
        if "chatgpt" not in st.lower():
            return fail(f"Codex on {host} is not signed in to a ChatGPT account. Sign in there once "
                        f"(`codex login --device-auth` in a terminal on {host}), or use Copy this Mac's sign-in "
                        f"in the chat's Codex panel — or pick a Codex model from another provider, which needs no sign-in there.")

    if host:
        prefs = prefs0
        cwd = _remote_cwd(host, prefs, mk, srv.home)
    else:
        cwd, prefs = _cwd_for(sid, project, mk)
    provider_key, config, model = provider_config(spec, srv.forward_port if host else None)
    mode = "plan" if read_only else (prefs.get("permission_mode") or cfg().get("permission_mode") or "auto")
    sandbox_works = True
    if host:
        import ssh_remote
        pinfo = ssh_remote._PROBES.get(host) or {}
        sandbox_works = bool(pinfo.get("bwrap")) or "bwrap" not in pinfo
    policy, sandbox, reviewer = permissions(mode, sandbox_works)
    if host and not mk.get("thread"):
        # a new chat's folder there, so Codex does not start somewhere else
        import ssh_remote, shlex
        ssh_remote.run(host, "mkdir -p " + shlex.quote(cwd), timeout=45)
    if prefs.get("add_dirs") and sandbox == "workspace-write" and not host:
        config = {**config, "sandbox_workspace_write": {"writable_roots": list(prefs["add_dirs"])}}
    dev = ""
    if cfg().get("orbit_context", True):
        try: dev = "\n\n".join(ce._system_parts(project))
        except Exception: pass
    if cfg().get("developer_instructions"):
        dev = (dev + "\n\n" if dev else "") + str(cfg()["developer_instructions"])

    thread = None
    same_provider = mk.get("thread") and (mk.get("imported") or mk.get("provider") == (provider_key or CHATGPT))
    # a chat branched from another shares its markers: its own thread starts here, with
    # the conversation as it is now (the parent's thread holds messages cut from this one)
    mine = not mk.get("owner") or not sid or mk.get("owner") == sid
    busy = mk.get("thread") in srv.threads
    if (mk.get("host") or None) != host and not mk.get("imported"): same_provider = False    # its thread is on another machine
    fresh = getattr(T, "codex_fresh", False)          # a fallback retry: the failed attempt is in the old thread
    # the chat was rewound past what Codex's thread holds: a new thread gets the chat as it is now
    fresh = fresh or bool(mk.get("rewound"))
    T.codex_fresh = False
    if same_provider and mine and not busy and not fresh:
        try:
            r = srv.request("thread/resume", {"threadId": mk["thread"], "cwd": cwd, "model": model,
                                              "modelProvider": provider_key, "config": config or None,
                                              "approvalPolicy": policy, "sandbox": sandbox,
                                              "approvalsReviewer": reviewer}, timeout=120)
            thread = (r.get("thread") or {}).get("id") or mk["thread"]
        except CodexError as e:
            emit("notice", {"msg": f"could not continue Codex's thread ({str(e)[:160]}) — starting a new one with the conversation so far"})
            thread = None
    if not thread:
        try:
            r = srv.request("thread/start", {"cwd": cwd, "model": model, "modelProvider": provider_key,
                                             "config": config or None, "approvalPolicy": policy, "sandbox": sandbox,
                                             "approvalsReviewer": reviewer,
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
    if host: mk["host"] = host
    messages.append({"role": "user", "content": user_content, "t": time.time(), "codex": dict(mk)})
    umsg = messages[-1]
    _remember_thread(thread, sid)

    qq = srv.subscribe(thread)
    effort = str(getattr(T, "effort", None) or q.pinned_effort() or cfg().get("default_effort") or "").lower()
    params = {"threadId": thread, "input": _inputs(user_content, prior), "model": model,
              "approvalPolicy": policy, "approvalsReviewer": reviewer}    # a mode changed since the thread began applies now
    if effort in EFFORTS: params["effort"] = effort
    elif effort in ("max", "ultra"): params["effort"] = "xhigh"
    try:
        r = srv.request("turn/start", params, timeout=180)
    except CodexError as e:
        srv.unsubscribe(thread)
        emit("error", f"Codex could not start the answer: {e}"); emit("done", None)
        return ""
    turn_id = (r.get("turn") or {}).get("id")
    RUNS[sid or thread] = {"thread": thread, "turn": turn_id, "srv": srv, "host": host}

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
            reason = "Codex wants to run a command" + (f" on {host}" if host else "") + (f": {p['reason']}" if p.get("reason") else "")
            if read_only:
                return srv.respond(rid, {"decision": "decline"})
            if mode == "auto":
                # Auto: Orbit's own safety check decides, as for its own agent. Everyday commands
                # run; anything destructive or risky is put to you; the unrecoverable is refused.
                verdict, why = auto_verdict(cmd)
                if verdict == "allow":
                    emit("auto_approved", {"name": "shell", "args": {"command": cmd}, "reason": "Auto: " + (why or "no risk found")})
                    return srv.respond(rid, {"decision": "accept"})
                if verdict == "refuse":
                    emit("blocked", {"name": "shell", "reason": why})
                    return srv.respond(rid, {"decision": "decline"})
                reason = f"{reason} — {why}" if why else reason
            ok, always = _ask(approve, "run_command", {"command": cmd, "cwd": p.get("cwd") or cwd}, reason, "shell")
            return srv.respond(rid, {"decision": ("acceptForSession" if always else "accept") if ok else "decline"})
        if method in ("item/fileChange/requestApproval", "applyPatchApproval"):
            it = items.get(p.get("itemId")) or {}
            files = (it.get("args") or {}).get("files") or []
            reason = "Codex wants to change files" + (f": {p['reason']}" if p.get("reason") else "")
            if read_only:
                return srv.respond(rid, {"decision": "decline"})
            inside = all(not os.path.isabs(f) or f == cwd or f.startswith(cwd.rstrip("/") + "/") for f in files)
            if mode in ("auto", "acceptEdits") and inside:
                emit("auto_approved", {"name": "apply_patch", "args": {"files": files}, "reason": "edits inside the chat's folder"})
                return srv.respond(rid, {"decision": "accept"})
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
                    for x in ch if not host else []:
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
                # numbered like Orbit's own plan, so the page reads it; ">" is the step in hand
                mark = lambda st: "x" if st == "completed" else ">" if st in ("inProgress", "in_progress") else " "
                txt = "\n".join(f"{i}. [{mark(s.get('status'))}] {s.get('step')}" for i, s in enumerate(steps))
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
        srv.used = time.time()
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


def auto_verdict(cmd):
    """("allow" | "ask" | "refuse", why) for a command Codex wants to run in Auto mode."""
    try:
        level, why = Q.risk_check("run_shell", {"command": str(cmd or "")})
    except Exception as e:
        return "ask", f"could not check it ({type(e).__name__})"
    if not level: return "allow", ""
    if level == "block" and "protected" not in str(why):
        return "refuse", why
    return "ask", why


def _ask(approve, fn, args, reason, tool):
    """(allowed, always) from Orbit's approval prompt. With nobody watching (a scheduled
    run), the Codex setting for unattended runs decides."""
    if not approve:
        how = cfg().get("unattended") or "auto"
        if how == "allow": return True, False
        if how == "auto" and fn == "run_command":
            return auto_verdict((args or {}).get("command"))[0] == "allow", False
        if how == "auto" and fn == "write_file": return True, False
        return False, False
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
    remote = {k: {"running": v["srv"].alive(), "idle_min": round((time.time() - v["srv"].used) / 60, 1)}
              for k, v in _SERVERS.items() if k}
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
            "chats_answering": len(RUNS), "hosts": remote, "remote_install": cfg().get("remote_install", True)}



# ------------------------------------------------------------------ Codex's settings in Orbit

DEFAULTS = {
    "permission_mode": "auto",       # new Codex chats: Auto / Ask / Accept edits / Plan / Don't ask / Bypass
    "default_effort": "",             # "" = Codex's own (config.toml)
    "default_host": "",               # "" = this Mac
    "default_dir": "",                # "" = Orbit's workspace
    "remote_keep_alive_min": 30,      # Codex idle on an SSH host closes after this
    "remote_install": True,           # install (or upgrade) Codex on a host when a chat needs it
    "orbit_context": True,            # Orbit's project rules and your standing instructions as developer instructions
    "developer_instructions": "",     # extra instructions for every Codex chat
    "unattended": "auto",             # scheduled runs: auto (Orbit's safety check) / allow / deny
}


def cfg():
    s = dict(DEFAULTS)
    try: s.update({k: v for k, v in (Q.S.get("codex") or {}).items() if k in DEFAULTS})
    except Exception: pass
    return s


def save_cfg(changes):
    cur = Q.load_settings()
    cx = dict(cur.get("codex") or {})
    for k, v in (changes or {}).items():
        if k not in DEFAULTS: continue
        if k == "remote_keep_alive_min":
            try: v = max(1, min(24 * 60, int(v)))
            except (TypeError, ValueError): continue
        if k in ("remote_install", "orbit_context"): v = bool(v)
        if k == "permission_mode" and v not in PERMISSIONS: continue
        if k == "unattended" and v not in ("auto", "allow", "deny"): continue
        cx[k] = v
    cur["codex"] = cx
    Q.save_settings(cur); Q.reload_settings()
    return cfg()


CODEX_HOME = os.path.expanduser("~/.codex")


def _cli(args, timeout=60):
    exe = which_codex()
    if not exe: return 127, "", "Codex is not installed"
    import providers
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout, env=providers.cli_env(exe))
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "Codex did not answer in time"


def _json_out(out):
    i = min([x for x in (out.find("["), out.find("{")) if x >= 0] or [-1])
    if i < 0: return None
    try: return json.loads(out[i:])
    except ValueError: return None


def codex_skills():
    """~/.codex/skills: each folder with a SKILL.md."""
    base = os.path.join(CODEX_HOME, "skills")
    out = []
    try: names = sorted(os.listdir(base))
    except OSError: return out
    for n in names:
        f = os.path.join(base, n, "SKILL.md")
        if n.startswith(".") or not os.path.isfile(f): continue
        try: meta, _ = _ce()._frontmatter(open(f, encoding="utf-8", errors="replace").read(4000))
        except Exception: meta = {}
        out.append({"name": meta.get("name") or n, "dir": n, "description": str(meta.get("description") or "")[:400]})
    return out


def config_view():
    """What the Codex tab shows: install and sign-in, Orbit's Codex defaults, AGENTS.md,
    skills, plugins, MCP servers, and Codex's own config (model, effort)."""
    agents = os.path.join(CODEX_HOME, "AGENTS.md")
    try: agents_md = open(agents, encoding="utf-8", errors="replace").read()
    except OSError: agents_md = ""
    toml = {}
    try:
        import tomllib
        with open(os.path.join(CODEX_HOME, "config.toml"), "rb") as fh:
            t = tomllib.load(fh)
        toml = {k: t.get(k) for k in ("model", "model_reasoning_effort", "approval_policy", "sandbox_mode", "model_provider") if t.get(k) is not None}
    except Exception:
        pass
    rc, out, err = _cli(["plugin", "list", "--json"], timeout=60)
    plugins = _json_out(out) if rc == 0 else None
    rc2, out2, err2 = _cli(["mcp", "list", "--json"], timeout=60)
    mcp = _json_out(out2) if rc2 == 0 else None
    return {"settings": cfg(), "defaults": DEFAULTS, "info": info(), "agents_md": agents_md, "agents_md_path": agents,
            "skills": codex_skills(), "plugins": plugins, "plugins_error": None if rc == 0 else (err or out)[-300:],
            "mcp": [{k: v for k, v in m.items() if k in ("name", "enabled", "disabled_reason", "transport")}
                    for m in (mcp or []) if isinstance(m, dict)] if isinstance(mcp, list) else mcp,
            "mcp_error": None if rc2 == 0 else (err2 or out2)[-300:], "config_toml": toml,
            "modes": list(PERMISSIONS)}


def save_agents_md(text):
    path = os.path.join(CODEX_HOME, "AGENTS.md")
    _ce()._backup(path)
    os.makedirs(CODEX_HOME, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text if not text or text.endswith("\n") else text + "\n")
    return {"ok": True, "path": path}


def manage(kind, op, **kw):
    """Skills, plugins and MCP servers, through Codex itself where it has a command."""
    if kind == "skills":
        if op == "install":
            return _ce().skill_install(kw.get("source") or "", dest_base=os.path.join(CODEX_HOME, "skills"))
        if op == "remove":
            it = next((x for x in codex_skills() if x["name"] == kw.get("name") or x["dir"] == kw.get("name")), None)
            if not it: return {"error": "no such skill"}
            return {"ok": True, "trashed": _ce()._to_trash(os.path.join(CODEX_HOME, "skills", it["dir"]))}
    if kind == "plugins":
        name = str(kw.get("name") or "")
        if not re.fullmatch(r"[A-Za-z0-9_.@/-]{1,200}", name): return {"error": "plugin@marketplace"}
        if op in ("add", "remove"):
            rc, out, err = _cli(["plugin", op, name], timeout=300)
            return {"ok": rc == 0, "output": (out + err)[-600:], "error": None if rc == 0 else (err or out)[-300:]}
        if op == "marketplace":
            rc, out, err = _cli(["plugin", "marketplace", "add", name], timeout=300)
            return {"ok": rc == 0, "output": (out + err)[-600:], "error": None if rc == 0 else (err or out)[-300:]}
    if kind == "mcp":
        name = str(kw.get("name") or "")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", name): return {"error": "a server name (letters, digits, - _ .)"}
        if op == "remove":
            rc, out, err = _cli(["mcp", "remove", name])
        elif op == "add":
            cmd = [str(x) for x in (kw.get("command") or []) if str(x)]
            if not cmd: return {"error": "the command that starts the server"}
            rc, out, err = _cli(["mcp", "add", name, "--", *cmd])
        else:
            return {"error": f"unknown MCP action {op}"}
        return {"ok": rc == 0, "output": (out + err)[-600:], "error": None if rc == 0 else (err or out)[-300:]}
    return {"error": f"unknown {kind} action {op}"}
