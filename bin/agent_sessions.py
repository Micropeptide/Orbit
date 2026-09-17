"""Conversations from other coding agents on this Mac -- Codex and OpenCode -- listed
in Orbit, opened as chats, and continued in the agent's own session.

Each agent keeps its history its own way:
  Codex     ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl (one file per session)
  OpenCode  ~/.local/share/opencode/opencode.db (SQLite: session, message, part)
Orbit only reads them. Opening one saves an Orbit copy of the conversation; a new
message then runs the agent's CLI resuming that very session (`codex exec resume`,
`opencode run --session`), so the agent keeps its own context, tools and memory.
The session id travels with the chat as an "agent" marker on its messages.

Orbit chat ids: "cx-<codex session id>", "oc-<opencode session id>".
"""
import glob, json, os, re, sqlite3, threading, time

HOME = os.path.expanduser("~")
CODEX_DIR = os.path.join(os.environ.get("CODEX_HOME") or os.path.join(HOME, ".codex"), "sessions")
OPENCODE_DB = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share"),
                           "opencode", "opencode.db")

SOURCES = {
    "codex": {"prefix": "cx-", "label": "Codex", "backend": "codex-cli"},
    "opencode": {"prefix": "oc-", "label": "OpenCode", "backend": "opencode-cli"},
}
BACKEND_SOURCE = {v["backend"]: k for k, v in SOURCES.items()}

_SCRATCH = ("/private/var/folders/", "/var/folders/", "/tmp/", "/private/tmp/")
_LOCK = threading.Lock()
_CACHE = {"codex": {}, "opencode": {"key": None, "rows": []}}


def source_of(sid):
    for name, s in SOURCES.items():
        if str(sid or "").startswith(s["prefix"]): return name
    return None


def _clip(text, n=80):
    t = " ".join(str(text or "").split())
    return t[:n]


# ------------------------------------------------------------------ Codex

def _codex_user_text(payload):
    """What the person typed, from a Codex response item (not the environment or
    AGENTS.md preamble Codex sends as a user message)."""
    if payload.get("type") != "message" or payload.get("role") != "user": return ""
    text = " ".join(c.get("text", "") for c in payload.get("content") or []
                    if isinstance(c, dict) and c.get("type") in ("input_text", "text"))
    s = text.strip()
    if not s or s.startswith(("# AGENTS.md", "<INSTRUCTIONS>")): return ""
    # context Codex adds as a user message: a block wrapped in its own tag
    # (<environment_context>…</environment_context>, <recommended_plugins>…)
    m = re.match(r"^<([a-z_]+)[^>]*>", s)
    if m and f"</{m.group(1)}>" in s: return ""
    return s


def _codex_file(path):
    rows = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try: rows.append(json.loads(line))
                except ValueError: pass
    except OSError:
        pass
    return rows


def _codex_summary(path):
    meta, first, n, model, last_t, title = {}, "", 0, "", None, None
    for r in _codex_file(path):
        tp, p = r.get("type"), r.get("payload") or {}
        if tp == "session_meta": meta = p
        elif tp == "turn_context": model = p.get("model") or model
        elif tp == "event_msg" and p.get("type") == "thread_name_updated": title = p.get("thread_name") or title
        elif tp == "response_item":
            u = _codex_user_text(p)
            if u:
                n += 1
                first = first or u
        if r.get("timestamp"): last_t = r["timestamp"]
    sid = meta.get("id") or meta.get("session_id")
    if not sid or not n: return None
    cwd = meta.get("cwd") or ""
    try: mtime = os.path.getmtime(path)
    except OSError: mtime = time.time()
    return {"source": "codex", "session": sid, "id": SOURCES["codex"]["prefix"] + sid, "path": path, "cwd": cwd,
            "title": _clip(title or first) or "(untitled)", "n": n, "model": model, "mtime": mtime,
            "origin": meta.get("originator") or ""}


def codex_sessions():
    out = []
    for path in glob.glob(os.path.join(CODEX_DIR, "**", "rollout-*.jsonl"), recursive=True):
        try: key = (os.path.getmtime(path), os.path.getsize(path))
        except OSError: continue
        hit = _CACHE["codex"].get(path)
        if not hit or hit[0] != key:
            hit = (key, _codex_summary(path))
            _CACHE["codex"][path] = hit
        if hit[1]: out.append(hit[1])
    return out


