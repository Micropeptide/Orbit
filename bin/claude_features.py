"""Claude Code features Orbit shows and edits for you: subagent definitions, hooks, and the options it passes on.

Subagents are Markdown files Claude Code reads itself: ~/.claude/agents/<name>.md (yours, everywhere) and
<folder>/.claude/agents/<name>.md (one project). Each has a name, what it is for, the tools it may use and the
model it runs on -- which is how a cheap model searches and a strong one reviews. Orbit only writes the files;
Claude Code does the rest, so nothing here changes how a subagent runs.
"""
import json
import os
import re

MODELS = ("inherit", "haiku", "sonnet", "opus")
COLORS = ("", "red", "blue", "green", "yellow", "purple", "orange", "pink", "cyan")
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _home():
    return os.environ.get("ORBIT_CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def agents_dir(scope, cwd=None):
    """The folder for one scope: "user" or "project" (needs a folder)."""
    if scope == "user":
        return os.path.join(_home(), "agents")
    if scope == "project" and cwd and os.path.isabs(cwd):
        return os.path.join(cwd, ".claude", "agents")
    return None


def parse(text):
    """(front matter dict, body) of an agent file. Only flat `key: value` lines are read."""
    meta, body = {}, text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            k, sep, v = line.partition(":")
            if sep and k.strip() and not line.startswith((" ", "\t")):
                meta[k.strip()] = v.strip().strip("\"'")
        body = m.group(2)
    return meta, body.strip("\n")


def render(name, description, prompt, model="", tools="", color=""):
    desc = " ".join(str(description or "").split()).replace('"', "'")
    lines = ["---", f"name: {name}", f'description: "{desc}"']
    if tools: lines.append(f"tools: {tools}")
    if model and model != "inherit": lines.append(f"model: {model}")
    if color: lines.append(f"color: {color}")
    lines += ["---", "", str(prompt or "").strip(), ""]
    return "\n".join(lines)


def list_agents(cwd=None):
    out = []
    for scope in ("user", "project"):
        d = agents_dir(scope, cwd)
        if not d or not os.path.isdir(d): continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".md"): continue
            try: text = open(os.path.join(d, fn), encoding="utf-8").read()
            except OSError: continue
            meta, body = parse(text)
            out.append({"scope": scope, "file": fn, "name": meta.get("name") or fn[:-3],
                        "description": meta.get("description", ""), "model": meta.get("model") or "inherit",
                        "tools": meta.get("tools", ""), "color": meta.get("color", ""), "prompt": body})
    return out


def save_agent(scope, cwd, name, description, prompt, model="inherit", tools="", color=""):
    name = str(name or "").strip().lower()
    if not _NAME.match(name): return {"error": "a name is lowercase letters, digits and dashes"}
    if not str(description or "").strip(): return {"error": "say what it is for: Claude decides when to use it from this"}
    if not str(prompt or "").strip(): return {"error": "write the instructions it follows"}
    model = str(model or "inherit").strip()
    if not re.match(r"^[A-Za-z0-9._:/\[\]-]{1,100}$", model): return {"error": "that is not a model name"}
    color = color if color in COLORS else ""
    tools = ", ".join(t for t in re.split(r"[,\s]+", str(tools or "")) if re.match(r"^[A-Za-z0-9_*:()\-]+$", t))
    d = agents_dir(scope, cwd)
    if not d: return {"error": "pick a folder for a project subagent"}
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, name + ".md")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: f.write(render(name, description, prompt, model, tools, color))
    os.replace(tmp, path)
    return {"ok": True, "path": path}


def delete_agent(scope, cwd, name):
    d = agents_dir(scope, cwd)
    name = str(name or "").strip().lower()
    if not d or not _NAME.match(name): return {"error": "no such subagent"}
    path = os.path.join(d, name + ".md")
    if not os.path.isfile(path): return {"error": "no such subagent"}
    os.remove(path)
    return {"ok": True}


