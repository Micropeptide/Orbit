"""Claude Code as an Orbit engine, on the local Qwen model.

Orbit used to reach `claude-qwen` the way it reaches any command-line agent:
paste the whole chat into one prompt, run `claude -p`, keep the final text.
Every turn started a fresh Claude session, nothing it did with its tools was
visible, it could not ask for permission, and `--bare` left it three tools.

This runs the real harness instead, one long-lived Claude Code session per
Orbit chat:

- the session is resumed turn after turn (`--resume`), so Claude keeps its own
  history, compaction, todo list and file state, and the local model's prompt
  cache stays warm;
- its stream is translated into Orbit's events: thinking, text, every tool
  call and result (with diffs), subagents, compaction, usage;
- permission prompts come to Orbit (`--permission-prompt-tool stdio`) and are
  decided by Orbit's rules, autonomy mode and approval box; AskUserQuestion
  becomes Orbit's question box; notes sent mid-answer go in as queued messages;
- the skills offered are chosen per chat from your Claude skills, with full
  descriptions, instead of 1,000+ bare names;
- sessions you ran in a terminal with `claude-qwen` show up in Orbit's sidebar,
  and a chat continued in either place stays one conversation.

The same argument builder backs the `claude-qwen` launcher (`launch`).
"""
import base64, difflib, glob, json, os, re, secrets, shutil, signal, subprocess, sys
import threading, time, uuid, collections

HOME = os.path.expanduser("~")
BACKEND = "claude-qwen-cli"
Q = None                       # qqcore, bound by qqcore itself (no import cycle)

DEFAULTS = {
    # Orbit's Claude Code mode is the claude-qwen CLI in a window: the same
    # command, your Claude setup (~/.claude) as is. The options below marked
    # "launcher" apply to the terminal command and to Orbit alike; the ones
    # marked "Orbit extra" add something Claude itself does not do, and are off.

    # launcher: "standard" = Claude as you have it set up (all setting sources,
    # skills, plugins, hooks); "lean" = built-in tools and skills only (--safe-mode)
    "profile": "standard",
    # launcher: MCP servers loaded, by name from your Claude config; "*" = all of them,
    # including those your plugins bring. A shorter list drops plugin servers too, while
    # the plugins' hooks still run -- context-mode's then send web fetches to tools that
    # are not there -- so "standard" loads them all.
    "mcp_servers": ["*"],
    # launcher: tools that cannot work on a local model (WebSearch needs Anthropic's
    # servers) or that a local chat has no use for
    "disallowed_tools": ["WebSearch", "Workflow", "ScheduleWakeup", "CronCreate", "CronDelete",
                         "CronList", "EnterWorktree", "ExitWorktree", "ReportFindings",
                         "SendMessage", "RemoteTrigger", "ListMcpResourcesTool",
                         "ReadMcpResourceTool", "ReadMcpResourceDirTool"],
    # launcher: in easy mode, the only MCP servers started. [] = none of them, which is
    # the point: each one's tools are in every request whether they are called or not.
    "easy_mcp": [],
    # launcher: in easy mode (Settings -> Tools), the only Claude Code tools kept. The
    # rest are denied by name, which is why Orbit learns the names from Claude Code
    # itself rather than guessing: an unknown name in --disallowedTools stops the run.
    "easy_tools": ["Read", "Edit", "Write", "Bash", "Task", "Skill", "WebFetch"],
    # launcher: the profile to use when the model runs on this Mac. Its prompt costs
    # seconds there, and plugins, their MCP servers and their hooks are most of it.
    # "" keeps whatever "profile" says for every model alike.
    "local_profile": "lean",
    # launcher: "claude" = run the hooks your Claude settings define; "off" = none
    "hooks": "claude",
    "extra_args": [],
    # "New chat with…" presets (bunshin's agents): name, model, folder, permission mode
    "presets": [],
    "append_system": "",
    "effort_passthrough": True,

    # defaults for a new chat (each chat can change its own):
    # permission mode ("" = Claude's own, permissions.defaultMode in your Claude settings)
    "permission_mode": "auto",
    "default_effort": "",            # "" = Claude's own; low, medium, high, xhigh, max
    "default_host": "",              # "" = this Mac; else an SSH host new chats run on
    "default_dir": "",               # "" = Orbit's workspace (on another machine: that host's default)
    "remote_keep_alive_min": 30,     # a chat on another machine keeps Claude Code running this long between messages
    # permission mode for runs nobody is watching (scheduled jobs)
    "unattended_mode": "",
    # where "Don't ask again" saves: "suggested" (Claude's choice), "userSettings",
    # "projectSettings", "localSettings" or "session"
    "rule_destination": "suggested",
    "history": True,                 # list claude-qwen terminal sessions in the sidebar
    "history_all_models": False,     # ...including Claude sessions on other models

    # Orbit extras, all off: Claude alone decides and sees only what it would see
    "orbit_rules": False,            # Orbit's safety rules, autonomy mode and folder limit on top
    "orbit_tools": False,            # Orbit's own tools through an MCP bridge
    "project_tools": False,          # a trusted project's .orbit/tools through the bridge
    "orbit_tool_names": ["search_chats", "read_chat", "remember", "search_agent_memory",
                         "search_knowledge", "schedule_task", "list_scheduled_tasks",
                         "cancel_scheduled_task", "web_search", "check_citations"],
    "skill_routing": False,          # offer only the skills matching each chat
    "core_skills": ["deep-research", "literature-review", "paper-lookup",
                    "scientific-writing", "statistical-analysis", "dataviz"],
    "max_skills": 14,
    "skill_hint": False,             # name the best-matching skills in the message
    "orbit_skills": False,           # Orbit's saved skills as a Claude plugin
    "orbit_context": False,          # Orbit's project rules and instructions in the system prompt
    "message_time": False,           # prefix each message with when it was sent
    # with orbit_rules on: tools Orbit lets through without asking
    "auto_allow": ["Read", "Glob", "Grep", "LS", "Skill", "TodoWrite", "TaskCreate", "TaskGet",
                   "TaskList", "TaskUpdate", "TaskOutput", "Agent", "Task", "ToolSearch",
                   "WebFetch", "NotebookRead", "EnterPlanMode", "mcp__paper-fetch__*"],
}

LOCAL_MODEL_PREFIXES = ("mtplx", "local", "qwen")


def cfg():
    s = (Q.S.get("claude_qwen") if Q else None) or {}
    return {**DEFAULTS, **s}


def easy_mode(sid=None):
    """One switch for both engines: Orbit's own agent and Claude Code. Per chat, so a
    chat on a small model keeps it on while the one next to it does not."""
    try: return bool(Q.chat_setting("easy_mode", sid))
    except Exception: return False


def claude_dir():
    return os.environ.get("ORBIT_CLAUDE_CONFIG_DIR") or os.path.join(HOME, ".claude")


def projects_dir():
    return os.path.join(claude_dir(), "projects")


def which_claude():
    hit = shutil.which("claude")
    if hit: return hit
    for d in ("~/.local/bin", "/opt/homebrew/bin", "/usr/local/bin", "~/.claude/local", "~/bin"):
        p = os.path.join(os.path.expanduser(d), "claude")
        if os.path.isfile(p) and os.access(p, os.X_OK): return p
    return None


def is_engine(spec):
    """True when a resolved model spec should run through this engine: the local
    Qwen (claude-qwen) or any harness model (bin/harness.py)."""
    try:
        return (spec or {}).get("provider") in (BACKEND, "harness")
    except Exception:
        return False


def gateway_token():
    """The token Orbit's gateway asks for, so only Orbit's Claude runs can use
    the keys behind it. Made once, kept private (0600) in config/claude."""
    path = os.path.join(_work_dir(), "gateway-token")
    try:
        tok = open(path).read().strip()
        if len(tok) >= 32: return tok
    except OSError:
        pass
    tok = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh: fh.write(tok)
    return tok


def gateway_port():
    """The port Orbit's gateway is actually listening on, or None.

    This used to fall back to the configured number when the gateway had failed to
    start — which is the very port something else was already holding, so a failed
    gateway meant sending the conversation, and the gateway token, to whatever that
    was. A caller that gets None must not build a URL at all."""
    port = getattr(Q, "HARNESS_PORT", None)
    return int(port) if port else None


def _harness():
    import harness
    return harness


def harness_target(spec=None):
    """Where a Claude Code run for this model sends its requests: base URL, the
    model ids for Claude's tiers, context window, credentials, extra env, and
    whether it is the local server (which may need waking)."""
    spec = spec or {}
    pc = spec.get("provider_cfg") or {}
    if spec.get("provider") == "harness" and pc.get("subscription"):
        # plain Claude Code on your own login: no base URL, no key, Claude's own windows
        token = ""
        try: token = (Q.secrets_load() or {}).get("CLAUDE_CODE_OAUTH_TOKEN") or ""
        except Exception: pass
        return {"url": None, "model": pc.get("model") or "sonnet", "small": "haiku",
                "ctx": int(pc.get("context") or 200000), "local": False, "provider": "claude",
                "auth": {}, "env": ({"CLAUDE_CODE_OAUTH_TOKEN": token} if token else {}),
                "key_missing": False, "subscription": True, "token": bool(token),
                "cli_model": pc.get("model") or "sonnet"}
    if spec.get("provider") != "harness" or pc.get("local"):
        url, model, ctx = model_endpoint()
        return {"url": url, "model": model, "small": model, "ctx": ctx, "local": True, "provider": "local",
                "auth": {"ANTHROPIC_AUTH_TOKEN": "local-qwen"}, "env": {}, "key_missing": False}
    if pc.get("auth") == "gateway" or pc.get("format") != "messages":
        gp = gateway_port()
        if not gp:
            # with no gateway there is nowhere to send this. Saying so is the only safe
            # answer: a guessed port is a port something else is holding.
            return {"url": "", "model": pc.get("model"), "small": pc.get("model"),
                    "ctx": int(pc.get("context") or 128000), "local": False,
                    "provider": pc.get("provider"), "auth": {}, "env": {},
                    "key_missing": True,
                    "error": "Orbit's translating gateway is not running, and this model "
                             "needs it. Restart Orbit, or free port "
                             f"{(_harness().load(Q.ROOT).get('gateway_port') or 8897)}."}
        url = f"http://127.0.0.1:{gp}/h/{pc['provider']}"
        auth = {"ANTHROPIC_AUTH_TOKEN": gateway_token()}           # the gateway adds the real key
    else:
        url = pc.get("base") or ""
        auth = {"ANTHROPIC_API_KEY": pc.get("api_key") or ""}
    env = dict(pc.get("env") or {})
    if pc.get("proxy") and "ANTHROPIC_API_KEY" in auth:
        env.update(HTTPS_PROXY=pc["proxy"], HTTP_PROXY=pc["proxy"])
    return {"url": url, "model": pc.get("model"), "small": pc.get("small") or pc.get("model"),
            "ctx": int(pc.get("context") or 128000), "local": False, "provider": pc.get("provider"),
            "auth": auth, "env": env, "key_name": pc.get("key_name"),
            # a host on this Mac (Bionic) has nothing to sign in to: no key is not a fault
            "key_missing": not (pc.get("api_key") or pc.get("keyless"))}


# ------------------------------------------------------------------ the process

def model_endpoint():
    """(gateway URL, model id, context window) of the local server."""
    base = (getattr(Q, "BASE", "") or "http://127.0.0.1:8011/v1").rstrip("/")
    if base.endswith("/v1"): base = base[:-3]
    if os.environ.get("ORBIT_MODEL_URL"): base = os.environ["ORBIT_MODEL_URL"].rstrip("/")
    elif os.environ.get("ORBIT_MODEL_PORT"): base = f"http://127.0.0.1:{os.environ['ORBIT_MODEL_PORT']}"
    mid = getattr(Q, "MODEL", None) or "mtplx-qwen38-27b-optimized-speed"
    try: mid = Q.local_model_name() or mid
    except Exception: pass
    ctx = 131072
    try: ctx = int(((Q.S.get("server") or {}).get("context_window")) or ctx)
    except Exception: pass
    return base, mid, ctx


def harness_env(url, model, ctx, extra=None, small=None, auth=None):
    """The gateway variables, and nothing inherited from another Claude session.

    A shell started from a Claude desktop session carries CLAUDE_CODE_* values
    (entrypoint, session ids) that changed what the harness sent; they are
    dropped, as is any real Anthropic key, so nothing can leave the Mac."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE", "ANTHROPIC", "OTEL_"))}
    paths = env.get("PATH", "").split(":")
    for d in ("~/.local/bin", "/opt/homebrew/bin", "/usr/local/bin", "~/bin"):
        d = os.path.expanduser(d)
        if d not in paths: paths.append(d)
    env["PATH"] = ":".join(p for p in paths if p)
    if url is None:
        # your Claude subscription: Claude Code signs in as it does in a terminal
        env.update({"DISABLE_AUTOUPDATER": "1", "MCP_TOOL_TIMEOUT": "3600000", "BASH_DEFAULT_TIMEOUT_MS": "600000"})
        if os.environ.get("ORBIT_CLAUDE_CONFIG_DIR"):
            env["CLAUDE_CONFIG_DIR"] = os.environ["ORBIT_CLAUDE_CONFIG_DIR"]
        env.update(extra or {})
        return env
    env.update({
        "ANTHROPIC_BASE_URL": url,
        "ANTHROPIC_MODEL": model,
        "ANTHROPIC_DEFAULT_OPUS_MODEL": model,
        "ANTHROPIC_DEFAULT_SONNET_MODEL": model,
        # Claude's quick background calls go to the provider's small model
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": small or model,
        "ANTHROPIC_SMALL_FAST_MODEL": small or model,
        "CLAUDE_CODE_SUBAGENT_MODEL": model,
        "CLAUDE_CODE_MAX_CONTEXT_TOKENS": str(ctx),
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "DISABLE_AUTOUPDATER": "1",
        "DISABLE_TELEMETRY": "1",
        "DISABLE_ERROR_REPORTING": "1",
        # a tool answered by Orbit may wait on your approval for minutes
        "MCP_TOOL_TIMEOUT": "3600000",
        "BASH_DEFAULT_TIMEOUT_MS": "600000",
    })
    env.update(auth if auth is not None else {"ANTHROPIC_AUTH_TOKEN": "local-qwen"})
    if os.environ.get("ORBIT_CLAUDE_CONFIG_DIR"):
        env["CLAUDE_CONFIG_DIR"] = os.environ["ORBIT_CLAUDE_CONFIG_DIR"]
    env.update(extra or {})
    return env


def default_remote_dir(host):
    """The folder new chats on a host start in: its saved default, else your first
    bookmark there, else the home folder."""
    try:
        d = ((Q.S.get("remote_hosts") or {}).get(host) or {}).get("default_dir")
        if d: return d
        marks = (Q.S.get("folder_bookmarks") or {}).get(host) or []
        if marks: return marks[0]
    except Exception:
        pass
    return "~"


def remote_target_env(target, env):
    """What a Claude Code run on another machine gets from Orbit: its models come through
    Orbit's gateway on this Mac, reached by an SSH reverse tunnel (the gateway needs
    Orbit's token, so other users of a shared machine cannot use it); your Claude
    subscription token, when the chat uses it. Returns (env, (remote_port, local_port))."""
    import ssh_remote
    if target.get("subscription"):
        out = {k: v for k, v in (target.get("env") or {}).items()}
        out.update({"DISABLE_AUTOUPDATER": "1", "MCP_TOOL_TIMEOUT": "3600000", "BASH_DEFAULT_TIMEOUT_MS": "600000"})
        return out, None
    rport = ssh_remote.pick_port()
    provider = "local" if target.get("local") else target.get("provider")
    model = target.get("model")
    small = target.get("small") or model
    if target.get("local"):
        model = small = model_endpoint()[1]
    url = f"http://127.0.0.1:{rport}/h/{provider}"
    renv = harness_env(url, model, target.get("ctx") or 128000, extra=dict(target.get("env") or {}), small=small,
                       auth={"ANTHROPIC_AUTH_TOKEN": gateway_token()})
    return ssh_remote.remote_env(renv), (rport, gateway_port())


def target_env(target, extra=None):
    return harness_env(target["url"], target["model"], target["ctx"], extra={**target.get("env", {}), **(extra or {})},
                       small=target.get("small"), auth=target.get("auth"))


def encode_cwd(path):
    """Claude's project folder name for a working directory."""
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(path))


def jsonl_path(session_id, cwd=None):
    if not session_id: return None
    if cwd:
        p = os.path.join(projects_dir(), encode_cwd(cwd), session_id + ".jsonl")
        if os.path.exists(p): return p
    hits = glob.glob(os.path.join(projects_dir(), "*", session_id + ".jsonl"))
    return hits[0] if hits else None


def erase_session_traces(messages):
    """Remove what Claude Code keeps of this chat's session -- its transcript, file backups
    and session environment -- for a temporary chat, which promises to leave nothing on
    disk. Returns the paths removed."""
    mk = marker_of(messages) or {}
    sid = mk.get("session")
    if not sid or mk.get("host"): return []             # a session on another machine is its own
    removed = []
    jp = jsonl_path(sid, mk.get("cwd"))
    targets = [jp] if jp else []
    targets += [os.path.join(claude_dir(), "file-history", sid), os.path.join(claude_dir(), "session-env", sid)]
    if jp: targets.append(os.path.splitext(jp)[0])        # its subagents/ and tool-results/ folder
    for t in targets:
        try:
            if t and os.path.isdir(t): shutil.rmtree(t); removed.append(t)
            elif t and os.path.exists(t): os.remove(t); removed.append(t)
        except OSError:
            pass
    return removed


def user_mcp_servers():
    """MCP servers configured for Claude (user scope), by name."""
    out = {}
    for path in (os.path.join(HOME, ".claude.json"), os.path.join(claude_dir(), ".claude.json")):
        try: d = json.load(open(path))
        except Exception: continue
        for k, v in (d.get("mcpServers") or {}).items():
            out.setdefault(k, v)
    return out


def _work_dir():
    d = os.path.join(Q.ROOT if Q else os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "config", "claude")
    os.makedirs(d, exist_ok=True)
    return d