def codex_convert(path):
    """A Codex session as Orbit messages."""
    msgs, cur, meta, names = [], None, {}, {}
    def assistant(ts):
        nonlocal cur
        if cur is None:
            cur = {"role": "assistant", "content": "", "t": ts, "model": "Codex"}
            msgs.append(cur)
        return cur
    for r in _codex_file(path):
        tp, p = r.get("type"), r.get("payload") or {}
        ts = _ts(r.get("timestamp"))
        if tp == "session_meta": meta = p; continue
        if tp == "turn_context" and p.get("model"):
            if cur is not None: cur["model"] = "Codex · " + p["model"]
            continue
        if tp != "response_item": continue
        pt = p.get("type")
        if pt == "message" and p.get("role") == "user":
            u = _codex_user_text(p)
            if u:
                msgs.append({"role": "user", "content": u, "t": ts})
                cur = None
        elif pt == "message" and p.get("role") == "assistant":
            text = "".join(c.get("text", "") for c in p.get("content") or [] if isinstance(c, dict))
            if text.strip():
                a = assistant(ts)
                if a.get("tool_calls"):          # text after tools: a new step
                    cur = None; a = assistant(ts)
                a["content"] += text
        elif pt == "reasoning":
            s = " ".join(x.get("text", "") for x in p.get("summary") or [] if isinstance(x, dict))
            if s.strip():
                a = assistant(ts); a["reasoning_content"] = (a.get("reasoning_content") or "") + s
        elif pt in ("function_call", "custom_tool_call", "local_shell_call"):
            cid = p.get("call_id") or p.get("id") or f"call{len(names)}"
            name = p.get("name") or ("shell" if pt == "local_shell_call" else "tool")
            args = p.get("arguments") if isinstance(p.get("arguments"), str) else json.dumps(p.get("input") or p.get("action") or {})
            names[cid] = name
            assistant(ts).setdefault("tool_calls", []).append(
                {"id": cid, "type": "function", "function": {"name": name, "arguments": args or "{}"}})
        elif pt in ("function_call_output", "custom_tool_call_output", "local_shell_call_output"):
            cid = p.get("call_id")
            out = p.get("output")
            if isinstance(out, dict): out = out.get("content") or json.dumps(out)
            if isinstance(out, list):
                out = "\n".join(x.get("text", "") if isinstance(x, dict) else str(x) for x in out)
            msgs.append({"role": "tool", "tool_call_id": cid, "name": names.get(cid, "tool"),
                         "content": str(out or "")[:20000], "t": ts})
            cur = None
    return msgs, meta.get("cwd") or HOME


# ------------------------------------------------------------------ OpenCode

def _oc_connect():
    # read-only, and never blocks OpenCode (WAL mode lets readers in alongside it)
    return sqlite3.connect(f"file:{OPENCODE_DB}?mode=ro", uri=True, timeout=5)


def opencode_sessions():
    if not os.path.exists(OPENCODE_DB): return []
    try:
        key = tuple(os.path.getmtime(OPENCODE_DB + s) for s in ("", "-wal") if os.path.exists(OPENCODE_DB + s))
    except OSError:
        key = None
    if key and _CACHE["opencode"]["key"] == key: return list(_CACHE["opencode"]["rows"])
    rows = []
    try:
        con = _oc_connect()
        try:
            q = ("select s.id, s.title, s.directory, s.time_updated, s.model, "
                 "(select count(*) from message m where m.session_id = s.id and json_extract(m.data, '$.role') = 'user') n, "
                 "(select json_extract(p.data, '$.text') from part p join message m on m.id = p.message_id "
                 "  where p.session_id = s.id and json_extract(m.data, '$.role') = 'user' "
                 "  and json_extract(p.data, '$.type') = 'text' order by p.time_created limit 1) first "
                 "from session s where s.parent_id is null and s.time_archived is null")
            for sid, title, directory, updated, model, n, first in con.execute(q):
                if not n: continue
                if str(title or "").startswith("New session - "): title = None
                mdl = ""
                try:
                    mj = json.loads(model) if model else {}
                    mdl = (f"{mj.get('providerID')}/{mj.get('id') or mj.get('modelID')}" if isinstance(mj, dict) else "")
                except ValueError:
                    mdl = str(model or "")
                rows.append({"source": "opencode", "session": sid, "id": SOURCES["opencode"]["prefix"] + sid,
                             "cwd": directory or "", "title": _clip(title or first) or "(untitled)", "n": n,
                             "model": mdl.strip("/") if mdl and "None" not in mdl else "",
                             "mtime": (updated or 0) / 1000.0, "origin": "opencode"})
        finally:
            con.close()
    except sqlite3.Error:
        return list(_CACHE["opencode"]["rows"])
    _CACHE["opencode"].update(key=key, rows=rows)
    return list(rows)


