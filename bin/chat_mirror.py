"""A second copy of the chats that live in other apps' own folders.

Orbit's own backup (a daily archive) holds Orbit's chats. The conversations you have through Claude Code (the
terminal, the Claude desktop app, Orbit's sessions), Codex and Antigravity are kept by those programs, in
their own folders, and a lost Mac loses them too. This keeps a mirror of them next to the backup archives:
only what is new or changed is copied each time, nothing in the mirror is ever deleted or overwritten by a
restore, and a first big copy simply carries on at the next run if it runs out of time.

Never copied: a temporary chat (none of its sessions exist, but an id in `skip_ids` is left out whatever
turns up), the Claude memory tool's own observer sessions, and sessions run from scratch folders.
"""
import glob, json, os, re, shutil, sqlite3, time

# id -> (label, on by default, what it is)
SOURCES = {
    "claude":     ("Claude Code and Claude desktop chats", True, "session transcripts"),
    "claude_sub": ("…and the helper agents' own transcripts", False, "subagent transcripts: large, and the chat already holds their reports"),
    "claude_app": ("Claude desktop's session list", True, "titles and settings of desktop sessions"),
    "codex":      ("Codex chats", True, "~/.codex/sessions"),
    "agy":        ("Antigravity chats", True, "~/.gemini/antigravity/conversations"),
    "opencode":   ("OpenCode chats", False, "one database, around a gigabyte: copied whole each time it changes"),
}
RECENT = 60                       # a file written in the last minute is still being written: next time
SKIP_PROJECTS = re.compile(r"claude-mem-observer-sessions|^-private-tmp|^-private-var-folders|^-tmp-|stoptest")


def enabled(cfg):
    """The sources switched on: the defaults, changed by cfg["external"]."""
    if not cfg.get("include_external", True): return []
    chosen = cfg.get("external") or {}
    return [k for k, (_, on, _) in SOURCES.items() if chosen.get(k, on)]


def _files(src, home):
    """(source path, path relative to the mirror's folder for it) for what a source holds."""
    j = lambda *a: os.path.join(home, *a)
    if src in ("claude", "claude_sub"):
        base = j(".claude", "projects")
        try: projects = sorted(os.listdir(base))
        except OSError: return
        for proj in projects:
            if SKIP_PROJECTS.search(proj): continue
            d = os.path.join(base, proj)
            if not os.path.isdir(d): continue
            if src == "claude":
                for f in glob.glob(os.path.join(d, "*.jsonl")): yield f, os.path.join("claude", proj, os.path.basename(f))
            else:
                for f in glob.glob(os.path.join(d, "*", "subagents", "*.jsonl")):
                    yield f, os.path.join("claude", proj, os.path.relpath(f, d))
    elif src == "claude_app":
        base = j("Library", "Application Support", "Claude", "claude-code-sessions")
        for f in glob.glob(os.path.join(base, "*", "*", "local_*.json")): yield f, os.path.join("claude-app", os.path.relpath(f, base))
    elif src == "codex":
        for sub in ("sessions", "archived_sessions"):
            base = j(".codex", sub)
            for f in glob.glob(os.path.join(base, "**", "*.jsonl"), recursive=True):
                yield f, os.path.join("codex", sub, os.path.relpath(f, base))
    elif src == "agy":
        base = j(".gemini", "antigravity")
        for f in glob.glob(os.path.join(base, "conversations", "*.db")): yield f, os.path.join("antigravity", "conversations", os.path.basename(f))
        f = os.path.join(base, "conversation_summaries.db")
        if os.path.exists(f): yield f, os.path.join("antigravity", "conversation_summaries.db")
    elif src == "opencode":
        f = j(".local", "share", "opencode", "opencode.db")
        if os.path.exists(f): yield f, os.path.join("opencode", "opencode.db")


def _is_db(path):
    return path.endswith(".db")


def _skipped(path, skip_ids):
    return any(i and i in path for i in skip_ids)


def _copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".part"
    if _is_db(src):
        # a database in use: asked for its own consistent copy, not the file as it lies on disk
        a = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=30)
        try:
            b = sqlite3.connect(tmp)
            try: a.backup(b)
            finally: b.close()
        finally:
            a.close()
        shutil.copystat(src, tmp)
    else:
        shutil.copy2(src, tmp)
    os.replace(tmp, dst)


def _changed(src, dst):
    try: s = os.stat(src)
    except OSError: return False
    try: d = os.stat(dst)
    except OSError: return True
    return s.st_size != d.st_size or s.st_mtime > d.st_mtime + 1


def mirror(cfg, skip_ids=(), home=None, deadline_s=600, now=None):
    """Copy what is new or changed. Returns {"copied", "bytes", "seen", "left", "errors", "secs"}; `left` is
    what a short deadline did not get to (it carries on next time)."""
    t0 = time.time()
    now = now or t0
    home = home or os.path.expanduser("~")
    root = os.path.join(cfg["dest"], "external")
    out = {"copied": 0, "bytes": 0, "seen": 0, "left": 0, "errors": 0}
    for src in enabled(cfg):
        for path, rel in _files(src, home):
            out["seen"] += 1
            if _skipped(path, skip_ids): continue
            dst = os.path.join(root, rel)
            if not _changed(path, dst): continue
            try:
                if not _is_db(path) and now - os.path.getmtime(path) < RECENT: continue
            except OSError:
                continue
            if time.time() - t0 > deadline_s:
                out["left"] += 1; continue
            try:
                _copy(path, dst)
                out["copied"] += 1; out["bytes"] += os.path.getsize(dst)
            except (OSError, sqlite3.Error):
                out["errors"] += 1
    out["secs"] = round(time.time() - t0, 1)
    try:
        os.makedirs(root, exist_ok=True)
        with open(os.path.join(root, ".state.json"), "w") as f: json.dump({**out, "at": now}, f)
    except OSError:
        pass
    return out


def state(cfg):
    try:
        with open(os.path.join(cfg["dest"], "external", ".state.json")) as f: return json.load(f)
    except Exception:
        return {}


def restore_missing(cfg, home=None):
    """Put back what the mirror has and the programs' folders no longer do. Never overwrites."""
    home = home or os.path.expanduser("~")
    root = os.path.join(cfg["dest"], "external")
    maps = {"claude": os.path.join(home, ".claude", "projects"),
            "claude-app": os.path.join(home, "Library", "Application Support", "Claude", "claude-code-sessions"),
            "codex": os.path.join(home, ".codex"),
            "antigravity": os.path.join(home, ".gemini", "antigravity"),
            "opencode": os.path.join(home, ".local", "share", "opencode")}
    added = 0
    for top, base in maps.items():
        for f in glob.glob(os.path.join(root, top, "**", "*"), recursive=True):
            if not os.path.isfile(f) or f.endswith(".part"): continue
            rel = os.path.relpath(f, os.path.join(root, top))
            dst = os.path.join(base, rel)
            if os.path.exists(dst): continue
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(f, dst); added += 1
            except OSError:
                pass
    return {"ok": True, "n": added}