def orbit_skills_plugin():
    """Orbit's own skills (skills/*.md) as a Claude plugin, so a chat on this
    engine can load them with the Skill tool too. Rebuilt when they change."""
    if not Q: return None
    src = getattr(Q, "SKILLS", None)
    if not src or not os.path.isdir(src): return None
    files = sorted(f for f in os.listdir(src) if f.endswith(".md"))
    if not files: return None
    root = os.path.join(_work_dir(), "orbit-plugin")
    stamp = json.dumps([(f, os.path.getmtime(os.path.join(src, f))) for f in files])
    mark = os.path.join(root, ".stamp")
    try:
        if open(mark).read() == stamp: return root
    except OSError: pass
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(os.path.join(root, ".claude-plugin"), exist_ok=True)
    json.dump({"name": "orbit", "version": "1.0.0",
               "description": "Skills saved in Orbit"},
              open(os.path.join(root, ".claude-plugin", "plugin.json"), "w"))
    for f in files:
        text = open(os.path.join(src, f), encoding="utf-8", errors="replace").read()
        name = re.sub(r"[^a-z0-9-]+", "-", f[:-3].lower()).strip("-") or "skill"
        meta, body = _frontmatter(text)
        desc = (meta.get("description") or _first_line(body) or name)[:900]
        d = os.path.join(root, "skills", name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "SKILL.md"), "w") as fh:
            fh.write(f"---\nname: {name}\ndescription: {json.dumps(desc)}\n---\n\n{body.strip()}\n")
    open(mark, "w").write(stamp)
    return root


# ------------------------------------------------------------------ skills

_SKILL_INDEX = {"key": None, "items": []}


def _frontmatter(text):
    meta, body = {}, text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            for line in text[3:end].splitlines():
                m = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
                if m: meta[m.group(1).strip()] = m.group(2).strip().strip('"').strip("'")
            body = text[end + 4:]
    return meta, body


def _first_line(body):
    for line in body.splitlines():
        line = line.strip().lstrip("#").strip()
        if line: return line
    return ""


def skill_index():
    """Name and description of every skill in ~/.claude/skills."""
    base = os.path.join(claude_dir(), "skills")
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return []
    key = (len(names), int(os.path.getmtime(base)))
    if _SKILL_INDEX["key"] == key: return _SKILL_INDEX["items"]
    items = []
    for n in names:
        p = os.path.join(base, n, "SKILL.md")
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                head = fh.read(4000)
        except OSError:
            continue
        meta, body = _frontmatter(head)
        items.append({"name": meta.get("name") or n, "dir": n,
                      "description": meta.get("description") or _first_line(body)})
    _SKILL_INDEX.update(key=key, items=items)
    return items


_STOP = set("a an and are as at be by can do for from get has have how i in into is it its me my "
            "of on or our please so that the their them then this to up use using want we what when "
            "which will with you your make help new file files data".split())


def _words(text):
    return [w for w in re.findall(r"[a-z0-9][a-z0-9+-]{1,}", (text or "").lower()) if w not in _STOP]


def route_skills(text, limit=6):
    """Skills whose name and description best match what was asked: a plain
    weighted word overlap, cheap enough to run on every message."""
    words = set(_words(text))
    if not words: return []
    items = skill_index()
    df = collections.Counter()
    toks = []
    for it in items:
        t = set(_words(it["name"].replace("-", " ") + " " + it["description"]))
        toks.append(t)
        df.update(t)
    n = max(1, len(items))
    scored = []
    import math
    for it, t in zip(items, toks):
        name_t = set(_words(it["name"].replace("-", " ")))
        hit = words & t
        s = sum(math.log(1 + n / (1 + df[w])) * (2.5 if w in name_t else 1.0) for w in hit)
        # one shared everyday word is not a match: a word of its name, or two words
        if s > 0 and (hit & name_t or len(hit) >= 2):
            scored.append((s, it))
    scored.sort(key=lambda x: -x[0])
    if not scored: return []
    top = scored[0][0]
    return [it for s, it in scored[:limit] if s >= top * 0.45]


# ------------------------------------------------------------------ arguments

def build_argv(c, *, session_id=None, resume=False, read_only=False, effort=None, mode=None,
               settings_path=None, mcp_path=None, append=None, sdk=True, add_dirs=None, model=None,
               kind="local", remote=False, **_):
    """The claude command line. The same for the terminal (sdk=False) and for
    Orbit, which only adds the stream transport, the session and a chat's mode.

    kind: "local" (the MTPLX model: tools that cannot work there are turned off and the
    system prompt is kept identical so its cache is reused), "provider" (another model
    through Orbit: only WebSearch, which needs Anthropic's servers, is turned off) or
    "subscription" (your own Claude: nothing is changed). Outside the local model, Claude
    Code starts as your own setup has it -- nothing chosen or added by Orbit."""
    exe = which_claude() or "claude"
    argv = [exe]
    if sdk:
        argv += ["--print", "--output-format", "stream-json", "--verbose",
                 "--input-format", "stream-json", "--include-partial-messages",
                 "--include-hook-events", "--permission-prompt-tool", "stdio"]
    # "sonnet" is mapped to the chosen model by the environment; your Claude
    # subscription takes the model name itself
    argv += ["--model", model or "sonnet"]
    prof = c.get("profile") or "standard"
    if prof == "lean":
        argv.append("--safe-mode")
    elif prof == "focused":                     # older setting: user settings only
        argv += ["--setting-sources", "user"]
    if session_id:
        argv += (["--resume", session_id] if resume else ["--session-id", session_id])
    mode = "plan" if read_only else (mode or "")
    if mode == "auto" and kind == "local":
        # Claude Code's "auto" asks the *model* to classify each tool call's safety.
        # Pointed at a model on this Mac that is already busy generating the turn, the
        # classifier waits behind it and times out at 60s -- and a classifier that times
        # out refuses the tool: "…cannot determine the safety of Bash right now". Every
        # Bash call in the chat fails that way. Orbit answers the same question from
        # risk_check in microseconds through --permission-prompt-tool, so the local
        # model gets Orbit's gate instead of Claude's.
        mode = "default"
    if mode in PERMISSION_MODES and mode != "default":     # "default" (ask first) is Claude's own
        argv += ["--permission-mode", mode]
    dis = [t for t in (c.get("disallowed_tools") if kind == "local" else
                       [] if kind == "subscription" else c.get("provider_disallowed_tools", ["WebSearch"])) or [] if t]
    if easy_mode():
        # keep a few, deny the rest -- but only names Claude Code has said it has, so a
        # tool it has never heard of cannot stop the run
        keep = {str(t) for t in (c.get("easy_tools") or []) if t}
        dis = sorted(set(dis) | {t for t in known_tools() if t not in keep})
    if dis: argv += ["--disallowedTools", *dis]
    if settings_path: argv += ["--settings", settings_path]
    if mcp_path:
        argv += ["--mcp-config", mcp_path]
        if easy_mode() or ("*" not in (c.get("mcp_servers") or []) and prof != "full"):
            argv.append("--strict-mcp-config")
    if prof != "lean" and not easy_mode() and not remote:
        # plugins' own MCP servers: a Claude Code started with --print marks them failed
        # without starting them (while the plugins' hooks still run -- context-mode's then
        # send every web fetch to tools that are not there). Naming each plugin's folder,
        # as Claude's desktop app does, starts them; the plugins are not loaded twice.
        for pd in plugin_dirs_with_mcp():
            argv += ["--plugin-dir", pd]
    if prof != "lean" and c.get("orbit_skills"):
        pd = orbit_skills_plugin()
        if pd: argv += ["--plugin-dir", pd]
    for d in add_dirs or []:
        argv += ["--add-dir", d]
    if append: argv += ["--append-system-prompt", append]
    # only an explicit step up ("retry deeper"): the terminal command passes no effort
    if effort and c.get("effort_passthrough") and effort in ("high", "xhigh", "max"):
        argv += ["--effort", effort]
    elif c.get("default_effort") in ("low", "medium", "high", "xhigh", "max"):
        argv += ["--effort", c["default_effort"]]
    # identical system text across sessions and days: the local prompt cache keeps it
    if kind == "local":
        argv.append("--exclude-dynamic-system-prompt-sections")
    argv += [str(x) for x in (c.get("extra_args") or [])]
    return argv


def launcher_files(c, tag, skills=None, extra_servers=None):
    """--settings and --mcp-config files for one run (None where not needed)."""
    settings = {}
    # A plugin's hooks expect that plugin's MCP tools to be there. Easy mode takes the
    # servers away, so the hooks go with them rather than firing at tools that are gone.
    if easy_mode() or c.get("hooks") in (False, "off"):
        settings["disableAllHooks"] = True
    if skills is not None and c.get("skill_routing") and (c.get("profile") or "standard") != "lean":
        keep = set(skills)
        settings["skillOverrides"] = {it["name"]: "off" for it in skill_index() if it["name"] not in keep}
        settings["skillListingBudgetFraction"] = 0.05
    settings_path = _write_json(f"settings-{tag}.json", settings) if settings else None
    # Easy mode is about what the model is handed, and an MCP server hands it tools:
    # the servers cost prompt whether or not the model ever calls them, and they are
    # most of what a plugin-heavy setup sends.
    names = (c.get("easy_mcp") or []) if easy_mode() else (c.get("mcp_servers") or [])
    servers = {}
    if "*" not in names:
        known = user_mcp_servers()
        servers = {k: v for k, v in known.items() if k in names}
    servers.update(extra_servers or {})
    mcp_path = _write_json(f"mcp-{tag}.json", {"mcpServers": servers}) \
        if (servers or "*" not in names) else None
    return settings_path, mcp_path


def plugin_dirs_with_mcp():
    """Install folders of your enabled Claude plugins that bring MCP servers."""
    base = os.path.join(claude_dir(), "plugins")
    try: reg = json.load(open(os.path.join(base, "installed_plugins.json")))
    except Exception: return []
    enabled = dict(reg.get("enabledPlugins") or {})
    try: enabled.update((read_claude_settings("user") or {}).get("enabledPlugins") or {})
    except Exception: pass
    out = []
    for name, installs in (reg.get("plugins") or {}).items():
        if not enabled.get(name): continue
        for inst in installs if isinstance(installs, list) else [installs]:
            d = (inst or {}).get("installPath")
            if not d or not os.path.isdir(d): continue
            has = os.path.isfile(os.path.join(d, ".mcp.json"))
            try: has = has or bool(json.load(open(os.path.join(d, ".claude-plugin", "plugin.json"))).get("mcpServers"))
            except Exception: pass
            if has and d not in out: out.append(d)
            break
    return out


def launcher_append(c, extra=None, kind="local"):
    parts = ([TERMINAL_NOTE] if kind == "local" else []) + list(extra or [])
    if c.get("append_system"): parts.append(str(c["append_system"]))
    return "\n\n".join(p for p in parts if p)


TERMINAL_NOTE = ("# Local model\n- WebSearch is unavailable with this local model; use WebFetch on "
                 "known URLs.")


_WRITE_LOCK = threading.RLock()


def _write_json(name, data):
    # a temp file per writer: two chats saving at once (one process, two threads)
    # used to share one temp name, and the second rename failed
    p = os.path.join(_work_dir(), name)
    tmp = p + f".{os.getpid()}.{threading.get_ident()}.tmp"
    with _WRITE_LOCK:
        with open(tmp, "w") as fh: json.dump(data, fh)
        os.replace(tmp, p)
    return p


# ------------------------------------------------------------------ Orbit tools bridge

BRIDGE = {}          # token -> what a tool call from that run needs


def bridge_url():
    port = getattr(Q, "UI_PORT", None)
    return f"http://127.0.0.1:{port}/api/mcp_bridge" if port else None


def _to_mcp(spec):
    f = spec.get("function") or {}
    return {"name": f.get("name"), "description": (f.get("description") or "")[:1500],
            "inputSchema": f.get("parameters") or {"type": "object", "properties": {}}}


def bridge_list(token):
    ctx = BRIDGE.get(token)
    if not ctx: return {"error": "unknown run"}
    return {"tools": [_to_mcp(s) for s in ctx["specs"]]}


def bridge_call(token, name, arguments):
    """Run one Orbit tool for a Claude run, with Orbit's own safety checks and
    approvals, in the context of the chat that asked."""
    ctx = BRIDGE.get(token)
    if not ctx: return {"error": "unknown run", "ok": False}
    if name not in {s["function"]["name"] for s in ctx["specs"]}:
        return {"text": f"Error: {name} is not offered to this chat.", "ok": False}
    T = Q.TURN_CTX
    T.sid, T.project, T.read_only = ctx["sid"], ctx["project"], ctx["read_only"]
    T.model, T.emit, T.approve, T.cancel = ctx.get("model"), ctx["emit"], ctx["approve"], ctx["cancel"]
    T.changes = ctx.setdefault("changes", [])
    T.ask = ctx.get("ask")
    scratch = []
    passthru = ("auto_approved", "blocked", "injection", "stagnation")
    emit = lambda k, p: ctx["emit"](k, p) if k in passthru else None
    tc = {"id": "orbit_" + uuid.uuid4().hex[:10], "type": "function",
          "function": {"name": name, "arguments": json.dumps(arguments or {})}}
    Q._run_one_tool(tc, name, arguments or {}, scratch, emit, ctx["approve"], ctx.setdefault("seen", {}))
    out = next((m for m in scratch if m.get("role") == "tool"), {})
    return {"text": str(out.get("content") or ""), "ok": out.get("ok", True) is not False}


# ------------------------------------------------------------------ permissions

WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")


def _glob_match(name, patterns):
    import fnmatch
    return any(fnmatch.fnmatchcase(name, p) for p in patterns or [])


def orbit_view(tool, inp):
    """A Claude tool call as the Orbit tool it resembles, for Orbit's risk rules."""
    inp = inp or {}
    if tool == "Bash":
        return "run_shell", {"command": inp.get("command", "")}
    if tool == "Write":
        return "write_file", {"path": inp.get("file_path", ""), "content": inp.get("content", "")}
    if tool in ("Edit", "MultiEdit"):
        a = {"path": inp.get("file_path", "")}
        if tool == "Edit":
            a.update(old_string=inp.get("old_string", ""), new_string=inp.get("new_string", ""),
                     replace_all=bool(inp.get("replace_all")))
        return "edit_file", a
    if tool == "NotebookEdit":
        return "edit_file", {"path": inp.get("notebook_path", "")}
    return tool, inp


PERMISSION_MODES = ("default", "acceptEdits", "plan", "auto", "dontAsk", "bypassPermissions")


def rule_text(rule):
    """{"toolName": "Bash", "ruleContent": "git diff:*"} -> "Bash(git diff:*)"."""
    t, c = rule.get("toolName") or "", rule.get("ruleContent")
    return f"{t}({c})" if c else t


def parse_rule(text):
    m = re.match(r"^\s*([A-Za-z0-9_:.*-]+)\s*(?:\((.*)\))?\s*$", text or "", re.S)
    if not m: return None
    r = {"toolName": m.group(1)}
    if m.group(2): r["ruleContent"] = m.group(2)
    return r


def _suggested(req):
    """What Claude offers for "don't ask again", as editable text."""
    for sgg in req.get("permission_suggestions") or []:
        if sgg.get("type") in ("addRules", "replaceRules") and sgg.get("rules"):
            return rule_text(sgg["rules"][0]), sgg
        if sgg.get("type") == "setMode" and sgg.get("mode"):
            return "mode:" + sgg["mode"], sgg
    return (req.get("tool_name") or ""), None


def _always(pattern, sugg, tool, c):
    """updatedPermissions for an "Always allow", in Claude's own terms."""
    dest = c.get("rule_destination") or "suggested"
    pattern = (pattern or "").strip()
    if pattern.startswith("mode:"):
        mode = pattern[5:].strip()
        if mode not in PERMISSION_MODES: return None
        return [{"type": "setMode", "mode": mode,
                 "destination": "session" if dest == "suggested" else dest}]
    rule = parse_rule(pattern) or {"toolName": tool}
    d = (sugg or {}).get("destination") or "localSettings"
    return [{"type": "addRules", "rules": [rule], "behavior": "allow",
             "destination": d if dest == "suggested" else dest}]


def _call_approve(approve, fn, args, reason, info):
    import inspect
    try:
        n = len(inspect.signature(approve).parameters)
        star = any(p.kind == p.VAR_POSITIONAL for p in inspect.signature(approve).parameters.values())
    except (TypeError, ValueError):
        n, star = 3, False
    return approve(fn, args, reason, info) if (star or n >= 4) else approve(fn, args, reason)


