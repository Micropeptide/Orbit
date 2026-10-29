"""Shared projects: members, tokens, invites, grants, and the tamper-evident event log. See docs/collab/DESIGN.md and PROTOCOL.md.

The host is the only writer. A client sends an *intent*; the store checks who sent it (a member token), what that member may do (their
grant), the shape and size of what they sent, and then appends an event whose author, order and time the store sets itself. Events are
chained by hash, so editing, removing or reordering a line of the file is found by `verify`.

Everything that reaches the world (the clock) is passed in. Raw text is stored as written (minus NUL) and escaped when drawn: nothing
here ever interprets a message.
"""
import collections, hashlib, hmac, json, os, re, secrets, threading, time, unicodedata

import collab_policy as P
import collab_guard as G

PROTO = 1
MAX_TEXT = 100_000
MAX_IMPORT = 2000
APPROVAL_TTL_S = 900
MAX_IMPORT_CHARS = 2_000_000
MAX_INTENT_BYTES = 200_000
RATE_PER_MIN = 30
DEFAULT_CHAT = "main"
MAX_CHATS = 60
INTENT_TYPES = ("msg", "edit", "delete", "react", "queue_withdraw", "note", "decision_pin", "task", "approval")
SYSTEM_TYPES = ("project", "chat", "chat_removed", "approval_request", "join", "leave", "grant", "revoke", "role", "member_state", "model_turn_start", "model_turn_end",
                "tool_request", "guard_decision", "tool_result", "queue_add", "panic", "config", "turn_changes", "turn_undone", "file_upload", "file_edit")
ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
CHAT_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
PID_RE = re.compile(r"^p_[0-9a-f]{12}$")
GENESIS = "0" * 64
STATUS = {"bad_input": 400, "unauthorized": 401, "forbidden": 403, "not_a_member": 403, "not_found": 404, "conflict": 409, "too_large": 413, "rate_limited": 429}


class CollabError(Exception):
    def __init__(self, code, message):
        super().__init__(message); self.code, self.status = code, STATUS.get(code, 400)


def _sha(s):
    return hashlib.sha256(s.encode("utf-8") if isinstance(s, str) else s).hexdigest()


def _canon(d):
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _clean_name(s, n, what="name"):
    if not isinstance(s, str): raise CollabError("bad_input", f"{what} must be text")
    # control characters become spaces; invisible and direction-changing ones (zero-width, bidi overrides) are dropped: a name must not be able to
    # reorder or hide the text around it
    s = "".join(" " if unicodedata.category(c) in ("Cc", "Zl", "Zp") else "" if unicodedata.category(c) in ("Cf", "Co", "Cs") else c for c in s)
    s = re.sub(r"\s+", " ", s).strip()[:n].strip()
    if not s: raise CollabError("bad_input", f"{what} is empty")
    return s


def _clean_account(a):
    if a is None: return None
    if not isinstance(a, dict) or not all(isinstance(a.get(k), str) and 0 < len(a[k]) <= 100 for k in ("provider", "sub")):
        raise CollabError("bad_input", "an account link needs a provider and a subject")
    return {"provider": a["provider"], "sub": a["sub"]}


def _same_account(a, b):
    """Are two account links the same person? Constant-time on the id, so a guess at someone's id leaks nothing through timing."""
    if not (isinstance(a, dict) and isinstance(b, dict)): return False
    same = lambda x, y: hmac.compare_digest(str(x).encode("utf-8", "replace"), str(y).encode("utf-8", "replace"))
    return bool(same(a.get("provider"), b.get("provider")) & same(a.get("sub"), b.get("sub")))        # both comparisons always run


def _write(path, obj):
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f: json.dump(obj, f, indent=1, sort_keys=True)
    os.replace(tmp, path)


def _read(path, default):
    try: return json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError): return default


def _same_grant(a, b):
    ka = {k: (sorted(v) if isinstance(v, list) else v) for k, v in a.items() if k != "role"}
    kb = {k: (sorted(v) if isinstance(v, list) else v) for k, v in b.items() if k != "role"}
    return ka == kb


class _Project:
    """One project in memory: its files, its events, and the lock around them."""

    def __init__(self, path):
        self.path, self.lock = path, threading.RLock()
        self.meta = _read(os.path.join(path, "project.json"), {})
        self.members = _read(os.path.join(path, "members.json"), {})
        self.grants = _read(os.path.join(path, "grants.json"), {})
        self.invites = _read(os.path.join(path, "invites.json"), {})
        self.events, self.by_id, self.iids, self.deleted = [], {}, {}, set()
        self.requests = {}                               # approval request id -> {chat, by, ts, closed}
        self.seen = {}                                   # chat -> the last seq the model was shown
        self.rates = collections.defaultdict(collections.deque)
        self.devs = {}                                   # token hash -> (member id, device id)
        self._load_events()
        self._index_devices()

    def _load_events(self):
        try: lines = open(os.path.join(self.path, "events.jsonl"), encoding="utf-8").read().splitlines()
        except OSError: lines = []
        for ln in lines:
            try: e = json.loads(ln)
            except ValueError: continue
            self._index(e)
        self.seen = _read(os.path.join(self.path, "seen.json"), {})

    def _index(self, e):
        self.events.append(e); self.by_id[e["id"]] = e
        if e.get("iid"): self.iids[(e["author"], e["iid"])] = (e["seq"], e.get("ihash"))
        if e["type"] == "delete": self.deleted.add((e.get("payload") or {}).get("target"))
        if e["type"] == "approval_request":
            pl = e.get("payload") or {}
            self.requests[pl.get("request")] = {"chat": e["chat"], "by": pl.get("requested_by"), "ts": e["ts"], "closed": False, "need": int(pl.get("need") or 1), "allows": []}
        if e["type"] == "approval" and (e.get("payload") or {}).get("request") in self.requests:
            r, pl = self.requests[e["payload"]["request"]], e["payload"]
            if pl.get("final", True): r["closed"] = True
            elif pl.get("approver") not in r["allows"]: r["allows"].append(pl.get("approver"))

    def _index_devices(self):
        self.devs = {}
        for mid, m in self.members.items():
            if m["state"] in ("active", "muted"):
                for d in m["devices"]: self.devs[d["hash"]] = (mid, d["id"])

    def save(self, which):
        _write(os.path.join(self.path, which + ".json"), getattr(self, "meta" if which == "project" else which))