# the starting points offered when you add one: a cheap searcher, a strong reviewer, a careful planner
TEMPLATES = [
    {"name": "searcher", "model": "haiku", "tools": "Read, Grep, Glob",
     "description": "Finds where something is in the code or the files and reports back briefly. Use for any search or lookup.",
     "prompt": "You search. Find what you were asked for with Grep, Glob and Read, and answer with file paths, line numbers and "
               "one line on each. Do not change anything. Be brief."},
    {"name": "reviewer", "model": "opus", "tools": "Read, Grep, Glob, Bash",
     "description": "Reviews a change for bugs and risks before it is called done. Use after finishing a non-trivial change.",
     "prompt": "You review. Read the change and what it touches, run the tests if there are any, and report only real problems: "
               "what is wrong, where, and how it fails. Say plainly when you found nothing."},
    {"name": "summarizer", "model": "haiku", "tools": "Read",
     "description": "Summarizes long files, logs or outputs. Use when the text is long and only the gist matters.",
     "prompt": "You summarize. Read what you were given and return the points that matter, the numbers, and anything that "
               "looks wrong, in a short list."},
]


def hooks(cwd=None):
    """Every hook set in your Claude settings, by event: [{event, matcher, command, source}]."""
    files = [("user", os.path.join(_home(), "settings.json"))]
    if cwd and os.path.isabs(cwd):
        files += [("project", os.path.join(cwd, ".claude", "settings.json")),
                  ("local", os.path.join(cwd, ".claude", "settings.local.json"))]
    out = []
    for src, path in files:
        try: d = json.load(open(path))
        except Exception: continue
        if not isinstance(d, dict): continue
        for event, groups in (d.get("hooks") or {}).items():
            for g in groups if isinstance(groups, list) else []:
                for h in (g or {}).get("hooks") or []:
                    out.append({"event": event, "matcher": (g or {}).get("matcher") or "", "type": h.get("type") or "command",
                                "command": h.get("command") or h.get("url") or h.get("prompt") or "",
                                "source": src, "disabled": bool(d.get("disableAllHooks"))})
    return out


# ---------------------------------------------------------------- background sessions
# Claude Code can run a session on its own, detached from any window (`claude --bg`), and lists, reads, stops and
# removes them (`claude agents`, `logs`, `stop`, `rm`). Orbit drives those commands and shows the result; the sessions
# themselves live in Claude Code, so they carry on if Orbit is closed.
import subprocess

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,79}$")
BG_MODES = ("default", "acceptEdits", "plan", "auto", "dontAsk")      # not bypassPermissions: nobody is there to watch it