def decide(tool, inp, ctx, req=None):
    """(allow, message, updated_input, updated_permissions) for one of Claude's
    permission prompts.

    Claude Code has already applied its permission mode and your allow/deny
    rules: it only asks about what those leave open. By default Orbit simply
    puts that question in front of you. With orbit_rules on, Orbit's own safety
    rules, autonomy mode and folder limit are applied first."""
    c = ctx["cfg"]
    req = req or {}
    if tool == "AskUserQuestion":
        return _answer_questions(inp, ctx) + (None,)
    if tool == "ExitPlanMode" and ctx["read_only"]:
        return (False, "Plan mode is on in Orbit. Present the plan as your answer and stop; "
                       "the user switches plan mode off when they want it carried out.", None, None)
    if tool.startswith("mcp__orbit__"):
        return True, "", inp, None           # the bridge applies Orbit's own checks
    if ctx["read_only"] and tool in WRITE_TOOLS:
        return False, "Plan mode is on, so nothing may be changed. Describe the change instead.", None, None
    fn, args = orbit_view(tool, inp)
    reason = f"Claude Code wants to use {tool}" + (f": {req['description']}" if req.get("description") else "")
    if c.get("orbit_rules"):
        if _glob_match(tool, c.get("auto_allow")):
            return True, "", inp, None
        try:
            level, why = Q.risk_check(fn, args)
        except Exception:
            level, why = "confirm", f"use {tool}"
        if not level and tool in WRITE_TOOLS:
            # Orbit's write tool keeps itself to the chat's folders; Claude's does not
            path = os.path.realpath(os.path.expanduser(str(args.get("path") or "")))
            roots = [os.path.realpath(r) for r in ctx.get("roots") or [] if r]
            if path and not any(path == r or path.startswith(r.rstrip(os.sep) + os.sep) for r in roots):
                level, why = "confirm", f"write outside the chat's folder: {path}"
        if level == "block":
            ctx["emit"]("blocked", {"name": tool, "reason": why})
            Q.LOG_SAFETY(tool, args, "blocked", why)
            return False, f"REFUSED: {why}. This is blocked and cannot be approved.", None, None
        if not level and tool in ("Bash", "Write", "Edit", "MultiEdit"):
            return True, "", inp, None
        reason = why or reason
        mode = Q.S.get("autonomy_mode", "ask")
        by_rule = Q.allowed_by_rule(fn, args)
        auto = bool(by_rule) or (mode == "full" and not Q._never_auto(fn, reason)) \
            or (mode == "auto" and Q._auto_approvable(fn, args, reason))
        if auto:
            ctx["emit"]("auto_approved", {"name": tool, "args": inp, "reason": reason,
                                          "rule": (by_rule.get("note") or by_rule.get("pattern")) if by_rule else None})
            Q.LOG_SAFETY(tool, args, "auto-approved", reason)
            return True, "", inp, None
    approve = ctx.get("approve")
    if not approve:
        return False, ("Nobody is watching this run, so actions that need approval are refused. "
                       "Do what you can without it and report what needs the user."), None, None
    pattern, sugg = _suggested({**req, "tool_name": tool})
    info = {"claude": True, "tool": tool, "suggested_pattern": pattern,
            "suggestions": [rule_text(r) for sg in req.get("permission_suggestions") or []
                            for r in sg.get("rules") or []] +
                           ["mode:" + sg["mode"] for sg in req.get("permission_suggestions") or []
                            if sg.get("type") == "setMode" and sg.get("mode")]}
    said = _call_approve(approve, fn, args, reason, info)
    if isinstance(said, dict):
        ok, note, always = bool(said.get("allow")), (said.get("note") or "").strip(), said.get("always")
        pat = said.get("pattern") or pattern
    elif isinstance(said, tuple):
        ok, note, always, pat = bool(said[0]), (said[1] or "").strip(), False, pattern
    else:
        ok, note, always, pat = bool(said), "", False, pattern
    try: Q.LOG_SAFETY(tool, args, "approved" if ok else "denied", reason)
    except Exception: pass
    if ok:
        return True, note, inp, (_always(pat, sugg, tool, c) if always else None)
    return False, (f"The user denied this ({reason})." + (f" They said: “{note}”." if note else
                   " Don't retry it or work around it; say what you were going to do.")), None, None


def _answer_questions(inp, ctx):
    qs = (inp or {}).get("questions") or []
    ask = ctx.get("ask")
    answers = {}
    for qd in qs:
        text = str(qd.get("question") or "")
        opts = [str(o.get("label") if isinstance(o, dict) else o) for o in qd.get("options") or []]
        if Q.asks_to_continue(text):
            answers[text] = next((o for o in opts if re.match(r"(?i)(yes|continue|keep|proceed)", o)),
                                 "Yes — keep going")
            continue
        ans = ask(text[:600], opts[:8], bool(qd.get("multiSelect"))) if ask else None
        if ans is None or ans == "":
            return (False, "No answer came (nobody is watching, or 30 minutes passed). Make the most "
                           "reasonable choice yourself, say which and why, and carry on.", None)
        answers[text] = ", ".join(ans) if isinstance(ans, list) else str(ans)
    return True, "", {**(inp or {}), "answers": answers}


# ------------------------------------------------------------------ live control

RUNS = {}            # Orbit chat id -> the Claude Code process answering in it
# Claude Code's background work, per Orbit chat: shells started with run_in_background,
# subagents sent to the background, and whatever else it reports as a task. Kept here so
# /tasks, the home page and the phone can list it while it runs.
BG_TASKS = {}        # orbit sid -> {task id: {"id", "kind", "description", "status", "since", "ended", "summary"}}
_BG_LOCK = threading.Lock()

def bg_task(sid, tid, **kw):
    """Record or update one background task of a chat; returns its record."""
    if not tid: return None
    with _BG_LOCK:
        tasks = BG_TASKS.setdefault(sid or "_", {})
        # one task, two names (the id in the tool's result, the id in Claude's task events):
        # the call that started it ties them together
        if kw.get("tool_id") and str(tid) not in tasks:
            same = next((k for k, v in tasks.items() if v.get("tool_id") == kw["tool_id"]), None)
            if same: tid = same
        rec = tasks.setdefault(str(tid), {"id": str(tid), "kind": "task", "description": "",
                                          "status": "running", "since": time.time(), "ended": None})
        rec.update({k: v for k, v in kw.items() if v not in (None, "")})
        if rec["status"] not in ("running", "pending") and not rec.get("ended"):
            rec["ended"] = time.time()
        # finished ones are kept a while so the list can say how they ended
        for k in [k for k, v in tasks.items() if v.get("ended") and time.time() - v["ended"] > 1800]:
            tasks.pop(k, None)
        return dict(rec)

def bg_tasks(sid=None):
    """Background tasks still running (and those ended in the last half hour), newest first."""
    with _BG_LOCK:
        rows = [dict(r, sid=s) for s, t in BG_TASKS.items() if sid in (None, s) for r in t.values()]
    return sorted(rows, key=lambda r: -(r.get("since") or 0))

def bg_running(sid):
    with _BG_LOCK:
        return any(r["status"] in ("running", "pending") for r in (BG_TASKS.get(sid) or {}).values())

def bg_ended(sid, why="ended"):
    """The Claude process of a chat is gone: its background tasks went with it."""
    with _BG_LOCK:
        for r in (BG_TASKS.get(sid) or {}).values():
            if r["status"] in ("running", "pending"):
                r.update(status=why, ended=time.time())

def _brief_args(inp):
    """A subagent step's arguments, cut down to what a one-line row shows."""
    out = {}
    for k in ("file_path", "notebook_path", "path", "pattern", "command", "url", "query", "description",
              "prompt", "glob", "subagent_type"):
        v = (inp or {}).get(k)
        if v not in (None, ""): out[k] = str(v)[:200]
    return out

INIT = {}            # what the last run reported: commands, agents, models, tools, skills


def known_tools(add=None):
    """Every tool name Claude Code has told us it has.

    Easy mode keeps a few tools and denies the rest, which means naming them --- and a
    name Claude Code does not know stops the run before it starts ("Permission deny rule
    X matches no known tool"). Its own init event lists exactly what it has, in this
    version, with these plugins; that list is remembered here rather than guessed."""
    path = os.path.join(_work_dir(), "tools-seen.json")
    try: have = set(json.load(open(path)))
    except Exception: have = set()
    if add:
        fresh = have | {str(x) for x in add if x and not str(x).startswith("mcp__")}
        if fresh != have:
            have = fresh
            tmp = path + ".tmp"
            try:
                with open(tmp, "w") as fh: json.dump(sorted(have), fh)
                os.replace(tmp, path)
            except OSError: pass
    return sorted(have)
CONTROLS = ("set_permission_mode", "set_model", "set_max_thinking_tokens", "get_context_usage",
            "mcp_status", "mcp_toggle", "mcp_reconnect", "mcp_set_servers", "stop_task",
            "rewind_files", "reload_plugins", "get_settings", "apply_flag_settings", "interrupt")


def _prefs_path():
    return os.path.join(_work_dir(), "chat-prefs.json")


_PREFS_CACHE = {"at": None, "data": {}}

def chat_prefs(sid=None):
    """What a chat remembers for itself, or every chat's when no sid is given.

    Read on a hot path -- qqcore.chat_setting() asks for each per-chat key, and
    full_access() asks on every tool call -- so the parse is kept until the file's
    mtime and size change. Another process writing it is picked up the same way."""
    path = _prefs_path()
    try: stamp = os.stat(path)
    except OSError: stamp = None
    key = (stamp.st_mtime_ns, stamp.st_size) if stamp else None
    if key != _PREFS_CACHE["at"] or not isinstance(_PREFS_CACHE["data"], dict):
        try:
            with open(path) as f: d = json.load(f)
            if not isinstance(d, dict): d = {}
        except Exception: d = {}
        _PREFS_CACHE["data"], _PREFS_CACHE["at"] = d, key
    d = _PREFS_CACHE["data"]
    if not sid: return d
    got = d.get(sid)
    return dict(got) if isinstance(got, dict) else {}


def set_chat_pref(sid, **kw):
    with _WRITE_LOCK:                   # read, change, write: one chat at a time, or a change is lost
        return _set_chat_pref(sid, **kw)


def _set_chat_pref(sid, **kw):
    d = dict(chat_prefs())          # the cache's own dict must not be written through
    cur = dict(d.get(sid) or {})
    for k, v in kw.items():
        if v is None: cur.pop(k, None)
        else: cur[k] = v
    d[sid] = cur
    _write_json("chat-prefs.json", d)
    return cur


def control(sid, subtype, timeout=15, **params):
    """Send one control request to the Claude Code run answering in this chat
    and wait for its reply. None when nothing is running there."""
    run = RUNS.get(sid)
    if not run: return None
    if subtype not in CONTROLS: return {"error": f"unknown control {subtype}"}
    rid = "orbit-" + uuid.uuid4().hex[:10]
    ev = threading.Event()
    run["waiters"][rid] = {"event": ev, "response": None}
    if not run["send"]({"type": "control_request", "request_id": rid,
                        "request": {"subtype": subtype, **params}}):
        run["waiters"].pop(rid, None)
        return {"error": "the run has ended"}
    ev.wait(timeout)
    w = run["waiters"].pop(rid, {})
    return w.get("response") if ev.is_set() else {"error": "no reply from Claude Code"}


_LEARN = {"lock": threading.Lock()}


def _lines_until(proc, deadline):
    """Yield stdout lines until the deadline, and kill the process when it passes.

    `while time.time() < deadline: proc.stdout.readline()` only checks the clock
    *between* lines, so a claude that printed nothing and did not exit blocked for ever
    — with the lock these callers hold, so every later caller blocked behind it too.
    The timeout is enforced by a watchdog that kills the process, which is what makes
    readline return."""
    timer = threading.Timer(max(0.1, deadline - time.time()), lambda: _kill(proc))
    timer.daemon = True
    timer.start()
    try:
        while True:
            line = proc.stdout.readline()
            if not line: return
            yield line
    finally:
        timer.cancel()


def learn_tools(timeout=40):
    """Ask Claude Code what tools it has, by starting a turn and stopping at the answer
    to the first question it asks itself.

    The initialize handshake does not say; the init event at the start of a turn does.
    So a turn is started and the process killed the moment that event arrives -- before
    the model is called, so nothing is spent and nothing is saved."""
    with _LEARN["lock"]:
        exe = which_claude()
        if not exe: return known_tools()
        c = cfg()
        settings_path, mcp_path = launcher_files(c, "learn")
        argv = build_argv(c, settings_path=settings_path, mcp_path=mcp_path, append=launcher_append(c))
        proc = None
        try:
            proc = subprocess.Popen(argv + ["--no-session-persistence"], cwd=HOME,
                                    env=target_env(harness_target()), stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    start_new_session=True)
            proc.stdin.write((json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}})
                              + "\n").encode())
            proc.stdin.flush()
            for line in _lines_until(proc, time.time() + timeout):
                try: ev = json.loads(line)
                except ValueError: continue
                if ev.get("type") == "system" and ev.get("subtype") == "init" and ev.get("tools"):
                    INIT["tools"] = ev["tools"]
                    return known_tools(ev["tools"])
        except Exception:
            pass
        finally:
            if proc is not None: _kill(proc)
            for f in (settings_path, mcp_path):
                try:
                    if f: os.remove(f)
                except OSError: pass
        return known_tools()


_CATALOG = {"at": 0.0, "lock": threading.Lock()}


def command_catalog(max_age=600):
    """Claude's slash commands, skills, agents and models, as the initialize
    handshake reports them -- asked of a short-lived claude process that never
    calls the model, so the / menu is complete before a chat's first answer."""
    with _CATALOG["lock"]:
        if INIT.get("commands") and time.time() - _CATALOG["at"] < max_age:
            return INIT
        exe = which_claude()
        if not exe: return INIT
        c = cfg()
        settings_path, mcp_path = launcher_files(c, "catalog")
        argv = build_argv(c, settings_path=settings_path, mcp_path=mcp_path, append=launcher_append(c))
        try:
            proc = subprocess.Popen(argv + ["--no-session-persistence"], cwd=HOME,
                                    env=target_env(harness_target()), stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            return INIT
        try:
            proc.stdin.write((json.dumps({"type": "control_request", "request_id": "orbit-init",
                                          "request": {"subtype": "initialize"}}) + "\n").encode())
            proc.stdin.flush()
            for line in _lines_until(proc, time.time() + 30):
                try: ev = json.loads(line)
                except ValueError: continue
                if ev.get("type") == "system" and ev.get("subtype") == "init" and ev.get("tools"):
                    INIT["tools"] = ev["tools"]; known_tools(ev["tools"])
                if ev.get("type") == "control_response":
                    resp = (ev.get("response") or {}).get("response") or {}
                    for k in ("commands", "agents", "models", "output_style", "available_output_styles"):
                        if resp.get(k) is not None: INIT[k] = resp[k]
                    _CATALOG["at"] = time.time()
                    break
        finally:
            _kill(proc)
            for f in (settings_path, mcp_path):
                try:
                    if f: os.remove(f)
                except OSError: pass
        return INIT


def set_permission_mode(sid, mode):
    """Change a chat's permission mode: now, if it is answering, and for its next runs."""
    if mode not in PERMISSION_MODES: return {"error": f"unknown mode {mode}"}
    set_chat_pref(sid, permission_mode=mode)
    live = control(sid, "set_permission_mode", mode=mode)
    return {"ok": True, "mode": mode, "live": live is not None}


# ------------------------------------------------------------------ one answer

def _content_blocks(user_content, stamp):
    """Orbit's message content as Claude input blocks (text and images)."""
    blocks = []
    if isinstance(user_content, list):
        for part in user_content:
            if part.get("type") == "text":
                blocks.append({"type": "text", "text": part.get("text", "")})
            elif part.get("type") == "image_url":
                url = (part.get("image_url") or {}).get("url", "")
                m = re.match(r"data:(image/[a-z+.-]+);base64,(.*)$", url, re.S)
                if m:
                    blocks.append({"type": "image", "source": {"type": "base64",
                                   "media_type": m.group(1), "data": m.group(2)}})
    else:
        blocks.append({"type": "text", "text": str(user_content or "")})
    for b in blocks:
        if b["type"] == "text":
            b["text"] = stamp + b["text"]
            break
    return blocks


def _tool_text(content):
    if isinstance(content, str): return content
    out = []
    for b in content or []:
        if isinstance(b, dict):
            if b.get("type") == "text": out.append(b.get("text", ""))
            elif b.get("type") == "image": out.append("[image]")
    return "\n".join(out)


def _diff_for(name, inp, result):
    """Orbit's diff card for a finished Write/Edit, from what Claude reports."""
    try:
        r = result if isinstance(result, dict) else {}
        path = r.get("filePath") or (inp or {}).get("file_path") or ""
        if name == "Write":
            old = r.get("originalFile") or ""
            new = (inp or {}).get("content") or r.get("content") or ""
        elif name in ("Edit", "MultiEdit"):
            patch = r.get("structuredPatch")
            if patch:
                lines = []
                for h in patch:
                    lines.append(f"@@ -{h.get('oldStart')},{h.get('oldLines')} +{h.get('newStart')},{h.get('newLines')} @@")
                    lines += h.get("lines") or []
                added = sum(1 for l in lines if l.startswith("+"))
                removed = sum(1 for l in lines if l.startswith("-"))
                return {"path": path, "diff": "\n".join(lines[:400]), "added": added,
                        "removed": removed, "existed": True}
            old, new = (inp or {}).get("old_string", ""), (inp or {}).get("new_string", "")
        else:
            return None
        d = list(difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=3))[2:]
        return {"path": path, "diff": "\n".join(d[:400]),
                "added": sum(1 for l in d if l.startswith("+")),
                "removed": sum(1 for l in d if l.startswith("-")), "existed": bool(old)}
    except Exception:
        return None


class _Plan:
    """Claude's todo list (TodoWrite, or TaskCreate/TaskUpdate) as Orbit's plan."""

    def __init__(self):
        self.tasks = collections.OrderedDict()     # id -> [text, done, in progress]

    def from_tool(self, name, inp, result_text):
        inp = inp or {}
        if name == "TodoWrite":
            self.tasks.clear()
            for i, t in enumerate(inp.get("todos") or []):
                self.tasks[str(i)] = [t.get("content") or t.get("activeForm") or "", t.get("status") == "completed",
                                      t.get("status") == "in_progress"]
            return True
        if name == "TaskCreate":
            m = re.search(r"#(\d+)", result_text or "")
            tid = m.group(1) if m else str(len(self.tasks) + 1)
            self.tasks[tid] = [inp.get("subject") or inp.get("description") or "", False, False]
            return True
        if name == "TaskUpdate":
            tid = str(inp.get("taskId") or inp.get("id") or "")
            if tid in self.tasks:
                if inp.get("subject"): self.tasks[tid][0] = inp["subject"]
                if inp.get("status"):
                    self.tasks[tid][1] = inp["status"] == "completed"
                    self.tasks[tid][2] = inp["status"] == "in_progress"
                if inp.get("status") == "deleted": self.tasks.pop(tid, None)
                return True
        return False

    def text(self):
        return "\n".join(f"{i}. [{'x' if d else '>' if a else ' '}] {t}"
                         for i, (t, d, a) in enumerate(self.tasks.values()))

    def steps(self):
        return [{"text": t[:200], "done": d, "active": a} for t, d, a in self.tasks.values()]


def _snapshot(path, pending):
    """Before Claude changes a file: keep its current contents, so Orbit's undo
    can put it back (and remember whether the file is new)."""
    if not path: return
    p = os.path.abspath(os.path.expanduser(path))
    if p in pending: return
    existed = os.path.isfile(p)
    snap = None
    if existed:
        try: snap = Q._save_checkpoint(p)
        except Exception: snap = None
    pending[p] = {"path": p, "snap": snap, "created": not existed}