def opencode_convert(session):
    msgs, cwd, model = [], HOME, ""
    con = _oc_connect()
    try:
        row = con.execute("select directory from session where id = ?", (session,)).fetchone()
        if row and row[0]: cwd = row[0]
        mrows = con.execute("select id, data, time_created from message where session_id = ? order by time_created, id",
                            (session,)).fetchall()
        parts = {}
        for mid, data, tc in con.execute("select message_id, data, time_created from part where session_id = ? "
                                         "order by time_created, id", (session,)):
            parts.setdefault(mid, []).append(data)
    finally:
        con.close()
    for mid, data, tc in mrows:
        try: m = json.loads(data)
        except ValueError: continue
        role, ts = m.get("role"), (tc or 0) / 1000.0
        ps = []
        for d in parts.get(mid, []):
            try: ps.append(json.loads(d))
            except ValueError: pass
        if role == "user":
            text = "\n".join(p.get("text", "") for p in ps if p.get("type") == "text" and not p.get("synthetic"))
            files = [p.get("filename") or p.get("url", "")[:60] for p in ps if p.get("type") == "file"]
            if files: text += ("\n" if text else "") + "\n".join(f"[attached: {f}]" for f in files)
            if text.strip(): msgs.append({"role": "user", "content": text, "t": ts})
            continue
        if role != "assistant": continue
        if m.get("modelID"): model = f"{m.get('providerID')}/{m['modelID']}"
        cur = {"role": "assistant", "content": "", "t": ts, "model": "OpenCode · " + (m.get("modelID") or "")}
        msgs.append(cur)
        for p in ps:
            pt = p.get("type")
            if pt == "text" and not p.get("synthetic"):
                if cur.get("tool_calls"):          # text after tool calls: the next step
                    cur = {"role": "assistant", "content": "", "t": ts, "model": msgs[-1].get("model")}
                    msgs.append(cur)
                cur["content"] += p.get("text") or ""
            elif pt == "reasoning":
                cur["reasoning_content"] = (cur.get("reasoning_content") or "") + (p.get("text") or "")
            elif pt == "tool":
                cid = p.get("callID") or p.get("id")
                st = p.get("state") or {}
                cur.setdefault("tool_calls", []).append({"id": cid, "type": "function", "function": {
                    "name": p.get("tool") or "tool", "arguments": json.dumps(st.get("input") or {})}})
                out = st.get("output") if st.get("status") == "completed" else (st.get("error") or st.get("status"))
                msgs.append({"role": "tool", "tool_call_id": cid, "name": p.get("tool") or "tool",
                             "content": str(out or "")[:20000], "t": ts})
                cur = {"role": "assistant", "content": "", "t": ts, "model": cur.get("model")}
                msgs.append(cur)
    msgs = [x for x in msgs if not (x["role"] == "assistant" and not x.get("content") and not x.get("tool_calls")
                                   and not x.get("reasoning_content"))]
    return msgs, cwd, model


# ------------------------------------------------------------------ both

def _ts(s):
    if not s: return time.time()
    try:
        import datetime
        return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return time.time()


def sessions():
    """Every conversation from other agents, newest first (not other programs' one-shot calls)."""
    out = []
    with _LOCK:
        for fn in (codex_sessions, opencode_sessions):
            try: out += fn()
            except Exception: pass
    # other programs' one-shot calls (from a temporary folder, or from / with a
    # single message) are not conversations to continue
    out = [r for r in out if not (r.get("cwd") or "").startswith(_SCRATCH)
           and not ((r.get("cwd") or "/") in ("/", "") and (r.get("n") or 0) <= 1)]
    out.sort(key=lambda r: -(r.get("mtime") or 0))
    return out


