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
    # lean: Claude's built-in tools and bundled skills only (--safe-mode)
    # focused: your user settings, the skills that fit this chat, chosen MCP servers
    # full: everything in your Claude setup -- every skill, plugin, hook and server
    "profile": "focused",
    # Claude Code's permission mode for new runs: default (ask), acceptEdits, plan,
    # auto, dontAsk or bypassPermissions. Claude's own allow/deny rules apply as
    # always; Orbit only shows the prompts Claude raises and answers them.
    "permission_mode": "default",
    # also apply Orbit's own safety rules, autonomy mode and folder limit on top
    "orbit_rules": False,
    # where "Always allow" saves the rule: "suggested" (Claude's choice, usually the
    # project's .claude/settings.local.json), "userSettings", "projectSettings",
    # "localSettings" or "session"
    "rule_destination": "suggested",
    # permission mode for runs nobody is watching (scheduled jobs): what Claude
    # would ask about is refused there, unless this lets it through
    "unattended_mode": "default",
    "hooks": False,                  # run your Claude hooks (focused/full)
    "mcp_servers": ["paper-fetch"],  # from ~/.claude.json, by name ("*" = all)
    "orbit_tools": False,            # also offer Orbit's own tools (MCP bridge)
    # a project's own tools (<folder>/.orbit/tools, once trusted) in its chats --
    # they are the project's function (the market project's record_forecast...)
    "project_tools": True,
    "orbit_tool_names": ["search_chats", "read_chat", "remember", "search_agent_memory",
                         "search_knowledge", "schedule_task", "list_scheduled_tasks",
                         "cancel_scheduled_task", "web_search", "check_citations"],
    "skill_routing": True,           # pick skills per chat (focused)
    "core_skills": ["deep-research", "literature-review", "paper-lookup",
                    "scientific-writing", "statistical-analysis", "dataviz"],
    "max_skills": 14,
    "skill_hint": True,              # name the best-matching skills in the message
    "orbit_skills": True,            # Orbit's own skills as a plugin
    "disallowed_tools": ["WebSearch", "Workflow", "ScheduleWakeup", "CronCreate", "CronDelete",
                         "CronList", "EnterWorktree", "ExitWorktree", "ReportFindings",
                         "SendMessage", "RemoteTrigger", "ListMcpResourcesTool",
                         "ReadMcpResourceTool", "ReadMcpResourceDirTool"],
    # with orbit_rules on: tools Orbit lets through without asking
    "auto_allow": ["Read", "Glob", "Grep", "LS", "Skill", "TodoWrite", "TaskCreate", "TaskGet",
                   "TaskList", "TaskUpdate", "TaskOutput", "Agent", "Task", "ToolSearch",
                   "WebFetch", "NotebookRead", "EnterPlanMode", "mcp__paper-fetch__*"],
    "history": True,                 # list claude-qwen sessions in the sidebar
    "history_all_models": False,     # ...including ones run on other models
    "extra_args": [],
    "append_system": "",
    "effort_passthrough": True,
}

LOCAL_MODEL_PREFIXES = ("mtplx", "local", "qwen")


def cfg():
    s = (Q.S.get("claude_qwen") if Q else None) or {}
    return {**DEFAULTS, **s}


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
    """True when a resolved model spec should run through this engine."""
    try:
        return (spec or {}).get("provider") == BACKEND
    except Exception:
        return False


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