def last_assistant_uuid(path):
    """The uuid of the last main-thread assistant record in a transcript."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2); size = fh.tell()
            fh.seek(max(0, size - 400000))
            lines = fh.read().splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try: d = json.loads(line)
        except ValueError: continue
        if d.get("type") == "assistant" and not d.get("isSidechain"):
            return d.get("uuid")
    return None


def marker_of(messages):
    for m in reversed(messages or []):
        if isinstance(m, dict) and isinstance(m.get("claude"), dict) and m["claude"].get("session"):
            return m["claude"]
    return None


def _prior_transcript(messages, limit=24000):
    """A chat that began on another model: what was said, for the first turn."""
    lines = []
    for m in messages:
        role = m.get("role")
        if role not in ("user", "assistant") or m.get("nudge"): continue
        c = m.get("content")
        if isinstance(c, list):
            c = " ".join(p.get("text", "") for p in c if p.get("type") == "text")
        c = str(c or "").strip()
        if c: lines.append(("User: " if role == "user" else "Assistant: ") + c)
    text = "\n\n".join(lines)
    return text[-limit:]


def _system_parts(project):
    """Project rules and the user's standing instructions, as Orbit gives any model."""
    parts = []
    try:
        rules = Q.project_rules(project) if project else ""
        if rules: parts.append("# Project rules\n" + str(rules)[:12000])
    except Exception:
        pass
    try:
        ins = open(os.path.join(Q.CONFIG, "instructions.md")).read().strip()
        if ins: parts.append("# The user's standing instructions\n" + ins[:6000])
    except Exception:
        pass
    return parts


def _orbit_append(project, c, orbit_tools, chat_instructions=None, kind="local"):
    """What Orbit adds to Claude's system prompt: the launcher's note, this chat's
    own instructions (/sysprompt), and Orbit's own context only when that extra is
    turned on."""
    extra = []
    if chat_instructions:
        extra.append("# Instructions for this chat\n" + str(chat_instructions)[:8000])
    if c.get("orbit_context"):
        extra += _system_parts(project)
        extra.append("# Running inside Orbit\n- The user is chatting through Orbit, a local desktop "
                     "window onto this session.")
    if orbit_tools:
        extra.append("- Orbit's tools are available as mcp__orbit__*.")
    return launcher_append(c, extra, kind)


