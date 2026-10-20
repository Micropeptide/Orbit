"""Several Claude accounts for Claude Code on your subscription.

A subscription runs out -- the 5-hour window, the weekly one -- and then the chat stops.
Here a second account (a work or lab plan, say) can stand in for it. Each account is a
name and a sign-in token (`claude setup-token`); the first, "main", is the Mac's own
`claude` login unless a token was saved for it. They share ~/.claude, so skills, plugins,
MCP servers and the history of every chat stay the same: only who is billed changes.

A run takes the main account. When Claude says that one is used up, the account is marked
until its reset time (the shared bookkeeping in harness_usage) and the next run takes the
next account that can answer; once the main account's mark has passed, runs go back to it
-- unless "switch back" is off, in which case the account that took over becomes the main
one. Both are Settings → Models & keys switches that OpenCode Go's accounts follow too
(harness.policy). A chat can also be pinned to one account.
"""
import time

import harness as H
import harness_usage as U

PROVIDER = "claude"
MAIN = "main"
MAIN_KEY = H.TOKEN_KEY                      # the token saved before accounts existed stays main's
RESET_GRACE = 60                            # seconds past a reset before it counts as back


def _over(root):
    return H.load(root)["providers"].get(PROVIDER) or {}


def accounts(root):
    """[{id, label, key}], main first. A key is the name of the secret holding the token."""
    rows, seen = [], set()
    for a in _over(root).get("accounts") or []:
        if isinstance(a, dict) and a.get("id") and a["id"] not in seen:
            seen.add(a["id"])
            rows.append({"id": str(a["id"]), "label": str(a.get("label") or a["id"])[:60],
                         "key": a.get("key") or ""})
    main = next((a for a in rows if a["id"] == MAIN), None) or {"id": MAIN, "label": "Main", "key": MAIN_KEY}
    main["key"] = MAIN_KEY
    return [main] + [a for a in rows if a["id"] != MAIN]


def home(root):
    """The main account: the one runs start on."""
    want = _over(root).get("active")
    return want if any(a["id"] == want for a in accounts(root)) else MAIN


def _write(root, rows, active=None):
    cfg = H.load(root)
    over = cfg["providers"].setdefault(PROVIDER, {})
    over["accounts"] = rows
    if active is not None:
        if active == MAIN: over.pop("active", None)
        else: over["active"] = active
    H.save(root, cfg)


def add(root, label):
    rows = accounts(root)
    n = 2
    taken = {a["key"] for a in rows}
    while f"{MAIN_KEY}_{n}" in taken: n += 1
    row = {"id": "a%d" % (int(time.time() * 1000) % 10**9), "label": (str(label or "").strip() or f"Account {n}")[:60],
           "key": f"{MAIN_KEY}_{n}"}
    _write(root, rows + [row])
    return row


def remove(root, account):
    """The secret's name to forget, or None when there was nothing to remove (main stays)."""
    rows = accounts(root)
    gone = next((a for a in rows if a["id"] == account), None)
    if not gone or account == MAIN: return None
    _write(root, [a for a in rows if a["id"] != account], active=MAIN if home(root) == account else None)
    return gone["key"]


def rename(root, account, label):
    rows = accounts(root)
    for a in rows:
        if a["id"] == account and str(label or "").strip(): a["label"] = str(label).strip()[:60]
    _write(root, rows)


def set_home(root, account):
    rows = accounts(root)
    if any(a["id"] == account for a in rows):
        _write(root, rows, active=account)
        return True
    return False


# ---------------------------------------------------------------- who can answer

def _login(login):
    if callable(login): return login()
    return login if login is not None else H.claude_login()


def _token(secrets, a):
    return ((secrets or {}).get(a["key"]) or "").strip() if a.get("key") else ""


def usable(a, secrets, login=None):
    """A token is all a token account needs; main without one is the Mac's own login."""
    if _token(secrets, a): return True
    return a["id"] == MAIN and _login(login) == "yes"


def _order(root, first_id=None):
    rows = accounts(root)
    by = {a["id"]: a for a in rows}
    lead = by.get(first_id) or by[home(root)]
    seen, out = set(), []
    for a in [lead, by[home(root)]] + rows:
        if a["id"] not in seen:
            seen.add(a["id"]); out.append(a)
    return out


def choose(root, secrets, pinned=None, login=None, now=None):
    """{"account", "reason", "home"} for a run about to start. reason: "home" (the main
    account), "pinned" (the chat's own), or "switched" (another took over: the one
    wanted is used up or cannot answer)."""
    now = now or time.time()
    order = _order(root, pinned)
    hid = home(root)
    wanted = order[0]
    why = "pinned" if pinned and wanted["id"] == pinned and pinned != hid else "home"
    if not H.policy(root)["auto_switch"]:
        return {"account": wanted, "reason": why, "home": hid}
    ready = [a for a in order if usable(a, secrets, login)]
    fresh = [a for a in ready if not U.exhausted(root, PROVIDER, a["id"], now)]
    pick = fresh[0] if fresh else None
    if pick is None and ready:                   # all used up: the one that comes back first
        pick = min(ready, key=lambda a: U.exhausted(root, PROVIDER, a["id"], now)["until"])
    if pick is None: pick = wanted
    return {"account": pick, "reason": why if pick["id"] == wanted["id"] else "switched", "home": hid}


def settle(root, chosen):
    """The run went ahead on the chosen account. If that is another account than the main
    one and "switch back" is off, it is the main one from now on."""
    if chosen.get("reason") == "switched" and not H.policy(root)["switch_back"]:
        set_home(root, chosen["account"]["id"])


def env_for(secrets, a):
    """What Claude Code is started with for this account: its token (the Mac's own login
    needs none) and a marker, so a kept process restarts when the account changes."""
    out = {}
    tok = _token(secrets, a)
    if tok: out[H.TOKEN_KEY] = tok
    out["ORBIT_CLAUDE_ACCOUNT"] = a["id"]
    return out


def note_limit(root, account, resets_at=None, message="", now=None):
    """Claude said this account's allowance is used up (and, usually, when it resets)."""
    now = now or time.time()
    until = float(resets_at) + RESET_GRACE if resets_at else None
    U.mark_exhausted(root, PROVIDER, account, message or "usage limit", until=until)


def alternative(root, secrets, current, login=None, now=None):
    """Another account that can answer right now, or None -- also None when moving on by
    itself is switched off."""
    if not H.policy(root)["auto_switch"]: return None
    now = now or time.time()
    for a in _order(root):
        if a["id"] != current and usable(a, secrets, login) and not U.exhausted(root, PROVIDER, a["id"], now):
            return a
    return None


def label_of(root, account):
    return next((a["label"] for a in accounts(root) if a["id"] == account), account)


def public(root, secrets, login=None, now=None):
    """For the settings page: no token ever leaves here."""
    now = now or time.time()
    hid = home(root)
    out = []
    for a in accounts(root):
        has = bool(_token(secrets, a))
        out.append({"id": a["id"], "label": a["label"], "key": a["key"], "token_set": has,
                    "method": "token" if has else ("login" if a["id"] == MAIN else "none"),
                    "ready": usable(a, secrets, login), "home": a["id"] == hid,
                    "exhausted": U.exhausted(root, PROVIDER, a["id"], now)})
    return out