def _run(exe, args, cwd=None, env=None, timeout=30):
    try:
        r = subprocess.run([exe] + list(args), cwd=cwd if cwd and os.path.isdir(cwd) else None, env=env,
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "Claude Code did not answer in time"
    except OSError as e:
        return 127, f"Claude Code could not be started: {e}"
    return r.returncode, ((r.stdout or "") + (("\n" + r.stderr) if r.stderr and r.returncode else "")).strip()


def bg_list(exe, env=None, cwd=None, everything=False):
    """Sessions Claude Code is running or has run in the background: [{id, name, status, cwd, kind, started}]."""
    args = ["agents", "--json"] + (["--all"] if everything else [])
    if cwd and os.path.isabs(cwd): args += ["--cwd", cwd]
    rc, out = _run(exe, args, env=env)
    if rc != 0: return {"error": out or "could not list sessions"}
    try: rows = json.loads(out)
    except ValueError: return {"error": "Claude Code's list was not readable"}
    items = []
    for r in rows if isinstance(rows, list) else []:
        items.append({"id": r.get("sessionId") or r.get("id") or "", "name": r.get("name") or "", "status": r.get("status") or "",
                      "cwd": r.get("cwd") or "", "kind": r.get("kind") or "", "pid": r.get("pid"),
                      "started": (r.get("startedAt") or 0) / 1000.0})
    return {"sessions": items}


def bg_start(exe, prompt, cwd, env=None, model="", mode="", resume=""):
    """Start a session in the background; with resume, continue that Claude session there. {id, output} or {error}."""
    prompt = str(prompt or "").strip()
    if not prompt: return {"error": "say what it should do"}
    if not cwd or not os.path.isabs(cwd) or not os.path.isdir(cwd): return {"error": "pick a folder that exists"}
    args = ["--bg"]
    if model:
        if not re.match(r"^[A-Za-z0-9._:/\[\]-]{1,100}$", str(model)): return {"error": "that is not a model name"}
        args += ["--model", str(model)]
    if mode:
        if mode not in BG_MODES: return {"error": "a background session cannot use that permission mode"}
        args += ["--permission-mode", mode]
    if resume:
        if not re.match(r"^[0-9a-f-]{36}$", str(resume)): return {"error": "that is not a session id"}
        args += ["--resume", str(resume)]
    rc, out = _run(exe, args + ["--", prompt], cwd=cwd, env=env, timeout=60)
    if rc != 0: return {"error": out or "Claude Code did not start it"}
    m = re.search(r"\b([0-9a-f]{8}(?:-[0-9a-f]{4}){0,4}|[0-9a-f]{6,12})\b", out)
    return {"ok": True, "id": m.group(1) if m else "", "output": out[-400:]}


def _with_id(exe, verb, sid, env, extra=(), timeout=30):
    sid = str(sid or "").strip()
    if not _ID.match(sid) or sid.startswith("-"): return {"error": "that is not a session"}
    rc, out = _run(exe, [verb, *extra, sid], env=env, timeout=timeout)
    return {"ok": rc == 0, "output": out[-20000:]} if rc == 0 else {"error": out or f"{verb} failed"}


def bg_logs(exe, sid, env=None): return _with_id(exe, "logs", sid, env)
def bg_stop(exe, sid, env=None): return _with_id(exe, "stop", sid, env)
def bg_remove(exe, sid, env=None): return _with_id(exe, "rm", sid, env, timeout=60)
def bg_respawn(exe, sid, env=None): return _with_id(exe, "respawn", sid, env)


# ---------------------------------------------------------------- the status line
# Claude Code's `statusLine` setting names a command that prints one line for the footer of its terminal, given a JSON
# description of the session on stdin. Orbit runs the same command and shows its line, so a status line you built for Claude
# Code shows in Orbit too. It is your own command from your own settings, with a short time limit.
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")


def statusline_command(cwd=None):
    files = [os.path.join(cwd, ".claude", "settings.local.json"), os.path.join(cwd, ".claude", "settings.json")] if cwd and os.path.isabs(cwd) else []
    for path in files + [os.path.join(_home(), "settings.json")]:
        try: d = json.load(open(path))
        except Exception: continue
        sl = d.get("statusLine") if isinstance(d, dict) else None
        if isinstance(sl, dict) and sl.get("type") == "command" and str(sl.get("command") or "").strip():
            return str(sl["command"]).strip()
    return ""


def statusline(cwd=None, session_id="", model="", model_name="", cost=None, timeout=3):
    """The status line's text, or "" when none is set or it failed."""
    cmd = statusline_command(cwd)
    if not cmd: return ""
    payload = {"session_id": session_id or "", "cwd": cwd or "", "version": "",
               "model": {"id": model or "", "display_name": model_name or model or ""},
               "workspace": {"current_dir": cwd or "", "project_dir": cwd or ""},
               "output_style": {"name": "default"},
               "cost": {"total_cost_usd": cost or 0, "total_duration_ms": 0, "total_lines_added": 0, "total_lines_removed": 0}}
    try:
        r = subprocess.run(["/bin/sh", "-c", cmd], input=json.dumps(payload), capture_output=True, text=True, timeout=timeout,
                           cwd=cwd if cwd and os.path.isdir(cwd) else None)
    except (subprocess.TimeoutExpired, OSError):
        return ""
    lines = [_ANSI.sub("", ln).strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
    return " · ".join(lines[:2])[:300]


# ---------------------------------------------------------------- keybindings
def keybindings_path():
    return os.path.join(_home(), "keybindings.json")


def read_keybindings():
    try: return {"text": open(keybindings_path(), encoding="utf-8").read(), "path": keybindings_path()}
    except FileNotFoundError: return {"text": "", "path": keybindings_path()}
    except OSError as e: return {"error": str(e)}


def write_keybindings(text):
    """Claude Code's own ~/.claude/keybindings.json (the terminal's shortcuts), written only when it is valid JSON."""
    text = str(text or "")
    if text.strip():
        try: json.loads(text)
        except ValueError as e: return {"error": f"that is not valid JSON: {e}"}
    path = keybindings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        try: open(path + ".orbit-bak", "w", encoding="utf-8").write(open(path, encoding="utf-8").read())
        except OSError: pass
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: f.write(text if text.endswith("\n") or not text else text + "\n")
    os.replace(tmp, path)
    return {"ok": True, "path": path}