def run_turn(messages, user_content, tools, emit=None, approve=None, cancel=None, inbox=None,
             interrupt=None, sid=None, checkpoint=None, project=None, max_minutes=None,
             read_only=None, _compacting=False, **_):
    """One answer through Claude Code. Same contract as qqcore.turn()."""
    q = Q
    emit = emit or (lambda k, p: None)
    cancel = cancel or q.CANCEL
    c = cfg()
    T = q.TURN_CTX
    T.sid, T.project, T.read_only = sid, project, bool(read_only)
    T.changes = changes = []           # files this answer changes, shared with helper threads
    exe = which_claude()
    t_start = time.time()
    if not exe:
        msg = "Claude Code is not installed (no `claude` on PATH). Install it, or pick another model."
        emit("error", msg); emit("done", None)
        return msg

    spec = q.current_model() or {}
    label = (spec.get("label") or "Claude Code · local Qwen").replace(" · CLI", "")
    if not label.startswith("Claude Code"): label = "Claude Code · " + label
    emit("model", {"id": spec.get("id"), "label": label, "provider": "Claude Code"})
    target = harness_target(spec)
    if target["local"]:
        # A model on this Mac pays for the system prompt in seconds, not fractions of a
        # cent: measured here, "standard" gave Claude Code a 40k-token prompt of MCP
        # servers, plugins and their hooks, and one file read took 179s; the same read
        # on "lean" sent 10k and took 44s, with the same answer. So a local model gets
        # the lean profile unless you say otherwise (claude_qwen.local_profile).
        if c.get("local_profile"): c = {**c, "profile": c["local_profile"]}
        _wake_model(emit)
    elif target.get("subscription") and _harness().claude_login(
            max_age=30, token=(target.get("env") or {}).get("CLAUDE_CODE_OAUTH_TOKEN")) != "yes":
        msg = ("The `claude` command is not signed in to your Claude account. In a terminal run "
               "`claude setup-token`, then paste the token in Orbit → Settings → Models & keys → "
               "Claude · your subscription (or run `claude auth login`), and send this again.")
        messages.append({"role": "user", "content": user_content, "t": time.time()})
        emit("error", msg); emit("done", None)
        return msg
    elif target["key_missing"]:
        msg = target.get("error") or (
               f"No API key for {spec.get('provider_label') or target['provider']} "
               f"({target.get('key_name') or 'key'}). Add it in Settings → Models & keys.")
        messages.append({"role": "user", "content": user_content, "t": time.time()})
        emit("error", msg); emit("done", None)
        return msg

    prev = marker_of(messages) or {}
    used, old_id = int(prev.get("ctx") or 0), prev.get("model")
    if (not _compacting and old_id and old_id != spec.get("id") and used > 0.8 * target["ctx"]):
        # moving to a model with a smaller window than this chat now fills: Claude Code
        # would compact on the new model, sending it the whole chat it cannot hold.
        # Compact on the model the chat came from instead, which can.
        old = q.current_model(old_id)
        if old and is_engine(old) and harness_target(old)["ctx"] >= used:
            emit("notice", {"msg": f"this chat (~{used // 1000}k tokens) is bigger than {label}'s "
                                   f"{target['ctx'] // 1000}k window: compacting it on "
                                   f"{(old.get('label') or old_id)} first"})
            saved = getattr(q.TURN_CTX, "model", None)
            q.TURN_CTX.model = old_id
            try:
                run_turn(messages, "/compact", tools, emit=lambda k, p: k not in ("done", "model") and emit(k, p),
                         approve=approve, cancel=cancel, inbox=None, interrupt=interrupt, sid=sid,
                         project=project, read_only=read_only, _compacting=True)
            finally:
                q.TURN_CTX.model = saved
            if cancel is not None and cancel.is_set():
                emit("done", None)
                return ""

    mk = dict(marker_of(messages) or {})
    prefs0 = chat_prefs(sid) if sid else {}
    # a chat that runs on another machine over SSH (its folder is there); a chat keeps
    # the host its Claude session started on
    host = (mk.get("host") if mk.get("session") and mk.get("remote_ready") else None) \
        or (prefs0.get("host") if "host" in prefs0 else (None if mk.get("session") else c.get("default_host"))) or None
    remote = None
    if host:
        import ssh_remote
        info = ssh_remote.probe(host, max_age=1800)
        if not info.get("ok") or not info.get("claude"):
            msg = (f"Could not start Claude Code on {host}: " + (info.get("error") or "no `claude` found there — "
                   "install Claude Code on it (or open a Claude Code SSH session there once), then try again."))
            messages.append({"role": "user", "content": user_content, "t": time.time()})
            ssh_remote._PROBES.pop(host, None)
            emit("error", msg); emit("done", None)
            return msg
        remote = {"host": host, "claude": info["claude"], "home": info.get("home") or "~"}
    jp = None if remote else (jsonl_path(mk.get("session"), mk.get("cwd")) if mk else None)
    # on another machine the transcript lives there: a session that started there resumes
    resume = bool(jp) or bool(remote and mk.get("session") and mk.get("host") == host and mk.get("remote_ready"))
    fork, resume_at = False, None
    if resume and remote:
        # the transcript is on that machine: Orbit remembers where its session ended
        # (the last answer it received), so a chat edited or regenerated here resumes
        # at the last answer it still has, and a forked chat branches off
        fork = bool(sid and mk.get("owner") and mk["owner"] != sid)
        mine = next((m.get("claude_uuid") for m in reversed(messages)
                     if m.get("role") == "assistant" and m.get("claude_uuid")), None)
        last_there = prefs0.get("remote_last_uuid") if not fork else None
        if mine and last_there and mine != last_there:
            resume_at = mine
    if jp:
        # a chat forked in Orbit shares its parent's Claude session: branch it off
        fork = bool(sid and mk.get("owner") and mk["owner"] != sid)
        # a chat edited or regenerated in Orbit no longer ends where Claude's
        # transcript does: resume at the last message Orbit still has
        mine = next((m.get("claude_uuid") for m in reversed(messages)
                     if m.get("role") == "assistant" and m.get("claude_uuid")), None)
        if mine and mine != last_assistant_uuid(jp):
            resume_at = mine
    prefs = chat_prefs(sid) if sid else {}
    if not resume:
        # a new session starts in the folder chosen for this chat, else the
        # chat's project folder, else Orbit's workspace
        folder = None
        try: folder = q.project_folder(project) if project else None
        except Exception: folder = None
        cwd = prefs.get("cwd") or folder or (c.get("default_dir") or "").strip() or q.WORKSPACE
        if remote: cwd = prefs.get("cwd") or default_remote_dir(remote["host"])     # a folder on that machine
        prior = _prior_transcript([m for m in messages if m.get("role") != "system"])
        ran = []
        mk = {"session": str(uuid.uuid4()), "cwd": cwd, "skills": [], "owner": sid}
        if remote: mk["host"] = remote["host"]
    else:
        cwd = mk.get("cwd") or q.WORKSPACE
        prior = ""
        # shell commands you ran yourself ("!" in the box) since Claude's last answer are
        # in Orbit's chat but not in Claude's session: hand them over with this message
        last_seen = max((i for i, m in enumerate(messages) if m.get("role") == "assistant"), default=-1)
        ran = [m for m in messages[last_seen + 1:] if m.get("role") == "user" and m.get("bang")]
        if ran:
            prior_ran = "\n\n".join(str(m.get("content") or "") for m in ran)[-24000:]
        if jp and os.path.dirname(jp) != os.path.join(projects_dir(), encode_cwd(cwd)):
            # resumed from wherever the transcript actually is
            cwd = mk.get("cwd") or cwd
    if not remote and not os.path.isdir(cwd): cwd = q.WORKSPACE

    plain = user_content if isinstance(user_content, str) else " ".join(
        x.get("text", "") for x in user_content if isinstance(x, dict))
    # skills: this chat's set, grown by what this message needs
    chosen = list(dict.fromkeys(mk.get("skills") or []))
    hint = []
    if c.get("skill_routing") and c.get("profile") != "lean" and not remote:
        routed = route_skills(plain, limit=6)
        hint = routed[:3]
        want = [s["name"] for s in routed]
        m = re.match(r"^/([A-Za-z0-9:_-]+)", plain.strip())
        if m: want.insert(0, m.group(1))
        for n in c.get("core_skills") or []: want.append(n)
        for n in want:
            if n not in chosen: chosen.append(n)
        chosen = chosen[:max(int(c.get("max_skills") or 14), len(c.get("core_skills") or []))]
    mk["skills"] = chosen
    mk["owner"] = mk.get("owner") or sid
    # which model the chat is on and how full its window is, so a later switch to a
    # smaller model can make room first
    mk["model"], mk["ctx_max"] = spec.get("id"), target["ctx"]

    now = time.time()
    messages.append({"role": "user", "content": user_content, "t": now, "claude": dict(mk)})
    umsg = messages[-1]
    if sid: q.LAST_TURN.pop(sid, None)

    token = None
    servers = {}
    specs = []
    if bridge_url() and not remote:
        if c.get("orbit_tools"):
            allow = set(c.get("orbit_tool_names") or [])
            specs = [x for x in (tools or []) if x.get("function", {}).get("name") in allow]
        if (c.get("orbit_tools") or c.get("project_tools")) and project:
            try:
                q.file_tool_specs(project)
                mine = set((q.PROJECT_FILE_TOOLS.get(project) or {}).keys())
                specs += [x for x in (tools or []) if x.get("function", {}).get("name") in mine
                          and x not in specs]
            except Exception:
                pass
    orbit_tools = bool(specs)
    if orbit_tools:
        token = secrets.token_hex(16)
        BRIDGE[token] = {"sid": sid, "project": project, "read_only": bool(read_only),
                         "emit": emit, "approve": approve, "cancel": cancel, "specs": specs,
                         "ask": getattr(T, "ask", None), "model": getattr(T, "model", None)}
        servers["orbit"] = {"type": "stdio", "command": sys.executable,
                            "args": [os.path.join(os.path.dirname(os.path.abspath(__file__)), "orbit-mcp")],
                            "env": {"ORBIT_MCP_URL": bridge_url(), "ORBIT_MCP_TOKEN": token}}
    # on another machine Claude uses that machine's own setup (settings, skills, MCP)
    settings_path, mcp_path = (None, None) if remote else launcher_files(c, mk["session"], skills=chosen,
                                                                           extra_servers=servers)

    # a chat's own mode, else Orbit's default for new chats, else Claude's own
    mode = prefs.get("permission_mode") or c.get("permission_mode") or None
    if not approve and c.get("unattended_mode"):
        mode = c["unattended_mode"]
    kind = "subscription" if target.get("subscription") else ("local" if target.get("local") else "provider")
    argv = build_argv(c, session_id=mk["session"], resume=resume, read_only=bool(read_only), mode=mode,
                      model=target.get("cli_model"), kind=kind, remote=bool(remote),
                      effort=getattr(T, "effort", None) or q.S.get("reasoning_effort"),
                      settings_path=settings_path, mcp_path=mcp_path, add_dirs=prefs.get("add_dirs"),
                      append=_orbit_append(project, c, orbit_tools, prefs.get("instructions"), kind))
    if fork: argv.append("--fork-session")
    if resume_at: argv += ["--resume-session-at", resume_at]
    env = target_env(target)

    stamp = f"[{q.sent_at(now)}] " if c.get("message_time") else ""
    blocks = _content_blocks(user_content, stamp)
    if resume and ran:
        blocks.insert(0, {"type": "text", "text": "[Since your last reply, the user ran these commands themselves:]\n"
                          + prior_ran + "\n[End of the commands.]"})
    if prior:
        blocks.insert(0, {"type": "text", "text": "[Earlier in this chat, before it moved to Claude Code:]\n"
                          + prior + "\n[End of the earlier conversation.]"})
    if hint and c.get("skill_hint"):
        blocks.append({"type": "text", "text": "[Orbit: skills that may fit this request — load one with "
                       "the Skill tool if it applies: " + "; ".join(
                           f"{s['name']} ({s['description'][:160]})" for s in hint) + "]"})

    _run_log(sid, mk, resume, fork, resume_at, c, cwd, argv)
    # A chat on another machine keeps its Claude Code running between messages: a new
    # SSH connection and Claude Code starting on the host took most of every answer's
    # wait. The next message goes straight into the same session while nothing that
    # shapes the process changed; it closes after a while idle (see LIVE).
    live = None
    keep = bool(remote and sid and float(c.get("remote_keep_alive_min", 30) or 0) > 0)
    sig = None
    # A chat on this Mac keeps its Claude Code too while background work it started (a shell
    # run in the background, a background agent) is still going -- as Claude's own app does;
    # closing it would end that work with the answer.
    local_kept = bool(not remote and sid and (LIVE.get(sid) or {}).get("host") is None and sid in LIVE)
    if keep or local_kept or (not remote and sid):
        sig = json.dumps([(remote or {}).get("host"), (remote or {}).get("claude"), cwd, mk["session"], mode,
                          [a for i, a in enumerate(argv[1:]) if a not in ("--resume", "--session-id")
                           and argv[i] not in ("--resume", "--session-id")],
                          sorted((k, v) for k, v in env.items() if k.startswith(("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT",
                                 "CLAUDE_CODE_MAX_CONTEXT", "CLAUDE_CODE_SUBAGENT")))])
    if keep or local_kept:
        live = LIVE.get(sid)
        if live and (live["sig"] != sig or live["proc"].poll() is not None or fork or resume_at):
            close_live(sid)
            live = None
    try:
        if live:
            proc = live["proc"]
            emit("status", {"msg": f"continuing on {remote['host']}" if remote else "continuing the running session"})
        elif remote:
            import ssh_remote
            renv, forward = remote_target_env(target, env)
            emit("status", {"msg": f"starting Claude Code on {remote['host']}"})
            proc = ssh_remote.popen(remote["host"], remote["claude"], cwd, argv[1:], renv, forward=forward)
        else:
            proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, start_new_session=True)
    except (OSError, ValueError) as e:
        msg = f"Could not start Claude Code: {e}"
        emit("error", msg); emit("done", None)
        return msg

    wlock = live["wlock"] if live else threading.Lock()
    def send(obj):
        try:
            with wlock:
                proc.stdin.write((json.dumps(obj) + "\n").encode())
                proc.stdin.flush()
            return True
        except (BrokenPipeError, OSError, ValueError):
            return False

    lines = live["lines"] if live else collections.deque()
    got = live["got"] if live else threading.Event()
    trace = os.environ.get("ORBIT_ENGINE_TRACE")          # a file to copy Claude Code's events into, when debugging
    def reader():
        for raw in proc.stdout:
            if trace:
                try:
                    with open(trace, "ab") as fh: fh.write(b"< " + raw)
                except OSError: pass
            lines.append(raw); got.set()
        lines.append(None); got.set()
    err_tail = live["err_tail"] if live else collections.deque(maxlen=40)
    def err_reader():
        for raw in proc.stderr:
            s = raw.decode("utf-8", "replace").rstrip()
            if s and "unrecognized_model" not in s: err_tail.append(s)
    if not live:
        threading.Thread(target=reader, daemon=True).start()
        threading.Thread(target=err_reader, daemon=True).start()
    if live:
        live["err_tail"].clear()

    run = {"send": send, "waiters": {}, "session": mk["session"], "started": t_start}
    if sid: RUNS[sid] = run
    # what this Claude setup offers (slash commands with descriptions, agents, models)
    if not live:
        send({"type": "control_request", "request_id": "orbit-init", "request": {"subtype": "initialize"}})
    send({"type": "user", "message": {"role": "user", "content": blocks},
          "parent_tool_use_id": None, "session_id": mk["session"]})
    pending = 1
    roots = [cwd, q.WORKSPACE]
    try:
        if project: roots.append(q.project_folder(project))
    except Exception:
        pass
    ctx = {"cfg": c, "read_only": bool(read_only), "emit": emit, "approve": approve,
           "ask": getattr(T, "ask", None), "roots": roots}

    # state of the stream
    cur = None                         # the Orbit assistant message being written
    cur_id = None
    marks, mstate = [], [0, ""]
    tool_meta = {}                     # tool_use id -> (name, input, started)
    pending_changes = {}               # path -> the snapshot taken before Claude changed it
    plan = _Plan()
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    tool_runs = 0
    final_text, result_err = "", None
    interrupted_at = None
    every = float(q.S.get("long_run_notice_min") or 0) * 60
    next_notice = t_start + every if every else None
    last_ckpt = 0.0
    subagents = {}                     # Agent/Task call id -> what its subagent has done
    done_subs = {}                     # … and how it ended, when that came before the call's result
    streamed = set()                   # message ids whose text arrived as a stream
    step_prompt = [0]                  # prompt size reported at the start of the current message

    def respond(req_id, response):
        send({"type": "control_response", "response": {"subtype": "success", "request_id": req_id,
                                                        "response": response}})

    def handle_permission(req_id, r):
        # a thread of its own: an approval can wait for minutes while the stream goes on
        tool, inp = r.get("tool_name") or "", r.get("input") or {}
        try:
            PT = q.TURN_CTX
            PT.sid, PT.project, PT.read_only, PT.changes = sid, project, bool(read_only), changes
            ok, note, upd, perms = decide(tool, inp, ctx, r)
        except Exception as e:
            # an unanswered prompt would leave Claude Code waiting forever
            ok, note, upd, perms = False, f"Orbit could not decide on this ({type(e).__name__}: {e}).", None, None
        if ok:
            out = {"behavior": "allow", "updatedInput": upd if upd is not None else inp}
            if perms: out["updatedPermissions"] = perms
            respond(req_id, out)
        else:
            respond(req_id, {"behavior": "deny", "message": note or "Denied."})

    def new_step(msg_id):
        nonlocal cur, cur_id, marks, mstate
        cur = {"role": "assistant", "content": "", "model": label, "t": time.time()}
        cur_id = msg_id
        marks, mstate = [], [0, ""]
        messages.append(cur)

    stopped = False
    kept = False
    try:
        while True:
            if not lines:
                got.wait(0.25); got.clear()
            if cancel.is_set() and interrupted_at is None:
                interrupted_at = time.time()
                send({"type": "control_request", "request_id": "orbit-stop-" + uuid.uuid4().hex[:6],
                      "request": {"subtype": "interrupt"}})
                stopped = True
            if interrupted_at and time.time() - interrupted_at > 8 and proc.poll() is None:
                _kill(proc)
            if max_minutes and interrupted_at is None and (time.time() - t_start) / 60 > float(max_minutes):
                emit("round_limit", {"rounds": tool_runs, "reason": "time", "pending": []})
                cancel.set()
            if next_notice and time.time() >= next_notice:
                emit("long_running", {"minutes": int((time.time() - t_start) / 60), "rounds": tool_runs,
                                      "pending": [t for t, d, *_ in plan.tasks.values() if not d]})
                next_notice += every
            while inbox and interrupted_at is None:
                note = inbox.popleft()
                text = note.get("text", "") if isinstance(note, dict) else str(note)
                if send({"type": "user", "message": {"role": "user", "content": text},
                         "parent_tool_use_id": None, "session_id": mk["session"]}):
                    pending += 1
                    messages.append({"role": "user", "content": text, "t": time.time(),
                                     "interjection": True, "claude": dict(mk)})
                    emit("interjection", {"text": text})
            if interrupt is not None: interrupt.clear()
            if not lines:
                if proc.poll() is not None and not lines:
                    got.wait(0.5)
                    if not lines: break
                continue
            raw = lines.popleft()
            if raw is None: break
            try: ev = json.loads(raw)
            except ValueError: continue
            if not isinstance(ev, dict): continue
            t = ev.get("type")

            if t == "stream_event":
                if ev.get("parent_tool_use_id"): continue
                e = ev.get("event") or {}
                et = e.get("type")
                if et == "message_start":
                    mid = (e.get("message") or {}).get("id")
                    streamed.add(mid)
                    if mid != cur_id: new_step(mid)
                    u = (e.get("message") or {}).get("usage") or {}
                    ptok = (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) \
                        + (u.get("cache_creation_input_tokens") or 0)
                    if ptok and sid: q.SESSION_TOKENS[sid] = ptok
                    usage["prompt_tokens"] += ptok
                    step_prompt[0] = ptok
                elif et == "content_block_delta":
                    d = e.get("delta") or {}
                    if cur is None: new_step(None)
                    if d.get("type") == "text_delta":
                        emit("content_delta", d.get("text") or "")
                    elif d.get("type") == "thinking_delta":
                        s = d.get("thinking") or ""
                        q.para_marks(marks, mstate, s)
                        emit("thinking_delta", s)
                elif et == "message_delta":
                    u = e.get("usage") or {}
                    usage["completion_tokens"] += u.get("output_tokens") or 0
                    # some servers report the prompt size only at the end of a message
                    ptok = (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) \
                        + (u.get("cache_creation_input_tokens") or 0)
                    if ptok and not step_prompt[0]:
                        usage["prompt_tokens"] += ptok
                        if sid: q.SESSION_TOKENS[sid] = ptok
                continue

            if t == "assistant":
                msg = ev.get("message") or {}
                if ev.get("parent_tool_use_id"):
                    # a subagent at work: its steps go under the Agent row that started it
                    parent = ev["parent_tool_use_id"]
                    pinp = (tool_meta.get(parent) or ("", {}))[1] or {}
                    sa = subagents.setdefault(parent, {"description": pinp.get("description") or "helper",
                                                       "type": pinp.get("subagent_type") or "",
                                                       "steps": [], "tools": 0, "out": 0, "ctx": 0,
                                                       "t0": time.time()})
                    u = msg.get("usage") or {}
                    if u:
                        sa["out"] += int(u.get("output_tokens") or 0)
                        sa["ctx"] = max(sa["ctx"], int(u.get("input_tokens") or 0)
                                        + int(u.get("cache_read_input_tokens") or 0)
                                        + int(u.get("cache_creation_input_tokens") or 0))
                    for b in msg.get("content") or []:
                        if b.get("type") == "tool_use":
                            sa["tools"] += 1
                            step = {"name": b.get("name") or "tool", "args": _brief_args(b.get("input"))}
                            sa["steps"].append(step)
                            del sa["steps"][:-80]
                            emit("subagent", {"parent": parent, "description": sa["description"], "type": sa["type"],
                                              "name": step["name"], "args": step["args"], "tools": sa["tools"],
                                              "tokens": sa["ctx"] + sa["out"], "secs": round(time.time() - sa["t0"], 1)})
                            emit("subtask", {"description": sa["description"], "tool": step["name"]})
                    continue
                if msg.get("id") != cur_id or cur is None: new_step(msg.get("id"))
                if ev.get("uuid"): cur["claude_uuid"] = ev["uuid"]
                if msg.get("model") == "<synthetic>": cur["model"] = "Claude Code"
                for b in msg.get("content") or []:
                    bt = b.get("type")
                    if bt == "text":
                        cur["content"] = (cur.get("content") or "") + (b.get("text") or "")
                        if msg.get("id") not in streamed:
                            # local commands (/context, /cost, /compact…) answer at once, unstreamed
                            emit("content_delta", b.get("text") or "")
                    elif bt == "thinking":
                        cur["reasoning_content"] = (cur.get("reasoning_content") or "") + (b.get("thinking") or "")
                        if marks: cur["reasoning_marks"] = list(marks)
                    elif bt == "tool_use":
                        tid, name, inp = b.get("id"), b.get("name") or "", b.get("input") or {}
                        cur.setdefault("tool_calls", []).append({"id": tid, "type": "function", "function": {
                            "name": name, "arguments": json.dumps(inp)}})
                        tool_meta[tid] = (name, inp, time.time())
                        if name in WRITE_TOOLS:
                            _snapshot(inp.get("file_path") or inp.get("notebook_path"), pending_changes)
                        tool_runs += 1
                        emit("tool", {"name": name, "args": inp, "id": tid, "t": time.time()})
                continue

            if t == "user":
                if ev.get("parent_tool_use_id") or ev.get("isReplay"): continue
                msg = ev.get("message") or {}
                content = msg.get("content")
                if not isinstance(content, list): continue
                for b in content:
                    if b.get("type") != "tool_result": continue
                    tid = b.get("tool_use_id")
                    name, inp, t0 = tool_meta.get(tid, ("tool", {}, time.time()))
                    text = _tool_text(b.get("content"))
                    ok = not b.get("is_error")
                    secs = round(time.time() - t0, 2)
                    p = {"name": name, "id": tid, "ok": ok, "secs": secs, "output": text[:4000]}
                    if ok and name in ("Write", "Edit", "MultiEdit"):
                        dv = _diff_for(name, inp, ev.get("tool_use_result"))
                        if dv and dv.get("diff"): p["diff"] = dv
                        fp = os.path.abspath(inp.get("file_path") or "") if inp.get("file_path") else None
                        if fp and fp in pending_changes and not any(x.get("path") == fp for x in changes):
                            changes.append(pending_changes[fp])
                    sub = None
                    if name == "Agent" or name == "Task":
                        p["output"] = text[:4000]
                        # sent to the background ("Async agent launched"): the row stays open and
                        # its subagent keeps reporting until task_notification says it is done
                        low = text.lstrip().lower()
                        # "Async agent launched…", or a handback whose report comes as its own message:
                        # either way the subagent's own task event says when it is done
                        bg = bool(inp.get("run_in_background")) or low.startswith("async agent launched") \
                            or "delivered to you as a message" in low
                        if tid in done_subs:          # it reported back already: "Done (…)" straight away
                            bg = False
                            p["subagent"] = done_subs.pop(tid)
                        sa = None if p.get("subagent") else (subagents.get(tid) if bg else subagents.pop(tid, None))
                        if bg and sa is None:
                            sa = subagents[tid] = {"description": inp.get("description") or "helper",
                                                   "type": inp.get("subagent_type") or "", "steps": [], "tools": 0,
                                                   "out": 0, "ctx": 0, "t0": time.time()}
                        if p.get("subagent") and not sa:
                            sub = p["subagent"]
                        elif sa:
                            sub = {"description": sa["description"], "type": sa["type"], "tools": sa["tools"],
                                   "tokens": sa["ctx"] + sa["out"], "secs": secs, "steps": list(sa["steps"]),
                                   "background": bg}
                            p["subagent"] = sub
                    if name == "Bash" and inp.get("run_in_background"):
                        # "Command running in background with ID: bash_1"
                        m_ = re.search(r"background with ID:\s*(\S+)", text)
                        of_ = re.search(r"Output is being written to:\s*(\S+)", text)
                        rec = bg_task(sid, m_.group(1) if m_ else tid, kind="shell",
                                      description=inp.get("description") or str(inp.get("command") or "")[:160],
                                      command=str(inp.get("command") or "")[:300], tool_id=tid,
                                      output_file=of_.group(1).rstrip(".,;:)'\"") if of_ else None)
                        p["background"] = True
                        # the id the task goes by (Claude's own, when its task event came first)
                        if rec: emit("bgtask", {k: rec.get(k) for k in ("id", "kind", "description", "status")})
                    emit("tool_result", p)
                    tmsg = {"role": "tool", "tool_call_id": tid, "name": name, "t": time.time(),
                            "ok": ok, "secs": secs, "content": text[:60000]}
                    if sub: tmsg["subagent"] = sub
                    if p.get("background"): tmsg["background"] = True
                    messages.append(tmsg)
                    if ok and plan.from_tool(name, inp, text):
                        q.PLANS[sid or "_"] = {"steps": plan.steps(), "updated": time.time()}
                        emit("tool_result", {"name": "plan", "output": plan.text()})
                cur, cur_id = None, None
                if checkpoint and time.time() - last_ckpt > 15:
                    last_ckpt = time.time()
                    try: checkpoint()
                    except Exception: pass
                continue

            if t == "control_response":
                resp = ev.get("response") or {}
                rid = resp.get("request_id")
                if rid == "orbit-init":
                    INIT["commands"] = (resp.get("response") or {}).get("commands") or INIT.get("commands")
                    for k in ("agents", "models", "output_style", "available_output_styles", "account"):
                        if (resp.get("response") or {}).get(k) is not None:
                            INIT[k] = resp["response"][k]
                w = run["waiters"].get(rid)
                if w:
                    w["response"] = resp.get("response") if resp.get("subtype") == "success" \
                        else {"error": resp.get("error") or "failed"}
                    w["event"].set()
                continue

            if t == "control_request":
                r = ev.get("request") or {}
                rid = ev.get("request_id")
                if r.get("subtype") == "can_use_tool":
                    threading.Thread(target=handle_permission, args=(rid, r), daemon=True).start()
                else:
                    respond(rid, {})
                continue

            if t == "system":
                st = ev.get("subtype")
                if st == "init":
                    INIT.update({k: ev.get(k) for k in ("tools", "mcp_servers", "skills", "slash_commands",
                                                        "agents", "plugins", "permissionMode", "model",
                                                        "claude_code_version", "output_style") if k in ev})
                    if ev.get("tools"): known_tools(ev["tools"])
                    run["mode"] = ev.get("permissionMode")
                    if remote and not mk.get("remote_ready"):
                        mk["remote_ready"] = True; mk["host"] = remote["host"]
                        umsg["claude"] = dict(mk)
                    if ev.get("session_id") and ev["session_id"] != mk["session"]:
                        # a fork got its own session id: this chat follows it from now on
                        mk["session"] = ev["session_id"]; mk["owner"] = sid
                        umsg["claude"] = dict(mk)
                    bad = [s.get("name") for s in ev.get("mcp_servers") or []
                           if isinstance(s, dict) and s.get("status") not in ("connected", "pending")]
                    if bad:
                        emit("notice", {"msg": "MCP server not connected: " + ", ".join(bad)})
                elif st == "background_tasks_changed":
                    pass                                   # the task events above say it all
                elif st == "compact_boundary":
                    emit("notice", {"msg": "Claude Code compacted the conversation to make room"})
                elif st == "api_retry":
                    emit("retry", {"attempt": ev.get("attempt"), "of": ev.get("max_retries"),
                                   "wait": round((ev.get("retry_delay_ms") or 0) / 1000, 1),
                                   "error": str(ev.get("error") or "")[:300], "kind": "transient"})
                elif st == "status":
                    if ev.get("status") == "compacting":
                        emit("notice", {"msg": "compacting the conversation…"})
                    elif ev.get("compact_result") == "failed":
                        emit("notice", {"msg": "compacting failed: " + str(ev.get("compact_error") or "")})
                    elif ev.get("status") == "requesting":
                        emit("status", {"msg": "waiting for the model"})
                elif st in ("task_started", "task_progress", "task_notification", "task_updated"):
                    # Claude Code's background work: a shell run in the background, or a subagent
                    tid_ = ev.get("task_id") or ev.get("id") or ev.get("tool_use_id")
                    patch = ev.get("patch") or {}
                    status = str(ev.get("status") or patch.get("status") or "running").lower()
                    ttype = str(ev.get("task_type") or "").lower()
                    u_ = ev.get("usage") or {}
                    rec = bg_task(sid, tid_, status=status,
                                  kind=("agent" if "agent" in ttype else "shell" if ("bash" in ttype or "shell" in ttype) else None),
                                  description=ev.get("description"), tool_id=ev.get("tool_use_id"),
                                  summary=ev.get("summary") if st == "task_notification" else None,
                                  output_file=ev.get("output_file"), tools=u_.get("tool_uses"),
                                  tokens=u_.get("total_tokens"),
                                  secs=round(float(u_["duration_ms"]) / 1000, 1) if u_.get("duration_ms") else None)
                    if rec:
                        emit("bgtask", {k: rec.get(k) for k in ("id", "kind", "description", "status", "summary")})
                    parent = ev.get("tool_use_id") or (rec or {}).get("tool_id")
                    is_agent = parent in subagents or (tool_meta.get(parent) or ("",))[0] in ("Agent", "Task")
                    if st == "task_notification" and is_agent:
                        # a subagent finished: its Agent row now says "Done (…)"
                        pinp = (tool_meta.get(parent) or ("", {}))[1] or {}
                        sa = subagents.pop(parent, None) or {
                            "description": pinp.get("description") or "helper", "type": pinp.get("subagent_type") or "",
                            "steps": [], "tools": 0, "out": 0, "ctx": 0,
                            "t0": (tool_meta.get(parent) or ("", {}, time.time()))[2]}
                        u = ev.get("usage") or {}
                        sub = {"description": sa["description"], "type": sa["type"],
                               "tools": int(u.get("tool_uses") or sa["tools"]),
                               "tokens": int(u.get("total_tokens") or (sa["ctx"] + sa["out"])),
                               "secs": round(float(u.get("duration_ms") or 0) / 1000, 1) or round(time.time() - sa["t0"], 1),
                               "steps": list(sa["steps"]), "background": False,
                               "status": status, "summary": _report(ev.get("summary"))}
                        done_subs[parent] = sub
                        emit("subagent_done", {"parent": parent, "subagent": sub})
                        for m_ in reversed(messages):
                            if m_.get("role") == "tool" and m_.get("tool_call_id") == parent:
                                m_["subagent"] = sub; break
                    elif st == "task_notification" and (rec or {}).get("kind") != "agent":
                        msg = _system_notice(st, ev)
                        if msg: emit("notice", {"msg": msg, "kind": st})
                else:
                    msg = _system_notice(st, ev)
                    if msg: emit("notice", {"msg": msg, "kind": st})
                continue

            if t == "rate_limit_event":
                # Claude's plan allowance: a refused request says which window and when it resets,
                # so the chat can carry on by itself then (orbit-ui _LimitWatch)
                info = ev.get("rate_limit_info") or {}
                if info.get("status") == "rejected" and info.get("resetsAt"):
                    kind = {"five_hour": "5-hour", "seven_day": "weekly", "seven_day_opus": "weekly Opus",
                            "seven_day_sonnet": "weekly Sonnet"}.get(info.get("rateLimitType"), "usage")
                    when = time.strftime("%a %H:%M", time.localtime(float(info["resetsAt"])))
                    emit("notice", {"msg": f"Claude's {kind} limit reached — it resets {when}",
                                    "kind": "limit", "resets_at": float(info["resetsAt"])})
                continue

            if t == "result":
                pending -= 1
                if ev.get("is_error") and ev.get("subtype") not in ("success",):
                    result_err = ev.get("result") or ev.get("subtype")
                if isinstance(ev.get("result"), str) and not ev.get("is_error"):
                    final_text = ev["result"]
                if pending <= 0 or interrupted_at:
                    if inbox and interrupted_at is None:
                        continue               # a note arrived just as it finished
                    if (keep or (not remote and sid and bg_running(sid))) and proc.poll() is None:
                        kept = True            # the answer is done; the process waits for the next message
                        break
                    try: proc.stdin.close()
                    except Exception: pass
                continue
    finally:
        try:
            if kept and proc.poll() is None:
                LIVE[sid] = {"proc": proc, "sig": sig, "lines": lines, "got": got, "err_tail": err_tail,
                             "wlock": wlock, "host": remote["host"] if remote else None, "used": time.time()}
                _live_saved()
            elif proc.poll() is None:
                try: proc.stdin.close()
                except Exception: pass
                try: proc.wait(timeout=20)
                except subprocess.TimeoutExpired: _kill(proc)
            if not kept and LIVE.get(sid, {}).get("proc") is proc:
                LIVE.pop(sid, None); _live_saved()
            if not kept: bg_ended(sid)             # its background shells and agents ended with it
        except Exception:
            pass
        if token: BRIDGE.pop(token, None)
        for f in (settings_path, mcp_path):      # per-run files; the MCP one holds the run's token
            try:
                if f: os.remove(f)
            except OSError: pass
        if sid and RUNS.get(sid) is run: RUNS.pop(sid, None)
        for w in run["waiters"].values(): w["event"].set()

    rc = proc.poll()
    last = next((m for m in reversed(messages) if m.get("role") == "assistant"), None)
    answered = bool(last and last.get("t", 0) >= now and (last.get("content") or last.get("tool_calls")))
    if stopped and last is not None and last.get("t", 0) >= now:
        last["partial"] = True
    rec = {"secs": round(time.time() - t_start, 1), "usage": dict(usage), "tool_runs": tool_runs,
           "rounds": tool_runs}
    if remote and sid and not stopped:
        last_uuid = next((m.get("claude_uuid") for m in reversed(messages)
                          if m.get("role") == "assistant" and m.get("claude_uuid") and m.get("t", 0) >= now), None)
        if last_uuid: set_chat_pref(sid, remote_last_uuid=last_uuid)
    if isinstance(umsg.get("claude"), dict):
        # after /compact the old size no longer holds; the next answer measures it again
        umsg["claude"]["ctx"] = 0 if _compacting else int((q.SESSION_TOKENS.get(sid) if sid else 0)
                                                          or step_prompt[0] or 0)
    too_long = "prompt is too long" in (str(final_text or "") + " " + str(result_err or "")).lower()
    ch = [dict(x) for x in changes if x.get("path")]
    if last is not None and last.get("t", 0) >= now:
        last.update(secs=rec["secs"], usage=rec["usage"], tool_runs=tool_runs)
        if ch: last["changes"] = ch
        rec["t"] = last.get("t")
    rec["changes"] = [x["path"] for x in ch]
    if sid: q.LAST_TURN[sid] = rec
    if not answered and not stopped:
        tail = "\n".join(list(err_tail)[-6:]).strip()
        why = str(result_err or tail or f"Claude Code exited ({rc}) without answering")
        if remote and ("remote port forwarding failed" in why or "forwarding" in why.lower()):
            why += f" — the tunnel from {remote['host']} to this Mac could not open; send the message again."
        elif remote and rc == 255:
            why = f"The SSH connection to {remote['host']} failed: {why}"
        elif "ECONNREFUSED" in why or "Connection error" in why or "fetch failed" in why:
            why += " — the local model server is not answering. Start it (sidebar → Start) and try again."
        emit("error", why[:1200])
    elif result_err and not stopped:
        emit("notice", {"msg": f"Claude Code reported: {str(result_err)[:300]}"})
    if too_long and not stopped:
        emit("error", f"The chat does not fit {label}'s {target['ctx'] // 1000}k-token window, and Claude Code "
                      "could not compact it enough (the Claude setup's own prompt counts too). Pick a model with a "
                      "larger window, run /compact on the previous model, or start a new chat.")
    emit("done", None)
    if checkpoint:
        try: checkpoint()
        except Exception: pass
    if stopped:
        return ((last or {}).get("content") or "").strip() + "\n\n_(stopped)_"
    return final_text or ((last or {}).get("content") or "")