class Store:
    def __init__(self, root, policy=None, now=time.time):
        self.root, self.policy, self.now = root, policy or P.Policy(), now
        os.makedirs(root, mode=0o700, exist_ok=True)
        self.lock = threading.RLock()
        self.cache = {}
        self.listeners = []              # called with (project id, event) after each event is written; they must be quick and must not raise

    # ------------------------------------------------------------------------------------------------ projects
    def _proj(self, pid):
        if not isinstance(pid, str) or not PID_RE.match(pid): raise CollabError("not_found", "no such project")
        with self.lock:
            if pid not in self.cache:
                path = os.path.join(self.root, pid)
                if not os.path.isdir(path): raise CollabError("not_found", "no such project")
                self.cache[pid] = _Project(path)
            return self.cache[pid]

    def create_project(self, name, owner_name, working_dir, account=None):
        name = _clean_name(name, 80, "project name"); owner_name = _clean_name(owner_name, 40, "your name"); account = _clean_account(account)
        if not isinstance(working_dir, str) or not os.path.isabs(os.path.expanduser(working_dir)): raise CollabError("bad_input", "the working folder must be an absolute path")
        wd = os.path.realpath(os.path.expanduser(working_dir))
        if not os.path.isdir(wd) or wd == os.sep or wd == self.policy.home: raise CollabError("bad_input", "the working folder must be an existing folder (not the home folder or the disk root)")
        pid = "p_" + secrets.token_hex(6)
        path = os.path.join(self.root, pid); os.makedirs(path, mode=0o700)
        mid = "m_" + secrets.token_hex(5); tok = secrets.token_urlsafe(32); did = "d_" + secrets.token_hex(4)
        now = self.now()
        p = _Project(path)
        p.meta = {"id": pid, "name": name, "working_dir": wd, "owner": mid, "created": now, "proto": PROTO, "frozen": False, "turn_mode": "free", "allow_export": True, "guard": G.clean_config({}), "two_person": [],
                  "chats": {DEFAULT_CHAT: {"name": "Main", "visibility": {"mode": "all"}}}}
        p.members = {mid: {"id": mid, "name": owner_name, "role": "owner", "state": "active", "joined": now, "account": account,
                           "devices": [{"id": did, "name": "this computer", "hash": _sha(tok), "created": now}]}}
        p.grants = {mid: P.normalize(P.template("owner", project=wd), policy=self.policy)}
        p.invites = {}
        for w in ("project", "members", "grants", "invites"): p.save(w)
        p._index_devices()
        with p.lock: self._append(p, "project", mid, {"name": name}, device=did)
        self.cache[pid] = p
        return {"project": {"id": pid, "name": name}, "member": {"id": mid, "name": owner_name}, "token": tok}

    def projects_for(self, token):
        """The projects a token is a member of: [{id, name, member}]. Looks only at what is on disk under the store's own folder."""
        out = []
        try: names = sorted(os.listdir(self.root))
        except OSError: names = []
        for pid in names:
            if not PID_RE.match(pid): continue
            who = self.authenticate(pid, token)
            if who: out.append({"id": pid, "name": self._proj(pid).meta["name"], "member": who["id"]})
        return out

    def all_projects(self):
        """Every project on this host, for the host's own window (never served to members)."""
        out = []
        try: names = sorted(os.listdir(self.root))
        except OSError: names = []
        for pid in names:
            if not PID_RE.match(pid): continue
            try: p = self._proj(pid)
            except CollabError: continue
            out.append({"id": pid, "name": p.meta["name"], "working_dir": p.meta["working_dir"], "owner": p.meta["owner"],
                        "members": len([m for m in p.members.values() if m["state"] != "removed"]), "frozen": p.meta["frozen"], "created": p.meta["created"],
                        "allow_export": p.meta.get("allow_export", True)})
        return out

    def project_view_admin(self, pid):
        """Facts about a project for the host's window: who owns it and where it works."""
        p = self._proj(pid)
        return {"id": pid, "name": p.meta["name"], "owner": p.meta["owner"], "working_dir": p.meta["working_dir"], "frozen": p.meta["frozen"]}

    def project_view(self, pid, member):
        p = self._proj(pid); m = self._active(p, member)
        return {"id": pid, "name": p.meta["name"], "working_dir": p.meta["working_dir"], "proto": PROTO, "frozen": p.meta["frozen"],
                "turn_mode": p.meta["turn_mode"], "owner": p.meta["owner"], "me": member, "allow_export": p.meta.get("allow_export", True), "guard": p.meta.get("guard") or G.clean_config({}), "two_person": list(p.meta.get("two_person") or []),
                "members": [{"id": x["id"], "name": x["name"], "role": x["role"], "state": x["state"], "summary": P.summary(self.grant_of(pid, x["id"]))}
                            for x in p.members.values() if x["state"] != "removed"],
                "my_summary": P.summary(self.grant_of(pid, member)),
                "chats": [dict({"id": cid, "name": c["name"]}, **({"imported": c["imported"]["count"]} if c.get("imported") else {})) for cid, c in p.meta["chats"].items() if self._chat_visible(p, cid, member)],
                "my_grant": self.grant_of(pid, member)}

    # ------------------------------------------------------------------------------------------------ people
    def _active(self, p, member, write=False):
        m = p.members.get(member) if isinstance(member, str) else None
        if not m or m["state"] == "removed": raise CollabError("unauthorized", "you are not a member of this project")
        if write and m["state"] != "active": raise CollabError("forbidden", "you are muted in this project")
        return m

    def authenticate(self, pid, token):
        try: p = self._proj(pid)
        except CollabError: return None
        if not isinstance(token, str) or not token or len(token) > 200: return None
        h = _sha(token)
        for known, (mid, did) in p.devs.items():
            if hmac.compare_digest(known, h):
                m = p.members.get(mid)
                if m and m["state"] in ("active", "muted"): return {"id": mid, "name": m["name"], "device": did, "state": m["state"]}
        return None

    def _need(self, p, member, flag, why):
        self._active(p, member, write=True)
        if not self.grant_of(p.meta["id"], member).get(flag): raise CollabError("forbidden", why)

    def add_device(self, pid, token, name):
        p = self._proj(pid); who = self.authenticate(pid, token)
        if not who: raise CollabError("unauthorized", "invalid token")
        with p.lock:
            tok, did = secrets.token_urlsafe(32), "d_" + secrets.token_hex(4)
            p.members[who["id"]]["devices"].append({"id": did, "name": _clean_name(name, 40, "device name"), "hash": _sha(tok), "created": self.now()})
            p.save("members"); p._index_devices()
        return {"device": did, "token": tok}

    def add_device_for(self, pid, member, name):
        """A new device for a member, made by the host itself (the host's own window opening the page as the owner)."""
        p = self._proj(pid); m = self._active(p, member)
        with p.lock:
            tok, did = secrets.token_urlsafe(32), "d_" + secrets.token_hex(4)
            m["devices"].append({"id": did, "name": _clean_name(name, 40, "device name"), "hash": _sha(tok), "created": self.now()})
            p.save("members"); p._index_devices()
        return {"device": did, "token": tok}

    def revoke_device(self, pid, token, device):
        p = self._proj(pid); who = self.authenticate(pid, token)
        if not who: raise CollabError("unauthorized", "invalid token")
        with p.lock:
            m = p.members[who["id"]]; m["devices"] = [d for d in m["devices"] if d["id"] != device]
            p.save("members"); p._index_devices()

    def remove_member(self, pid, actor, member):
        p = self._proj(pid)
        with p.lock:
            self._need_moderator(p, actor)
            m = p.members.get(member)
            if not m or m["state"] == "removed": raise CollabError("not_found", "no such member")
            if member == p.meta["owner"]: raise CollabError("forbidden", "the owner cannot be removed")
            m["state"], m["devices"] = "removed", []
            for inv in p.invites.values():                          # what they could still invite, they no longer can
                if inv["created_by"] == member: inv["revoked"] = True
            p.save("members"); p.save("invites"); p._index_devices()
            self._append(p, "leave", actor, {"member": member, "by": actor, "removed": True})

    def set_member_state(self, pid, actor, member, state):
        p = self._proj(pid)
        with p.lock:
            self._need_moderator(p, actor)
            m = p.members.get(member)
            if state not in ("active", "muted") or not m or m["state"] == "removed": raise CollabError("bad_input", "cannot set that state")
            if member == p.meta["owner"]: raise CollabError("forbidden", "the owner cannot be muted")
            m["state"] = state; p.save("members"); p._index_devices()
            self._append(p, "member_state", actor, {"member": member, "state": state, "by": actor})

    def _need_moderator(self, p, actor):
        self._active(p, actor, write=True)
        if p.meta["frozen"]: raise CollabError("forbidden", "the project is frozen")
        if not self.grant_of(p.meta["id"], actor)["can_change_grants"]: raise CollabError("forbidden", "you cannot change members or grants here")

    # ------------------------------------------------------------------------------------------------ grants
    def grant_of(self, pid, member):
        p = self._proj(pid)
        g = p.grants.get(member)
        return dict(g) if g else P.normalize({}, policy=self.policy)

    def effective_grant(self, pid, members):
        p = self._proj(pid)
        gs = []
        for mid in members:
            m = p.members.get(mid)
            gs.append(self.grant_of(pid, mid) if m and m["state"] == "active" else P.normalize({}, policy=self.policy))
        return P.effective(gs, policy=self.policy)

    def _norm(self, g):
        try: return P.normalize(g, policy=self.policy)
        except ValueError as e: raise CollabError("bad_input", str(e))

    def set_grant(self, pid, actor, member, grant):
        p = self._proj(pid)
        with p.lock:
            self._need_moderator(p, actor)
            if member not in p.members or p.members[member]["state"] == "removed": raise CollabError("not_found", "no such member")
            if member == p.meta["owner"]: raise CollabError("forbidden", "the owner's grant cannot be changed")
            new, mine = self._norm(grant), self.grant_of(pid, actor)
            if not _same_grant(P.intersect(new, mine), new): raise CollabError("forbidden", "you cannot give more than you have")
            if member == actor and not _same_grant(P.intersect(new, self.grant_of(pid, actor)), new): raise CollabError("forbidden", "nobody promotes themselves")
            p.grants[member] = new; p.save("grants")
            self._append(p, "grant", actor, {"member": member, "grant": new, "set_by": actor})

    # ------------------------------------------------------------------------------------------------ invites
    def create_invite(self, pid, actor, grant, expires_in=None, uses=1, account_required=False, for_account=None):
        """`for_account` (an Orbit account id) addresses the invitation to ONE account: only that account can use it, with or without the link's secret, once.
        It implies `account_required` and a single use; the other settings (role, expiry) apply as for any invitation."""
        p = self._proj(pid)
        for_account = _clean_account({"provider": "orbit", "sub": for_account}) if for_account is not None else None
        if for_account: account_required, uses = True, 1
        with p.lock:
            self._need(p, actor, "can_add_members", "you cannot add members here")
            if p.meta["frozen"]: raise CollabError("forbidden", "the project is frozen")
            g, mine = self._norm(grant), self.grant_of(pid, actor)
            if not _same_grant(P.intersect(g, mine), g): raise CollabError("forbidden", "you cannot invite someone with more power than you have")
            iid, secret = "i_" + secrets.token_hex(5), secrets.token_urlsafe(24)
            p.invites[iid] = {"id": iid, "hash": _sha(secret), "grant": g, "created_by": actor, "created": self.now(),
                              "expires_at": self.now() + float(expires_in) if expires_in else None, "uses_left": int(uses) if uses else None, "revoked": False,
                              "account_required": bool(account_required), "for_account": for_account}
            p.save("invites")
        return {"id": iid, "secret": secret, "role": g["role"]}

    def revoke_invite(self, pid, actor, iid):
        p = self._proj(pid)
        with p.lock:
            self._need(p, actor, "can_add_members", "you cannot manage invites here")
            if iid not in p.invites: raise CollabError("not_found", "no such invite")
            p.invites[iid]["revoked"] = True; p.save("invites")

    def list_invites(self, pid, actor):
        p = self._proj(pid)
        self._need(p, actor, "can_add_members", "you cannot see invites here")
        return [{"id": i["id"], "created_by": i["created_by"], "created": i["created"], "expires_at": i["expires_at"], "uses_left": i["uses_left"],
                 "revoked": i["revoked"], "role": i["grant"]["role"], "account_required": bool(i.get("account_required")),
                 "for_account": (i.get("for_account") or {}).get("sub")} for i in p.invites.values()]

    def join(self, pid, invite_id, secret, name="Guest", account=None):
        bad = CollabError("unauthorized", "that invite does not work")
        try: p = self._proj(pid)
        except CollabError: raise bad
        if not isinstance(invite_id, str) or not isinstance(secret, str) or not secret: raise bad
        name = _clean_name(name or "Guest", 40, "name"); account = _clean_account(account)
        with p.lock:
            inv = p.invites.get(invite_id)
            ok = inv is not None and hmac.compare_digest(inv["hash"], _sha(secret))
            if not ok or inv["revoked"] or (inv["expires_at"] and self.now() > inv["expires_at"]) or p.meta["frozen"]: raise bad
            again = account and next((m for m in p.members.values() if m["state"] in ("active", "muted") and m.get("account") == account), None)
            if inv["uses_left"] == 0 and not again: raise bad       # a used-up invitation makes no new member; a member of this project with this account can still come back on a new device
            if inv.get("account_required") and not account:
                raise CollabError("forbidden", "this invite is for people signed in with an Orbit account: sign in, then open the link again")
            if inv.get("for_account") and not _same_account(account, inv["for_account"]):
                raise CollabError("forbidden", "this invitation was made for a different Orbit account: sign in with the account it was made for")
            if again:                                       # already a member under this account (even a muted one): a new device, not a second member, and the invite is not used up
                tok, did = secrets.token_urlsafe(32), "d_" + secrets.token_hex(4)
                again["devices"].append({"id": did, "name": "another device", "hash": _sha(tok), "created": self.now()}); p.save("members"); p._index_devices()
                return {"member": {"id": again["id"], "name": again["name"]}, "token": tok}
            return self._admit(p, inv, name, account)

    def _admit(self, p, inv, name, account):
        """Make a new member from an invitation that has been checked (the caller holds the project's lock)."""
        if inv["uses_left"] is not None: inv["uses_left"] -= 1
        mid, tok, did = "m_" + secrets.token_hex(5), secrets.token_urlsafe(32), "d_" + secrets.token_hex(4)
        p.members[mid] = {"id": mid, "name": name, "role": inv["grant"]["role"], "state": "active", "joined": self.now(), "account": account,
                          "devices": [{"id": did, "name": "first device", "hash": _sha(tok), "created": self.now()}]}
        p.grants[mid] = dict(inv["grant"])
        for w in ("members", "grants", "invites"): p.save(w)
        p._index_devices()
        self._append(p, "join", mid, {"name": name, "role": inv["grant"]["role"], "invite": inv["id"]}, device=did)
        return {"member": {"id": mid, "name": name}, "token": tok}

    def sign_in(self, pid, account, name=None):
        """A member who joined with an Orbit account gets a new device token by proving the account again (no invite needed). The account has been checked by the caller.
        An account that is not yet a member but has an open invitation ADDRESSED to it (`create_invite(for_account=)`) becomes a member the same way: the invitation is the
        host's yes, the proof is the person's, and the link's secret is not needed."""
        bad = CollabError("not_a_member", "that Orbit account is not a member of this project, and no invitation is waiting for it")
        account = _clean_account(account)
        try: p = self._proj(pid)
        except CollabError: raise bad
        if not account: raise bad
        with p.lock:
            m = next((m for m in p.members.values() if m["state"] in ("active", "muted") and m.get("account") == account), None)
            if m is None:
                now = self.now()
                waiting = [i for i in p.invites.values() if i.get("for_account") and _same_account(account, i["for_account"]) and not i["revoked"] and i["uses_left"] != 0
                           and not (i["expires_at"] and now > i["expires_at"])]
                if not waiting or p.meta["frozen"]: raise bad
                inv = max(waiting, key=lambda i: i["created"])
                try: nm = _clean_name(name or "Guest", 40, "name")
                except CollabError: nm = "Guest"
                return self._admit(p, inv, nm, account)
            tok, did = secrets.token_urlsafe(32), "d_" + secrets.token_hex(4)
            m["devices"].append({"id": did, "name": "signed in with account", "hash": _sha(tok), "created": self.now()}); p.save("members"); p._index_devices()
        return {"member": {"id": m["id"], "name": m["name"]}, "token": tok}

    # ------------------------------------------------------------------------------------------------ chats
    def _chat_visible(self, p, chat, member):
        c = p.meta["chats"].get(chat)
        if c is None or c.get("removed"): return False
        v = c.get("visibility") or {"mode": "all"}
        return v["mode"] == "all" or member in v.get("members", [])

    def create_chat(self, pid, actor, chat_id, name=None, visibility=None):
        p = self._proj(pid)
        with p.lock:
            self._need(p, actor, "can_post", "you cannot start chats here")
            if not isinstance(chat_id, str) or not CHAT_RE.match(chat_id): raise CollabError("bad_input", "a chat id is letters, digits, - and _")
            if chat_id in p.meta["chats"]: raise CollabError("conflict", "that chat exists")
            if len(p.meta["chats"]) >= MAX_CHATS: raise CollabError("too_large", f"a project has at most {MAX_CHATS} chats")
            if visibility is not None and not isinstance(visibility, dict): raise CollabError("bad_input", "visibility must be all or members")
            v = visibility or {"mode": "all"}
            if v.get("mode") == "members":
                ms = list(dict.fromkeys(list(v.get("members") or []) + [actor]))
                if len(ms) < 1 or not v.get("members") or any(x not in p.members or p.members[x]["state"] == "removed" for x in ms):
                    raise CollabError("bad_input", "a private chat needs real members")
                v = {"mode": "members", "members": ms}
            elif v.get("mode") != "all": raise CollabError("bad_input", "visibility must be all or members")
            p.meta["chats"][chat_id] = {"name": _clean_name(name or chat_id, 60, "chat name"), "visibility": v}
            p.save("project")
            self._append(p, "chat", actor, {"id": chat_id, "name": p.meta["chats"][chat_id]["name"]}, chat=chat_id)

    def import_chat(self, pid, actor, chat_id, name, messages, source=None):
        """Share a local chat into the project as a NEW chat, a copy: its user and assistant text, marked imported. Tool calls and their output are
        never part of it (they can hold file contents and secrets), and the local chat is untouched. Only the owner of the Mac it came from may."""
        p = self._proj(pid)
        with p.lock:
            self._active(p, actor, write=True)
            if actor != p.meta["owner"]: raise CollabError("forbidden", "only the owner can share a chat from this Mac")
            if not isinstance(chat_id, str) or not CHAT_RE.match(chat_id): raise CollabError("bad_input", "a chat id is letters, digits, - and _")
            if chat_id in p.meta["chats"]: raise CollabError("conflict", "that chat exists")
            if not isinstance(messages, list) or len(messages) > MAX_IMPORT: raise CollabError("bad_input", f"a chat to share has at most {MAX_IMPORT} messages")
            clean, total = [], 0
            for m in messages:
                if not isinstance(m, dict) or m.get("role") not in ("user", "assistant") or not isinstance(m.get("text"), str): raise CollabError("bad_input", "each message needs a role (user or assistant) and text")
                t = m["text"].replace("\x00", "").strip()
                if not t: continue
                total += len(t)
                if len(t) > MAX_TEXT or total > MAX_IMPORT_CHARS: raise CollabError("too_large", "that chat is too large to share")
                clean.append({"role": m["role"], "text": t, "ts": m.get("ts") if isinstance(m.get("ts"), (int, float)) else None,
                              "label": str(m.get("label"))[:60] if m.get("label") else None})
            title = _clean_name((source or {}).get("title") or name or chat_id, 80, "chat title") if (source or {}).get("title") or name else chat_id
            p.meta["chats"][chat_id] = {"name": _clean_name(name or title, 60, "chat name"), "visibility": {"mode": "all"}, "imported": {"count": len(clean), "at": self.now(), "title": title}}
            p.save("project")
            self._append(p, "chat", actor, {"id": chat_id, "name": p.meta["chats"][chat_id]["name"], "imported": len(clean)}, chat=chat_id)
            for m in clean:
                payload = {"text": m["text"][:MAX_TEXT], "imported": True}
                if m["ts"] is not None: payload["orig_ts"] = m["ts"]
                if m["role"] == "assistant":
                    if m["label"]: payload["model_label"] = m["label"]
                    self._append(p, "msg", "model:imported", payload, chat=chat_id)
                else: self._append(p, "msg", actor, payload, chat=chat_id)
        return {"chat": chat_id, "messages": len(clean)}

    def remove_chat(self, pid, actor, chat_id):
        """Take a chat out of the project: nobody can read or write it any more. The project's record keeps its lines (the chain must stay valid), but they
        are never served, exported or searched again."""
        p = self._proj(pid)
        with p.lock:
            self._need_moderator(p, actor)
            c = p.meta["chats"].get(chat_id) if isinstance(chat_id, str) else None
            if chat_id == DEFAULT_CHAT: raise CollabError("forbidden", "the main chat stays")
            if not c or c.get("removed"): raise CollabError("not_found", "no such chat")
            c["removed"], c["removed_at"] = True, self.now()
            p.save("project")
            self._append(p, "chat_removed", actor, {"id": chat_id, "name": c["name"], "by": actor})
        return {"ok": True}

    def set_allow_export(self, pid, actor, value):
        """Whether members may save a copy of a chat. The owner always may. (It cannot stop a screenshot; it stops the convenient copy.)"""
        p = self._proj(pid)
        with p.lock:
            self._need_moderator(p, actor)
            p.meta["allow_export"] = bool(value); p.save("project")
            self._append(p, "config", actor, {"allow_export": bool(value), "by": actor})

    def rename_project(self, pid, actor, name):
        """The project's name, for everyone. Owner only; the record says who changed it and from what."""
        name = _clean_name(name, 80, "project name"); p = self._proj(pid)
        with p.lock:
            self._active(p, actor, write=True)
            if actor != p.meta["owner"]: raise CollabError("forbidden", "only the owner renames the project")
            old = p.meta["name"]; p.meta["name"] = name; p.save("project")
            self._append(p, "config", actor, {"name": name, "was": old, "by": actor})
        return name

    TWO_PERSON_FLAGS = ("delete", "git_push", "install", "network", "run_code")

    def set_two_person(self, pid, actor, flags):
        """Which kinds of risky action need TWO different approvers. Owner only."""
        p = self._proj(pid)
        with p.lock:
            self._active(p, actor, write=True)
            if actor != p.meta["owner"]: raise CollabError("forbidden", "only the owner decides what needs two approvers")
            if not isinstance(flags, (list, tuple)) or any(f not in self.TWO_PERSON_FLAGS for f in flags): raise CollabError("bad_input", "choose from: " + ", ".join(self.TWO_PERSON_FLAGS))
            p.meta["two_person"] = [f for f in self.TWO_PERSON_FLAGS if f in flags]; p.save("project")
            self._append(p, "config", actor, {"two_person": p.meta["two_person"], "by": actor})
        return list(p.meta["two_person"])

    TURN_MODES = ("free", "round_robin", "approve_each")

    def set_turn_mode(self, pid, actor, mode):
        """How questions to a model are taken up: first come first served, one member's turn after another's, or each one waiting for an approver's yes. Owner only."""
        p = self._proj(pid)
        with p.lock:
            self._active(p, actor, write=True)
            if actor != p.meta["owner"]: raise CollabError("forbidden", "only the owner decides how turns are taken")
            if mode not in self.TURN_MODES: raise CollabError("bad_input", "choose from: " + ", ".join(self.TURN_MODES))
            p.meta["turn_mode"] = mode; p.save("project")
            self._append(p, "config", actor, {"turn_mode": mode, "by": actor})
        return mode

    def turn_mode(self, pid):
        m = self._proj(pid).meta.get("turn_mode")
        return m if m in self.TURN_MODES else "free"

    def turns_started(self, pid, member, since):
        """How many model turns this member started since a time (for the per-hour and per-day limits in a grant's budget)."""
        p, n = self._proj(pid), 0
        with p.lock:
            for e in reversed(p.events):
                if e["ts"] < since: break
                if e["type"] == "model_turn_start" and member in ((e["payload"] or {}).get("initiated_by") or []): n += 1
        return n

    def two_person_for(self, pid, flags):
        return 2 if set(flags or ()) & set(self._proj(pid).meta.get("two_person") or ()) else 1

    def guard_config(self, pid):
        return dict(self._proj(pid).meta.get("guard") or G.clean_config({}))

    def set_guard(self, pid, actor, cfg):
        """The guard's model and the owner's own instructions. Only the owner: a moderator must not be able to loosen the owner's words."""
        p = self._proj(pid)
        with p.lock:
            self._active(p, actor, write=True)
            if actor != p.meta["owner"]: raise CollabError("forbidden", "only the owner sets the guard")
            try: c = G.clean_config(cfg)
            except ValueError as e: raise CollabError("bad_input", str(e))
            p.meta["guard"] = c; p.save("project")
            self._append(p, "config", actor, {"guard": c, "by": actor})
        return c

    def export_events(self, pid, member, chat):
        """One chat's events for saving a copy: only a chat this member may read, and only when the owner allows members to save copies."""
        p = self._proj(pid); self._active(p, member)
        if member != p.meta["owner"] and not p.meta.get("allow_export", True): raise CollabError("forbidden", "the owner has turned off saving copies of chats here")
        if chat not in p.meta["chats"] or not self._chat_visible(p, chat, member): raise CollabError("not_found", "no such chat")
        with p.lock: return [self._view(p, e, member) for e in p.events if e["chat"] == chat]

    def chat_active(self, pid, chat):
        c = self._proj(pid).meta["chats"].get(chat)
        return bool(c and not c.get("removed"))

    # ------------------------------------------------------------------------------------------------ events
    def _append(self, p, etype, author, payload, chat=None, device=None, iid=None, ihash=None):
        with p.lock:
            prev = p.events[-1]["hash"] if p.events else GENESIS
            e = {"seq": len(p.events) + 1, "id": "e_" + secrets.token_hex(8), "ts": self.now(), "type": etype, "author": author,
                 "device": device, "chat": chat, "payload": payload, "iid": iid, "ihash": ihash, "prev": prev}
            e["hash"] = _sha(_canon(e))
            fd = os.open(os.path.join(p.path, "events.jsonl"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as f: f.write(_canon(e) + "\n"); f.flush(); os.fsync(f.fileno())
            p._index(e)
            for fn in list(self.listeners):
                try: fn(p.meta["id"], e)
                except Exception: pass
            return e

    def add_listener(self, fn): self.listeners.append(fn)

    def chat_events(self, pid, chat, upto_seq=None):
        """One chat's events, for the host's own turn engine (never served to a member: the engine only asks for the chat its asker is in)."""
        p = self._proj(pid)
        with p.lock: return [self._view(p, e) for e in p.events if e["chat"] == chat and (upto_seq is None or e["seq"] <= upto_seq)]

    def member_state(self, pid, member):
        """'active', 'muted', 'removed' or None."""
        m = self._proj(pid).members.get(member) if isinstance(member, str) else None
        return m["state"] if m else None

    def member_role(self, pid, member):
        m = self._proj(pid).members.get(member) if isinstance(member, str) else None
        return m["role"] if m else None

    def member_names(self, pid):
        return {mid: m["name"] for mid, m in self._proj(pid).members.items()}

    def append_model_message(self, pid, chat, handle, text, extra=None):
        """What a model says in a chat: an ordinary message whose author is the model, set by the host only (a member cannot post as one)."""
        if not isinstance(handle, str) or not re.match(r"^[A-Za-z][A-Za-z0-9_-]{0,29}$", handle): raise CollabError("bad_input", "bad model name")
        p = self._proj(pid)
        if chat not in p.meta["chats"]: raise CollabError("not_found", "no such chat")
        payload = dict(extra or {}); payload["text"] = str(text).replace("\x00", "")[:MAX_TEXT]
        return self._append(p, "msg", "model:" + handle, payload, chat=chat)

    def append_system(self, pid, etype, payload, author="system", chat=None):
        """For the host's own parts (the turn engine, the guard): an event the members cannot post themselves."""
        if etype not in SYSTEM_TYPES: raise CollabError("bad_input", "not a system event")
        p = self._proj(pid)
        return self._append(p, etype, author, payload if isinstance(payload, dict) else {}, chat=chat)

    def mark_model_seen(self, pid, chat, upto):
        p = self._proj(pid)
        with p.lock:
            p.seen[chat] = max(int(upto), p.seen.get(chat, 0)); _write(os.path.join(p.path, "seen.json"), p.seen)

    def read(self, pid, member, after=0, limit=200):
        p = self._proj(pid); self._active(p, member)
        out = []
        try: after = int(after)
        except (TypeError, ValueError): after = 0
        try: limit = max(1, min(int(limit or 200), 10_000))
        except (TypeError, ValueError): limit = 200
        with p.lock:
            for e in p.events[max(after, 0):]:
                if e["chat"] is not None and not self._chat_visible(p, e["chat"], member): continue
                out.append(self._view(p, e, member))
                if len(out) >= limit: break
        return out

    def read_tail(self, pid, member, before=None, limit=300):
        """The latest `limit` events this member may see (or the last ones before a seq), oldest first: a page opens on the end of a long chat without replaying all of it.
        Returns (events, more_before, head): `head` is the seq of the newest event of all, the cursor to stream or poll from."""
        p = self._proj(pid); self._active(p, member)
        try: limit = max(1, min(int(limit or 300), 2000))
        except (TypeError, ValueError): limit = 300
        try: before = int(before) if before is not None and before != "" else None
        except (TypeError, ValueError): before = None
        out, more = [], False
        with p.lock:
            head = len(p.events)
            top = head if before is None else max(0, min(before - 1, head))
            for e in reversed(p.events[:top]):
                if e["chat"] is not None and not self._chat_visible(p, e["chat"], member): continue
                if len(out) >= limit: more = True; break
                out.append(self._view(p, e, member))
        out.reverse()
        return out, more, head

    def activity(self, pid):
        """What has been going on in a project, for the host's dashboard (never served to members): counts and times, no text."""
        p = self._proj(pid); now = self.now(); day = now - 86400
        with p.lock:
            evs = p.events
            answered = {(e["payload"] or {}).get("request") for e in evs if e["type"] == "approval" or (e["type"] in ("guard_decision", "queue_add") and (e["payload"] or {}).get("request"))}
            waiting = [e for e in evs if e["type"] == "approval_request" and (e["payload"] or {}).get("request") not in answered and e["ts"] > now - 900]
            msgs = [e for e in evs if e["type"] == "msg" and e["ts"] >= day]
            turns = [e for e in evs if e["type"] == "model_turn_start" and e["ts"] >= day]
            by_model = {}
            for e in turns:
                k = (e["payload"] or {}).get("label") or (e["payload"] or {}).get("model") or "model"
                by_model[k] = by_model.get(k, 0) + 1
            last = max((e["ts"] for e in evs if e["type"] in ("msg", "model_turn_start", "join")), default=None)
            writers = {e["author"] for e in msgs if not str(e["author"]).startswith("model:")}
            return {"events": len(evs), "chats": len([c for c in p.meta["chats"].values() if not c.get("removed")]), "last_activity": last, "messages_24h": len(msgs), "turns_24h": len(turns),
                    "people_active_24h": len(writers), "models_24h": [{"model": k, "turns": n} for k, n in sorted(by_model.items(), key=lambda kv: -kv[1])][:6], "approvals_waiting": len(waiting)}

    def attach_message(self, pid, member, chat, att, text=""):
        """A message from a member that carries one attached file (the file itself is kept by collab_share). The same checks as any message."""
        p = self._proj(pid)
        with p.lock:
            self._active(p, member, write=True); grant = self.grant_of(pid, member)
            if not grant["can_post"]: raise CollabError("forbidden", "you cannot post here")
            if p.meta["frozen"] and not grant["can_change_grants"]: raise CollabError("forbidden", "the project is frozen")
            if chat not in p.meta["chats"] or not self._chat_visible(p, chat, member): raise CollabError("not_found", "you cannot use that chat")
            t = (text or "").replace("\x00", "").strip()[:MAX_TEXT] or f"attached {att['name']}"
            return self._append(p, "msg", member, {"text": t, "attachments": [{"id": att["id"], "name": att["name"], "size": att["size"]}]}, chat=chat)

    def search(self, pid, member, query, limit=50):
        """Messages the member can see that contain the words (all of them, any case), newest first. Deleted messages and chats the member cannot see are never matched."""
        p = self._proj(pid); self._active(p, member)
        if not isinstance(query, str): raise CollabError("bad_input", "search for some words")
        words = [w for w in query.casefold().split() if w][:8]
        if not words or len(query) > 200: raise CollabError("bad_input", "search for 1 to 8 words")
        try: limit = max(1, min(int(limit or 50), 200))
        except (TypeError, ValueError): limit = 50
        out = []
        with p.lock:
            for e in reversed(p.events):
                if e["type"] != "msg" or e["id"] in p.deleted or (e["payload"] or {}).get("deleted"): continue
                if e["chat"] is not None and not self._chat_visible(p, e["chat"], member): continue
                text = str((e["payload"] or {}).get("text") or "").casefold()
                if all(w in text for w in words): out.append(self._view(p, e, member))
                if len(out) >= limit: break
        return out

    # ------------------------------------------------------------------------------------------------ what a member may see of the host's machine
    _HOME_RE = re.compile(r"(?<![\w.~-])/(?:Users|home)/[^/\s'\"`)\]}>,;:]+")

    def _scrub_text(self, p, s):
        """A path on the host's Mac as a member may read it: inside the project it is relative, the folder itself is "the project folder", and any other home folder becomes ~
        (so the host's username and folder layout never reach a member, whatever wrote the line)."""
        if "/" not in s: return s
        wd = p.meta["working_dir"]
        for base in sorted({wd.rstrip("/"), os.path.realpath(wd).rstrip("/")}, key=len, reverse=True):
            if base and base != "/":
                s = s.replace(base + "/", "")
                s = re.sub(re.escape(base) + r"(?![\w.-])", "the project folder", s)
        home = (self.policy.home or "").rstrip("/")
        if home and home != "/":
            s = s.replace(home + "/", "~/")
            s = re.sub(re.escape(home) + r"(?![\w.-])", "~", s)
        return self._HOME_RE.sub("~", s)

    def _scrub(self, p, o, depth=0):
        if isinstance(o, str): return self._scrub_text(p, o)
        if depth > 12: return o
        if isinstance(o, dict): return {k: self._scrub(p, v, depth + 1) for k, v in o.items()}
        if isinstance(o, (list, tuple)): return [self._scrub(p, v, depth + 1) for v in o]
        return o

    def scrub_for(self, pid, member, obj):
        """`obj` as `member` may read it: unchanged for the owner (it is their own machine), without the host's paths for everyone else."""
        try: p = self._proj(pid)
        except CollabError: return obj
        if not member or member == p.meta["owner"]: return obj
        return self._scrub(p, obj)

    def _view(self, p, e, member=None):
        e = dict(e)
        if e["type"] == "turn_changes" and member is not None and member != p.meta["owner"]:
            e["payload"] = self._changes_for(p, e["payload"], member)
        if e["type"] in ("msg", "edit") and (e["id"] in p.deleted or (e["type"] == "edit" and (e["payload"] or {}).get("target") in p.deleted)):
            e["payload"] = {"deleted": True}
        if member is not None and member != p.meta["owner"] and e.get("payload"):
            pl = e["payload"]
            if e["type"] == "model_turn_start" and isinstance(pl, dict):             # the host's private label and model id stay with the host: people know the model by the handle they type
                pl = {k: v for k, v in pl.items() if k != "model_id"}; pl["label"] = pl.get("model") or pl.get("label")
            e["payload"] = self._scrub(p, pl)
        return e

    def _changes_for(self, p, pl, member):
        """A member sees the names of changed files only where their own grant could read them; the rest is counted, not named."""
        g, wd, hidden = p.grants.get(member) or P.normalize({}, policy=self.policy), p.meta["working_dir"], 0
        out = dict(pl)
        for k in ("created", "modified", "deleted"):
            keep = []
            for rel in pl.get(k) or []:
                try: ok = self.policy.check_path(g, os.path.join(wd, rel), "read", wd)[0]
                except Exception: ok = False
                if ok: keep.append(rel)
                else: hidden += 1
            out[k] = keep
        out["hidden"] = hidden
        return out

    def verify(self, pid):
        """Read the file again from disk and check every link of the chain."""
        p = self._proj(pid)
        prev, n = GENESIS, 0
        try: lines = open(os.path.join(p.path, "events.jsonl"), encoding="utf-8").read().splitlines()
        except OSError: lines = []
        for i, ln in enumerate(lines, 1):
            try: e = json.loads(ln)
            except ValueError: return {"ok": False, "at": i, "events": n, "why": "a line is not readable"}
            h = e.pop("hash", None)
            if e.get("seq") != i or e.get("prev") != prev or _sha(_canon(e)) != h: return {"ok": False, "at": i, "events": n, "why": "the chain breaks here"}
            prev, n = h, n + 1
        return {"ok": True, "events": n}

    # ------------------------------------------------------------------------------------------------ intents
    def submit(self, pid, token, intent):
        self._proj(pid)
        who = self.authenticate(pid, token)
        if not who: raise CollabError("unauthorized", "invalid token")
        return self._submit(pid, who, intent)

    def submit_as(self, pid, member, intent):
        """The host's own parts (its own window, the turn engine) acting for a member who is already known to be in the project."""
        p = self._proj(pid); self._active(p, member)
        return self._submit(pid, {"id": member, "device": None}, intent)

    def _submit(self, pid, who, intent):
        p = self._proj(pid)
        mid = who["id"]
        try: size = len(_canon(intent)) if isinstance(intent, dict) else -1
        except (TypeError, ValueError, RecursionError): size = -1
        if size < 0 or size > MAX_INTENT_BYTES: raise CollabError("bad_input" if size < 0 else "too_large", "that is not a usable message")
        iid, etype = intent.get("id"), intent.get("type")
        if not isinstance(iid, str) or not ID_RE.match(iid): raise CollabError("bad_input", "an intent needs an id")
        if not isinstance(etype, str) or not etype: raise CollabError("bad_input", "an intent needs a type")
        if etype in SYSTEM_TYPES: raise CollabError("forbidden", f"{etype} cannot be posted")
        if etype not in INTENT_TYPES: raise CollabError("bad_input", f"unknown type {etype!r}")
        chat = intent.get("chat", DEFAULT_CHAT)
        if not isinstance(chat, str) or not CHAT_RE.match(chat): raise CollabError("bad_input", "bad chat id")
        payload = intent.get("payload")
        if not isinstance(payload, dict): raise CollabError("bad_input", "the payload must be an object")
        with p.lock:
            m = self._active(p, mid, write=True)
            grant = self.grant_of(pid, mid)
            if p.meta["frozen"] and not grant["can_change_grants"]: raise CollabError("forbidden", "the project is frozen")
            if chat not in p.meta["chats"] or not self._chat_visible(p, chat, mid): raise CollabError("forbidden" if chat in p.meta["chats"] else "not_found", "you cannot use that chat")
            clean = self._payload(p, mid, grant, etype, payload, chat)
            ihash = _sha(_canon({"type": etype, "chat": chat, "payload": clean}))
            known = p.iids.get((mid, iid))
            if known:
                if known[1] == ihash: return {"seq": known[0], "id": iid, "duplicate": True}
                raise CollabError("conflict", "that id was already used for something else")
            now = self.now(); dq = p.rates[mid]
            while dq and now - dq[0] >= 60: dq.popleft()
            if len(dq) >= RATE_PER_MIN: raise CollabError("rate_limited", "slow down: too many messages in a minute")
            dq.append(now)
            e = self._append(p, etype, mid, clean, chat=chat, device=who["device"], iid=iid, ihash=ihash)
        return {"seq": e["seq"], "id": iid}

    def _payload(self, p, mid, grant, etype, payload, chat):
        def text(key="text"):
            t = payload.get(key)
            if not isinstance(t, str) or not t.strip(): raise CollabError("bad_input", "text is required")
            t = t.replace("\x00", "")
            if len(t) > MAX_TEXT: raise CollabError("too_large", "that message is too long")
            return t
        def target(own_only):
            tid = payload.get("target")
            e = p.by_id.get(tid) if isinstance(tid, str) else None
            if e is None or e["type"] != "msg" or e["chat"] != chat: raise CollabError("not_found", "no such message")
            if own_only and e["author"] != mid and not grant["can_change_grants"]: raise CollabError("forbidden", "that is not your message")
            return e
        if etype in ("msg", "note", "task", "decision_pin") and not grant["can_post"]: raise CollabError("forbidden", "you cannot post here")
        if etype == "msg":
            out = {"text": text()}
            to = payload.get("to", [])
            if not isinstance(to, list) or len(to) > 10 or not all(isinstance(x, str) and len(x) <= 80 for x in to): raise CollabError("bad_input", "bad recipients")
            if to: out["to"] = to
            for k in ("reply_to", "thread"):
                if payload.get(k) is not None:
                    if not isinstance(payload[k], str) or len(payload[k]) > 80: raise CollabError("bad_input", f"bad {k}")
                    out[k] = payload[k]
            return out
        if etype == "edit":
            e = target(own_only=False)
            if e["author"] != mid: raise CollabError("forbidden", "only the author edits a message")
            return {"target": e["id"], "text": text()}
        if etype == "delete":
            e = target(own_only=True)
            if e["seq"] <= p.seen.get(chat, 0): raise CollabError("conflict", "the model has already read that message, so it stays")
            return {"target": e["id"]}
        if etype == "react":
            e = target(own_only=False)
            em = payload.get("emoji")
            if not isinstance(em, str) or not em or len(em) > 20: raise CollabError("bad_input", "bad reaction")
            return {"target": e["id"], "emoji": em}
        if etype == "approval":
            if not grant["approver"]: raise CollabError("forbidden", "you cannot approve actions here")
            rid = payload.get("request")
            r = p.requests.get(rid) if isinstance(rid, str) else None
            if r is None or r["chat"] != chat: raise CollabError("not_found", "no such request in this chat")
            if r["closed"] or self.now() - r["ts"] > APPROVAL_TTL_S: raise CollabError("conflict", "that request was already answered or has expired")
            if mid == r["by"] and mid != p.meta["owner"]: raise CollabError("forbidden", "nobody approves their own request")
            if payload.get("decision") not in ("allow", "deny"): raise CollabError("bad_input", "decision must be allow or deny")
            mode = payload.get("mode") if payload.get("mode") in ("once", "chat") else "once"
            if payload["decision"] == "allow" and mid in r["allows"]: raise CollabError("conflict", "you already approved this one; it needs someone else")
            have = len(r["allows"]) + (1 if payload["decision"] == "allow" else 0)
            final = payload["decision"] == "deny" or have >= r["need"]
            if r["need"] > 1: mode = "once"                                              # a two-person action is never remembered
            return {"request": rid, "decision": payload["decision"], "mode": mode, "note": str(payload.get("note") or "")[:300], "approver": mid, "final": final, "have": have, "need": r["need"]}
        if etype == "queue_withdraw":
            return {"item": str(payload.get("item"))[:80]}
        return {"text": text()} if etype in ("note", "decision_pin") else {"text": text("title")}

    # ------------------------------------------------------------------------------------------------ kill switch
    def panic(self, pid, actor):
        p = self._proj(pid)
        with p.lock:
            self._active(p, actor, write=True)
            if not self.grant_of(pid, actor)["can_change_grants"]: raise CollabError("forbidden", "only a moderator can freeze the project")
            p.meta["frozen"] = True; p.save("project")
            self._append(p, "panic", actor, {"by": actor})

    def resume(self, pid, actor):
        p = self._proj(pid)
        with p.lock:
            self._active(p, actor, write=True)
            if actor != p.meta["owner"]: raise CollabError("forbidden", "only the owner lifts a freeze")
            p.meta["frozen"] = False; p.save("project")
            self._append(p, "config", actor, {"frozen": False, "by": actor})