def convert(sid):
    """(messages, title, cwd, marker, model_id) for an Orbit chat id cx-… / oc-…"""
    src = source_of(sid)
    session = sid[len(SOURCES[src]["prefix"]):] if src else None
    if src == "codex":
        row = next((r for r in codex_sessions() if r["session"] == session), None)
        if not row: return None
        msgs, cwd = codex_convert(row["path"])
        model = row.get("model") or ""
        title = row["title"]
    elif src == "opencode":
        row = next((r for r in opencode_sessions() if r["session"] == session), None)
        if not row: return None
        msgs, cwd, model = opencode_convert(session)
        title = row["title"]
    else:
        return None
    marker = {"source": src, "id": session, "cwd": cwd}
    for m in msgs:
        m["agent"] = dict(marker)          # every message so far is already in the agent's session
    backend = SOURCES[src]["backend"]
    return msgs, title, cwd, marker, f"{backend}:{model or 'default'}"


def marker_of(messages, backend=None):
    """The agent session a chat continues, if its latest one is this backend's."""
    src = BACKEND_SOURCE.get(backend) if backend else None
    for m in reversed(messages or []):
        a = m.get("agent") if isinstance(m, dict) else None
        if isinstance(a, dict) and a.get("id"):
            return a if (src is None or a.get("source") == src) else None
    return None


def since_marker(messages):
    """Messages after the last one the agent's session already holds -- what was said
    in this chat on another model meanwhile (the newest message included)."""
    last = -1
    for i, m in enumerate(messages or []):
        if isinstance(m, dict) and isinstance(m.get("agent"), dict): last = i
    return list(messages[last + 1:])


# ------------------------------------------------------------------ in Orbit's sidebar

def _hidden_path(root):
    return os.path.join(root, "config", "agent-hidden-sessions.json")


def hidden(root):
    try: return set(json.load(open(_hidden_path(root))))
    except Exception: return set()


def hide(root, sid):
    """Deleting a chat that came from another agent keeps that session out of the
    sidebar (the agent's own history is left alone)."""
    if not source_of(sid): return False
    h = hidden(root); h.add(sid)
    tmp = _hidden_path(root) + ".tmp"
    with open(tmp, "w") as fh: json.dump(sorted(h), fh)
    os.replace(tmp, _hidden_path(root))
    _ROWS["at"] = 0
    return True


_ROWS = {"rows": [], "at": 0.0, "busy": False}


def rows_cached(root, max_age=20):
    """Sidebar rows, without making the sidebar wait: a scan runs in the background."""
    now = time.time()
    if now - _ROWS["at"] > max_age and not _ROWS["busy"]:
        _ROWS["busy"] = True
        def work():
            try:
                hid = hidden(root)
                _ROWS["rows"] = [{"id": r["id"], "title": r["title"], "mtime": r["mtime"], "pinned": False,
                                  "archived": False, "tags": [r["source"]], "project": None, "order": None,
                                  "n": r["n"], "source": r["source"], "cwd": r["cwd"], "external": True,
                                  "agent_model": r.get("model") or ""}
                                 for r in sessions() if r["id"] not in hid]
            except Exception:
                pass
            finally:
                _ROWS["at"] = time.time(); _ROWS["busy"] = False
        th = threading.Thread(target=work, daemon=True); th.start()
        if not _ROWS["at"]: th.join(timeout=4)
    return list(_ROWS["rows"])


def changed_since(sid, stamp):
    """Whether the agent's own session has changed after `stamp` (it was continued
    there, or by Orbit through the agent)."""
    src = source_of(sid)
    session = sid[len(SOURCES[src]["prefix"]):] if src else None
    if src == "codex":
        row = next((r for r in codex_sessions() if r["session"] == session), None)
        return bool(row and row["mtime"] > (stamp or 0) + 1)
    if src == "opencode":
        row = next((r for r in opencode_sessions() if r["session"] == session), None)
        return bool(row and row["mtime"] > (stamp or 0) + 1)
    return False