def _run_log(sid, mk, resume, fork, resume_at, c, cwd, argv):
    """One line per run in logs/claude.log: which chat, session, mode and profile."""
    try:
        line = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "chat": sid, "session": mk.get("session"),
                "resume": resume, "fork": fork, "resume_at": resume_at, "cwd": cwd,
                "profile": c.get("profile"), "mode": next((argv[i + 1] for i, a in enumerate(argv) if a == "--permission-mode"), "claude's"),
                "skills": len(mk.get("skills") or []),
                "args": [a for a in argv[1:] if a.startswith("--")]}
        with open(os.path.join(Q.LOGS, "claude.log"), "a") as fh:
            fh.write(json.dumps(line) + "\n")
    except Exception:
        pass


def _system_notice(st, ev):
    """A line for the chat from one of Claude Code's other system events."""
    def g(*keys):
        for k in keys:
            v = ev.get(k)
            if v: return str(v)
        return ""
    if st in ("hook_started",):
        return ""                                   # the finished line says it all
    if st in ("hook_response",):
        out = g("output", "stdout", "message", "stderr").strip()
        # a hook's context for the model (additionalContext JSON) is not for reading
        first = next((l for l in out.splitlines() if l.strip() and not l.lstrip().startswith("{")), "")
        code = ev.get("exit_code")
        return f"hook {g('hook_name', 'hook_event', 'name')} ran" + \
            (f" (exit {code})" if code not in (None, 0) else "") + (f" — {first[:160]}" if first else "")
    if st == "task_started":
        return f"background task started: {g('description', 'task_id')}"
    if st == "task_notification":
        return f"background task {g('status')}: {g('summary', 'description', 'task_id')}"[:400]
    if st == "permission_denied":
        return f"permission denied: {g('tool_name')} {g('message', 'reason')}".strip()
    if st in ("model_fallback", "model_refusal_fallback", "model_consent_fallback"):
        return f"model fallback: {g('message', 'reason', 'fallback_model', 'model')}"
    if st == "api_error":
        return f"model request failed: {g('error', 'message')[:300]}"
    if st in ("notification", "informational"):
        return g("message", "text", "content")[:400]
    if st == "local_command":
        return g("content", "message", "output")[:2000]
    if st == "stop_hook_summary":
        return g("summary", "message")[:400]
    return ""


# ------------------------------------------------------------------ remote sessions kept between messages

LIVE = {}              # chat id -> a remote Claude Code process waiting for its next message
_LIVE_LOCK = threading.Lock()


def _live_path():
    return os.path.join(_work_dir(), "live-remote.json")


def _live_saved():
    """Which SSH processes are kept, so the next start of Orbit can end any it left
    behind (a restart does not wait for them)."""
    try:
        _write_json("live-remote.json", {s: {"pid": v["proc"].pid, "host": v["host"]} for s, v in LIVE.items()})
    except Exception:
        pass


def close_live(sid=None, why=""):
    """End a kept remote session (all of them without a chat id): closing its input ends
    Claude Code there, and the SSH connection with it."""
    with _LIVE_LOCK:
        ids = [sid] if sid else list(LIVE)
        for k in ids:
            v = LIVE.pop(k, None)
            bg_ended(k)
            if not v: continue
            try: v["proc"].stdin.close()
            except Exception: pass
            def finish(p=v["proc"]):
                try: p.wait(timeout=15)
                except Exception: _kill(p)
            threading.Thread(target=finish, daemon=True).start()
        _live_saved()


def watch_live():
    """Between answers, keep the background-task list current from a kept session's
    output: its task events are read where they wait for the next answer, not taken."""
    for k, v in list(LIVE.items()):
        if k in RUNS: continue
        seen = v.setdefault("seen", set())
        for raw in list(v["lines"]):
            if raw is None or id(raw) in seen: continue
            seen.add(id(raw))
            try: ev = json.loads(raw)
            except Exception: continue
            if ev.get("type") == "assistant" and ev.get("parent_tool_use_id"):
                # a background subagent's step, taken after its answer ended
                steps = [{"name": b.get("name") or "tool", "args": _brief_args(b.get("input"))}
                         for b in (ev.get("message") or {}).get("content") or [] if b.get("type") == "tool_use"]
                if steps:
                    with _BG_LOCK:
                        rec = next((r for r in (BG_TASKS.get(k) or {}).values()
                                    if r.get("tool_id") == ev["parent_tool_use_id"]), None)
                        if rec is not None:
                            rec["steps"] = (rec.get("steps") or [])[-79:] + steps
                continue
            if ev.get("type") != "system": continue
            st = ev.get("subtype")
            if st in ("task_started", "task_updated", "task_notification"):
                patch = ev.get("patch") or {}
                u = ev.get("usage") or {}
                rec = bg_task(k, ev.get("task_id") or ev.get("tool_use_id"), tool_id=ev.get("tool_use_id"),
                              status=str(ev.get("status") or patch.get("status") or "running").lower(),
                              summary=ev.get("summary") if st == "task_notification" else None,
                              output_file=ev.get("output_file"),
                              tools=u.get("tool_uses"), tokens=u.get("total_tokens"),
                              secs=round(float(u["duration_ms"]) / 1000, 1) if u.get("duration_ms") else None)
                if st == "task_notification" and rec and rec.get("kind") == "agent" and rec.get("tool_id"):
                    _saved_subagent_done(k, rec)

def bg_output(sid, tid, limit=60000):
    """What a background task has written so far: a shell's output, or a subagent's steps and
    words from its transcript. Only the file Claude Code named for that task is read."""
    with _BG_LOCK:
        tasks = BG_TASKS.get(sid) or {}
        rec = tasks.get(str(tid)) or next((r for r in tasks.values() if r.get("tool_id") == tid), None)
        rec = dict(rec or {})
    if not rec: return None
    out = {k: rec.get(k) for k in ("id", "kind", "description", "status", "summary", "command",
                                   "since", "ended", "tools", "tokens", "secs")}
    out["steps"] = rec.get("steps") or []
    path = rec.get("output_file")
    if path and not os.path.exists(path): path = path.rstrip(".,;:)'\"")
    if not path or not os.path.exists(path):
        # Claude Code keeps every task's output as <its temp folder>/<project>/<session>/tasks/<id>.output
        import glob
        tid_ = re.sub(r"[^\w-]", "", str(rec.get("id") or ""))
        if tid_:
            hits = glob.glob(f"/private/tmp/claude-*/*/*/tasks/{tid_}.output") or \
                   glob.glob(f"/tmp/claude-*/*/*/tasks/{tid_}.output")
            if hits: path = max(hits, key=os.path.getmtime)
    text = ""
    if path:
        real = os.path.realpath(path)
        ok_dirs = [os.path.realpath(d) for d in ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders",
                                                    os.path.join(claude_dir(), "projects"))]
        if any(real == d or real.startswith(d + os.sep) for d in ok_dirs) and os.path.isfile(real):
            try:
                size = os.path.getsize(real)
                with open(real, "rb") as f:
                    if size > limit: f.seek(size - limit)
                    raw = f.read().decode("utf-8", "replace")
                text = _transcript_text(raw) if raw.lstrip().startswith("{") else raw
                if size > limit: text = "…\n" + text
            except OSError:
                pass
    out["output"] = text
    return out

def _transcript_text(raw):
    """A subagent's transcript (JSON lines) as something to read: what it said and did."""
    lines = []
    for ln in raw.splitlines():
        try: ev = json.loads(ln)
        except ValueError: continue
        content = (ev.get("message") or {}).get("content")
        if not isinstance(content, list): continue
        for b in content:
            if b.get("type") == "text" and ev.get("type") == "assistant" and b.get("text", "").strip():
                lines.append(b["text"].strip())
            elif b.get("type") == "tool_use":
                args = _brief_args(b.get("input"))
                first = next(iter(args.values()), "")
                lines.append(f"⏺ {b.get('name')}({str(first)[:120]})")
    return "\n\n".join(lines)

def _report(text):
    """What a subagent reported, without Claude Code's note that the report went to the model."""
    t = str(text or "")
    return "" if "delivered to you as a message" in t.lower() else t[:2000]

def _saved_subagent_done(sid, rec):
    """A background subagent finished after its answer was saved: its Agent call in the
    saved chat now says how it ended."""
    try:
        path = Q.session_path(sid)
        if not os.path.exists(path): return
        d = json.load(open(path))
        msgs = d.get("messages") if isinstance(d, dict) else d
        for m in reversed(msgs or []):
            if m.get("role") == "tool" and m.get("tool_call_id") == rec["tool_id"]:
                sub = dict(m.get("subagent") or {})
                if rec.get("steps"): sub["steps"] = (sub.get("steps") or []) + rec["steps"]
                sub.update(background=False, status=rec.get("status"), summary=_report(rec.get("summary")),
                           tools=int(rec.get("tools") or sub.get("tools") or 0),
                           tokens=int(rec.get("tokens") or sub.get("tokens") or 0),
                           secs=rec.get("secs") or sub.get("secs"))
                m["subagent"] = sub
                Q._atomic_write(path, d)
                break
    except Exception:
        pass

def reap_live(max_idle_min=None):
    """Close kept remote sessions idle for longer than remote_keep_alive_min, and a chat
    on this Mac's session once its background work is over."""
    try: watch_live()
    except Exception: pass
    limit = float(max_idle_min if max_idle_min is not None else (cfg().get("remote_keep_alive_min", 30) or 0)) * 60
    for k, v in list(LIVE.items()):
        local_done = v.get("host") is None and k not in RUNS and not bg_running(k)
        if v["proc"].poll() is not None or local_done or (limit and time.time() - v["used"] > limit and k not in RUNS):
            close_live(k)


def end_leftover_live():
    """At start: SSH processes a previous run of Orbit kept open (it was restarted) are ended."""
    try: old = json.load(open(_live_path()))
    except Exception: return
    for v in (old or {}).values():
        pid = int((v or {}).get("pid") or 0)
        if not pid: continue
        try:
            out = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True).stdout
            # an SSH session to a host, or a chat's own Claude Code kept for its background work
            if (out.startswith("ssh") and "orbit" in out) or (not (v or {}).get("host") and "claude" in out):
                os.killpg(os.getpgid(pid), signal.SIGTERM)
        except Exception:
            pass
    try: os.remove(_live_path())
    except OSError: pass


def _kill(proc):
    try: os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        try: proc.terminate()
        except Exception: pass


def _wake_model(emit):
    q = Q
    try:
        if q.probe(2):
            return
    except Exception:
        return
    t0 = time.time()
    emit("server_starting", {"msg": "model server is asleep — starting it"})
    stop = threading.Event()
    def ticker():
        while not stop.wait(2):
            emit("server_starting", {"msg": "loading model weights", "elapsed": int(time.time() - t0)})
    threading.Thread(target=ticker, daemon=True).start()
    try:
        q.ensure_model()
    finally:
        stop.set()
    emit("server_ready", {"elapsed": int(time.time() - t0)})


# ------------------------------------------------------------------ history

_SCAN = {}            # path -> (mtime, size, summary or None)
_SCAN_LOCK = threading.Lock()
_CMD_RE = re.compile(r"<command-name>/?([^<]+)</command-name>.*?(?:<command-args>(.*?)</command-args>)?", re.S)
_SR_RE = re.compile(r"<system-reminder>.*?</system-reminder>\s*", re.S)


def harness_model_names():
    """Model ids of every harness provider: a Claude session that ran on one of
    them is a harness session, whichever provider served it."""
    try:
        import harness
        # Claude's own models are left out: a session on those is ordinary Claude Code
        return {m["id"].lower() for p in harness.providers(Q.ROOT).values() for m in p["models"]
                if not m["id"].lower().startswith("claude")}
    except Exception:
        return set()


def _is_local_model(name, local):
    n = (name or "").lower()
    return bool(n) and (n in local or n.startswith(LOCAL_MODEL_PREFIXES))


def _user_text(content):
    """What the person typed, from a stored user record; None for tool results
    and harness-generated records."""
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        text = " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    else:
        text = str(content or "")
    text = _SR_RE.sub("", text).strip()
    if not text: return None
    if text.startswith(("<local-command-stdout>", "<local-command-caveat>", "Caveat: The messages below",
                        "<bash-stdout>", "<bash-stderr>")):
        return None
    m = _CMD_RE.search(text)
    if m and text.startswith("<command-"):
        return ("/" + m.group(1).strip() + (" " + m.group(2).strip() if m.group(2) else "")).strip()
    text = re.sub(r"^\[(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d{1,2} [A-Z][a-z]{2} \d{4}, \d{2}:\d{2}[^\]]*\]\s*", "", text)
    return text


def _ts(s):
    try:
        import datetime
        return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _summarise(path, local, include_all):
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return None
    if not include_all:
        # one pass over the file: which models answered in it
        used = {x.decode("utf-8", "replace").lower() for x in re.findall(rb'"model":"([^"]{1,120})"', raw)}
        if not any(_is_local_model(x, local) for x in used):
            return None
    first, title, ai_title, cwd, last_t, first_t, n, models, entry = None, None, None, None, None, None, 0, set(), None
    for line in raw.splitlines():
        try: d = json.loads(line)
        except ValueError: continue
        tp = d.get("type")
        if tp == "custom-title": title = d.get("customTitle") or title
        elif tp in ("ai-title", "summary"): ai_title = d.get("aiTitle") or d.get("summary") or ai_title
        if tp not in ("user", "assistant") or d.get("isSidechain"): continue
        cwd = d.get("cwd") or cwd
        entry = entry or d.get("entrypoint")
        ts = _ts(d.get("timestamp"))
        if ts:
            last_t = ts
            first_t = first_t or ts
        msg = d.get("message") or {}
        if tp == "assistant":
            if msg.get("model"): models.add(msg["model"])
        elif not d.get("isMeta"):
            u = _user_text(msg.get("content"))
            if u:
                n += 1
                first = first or u
    if not include_all and not any(_is_local_model(m, local) for m in models):
        return None
    if not first and not n: return None
    return {"session": os.path.basename(path)[:-6], "path": path, "cwd": cwd,
            "title": (title or ai_title or first or "(untitled)")[:80],
            "first": (first or "")[:200], "mtime": last_t or os.path.getmtime(path),
            "started": first_t, "n": n, "models": sorted(models), "entrypoint": entry}


