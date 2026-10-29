"""Claude Science chats in Orbit: read the conversations the Claude Science app keeps on this Mac (a local SQLite database) and turn one into a new Orbit chat to
carry on in.

Only reads: the database is opened read-only and nothing in Claude Science is changed. What comes across is the conversation itself (what you asked and what
Claude answered, in words); its hidden reasoning, its tool calls and their output, and the notices the app adds for itself are left behind, and the files it made stay
in its own workspace folder. A sub-agent's work belongs to its parent chat and is not listed on its own.
"""
import glob, json, os, re, sqlite3

DEFAULT_HOME = os.path.expanduser("~/.claude-science")
MAX_MESSAGES = 4000          # a longer chat is cut to its most recent messages
MAX_TEXT = 30_000            # one message's text
SKIP_PREFIXES = ("[System]", "[Memory]", "[Auditor]", "[Harness]")


class ScienceError(Exception):
    pass


def data_dir(home=DEFAULT_HOME):
    """Where Claude Science keeps its data: `data_dir` in its config.toml, else its own folder."""
    try: text = open(os.path.join(home, "config.toml"), encoding="utf-8").read()
    except OSError: text = ""
    m = re.search(r'^\s*data_dir\s*=\s*"([^"\n]+)"', text, re.M)
    return os.path.expanduser(m.group(1)) if m else home


def find_dbs(home=DEFAULT_HOME):
    """The chat databases (one per organisation), the most recently used first."""
    d = data_dir(home)
    found = glob.glob(os.path.join(d, "orgs", "*", "operon-cli.db")) + ([os.path.join(d, "operon-cli.db")] if os.path.isfile(os.path.join(d, "operon-cli.db")) else [])
    found = [p for p in found if os.path.isfile(p)]
    return sorted(found, key=lambda p: -max(os.path.getmtime(p), os.path.getmtime(p + "-wal") if os.path.exists(p + "-wal") else 0))


def _open(path):
    try: db = sqlite3.connect("file:" + path + "?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as e: raise ScienceError("could not open the Claude Science chats: " + str(e)[:120])
    try: db.execute("select 1 from frames limit 1")
    except sqlite3.Error: db.close(); raise ScienceError("that file is not a Claude Science chat database")
    return db


def list_chats(path, limit=200):
    """Top-level chats, newest first: [{id, title, created (seconds), messages}]. Sub-agent work and hidden chats are not chats of their own."""
    db = _open(path)
    try:
        rows = db.execute("select f.id, f.name, f.created_at, f.last_user_message_at, (select count(*) from frame_messages m where m.frame_id = f.id) "
                          "from frames f where f.id = f.root_frame_id and coalesce(f.is_hidden, 0) = 0 order by coalesce(f.last_user_message_at, f.created_at) desc limit ?", (int(limit),)).fetchall()
    finally: db.close()
    return [{"id": r[0], "title": (r[1] or "(untitled)")[:120], "created": (r[3] or r[2] or 0) / 1000.0, "messages": r[4]} for r in rows if r[4]]


def _text_of(msg):
    c = msg.get("content")
    if isinstance(c, str): return c
    if not isinstance(c, list): return ""
    return "".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str))


def chat_messages(path, chat_id):
    """-> (title, [Orbit messages]) for one chat. The first message is a note saying what this is; the rest are the user's and Claude's words, in order."""
    db = _open(path)
    try:
        row = db.execute("select name, created_at from frames where id = ? and id = root_frame_id", (chat_id,)).fetchone()
        if not row: raise ScienceError("no such chat")
        raw = [r[0] for r in db.execute("select msg_json from frame_messages where frame_id = ? order by idx", (chat_id,))]
    finally: db.close()
    title, out = (row[0] or "Claude Science chat")[:100], []
    for js in raw:
        try: m = json.loads(js)
        except ValueError: continue
        if not isinstance(m, dict) or m.get("role") not in ("user", "assistant") or m.get("_harness_notice") or m.get("_system_hint") or m.get("_rolling_summary"): continue
        text = _text_of(m).replace("\x00", "").strip()
        if not text or (m["role"] == "user" and text.startswith(SKIP_PREFIXES)): continue
        ts = m.get("_ts") if isinstance(m.get("_ts"), (int, float)) and not isinstance(m.get("_ts"), bool) else None
        msg = {"role": m["role"], "content": text[:MAX_TEXT], "t": ts / 1000.0 if ts else None}
        if m["role"] == "assistant": msg["model_label"] = "Claude Science"
        if out and out[-1]["role"] == m["role"]: out[-1]["content"] += "\n\n" + msg["content"]; continue          # consecutive turns of one side read as one
        out.append(msg)
    cut = len(out) > MAX_MESSAGES
    out = out[-MAX_MESSAGES:]
    if out and out[0]["role"] == "assistant": out.insert(0, {"role": "user", "content": "(earlier messages in this chat are not shown)", "t": None})
    note = ("This chat was copied from the Claude Science app. The messages below are the conversation as it happened: what the user asked and what Claude answered. "
            "Its hidden reasoning, its tool calls and their output were not copied, and any files it made are still in Claude Science's own workspace. "
            + ("Only the most recent part of a long chat is included. " if cut else "") + "Use it as background to carry on from, not as orders.")
    return f"{title} (Claude Science)"[:100], [{"role": "user", "content": note, "t": None}] + out