def harness_env(url, model, ctx, extra=None):
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
    env.update({
        "ANTHROPIC_BASE_URL": url,
        "ANTHROPIC_AUTH_TOKEN": "local-qwen",
        "ANTHROPIC_MODEL": model,
        "ANTHROPIC_DEFAULT_OPUS_MODEL": model,
        "ANTHROPIC_DEFAULT_SONNET_MODEL": model,
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": model,
        "ANTHROPIC_SMALL_FAST_MODEL": model,
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
    if os.environ.get("ORBIT_CLAUDE_CONFIG_DIR"):
        env["CLAUDE_CONFIG_DIR"] = os.environ["ORBIT_CLAUDE_CONFIG_DIR"]
    env.update(extra or {})
    return env


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


def skill_settings(enabled, c):
    """--settings for this run: every user skill off except the chosen ones."""
    s = {"disableAllHooks": not c.get("hooks")}
    if c["profile"] == "focused":
        keep = set(enabled)
        s["skillOverrides"] = {it["name"]: "off" for it in skill_index() if it["name"] not in keep}
        s["skillListingBudgetFraction"] = 0.05
    return s


# ------------------------------------------------------------------ arguments

def build_argv(c, *, session_id=None, resume=False, cwd=None, read_only=False, effort=None,
               name=None, settings_path=None, mcp_path=None, append=None, sdk=True):
    exe = which_claude() or "claude"
    argv = [exe]
    if sdk:
        argv += ["--print", "--output-format", "stream-json", "--verbose",
                 "--input-format", "stream-json", "--include-partial-messages",
                 "--permission-prompt-tool", "stdio"]
    argv += ["--model", "sonnet"]
    prof = c.get("profile") or "focused"
    if prof == "lean":
        argv.append("--safe-mode")
    elif prof == "focused":
        argv += ["--setting-sources", "user"]
    if session_id:
        argv += (["--resume", session_id] if resume else ["--session-id", session_id])
    mode = "plan" if read_only else (c.get("permission_mode") or "default")
    if mode not in PERMISSION_MODES: mode = "default"
    if mode != "default": argv += ["--permission-mode", mode]
    dis = [t for t in c.get("disallowed_tools") or [] if t]
    if dis: argv += ["--disallowedTools", *dis]
    if settings_path: argv += ["--settings", settings_path]
    if mcp_path:
        argv += ["--mcp-config", mcp_path]
        if prof != "full" and "*" not in (c.get("mcp_servers") or []):
            argv.append("--strict-mcp-config")
    if prof != "lean" and c.get("orbit_skills"):
        pd = orbit_skills_plugin()
        if pd: argv += ["--plugin-dir", pd]
    if append: argv += ["--append-system-prompt", append]
    if effort and c.get("effort_passthrough") and effort in ("low", "medium", "high", "xhigh", "max"):
        argv += ["--effort", effort]
    if name and not resume: argv += ["--name", name[:80]]
    # identical system text across sessions and days: the local prompt cache keeps it
    argv.append("--exclude-dynamic-system-prompt-sections")
    argv += [str(x) for x in (c.get("extra_args") or [])]
    return argv


def _write_json(name, data):
    p = os.path.join(_work_dir(), name)
    tmp = p + f".{os.getpid()}.tmp"
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
        auto = bool(by_rule) or (mode == "full" and fn not in Q.NEVER_AUTO_FNS and reason not in Q.NEVER_AUTO) \
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
INIT = {}            # what the last run reported: commands, agents, models, tools, skills
CONTROLS = ("set_permission_mode", "set_model", "set_max_thinking_tokens", "get_context_usage",
            "mcp_status", "mcp_toggle", "mcp_reconnect", "mcp_set_servers", "stop_task",
            "rewind_files", "reload_plugins", "get_settings", "apply_flag_settings", "interrupt")


def _prefs_path():
    return os.path.join(_work_dir(), "chat-prefs.json")


def chat_prefs(sid=None):
    try: d = json.load(open(_prefs_path()))
    except Exception: d = {}
    return d.get(sid) or {} if sid else d


def set_chat_pref(sid, **kw):
    d = chat_prefs()
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
        self.tasks = collections.OrderedDict()     # id -> [text, done]

    def from_tool(self, name, inp, result_text):
        inp = inp or {}
        if name == "TodoWrite":
            self.tasks.clear()
            for i, t in enumerate(inp.get("todos") or []):
                self.tasks[str(i)] = [t.get("content") or t.get("activeForm") or "", t.get("status") == "completed"]
            return True
        if name == "TaskCreate":
            m = re.search(r"#(\d+)", result_text or "")
            tid = m.group(1) if m else str(len(self.tasks) + 1)
            self.tasks[tid] = [inp.get("subject") or inp.get("description") or "", False]
            return True
        if name == "TaskUpdate":
            tid = str(inp.get("taskId") or inp.get("id") or "")
            if tid in self.tasks:
                if inp.get("subject"): self.tasks[tid][0] = inp["subject"]
                if inp.get("status"): self.tasks[tid][1] = inp["status"] == "completed"
                if inp.get("status") == "deleted": self.tasks.pop(tid, None)
                return True
        return False

    def text(self):
        return "\n".join(f"{i}. [{'x' if d else ' '}] {t}" for i, (t, d) in enumerate(self.tasks.values()))

    def steps(self):
        return [{"text": t[:200], "done": d} for t, d in self.tasks.values()]


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


def _append_system(project, c, orbit_tools):
    parts = _system_parts(project)
    parts.append(
        "# Running inside Orbit\n"
        "- The user is chatting through Orbit, a local web app, not a terminal. Messages start with "
        "when they were sent, e.g. [Wed 16 Sep 2026, 14:30 PDT]; that is the current date and time.\n"
        "- There is no time limit and no need to check in. Never stop to ask whether to continue; "
        "keep working until the whole task is done. Ask (AskUserQuestion) only for a real choice.\n"
        "- WebSearch is unavailable with this local model. Use WebFetch on known URLs"
        + (", or mcp__orbit__web_search" if orbit_tools else "") + ".")
    if c.get("append_system"): parts.append(str(c["append_system"]))
    return "\n\n".join(parts)


def run_turn(messages, user_content, tools, emit=None, approve=None, cancel=None, inbox=None,
             interrupt=None, sid=None, checkpoint=None, project=None, max_minutes=None,
             read_only=None, **_):
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
    label = "Claude Code · " + (spec.get("label") or "local Qwen").replace(" · CLI", "")
    emit("model", {"id": spec.get("id"), "label": label, "provider": "Claude Code"})
    _wake_model(emit)

    mk = dict(marker_of(messages) or {})
    jp = jsonl_path(mk.get("session"), mk.get("cwd")) if mk else None
    resume = bool(jp)
    fork, resume_at = False, None
    if resume:
        # a chat forked in Orbit shares its parent's Claude session: branch it off
        fork = bool(sid and mk.get("owner") and mk["owner"] != sid)
        # a chat edited or regenerated in Orbit no longer ends where Claude's
        # transcript does: resume at the last message Orbit still has
        mine = next((m.get("claude_uuid") for m in reversed(messages)
                     if m.get("role") == "assistant" and m.get("claude_uuid")), None)
        if mine and mine != last_assistant_uuid(jp):
            resume_at = mine
    if not resume:
        folder = None
        try: folder = q.project_folder(project) if project else None
        except Exception: folder = None
        cwd = folder or q.WORKSPACE
        prior = _prior_transcript([m for m in messages if m.get("role") != "system"])
        mk = {"session": str(uuid.uuid4()), "cwd": cwd, "skills": [], "owner": sid}
    else:
        cwd = mk.get("cwd") or q.WORKSPACE
        prior = ""
        if jp and os.path.dirname(jp) != os.path.join(projects_dir(), encode_cwd(cwd)):
            # resumed from wherever the transcript actually is
            cwd = mk.get("cwd") or cwd
    if not os.path.isdir(cwd): cwd = q.WORKSPACE

    plain = user_content if isinstance(user_content, str) else " ".join(
        x.get("text", "") for x in user_content if isinstance(x, dict))
    # skills: this chat's set, grown by what this message needs
    chosen = list(dict.fromkeys(mk.get("skills") or []))
    hint = []
    if c["profile"] == "focused" and c.get("skill_routing"):
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

    now = time.time()
    messages.append({"role": "user", "content": user_content, "t": now, "claude": dict(mk)})
    umsg = messages[-1]
    if sid: q.LAST_TURN.pop(sid, None)

    settings_path = _write_json(f"settings-{mk['session']}.json", skill_settings(chosen, c))
    servers = {}
    known = user_mcp_servers()
    names = c.get("mcp_servers") or []
    for n in (known if "*" in names else names):
        if n in known: servers[n] = known[n]
    token = None
    specs = []
    if bridge_url():
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
    mcp_path = _write_json(f"mcp-{mk['session']}.json", {"mcpServers": servers})

    prefs = chat_prefs(sid) if sid else {}
    if prefs.get("permission_mode"): c["permission_mode"] = prefs["permission_mode"]
    if not approve and (c.get("unattended_mode") or "default") != "default":
        c["permission_mode"] = c["unattended_mode"]
    url, model_name, ctxw = model_endpoint()
    argv = build_argv(c, session_id=mk["session"], resume=resume, cwd=cwd, read_only=bool(read_only),
                      effort=getattr(T, "effort", None) or q.S.get("reasoning_effort"),
                      name=None, settings_path=settings_path, mcp_path=mcp_path,
                      append=_append_system(project, c, orbit_tools))
    if fork: argv.append("--fork-session")
    if resume_at: argv += ["--resume-session-at", resume_at]
    env = harness_env(url, model_name, ctxw)

    stamp = f"[{q.sent_at(now)}] "
    blocks = _content_blocks(user_content, stamp)
    if prior:
        blocks.insert(0, {"type": "text", "text": "[Earlier in this chat, before it moved to Claude Code:]\n"
                          + prior + "\n[End of the earlier conversation.]"})
    if hint and c.get("skill_hint"):
        blocks.append({"type": "text", "text": "[Orbit: skills that may fit this request — load one with "
                       "the Skill tool if it applies: " + "; ".join(
                           f"{s['name']} ({s['description'][:160]})" for s in hint) + "]"})

    _run_log(sid, mk, resume, fork, resume_at, c, cwd, argv)
    try:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, start_new_session=True)
    except OSError as e:
        msg = f"Could not start Claude Code: {e}"
        emit("error", msg); emit("done", None)
        return msg

    wlock = threading.Lock()
    def send(obj):
        try:
            with wlock:
                proc.stdin.write((json.dumps(obj) + "\n").encode())
                proc.stdin.flush()
            return True
        except (BrokenPipeError, OSError, ValueError):
            return False

    lines = collections.deque()
    got = threading.Event()
    def reader():
        for raw in proc.stdout:
            lines.append(raw); got.set()
        lines.append(None); got.set()
    err_tail = collections.deque(maxlen=40)
    def err_reader():
        for raw in proc.stderr:
            s = raw.decode("utf-8", "replace").rstrip()
            if s and "unrecognized_model" not in s: err_tail.append(s)
    threading.Thread(target=reader, daemon=True).start()
    threading.Thread(target=err_reader, daemon=True).start()

    run = {"send": send, "waiters": {}, "session": mk["session"], "started": t_start}
    if sid: RUNS[sid] = run
    # what this Claude setup offers (slash commands with descriptions, agents, models)
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
    subagents = {}

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
                                      "pending": [t for t, d in plan.tasks.values() if not d]})
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
                    if mid != cur_id: new_step(mid)
                    u = (e.get("message") or {}).get("usage") or {}
                    ptok = (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) \
                        + (u.get("cache_creation_input_tokens") or 0)
                    if ptok and sid: q.SESSION_TOKENS[sid] = ptok
                    usage["prompt_tokens"] += ptok
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
                continue

            if t == "assistant":
                msg = ev.get("message") or {}
                if ev.get("parent_tool_use_id"):
                    for b in msg.get("content") or []:
                        if b.get("type") == "tool_use":
                            parent = ev["parent_tool_use_id"]
                            subagents[parent] = subagents.get(parent, 0) + 1
                            emit("subtask", {"description": (tool_meta.get(parent) or ("", {}))[1].get("description", "helper"),
                                             "tool": b.get("name")})
                    continue
                if msg.get("id") != cur_id or cur is None: new_step(msg.get("id"))
                if ev.get("uuid"): cur["claude_uuid"] = ev["uuid"]
                for b in msg.get("content") or []:
                    bt = b.get("type")
                    if bt == "text":
                        cur["content"] = (cur.get("content") or "") + (b.get("text") or "")
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
                    if name == "Agent" or name == "Task":
                        p["output"] = text[:4000]
                    emit("tool_result", p)
                    messages.append({"role": "tool", "tool_call_id": tid, "name": name, "t": time.time(),
                                     "ok": ok, "secs": secs, "content": text[:60000]})
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
                    run["mode"] = ev.get("permissionMode")
                    if ev.get("session_id") and ev["session_id"] != mk["session"]:
                        # a fork got its own session id: this chat follows it from now on
                        mk["session"] = ev["session_id"]; mk["owner"] = sid
                        umsg["claude"] = dict(mk)
                    bad = [s.get("name") for s in ev.get("mcp_servers") or []
                           if isinstance(s, dict) and s.get("status") not in ("connected", "pending")]
                    if bad:
                        emit("notice", {"msg": "MCP server not connected: " + ", ".join(bad)})
                elif st == "compact_boundary":
                    emit("notice", {"msg": "Claude Code compacted the conversation to make room"})
                elif st == "api_retry":
                    emit("retry", {"attempt": ev.get("attempt"), "of": ev.get("max_retries"),
                                   "wait": round((ev.get("retry_delay_ms") or 0) / 1000, 1),
                                   "error": str(ev.get("error") or "")[:300], "kind": "transient"})
                elif st == "status" and ev.get("status") == "compacting":
                    emit("notice", {"msg": "compacting the conversation…"})
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
                    try: proc.stdin.close()
                    except Exception: pass
                continue
    finally:
        try:
            if proc.poll() is None:
                try: proc.stdin.close()
                except Exception: pass
                try: proc.wait(timeout=20)
                except subprocess.TimeoutExpired: _kill(proc)
        except Exception:
            pass
        if token: BRIDGE.pop(token, None)
        for f in (settings_path, mcp_path):      # per-run files; the MCP one holds the run's token
            try: os.remove(f)
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
        if "ECONNREFUSED" in why or "Connection error" in why or "fetch failed" in why:
            why += " — the local model server is not answering. Start it (sidebar → Start) and try again."
        emit("error", why[:1200])
    elif result_err and not stopped:
        emit("notice", {"msg": f"Claude Code reported: {str(result_err)[:300]}"})
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
                "profile": c.get("profile"), "mode": c.get("permission_mode"),
                "skills": len(mk.get("skills") or []),
                "args": [a for a in argv[1:] if a.startswith("--")]}
        with open(os.path.join(Q.LOGS, "claude.log"), "a") as fh:
            fh.write(json.dumps(line) + "\n")
    except Exception:
        pass


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
    if not include_all and not any(b'"model":"' + p.encode() in raw
                                   for p in LOCAL_MODEL_PREFIXES + tuple(m for m in local if m)):
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
    """Claude sessions run on the local model, newest first."""
    c = cfg()
    include_all = c.get("history_all_models") if include_all is None else include_all
    local = set(x.lower() for x in (local or []))
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
            if hit[1]: out.append(hit[1])
    out.sort(key=lambda x: -(x["mtime"] or 0))
    return out


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
                if msg.get("model") == "<synthetic>": continue
                if msg.get("id") != cur_id or cur is None:
                    cur = {"role": "assistant", "content": "", "model": "Claude Code · " + str(msg.get("model") or ""),
                           "t": ts}
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
    extra = {"model": f"{BACKEND}:default", "tags": ["claude-qwen"], "source": "claude-qwen",
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


def resume_command(orbit_msgs):
    mk = marker_of(orbit_msgs)
    if not mk: return None
    cwd = mk.get("cwd") or HOME
    return f"cd {json.dumps(cwd)} && claude-qwen --resume {mk['session']}"


# ------------------------------------------------------------------ terminal launcher

def launch(args):
    """`claude-qwen`: the interactive harness, set up the way Orbit runs it.

    CLAUDE_QWEN_PROFILE=lean|focused|full picks the profile (default: Orbit's
    setting); CLAUDE_QWEN_BARE=1 brings back the old --bare mode (three tools)."""
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
    names = c.get("mcp_servers") or []
    servers = {k: v for k, v in user_mcp_servers().items() if "*" in names or k in names}
    mcp_path = _write_json("mcp-terminal.json", {"mcpServers": servers})
    # no per-message skill routing in a terminal, so every skill stays listed
    settings_path = _write_json("settings-terminal.json", {"disableAllHooks": not c.get("hooks")})
    append = "\n\n".join(_system_parts(None) + [TERMINAL_NOTE] +
                         ([str(c["append_system"])] if c.get("append_system") else []))
    argv = build_argv(c, settings_path=settings_path, mcp_path=mcp_path, sdk=False, append=append)
    if os.environ.get("CLAUDE_QWEN_DRY_RUN") == "1":
        print(json.dumps({"argv": argv + list(args), "cwd": os.getcwd(),
                          "env": {k: v for k, v in env.items() if k.startswith(("ANTHROPIC", "CLAUDE"))}}, indent=1))
        return 0
    os.execvpe(exe, argv + list(args), env)


TERMINAL_NOTE = ("# Local model\n- WebSearch is unavailable with this local model; use WebFetch on "
                 "known URLs.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "launch":
        sys.exit(launch(sys.argv[2:]) or 0)
    print(__doc__)