def scan_history(include_all=None, local=None):
    """Claude sessions from a terminal, newest first: those run on Orbit's models --
    or, in Claude Code mode (or with "on any model" set), every Claude session."""
    c = cfg()
    if include_all is None:
        include_all = bool(c.get("history_all_models") or (getattr(Q, "S", None) or {}).get("harness_mode"))
    local = set(x.lower() for x in (local or [])) | harness_model_names()
    try:
        local.add((Q.local_model_name() or "").lower())
    except Exception:
        pass
    out = []
    with _SCAN_LOCK:
        for path in glob.glob(os.path.join(projects_dir(), "*", "*.jsonl")):
            try:
                st = os.stat(path)
            except OSError:
                continue
            key = (st.st_mtime, st.st_size, bool(include_all))
            hit = _SCAN.get(path)
            if not hit or hit[0] != key:
                hit = (key, _summarise(path, local, include_all))
                _SCAN[path] = hit
            if hit[1] and (not include_all or _is_a_conversation(hit[1])
                           or any(_is_local_model(m.lower(), local) for m in hit[1]["models"])):
                out.append(hit[1])
    out.sort(key=lambda x: -(x["mtime"] or 0))
    return out


_SCRATCH = ("/private/var/folders/", "/var/folders/", "/tmp/", "/private/tmp/")


def _is_a_conversation(h):
    """A session someone had with Claude, not a program's one-shot call: other apps
    drive Claude Code by the thousand (from temporary folders, the TypeScript/Python
    SDK, or `claude -p` for a single answer), and those are not chats to list."""
    cwd = h.get("cwd") or ""
    if cwd.startswith(_SCRATCH) or "/.claude-mem/" in cwd + "/": return False
    ep = h.get("entrypoint") or ""
    if ep in ("sdk-ts", "sdk-py"): return False
    if ep == "sdk-cli" and (h.get("n") or 0) <= 1: return False
    return True


def convert(path):
    """A Claude transcript as Orbit messages (and its title and cwd)."""
    msgs, cur, cur_id = [], None, None
    names = {}
    title, ai_title, cwd, first = None, None, None, None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try: d = json.loads(line)
            except ValueError: continue
            tp = d.get("type")
            if tp == "custom-title": title = d.get("customTitle") or title
            elif tp in ("ai-title", "summary"): ai_title = d.get("aiTitle") or d.get("summary") or ai_title
            if tp not in ("user", "assistant") or d.get("isSidechain"): continue
            cwd = d.get("cwd") or cwd
            ts = _ts(d.get("timestamp")) or time.time()
            msg = d.get("message") or {}
            if tp == "assistant":
                synthetic = msg.get("model") == "<synthetic>"
                if msg.get("id") != cur_id or cur is None:
                    cur = {"role": "assistant", "content": "", "t": ts,
                           "model": "Claude Code" if synthetic else "Claude Code · " + str(msg.get("model") or "")}
                    cur_id = msg.get("id")
                    msgs.append(cur)
                if d.get("uuid"): cur["claude_uuid"] = d["uuid"]
                for b in msg.get("content") or []:
                    bt = b.get("type")
                    if bt == "text": cur["content"] += b.get("text") or ""
                    elif bt == "thinking":
                        cur["reasoning_content"] = (cur.get("reasoning_content") or "") + (b.get("thinking") or "")
                    elif bt == "tool_use":
                        names[b.get("id")] = b.get("name")
                        cur.setdefault("tool_calls", []).append({"id": b.get("id"), "type": "function",
                            "function": {"name": b.get("name"), "arguments": json.dumps(b.get("input") or {})}})
                u = msg.get("usage") or {}
                if u.get("output_tokens"):
                    cur["usage"] = {"prompt_tokens": (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0),
                                    "completion_tokens": u.get("output_tokens") or 0}
                continue
            content = msg.get("content")
            if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                for b in content:
                    if not isinstance(b, dict) or b.get("type") != "tool_result": continue
                    msgs.append({"role": "tool", "tool_call_id": b.get("tool_use_id"),
                                 "name": names.get(b.get("tool_use_id"), "tool"), "t": ts,
                                 "ok": not b.get("is_error"), "content": _tool_text(b.get("content"))[:60000]})
                cur, cur_id = None, None
                continue
            if d.get("isMeta"): continue
            if d.get("isCompactSummary"):
                msgs.append({"role": "user", "content": "[earlier conversation, compacted by Claude Code]",
                             "t": ts, "nudge": True})
                cur, cur_id = None, None
                continue
            text = _user_text(content)
            if not text: continue
            first = first or text
            parts = [{"type": "text", "text": text}]
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "image":
                        src = b.get("source") or {}
                        if src.get("type") == "base64":
                            parts.append({"type": "image_url", "image_url": {
                                "url": f"data:{src.get('media_type')};base64,{src.get('data')}"}})
            msgs.append({"role": "user", "content": text if len(parts) == 1 else parts, "t": ts})
            cur, cur_id = None, None
    return msgs, (title or ai_title or (first or "")[:60] or "(untitled)"), cwd


def history_sid(session):
    return "cq-" + session


def linked_sessions():
    """Claude session id -> Orbit chat id, for chats that ran on this engine."""
    try:
        names = [f for f in os.listdir(Q.SESSIONS) if f.endswith(".json")]
        key = (len(names), round(sum(os.path.getmtime(os.path.join(Q.SESSIONS, f)) for f in names), 3))
    except OSError:
        key = None
    if key and _LINKED["key"] == key:
        return dict(_LINKED["val"])
    out = {}
    try:
        for f in os.listdir(Q.SESSIONS):
            if not f.endswith(".json"): continue
            p = os.path.join(Q.SESSIONS, f)
            try:
                with open(p, "rb") as fh:
                    raw = fh.read()
            except OSError:
                continue
            if b'"claude"' not in raw: continue
            for m in re.finditer(rb'"claude": \{"session": "([0-9a-f-]{36})"', raw):
                out.setdefault(m.group(1).decode(), f[:-5])
            for m in re.finditer(rb'"claude_session": "([0-9a-f-]{36})"', raw):
                out.setdefault(m.group(1).decode(), f[:-5])
    except OSError:
        pass
    _LINKED.update(key=key, val=dict(out))
    return out


def _hidden_path():
    return os.path.join(_work_dir(), "hidden-sessions.json")


def hidden_sessions():
    try: return set(json.load(open(_hidden_path())))
    except Exception: return set()


def hide_history(orbit_sid):
    """Deleting a chat that came from a Claude session: keep that session out
    of the sidebar (its transcript in ~/.claude is left alone)."""
    session = None
    if orbit_sid.startswith("cq-"):
        session = orbit_sid[3:]
    else:
        try:
            session = (marker_of(Q.session_load(orbit_sid)[0]) or {}).get("session")
        except Exception:
            session = None
    if not session: return False
    h = hidden_sessions(); h.add(session)
    _write_json("hidden-sessions.json", sorted(h))
    _HIST["at"] = 0.0
    _HIST["rows"] = [r for r in _HIST["rows"] if r["id"] != history_sid(session)]
    return True


def history_items():
    """Sidebar rows for terminal sessions not yet opened in Orbit."""
    c = cfg()
    if not c.get("history"): return []
    linked = linked_sessions()
    linked.update({s: None for s in hidden_sessions()})
    rows = []
    try:
        projects = Q.projects_load()
    except Exception:
        projects = {}
    for h in scan_history():
        if h["session"] in linked: continue
        proj = None
        for pid, p in (projects or {}).items():
            f = (p or {}).get("folder")
            if f and h["cwd"] and os.path.abspath(h["cwd"]).startswith(os.path.abspath(os.path.expanduser(f))):
                proj = pid
                break
        rows.append({"id": history_sid(h["session"]), "title": h["title"], "mtime": h["mtime"],
                     "pinned": False, "archived": False, "tags": ["claude-qwen"], "project": proj,
                     "order": None, "n": h["n"], "source": "claude-qwen", "cwd": h["cwd"],
                     "external": True})
    return rows


_HIST = {"rows": [], "at": 0.0, "busy": False}
_LINKED = {"key": None, "val": {}}


def history_items_cached(max_age=20):
    """history_items() without making the sidebar wait: the first scan of a
    large ~/.claude runs in the background, and later ones only re-read
    transcripts that changed."""
    if not cfg().get("history"): return []
    now = time.time()
    if now - _HIST["at"] > max_age and not _HIST["busy"]:
        _HIST["busy"] = True
        def work():
            try:
                _HIST["rows"] = history_items()
            except Exception:
                pass
            finally:
                _HIST["at"] = time.time()
                _HIST["busy"] = False
        th = threading.Thread(target=work, daemon=True)
        th.start()
        if not _HIST["at"]:
            th.join(timeout=4)                    # the first page load waits a moment
    return list(_HIST["rows"])


def import_session(orbit_sid):
    """Open a terminal session in Orbit: convert it and save it as a chat.
    Returns the Orbit chat id, or None."""
    if not orbit_sid.startswith("cq-"): return None
    session = orbit_sid[3:]
    path = jsonl_path(session)
    if not path: return None
    msgs, title, cwd = convert(path)
    mk = {"session": session, "cwd": cwd or HOME, "skills": []}
    for m in msgs:
        if m.get("role") == "user":
            m["claude"] = dict(mk)
    sysmsg = {"role": "system", "content": Q.system_prompt_for(None, None)}
    summ = next((h for h in scan_history() if h["session"] == session), None)
    extra = {"model": model_for_session((summ or {}).get("models")), "tags": ["claude-qwen"], "source": "claude-qwen",
             "claude_session": session}
    proj = next((r["project"] for r in history_items() if r["id"] == orbit_sid), None)
    extra["project"] = proj
    Q.session_save(orbit_sid, [sysmsg] + msgs, title, extra)
    try:
        os.utime(Q.session_path(orbit_sid), (os.path.getmtime(path), os.path.getmtime(path)))
    except OSError:
        pass
    return orbit_sid


def sync_session(orbit_sid, running=False):
    """A chat whose Claude session was continued somewhere else (a terminal):
    bring the new part in. True if the saved chat changed."""
    if running: return False
    p = Q.session_path(orbit_sid)
    if not os.path.exists(p):
        return bool(import_session(orbit_sid))
    try:
        d = json.load(open(p))
    except Exception:
        return False
    if not isinstance(d, dict): return False
    msgs = d.get("messages") or []
    mk = marker_of(msgs)
    if not mk: return False
    if mk.get("host"):
        _remote_sync_later(orbit_sid, mk, float(d.get("saved") or 0))
        return False
    path = jsonl_path(mk.get("session"), mk.get("cwd"))
    if not path: return False
    saved = float(d.get("saved") or 0)
    if os.path.getmtime(path) <= saved + 2: return False
    # where this Claude session begins in the Orbit chat
    start = next((i for i, m in enumerate(msgs) if isinstance(m.get("claude"), dict)
                  and m["claude"].get("session") == mk["session"]), None)
    if start is None: return False
    new, _title, cwd = convert(path)
    ours = [m for m in msgs[start:] if m.get("role") in ("user", "assistant")]
    theirs = [m for m in new if m.get("role") in ("user", "assistant")]
    if len(theirs) <= len(ours): return False
    mk2 = {**mk, "cwd": cwd or mk.get("cwd")}
    for m in new:
        if m.get("role") == "user": m["claude"] = dict(mk2)
    # the part before this session keeps Orbit's own copy (another model, or
    # the transcript Claude was given as context)
    keep = msgs[:start]
    extra = {k: v for k, v in d.items() if k not in ("schema", "title", "messages", "saved")}
    Q.session_save(orbit_sid, keep + new, d.get("title"), extra)
    return True


_REMOTE_SYNC = {}


def _remote_sync_later(orbit_sid, mk, saved):
    """A chat on another machine whose session was continued there (a terminal on
    that machine): fetch its transcript in the background, at most once a minute, and
    bring the new part into the chat. Opening the chat never waits for SSH."""
    now = time.time()
    if now - _REMOTE_SYNC.get(orbit_sid, 0) < 60: return
    _REMOTE_SYNC[orbit_sid] = now
    def work():
        try:
            import ssh_remote, tempfile
            mtime, text = ssh_remote.fetch_transcript(mk["host"], mk.get("cwd"), mk.get("session"), since=saved + 2)
            if not text: return
            if orbit_sid in RUNS: return                       # answering now: its own stream is the truth
            fd, tmp = tempfile.mkstemp(suffix=".jsonl"); os.close(fd)
            try:
                with open(tmp, "w", encoding="utf-8") as fh: fh.write(text)
                merge_transcript(orbit_sid, tmp)
            finally:
                os.remove(tmp)
        except Exception:
            pass
    threading.Thread(target=work, daemon=True).start()


def merge_transcript(orbit_sid, path):
    """Bring a Claude transcript's newer part into an Orbit chat. True if it changed."""
    try: d = json.load(open(Q.session_path(orbit_sid)))
    except Exception: return False
    if not isinstance(d, dict): return False
    msgs = d.get("messages") or []
    mk = marker_of(msgs)
    if not mk: return False
    start = next((i for i, m in enumerate(msgs) if isinstance(m.get("claude"), dict)
                  and m["claude"].get("session") == mk["session"]), None)
    if start is None: return False
    new, _title, cwd = convert(path)
    ours = [m for m in msgs[start:] if m.get("role") in ("user", "assistant")]
    theirs = [m for m in new if m.get("role") in ("user", "assistant")]
    if len(theirs) <= len(ours): return False
    mk2 = {**mk, "cwd": mk.get("cwd") if mk.get("host") else (cwd or mk.get("cwd"))}
    for m in new:
        if m.get("role") == "user": m["claude"] = dict(mk2)
    extra = {k: v for k, v in d.items() if k not in ("schema", "title", "messages", "saved")}
    Q.session_save(orbit_sid, msgs[:start] + new, d.get("title"), extra)
    return True


def resume_command(orbit_msgs, spec=None):
    """The terminal command that continues this chat's Claude session."""
    mk = marker_of(orbit_msgs)
    if not mk: return None
    cwd = mk.get("cwd") or HOME
    if mk.get("host"):
        try:
            import ssh_remote
            exe = (ssh_remote._PROBES.get(mk["host"]) or {}).get("claude") or "claude"
        except Exception:
            exe = "claude"
        return (f"ssh -t {mk['host']} " + json.dumps(f"cd {cwd} && {exe} --resume {mk['session']}")
                + "   # it runs on your Claude login there; other models need Orbit's tunnel")
    pc = (spec or {}).get("provider_cfg") or {}
    if (spec or {}).get("provider") == "harness" and not pc.get("local"):
        return f"cd {json.dumps(cwd)} && claude-harness {json.dumps(spec['id'])} --resume {mk['session']}"
    return f"cd {json.dumps(cwd)} && claude-qwen --resume {mk['session']}"


def model_for_session(models):
    """The Orbit model id for a Claude session, from the model names in its transcript.
    A session on Claude itself (claude-opus-5…) continues on your Claude subscription,
    as it ran; others on the provider that serves that model; else the local model."""
    names = [m for m in models or [] if m and m != "<synthetic>"]
    for name in reversed(names):
        low = name.lower()
        if low.startswith("claude-"):
            for fam in ("opus", "sonnet", "haiku"):
                if fam in low:
                    return f"harness:claude/{fam}"
    try:
        import harness
        provs = harness.providers(Q.ROOT, Q.local_model_name())
        secrets_ = Q.secrets_load()
        for name in reversed(names):
            hits = [(pid, p) for pid, p in provs.items() if pid != "claude" and any(x["id"] == name for x in p["models"])]
            if not hits: continue
            hits.sort(key=lambda h: (h[0] == "local", not harness._ready(h[0], h[1], secrets_)))
            pid = hits[0][0]
            return f"{BACKEND}:default" if pid == "local" else f"harness:{pid}/{name}"
    except Exception:
        pass
    return f"{BACKEND}:default"


# ------------------------------------------------------------------ your Claude setup
#
# Orbit does not keep a copy of Claude's configuration. Skills, plugins, MCP
# servers and permission settings are read from where Claude keeps them, and
# changes are made there -- through Claude's own CLI where it has one -- so the
# terminal and Orbit always see the same setup.

def claude_settings_path(scope="user", cwd=None):
    if scope == "user":
        return os.path.join(claude_dir(), "settings.json")
    base = os.path.join(cwd or os.getcwd(), ".claude")
    return os.path.join(base, "settings.local.json" if scope == "local" else "settings.json")


def read_claude_settings(scope="user", cwd=None):
    try:
        with open(claude_settings_path(scope, cwd)) as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def write_claude_settings(patch, scope="user", cwd=None):
    """Merge a change into Claude's settings file (a key set to None is removed).
    The previous file is kept in Orbit's config/claude/backups first."""
    path = claude_settings_path(scope, cwd)
    cur = read_claude_settings(scope, cwd)
    if os.path.exists(path):
        bk = os.path.join(_work_dir(), "backups")
        os.makedirs(bk, exist_ok=True)
        shutil.copy2(path, os.path.join(bk, f"{scope}-settings-{time.strftime('%Y%m%d-%H%M%S')}.json"))
    def merge(a, b):
        for k, v in b.items():
            if v is None: a.pop(k, None)
            elif isinstance(v, dict) and isinstance(a.get(k), dict): merge(a[k], v)
            else: a[k] = v
        return a
    new = merge(cur, patch or {})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + f".{os.getpid()}.tmp"
    with open(tmp, "w") as fh:
        json.dump(new, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)
    return new


def claude_cli(args, timeout=120):
    """Run a claude management command (plugin, mcp...) as your normal Claude,
    not the local-model harness. Returns (exit code, stdout, stderr)."""
    exe = which_claude()
    if not exe: return 127, "", "claude is not installed"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_CODE_", "CLAUDECODE"))}
    if os.environ.get("ORBIT_CLAUDE_CONFIG_DIR"):
        env["CLAUDE_CONFIG_DIR"] = os.environ["ORBIT_CLAUDE_CONFIG_DIR"]
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout, env=env,
                           stdin=subprocess.DEVNULL)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"claude {' '.join(args[:2])} took longer than {timeout}s"


def skills_list():
    """Your skills (~/.claude/skills) and whether Claude has each turned off."""
    over = read_claude_settings().get("skillOverrides") or {}
    out = []
    for it in skill_index():
        out.append({**it, "enabled": over.get(it["name"]) != "off",
                    "path": os.path.join(claude_dir(), "skills", it["dir"])})
    return out


def skill_set_enabled(name, on):
    write_claude_settings({"skillOverrides": {name: None if on else "off"}})
    return {"ok": True, "name": name, "enabled": bool(on)}


def write_claude_skill(name, body):
    """Save a procedure as a Claude skill: ~/.claude/skills/<name>/SKILL.md."""
    name = re.sub(r"[^a-z0-9-]+", "-", (name or "skill").lower()).strip("-") or "skill"
    title = next((l.lstrip("# ").strip() for l in body.splitlines() if l.strip()), name)
    d = os.path.join(claude_dir(), "skills", name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "SKILL.md"), "w") as fh:
        fh.write(f"---\nname: {name}\ndescription: {json.dumps(title[:300])}\n---\n\n{body.strip()}\n")
    _SKILL_INDEX["key"] = None
    return name


def _skill_dirs(root, depth=4):
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("node_modules",)]
        if dirpath[len(root):].count(os.sep) >= depth:
            dirnames[:] = []
        if "SKILL.md" in filenames:
            found.append(dirpath)
            dirnames[:] = []                        # a skill's own subfolders are its files
    return found


def skill_install(source, overwrite=False, dest_base=None):
    """Install skills into ~/.claude/skills from a git repository (URL or
    owner/repo) or a local folder: every folder with a SKILL.md is one skill."""
    import tempfile
    source = (source or "").strip()
    if not source: return {"error": "nothing to install from"}
    tmp = None
    if os.path.isdir(os.path.expanduser(source)):
        root = os.path.abspath(os.path.expanduser(source))
    else:
        url = source
        if re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", source):
            url = f"https://github.com/{source}.git"
        if not re.match(r"^(https?://|git@)", url):
            return {"error": "give a folder, a git URL, or owner/repo"}
        tmp = tempfile.mkdtemp(prefix="orbit-skill-")
        r = subprocess.run(["git", "clone", "--depth", "1", url, os.path.join(tmp, "repo")],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            shutil.rmtree(tmp, ignore_errors=True)
            return {"error": "git clone failed: " + (r.stderr.strip().splitlines() or ["?"])[-1][:300]}
        root = os.path.join(tmp, "repo")
    try:
        dirs = _skill_dirs(root)
        if not dirs: return {"error": "no SKILL.md found there"}
        dest_base = dest_base or os.path.join(claude_dir(), "skills")
        os.makedirs(dest_base, exist_ok=True)
        installed, skipped = [], []
        for d in dirs:
            try:
                meta, _ = _frontmatter(open(os.path.join(d, "SKILL.md"), encoding="utf-8", errors="replace").read(4000))
            except OSError:
                meta = {}
            name = re.sub(r"[^A-Za-z0-9_.-]+", "-", meta.get("name") or os.path.basename(d.rstrip(os.sep))).strip("-")
            if d == root and tmp and not meta.get("name"):
                name = re.sub(r"\.git$", "", source.rstrip("/").split("/")[-1])
            dest = os.path.join(dest_base, name)
            if os.path.exists(dest) and not overwrite:
                skipped.append(name); continue
            if os.path.exists(dest):
                _to_trash(dest)
            shutil.copytree(d, dest, ignore=shutil.ignore_patterns(".git"))
            installed.append(name)
        _SKILL_INDEX["key"] = None
        return {"ok": True, "installed": installed, "skipped": skipped}
    finally:
        if tmp: shutil.rmtree(tmp, ignore_errors=True)


def _to_trash(path):
    """Into the macOS Trash (recoverable), not deleted."""
    trash = os.path.join(HOME, ".Trash")
    os.makedirs(trash, exist_ok=True)
    dest = os.path.join(trash, os.path.basename(path.rstrip(os.sep)) + time.strftime("-%Y%m%d-%H%M%S"))
    shutil.move(path, dest)
    return dest


def skill_remove(name):
    it = next((x for x in skill_index() if x["name"] == name or x["dir"] == name), None)
    if not it: return {"error": f"no skill {name}"}
    dest = _to_trash(os.path.join(claude_dir(), "skills", it["dir"]))
    _SKILL_INDEX["key"] = None
    return {"ok": True, "trashed": dest}


# ------------------------------------------------------------------ Claude's memory and instructions
#
# In Claude Code mode the instructions and memory are Claude's own, as a terminal
# session sees them: CLAUDE.md for you (~/.claude/CLAUDE.md) and for a folder
# (<folder>/CLAUDE.md, .claude/CLAUDE.md, CLAUDE.local.md), and the memory Claude
# keeps per folder (~/.claude/projects/<folder>/memory: MEMORY.md and one file per
# memory). Orbit reads and edits those files; it adds nothing of its own.

_MEM_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.md$")


def claude_instruction_files(cwd=None):
    """Instruction files Claude loads for a folder: user, then the folder's."""
    out = [{"scope": "user", "path": os.path.join(claude_dir(), "CLAUDE.md"), "label": "You, in every folder"}]
    if cwd:
        cwd = os.path.abspath(os.path.expanduser(cwd))
        out += [{"scope": "project", "path": os.path.join(cwd, "CLAUDE.md"), "label": "This folder (shared, e.g. in git)"},
                {"scope": "project-dir", "path": os.path.join(cwd, ".claude", "CLAUDE.md"), "label": "This folder's .claude/"},
                {"scope": "local", "path": os.path.join(cwd, "CLAUDE.local.md"), "label": "This folder, only on this Mac"}]
    for f in out:
        f["exists"] = os.path.isfile(f["path"])
        try: f["text"] = open(f["path"], encoding="utf-8", errors="replace").read() if f["exists"] else ""
        except OSError: f["text"] = ""
    return out


def claude_memory_dir(cwd):
    return os.path.join(projects_dir(), encode_cwd(os.path.abspath(os.path.expanduser(cwd or HOME))), "memory")


def _mem_meta(text):
    meta = {}
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            for line in text[3:end].splitlines():
                if ":" in line and not line.startswith(" "):
                    k, _, v = line.partition(":")
                    meta[k.strip()] = v.strip()
    return meta


def claude_memory(cwd=None):
    """Claude's memory for a folder: the index and each memory file."""
    d = claude_memory_dir(cwd)
    items, index = [], ""
    try: index = open(os.path.join(d, "MEMORY.md"), encoding="utf-8", errors="replace").read()
    except OSError: pass
    for root, _, files in os.walk(d) if os.path.isdir(d) else []:
        for f in sorted(files):
            if not f.endswith(".md") or (root == d and f == "MEMORY.md"): continue
            path = os.path.join(root, f)
            try: text = open(path, encoding="utf-8", errors="replace").read()
            except OSError: continue
            meta = _mem_meta(text)
            items.append({"file": os.path.relpath(path, d), "name": meta.get("name") or f[:-3],
                          "description": meta.get("description") or "", "type": meta.get("type") or "",
                          "mtime": os.path.getmtime(path), "text": text})
    items.sort(key=lambda x: -x["mtime"])
    return {"cwd": os.path.abspath(os.path.expanduser(cwd or HOME)), "dir": d, "index": index, "items": items}


def claude_memory_folders():
    """Folders Claude keeps memory for (from ~/.claude/projects/*/memory), with counts."""
    out = []
    try: names = os.listdir(projects_dir())
    except OSError: names = []
    folders = {encode_cwd(f["path"]): f["path"] for f in (recent_folders() or []) if isinstance(f, dict) and f.get("path")}
    for n in names:
        md = os.path.join(projects_dir(), n, "memory")
        if not os.path.isdir(md): continue
        cnt = sum(1 for _, _, fs in os.walk(md) for f in fs if f.endswith(".md") and f != "MEMORY.md")
        # the folder name is encoded (/ and . become -): a folder Orbit knows by path reads back exactly
        path = folders.get(n) or ("/" + n.lstrip("-").replace("-", "/"))
        if path.startswith(_SCRATCH): continue          # a temporary folder some program ran Claude in
        out.append({"key": n, "path": path, "count": cnt, "mtime": os.path.getmtime(md)})
    return sorted(out, key=lambda x: -x["mtime"])


def _backup(path):
    if os.path.isfile(path):
        bk = os.path.join(_work_dir(), "backups")
        os.makedirs(bk, exist_ok=True)
        shutil.copy2(path, os.path.join(bk, time.strftime("%Y%m%d-%H%M%S-") + os.path.basename(path)))


def save_claude_instructions(scope, text, cwd=None):
    f = next((x for x in claude_instruction_files(cwd) if x["scope"] == scope), None)
    if not f: return {"error": f"no such instructions file ({scope})" + ("" if cwd else " — pick a folder first")}
    _backup(f["path"])
    os.makedirs(os.path.dirname(f["path"]), exist_ok=True)
    with open(f["path"], "w", encoding="utf-8") as fh: fh.write(text if text.endswith("\n") or not text else text + "\n")
    return {"ok": True, "path": f["path"]}


def save_claude_memory(cwd, file, text):
    """Write one memory file (new or edited); a new one gets a line in MEMORY.md."""
    file = os.path.basename(str(file or "").strip())
    if not file.endswith(".md"): file += ".md"
    if not _MEM_NAME.match(file) or file == "MEMORY.md": return {"error": "a memory file name like lab-context.md"}
    d = claude_memory_dir(cwd)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, file)
    new = not os.path.exists(path)
    _backup(path)
    with open(path, "w", encoding="utf-8") as fh: fh.write(text if text.endswith("\n") else text + "\n")
    if new:
        meta = _mem_meta(text)
        line = f"- [{meta.get('name') or file[:-3]}]({file})" + (f" — {meta['description']}" if meta.get("description") else "")
        idx = os.path.join(d, "MEMORY.md")
        _backup(idx)
        with open(idx, "a", encoding="utf-8") as fh: fh.write(line + "\n")
    return {"ok": True, "path": path, "new": new}


def delete_claude_memory(cwd, file):
    """A memory file to the Trash, and its line out of MEMORY.md."""
    d = claude_memory_dir(cwd)
    path = os.path.normpath(os.path.join(d, str(file or "")))
    if not path.startswith(d + os.sep) or not os.path.isfile(path): return {"error": "no such memory"}
    dest = _to_trash(path)
    idx = os.path.join(d, "MEMORY.md")
    if os.path.isfile(idx):
        _backup(idx)
        rel = os.path.relpath(path, d)
        lines = open(idx, encoding="utf-8", errors="replace").read().splitlines(keepends=True)
        open(idx, "w", encoding="utf-8").writelines(l for l in lines if f"({rel})" not in l)
    return {"ok": True, "trashed": dest}


def plugins_list():
    rc, out, err = claude_cli(["plugin", "list", "--json"], timeout=60)
    try: return {"plugins": json.loads(out)}
    except ValueError: return {"plugins": [], "error": (err or out).strip()[:400]}


def plugin_action(op, name):
    if op not in ("enable", "disable", "install", "uninstall", "update"):
        return {"error": f"unknown plugin action {op}"}
    rc, out, err = claude_cli(["plugin", op, name], timeout=300)
    return {"ok": rc == 0, "output": (out + err).strip()[-1500:]}


def marketplaces_list():
    rc, out, err = claude_cli(["plugin", "marketplace", "list", "--json"], timeout=60)
    try: return {"marketplaces": json.loads(out)}
    except ValueError: return {"marketplaces": [], "output": (out + err).strip()[-800:]}


def mcp_list():
    """`claude mcp list`, with each server's health."""
    rc, out, err = claude_cli(["mcp", "list"], timeout=90)
    rows = []
    for line in out.splitlines():
        m = re.match(r"^([^:\s][^:]*):\s+(.*?)\s+-\s+(.*)$", line.strip())
        if m:
            rows.append({"name": m.group(1).strip(), "target": m.group(2).strip(),
                         "status": re.sub(r"^[^A-Za-z]+", "", m.group(3)).strip()})
    return {"servers": rows, "error": None if rc == 0 else (err or out).strip()[-400:]}


def mcp_action(op, name, config=None, scope="user"):
    if op == "remove":
        rc, out, err = claude_cli(["mcp", "remove", name, "--scope", scope], timeout=60)
    elif op == "add":
        rc, out, err = claude_cli(["mcp", "add-json", name, json.dumps(config or {}), "--scope", scope], timeout=60)
    else:
        return {"error": f"unknown MCP action {op}"}
    return {"ok": rc == 0, "output": (out + err).strip()[-1500:]}


def recent_folders(limit=30):
    """Folders to start a chat in: where Claude sessions ran, Orbit's projects
    and workspace."""
    seen, out = set(), []
    def add(p, why):
        if not p: return
        p = os.path.abspath(os.path.expanduser(p))
        if p in seen or not os.path.isdir(p): return
        seen.add(p); out.append({"path": p, "why": why})
    try: add(Q.WORKSPACE, "Orbit workspace")
    except Exception: pass
    try:
        for pid, pr in (Q.projects_load() or {}).items():
            add((pr or {}).get("folder"), "project: " + str((pr or {}).get("name") or pid))
    except Exception:
        pass
    for h in sorted(_SCAN.values(), key=lambda x: -((x[1] or {}).get("mtime") or 0)):
        if h[1]: add(h[1].get("cwd"), "recent Claude session")
        if len(out) >= limit: break
    return out


# ------------------------------------------------------------------ terminal launcher

def launch(args):
    """`claude-qwen`: the interactive harness on the local model, with the same
    command Orbit's Claude Code mode uses.

    CLAUDE_QWEN_PROFILE=standard|lean picks a profile for one run;
    CLAUDE_QWEN_BARE=1 brings back the old --bare mode (three tools)."""
    global Q
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    import qqcore
    Q = qqcore
    c = cfg()
    if os.environ.get("CLAUDE_QWEN_PROFILE"): c["profile"] = os.environ["CLAUDE_QWEN_PROFILE"]
    try:
        if os.environ.get("CLAUDE_QWEN_DRY_RUN") != "1" and not os.environ.get("ORBIT_MODEL_URL") and not Q.probe(2):
            print("Starting the local Qwen model...", file=sys.stderr)
            Q.ensure_model(lambda s: print(s, file=sys.stderr, flush=True))
    except Exception as e:
        print(f"Could not start the local model: {e}", file=sys.stderr)
    url, model, ctx = model_endpoint()
    env = harness_env(url, model, ctx)
    exe = which_claude()
    if not exe:
        print("claude is not installed", file=sys.stderr)
        return 127
    if os.environ.get("CLAUDE_QWEN_BARE") == "1":
        env["ANTHROPIC_API_KEY"] = "local-qwen"
        os.execvpe(exe, [exe, "--bare", "--model", "sonnet", *args], env)
    settings_path, mcp_path = launcher_files(c, "terminal")
    argv = build_argv(c, settings_path=settings_path, mcp_path=mcp_path, sdk=False,
                      mode=c.get("permission_mode") or None, append=launcher_append(c))
    if os.environ.get("CLAUDE_QWEN_DRY_RUN") == "1":
        print(json.dumps({"argv": argv + list(args), "cwd": os.getcwd(),
                          "env": {k: v for k, v in env.items() if k.startswith(("ANTHROPIC", "CLAUDE"))}}, indent=1))
        return 0
    os.execvpe(exe, argv + list(args), env)


def launch_harness(query, args):
    """`claude-harness <model> [claude args]`: the interactive harness on any
    harness model -- "deepseek v4 pro go", "kimi k3", "local qwen" or an id."""
    global Q
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    import qqcore
    Q = qqcore
    if query in ("--list", "-l", "?"):
        for m in [m for m in Q.model_catalogue() if not m.get("switch") and not m["id"].startswith("local-dir:")
                  and Q.CE.is_engine(Q.current_model(m["id"]))]:
            print(f"  {m['id']:<52} {m['label']}{'' if m.get('ready', True) else '  (needs a key)'}")
        return 0
    mid = Q.find_model(query) if query else None
    spec = Q.current_model(mid) if mid else None
    if not spec or not is_engine(spec):
        print(f"No harness model matches {query!r}. Some choices:", file=sys.stderr)
        for m in [m for m in Q.model_catalogue() if m["id"].startswith("harness:")][:30]:
            print(f"  {m['id']:<48} {m['label']}", file=sys.stderr)
        return 2
    t = harness_target(spec)
    if t["local"]:
        if os.environ.get("CLAUDE_QWEN_DRY_RUN") != "1" and not Q.probe(2):
            print("Starting the local model...", file=sys.stderr)
            Q.ensure_model(lambda s: print(s, file=sys.stderr, flush=True))
    elif t["key_missing"]:
        print(f"No API key for {spec['provider_label']} ({t.get('key_name')}). Add it in Orbit → Settings → "
              "Models & keys.", file=sys.stderr)
        return 3
    elif (t["url"] or "").startswith("http://127.0.0.1:"):
        import urllib.request
        try:
            urllib.request.urlopen(t["url"].split("/h/")[0] + "/health", timeout=3).read()
        except Exception:
            print("Orbit's gateway is not answering; this model needs Orbit running.", file=sys.stderr)
            return 4
    c = cfg()
    settings_path, mcp_path = launcher_files(c, "terminal-harness")
    kind = "subscription" if t.get("subscription") else ("local" if t.get("local") else "provider")
    argv = build_argv(c, settings_path=settings_path, mcp_path=mcp_path, sdk=False, kind=kind,
                      mode=c.get("permission_mode") or None, append=launcher_append(c, None, kind),
                      model=t.get("cli_model"))
    env = target_env(t)
    # `--disallowedTools <tools...>` is variadic: it eats every non-option argument after
    # it. Whatever the user typed — `claude-harness kimi "fix the bug"` — landed on the
    # end of that list as a deny rule, and an unknown deny name aborts the run. Inside
    # Orbit nothing follows, so this only bit the terminal launcher. `--` ends the list.
    rest = list(args)
    if rest and "--disallowedTools" in argv and "--" not in argv:
        argv = argv + ["--"]
    print(f"Claude Code on {spec['label']}", file=sys.stderr)
    if os.environ.get("CLAUDE_QWEN_DRY_RUN") == "1":
        print(json.dumps({"argv": argv + rest, "env": {k: ("<set>" if "KEY" in k else v) for k, v in env.items()
                                                       if k.startswith(("ANTHROPIC", "CLAUDE"))}}, indent=1))
        return 0
    exe = which_claude()
    os.execvpe(exe, argv + rest, env)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "harness":
        sys.exit(launch_harness(sys.argv[2], sys.argv[3:]) or 0)
    if len(sys.argv) > 1 and sys.argv[1] == "launch":
        sys.exit(launch(sys.argv[2:]) or 0)
    print(__doc__)
