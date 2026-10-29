"""Shared projects: this Orbit as the host. Turns the feature on and off, opens the door members use, and lets the person who owns this Mac
make projects and invitations. Nothing here is reachable by a member: the member door (collab_server.py) has no route to any of it.

Off by default. While it is off nothing listens, no folder is made, and the rest of Orbit does not know it exists.
"""
import copy, json, os, re, threading, time

import collab_accounts as CA
import collab_policy as P
import collab_server as V
import collab_store as S
import collab_backup as B
import collab_relay as RL
import collab_turns as T
import collab_local as L

DEFAULTS = {"enabled": False, "mode": "local", "port": 8450, "public_url": "", "models": [], "relay": {"service": "https://orbit.runtianwu.com", "projects": {}}}
HANDLE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,29}$")
MODES = ("local", "tailscale", "lan")


class Host:
    def __init__(self, root, cfg_path=None, remote=None, policy=None, tools=None, run=None, local=None, guard_models=None, guard_ask=None, notify=None, accounts=None, relay_token=None, relay_ws=None, usage=None):
        self.root = root
        self.usage = usage          # usage(model_id) -> {"label", "left_pct", "state"} or None: what is left of a model, shown to members only where the host switched it on
        self.relay_token = relay_token  # relay_token() -> the Orbit account's access token, or None when not signed in
        self.relays = {}                # project id -> RelayClient
        self.relay_ws = relay_ws        # a WebSocket client factory, replaced in tests
        self.accounts = accounts      # verify(token) -> claims for an Orbit account token, checked here with the service's public keys; None = this host cannot check accounts
        self.notify = notify         # notify(title, text): a notice on this Mac and the phone; best effort
        self.guard_models, self.guard_ask = guard_models, guard_ask      # guard_models(): [{id, label}] a plain, ready model that may act as the guard
        self.local = local          # the person's own chats on this Mac: .folder, .marker, .list()
        self.tools, self.run, self.engine = tools, run, None
        self.cfg_path = cfg_path or os.path.join(root, "config", "collab.json")
        self.remote = remote
        self.policy = policy
        self.store = None
        self.servers, self.threads = [], []
        self.lock = threading.RLock()
        self.cfg = self._load()

    # ------------------------------------------------------------------------------------------------ settings
    def _load(self):
        try: d = json.load(open(self.cfg_path, encoding="utf-8"))
        except (OSError, ValueError): d = {}
        c = copy.deepcopy(DEFAULTS)
        try: c.update(self._clean(d if isinstance(d, dict) else {}))
        except ValueError: pass
        return c

    @staticmethod
    def _clean(d):
        out = {}
        if "enabled" in d:
            if not isinstance(d["enabled"], bool): raise ValueError("enabled must be true or false")
            out["enabled"] = d["enabled"]
        if "mode" in d:
            if d["mode"] not in MODES: raise ValueError("mode must be one of " + ", ".join(MODES))
            out["mode"] = d["mode"]
        if "port" in d:
            if not isinstance(d["port"], int) or isinstance(d["port"], bool) or not (d["port"] == 0 or 1024 <= d["port"] <= 65535): raise ValueError("port must be 1024-65535")
            out["port"] = d["port"]
        if "models" in d:
            ms = d["models"]
            if not isinstance(ms, list) or len(ms) > 10: raise ValueError("models must be a list of at most 10")
            seen, clean = set(), []
            for m in ms:
                if not isinstance(m, dict) or not isinstance(m.get("handle"), str) or not HANDLE.match(m["handle"]) or m["handle"].lower() in seen: raise ValueError("each model needs a unique short handle (letters, digits, - and _)")
                if not isinstance(m.get("id"), str) or not m["id"] or len(m["id"]) > 120: raise ValueError("each model needs the id Orbit knows it by")
                seen.add(m["handle"].lower())
                clean.append({"handle": m["handle"], "id": m["id"], "label": str(m.get("label") or m["handle"])[:60], "payer": str(m.get("payer") or "the host")[:80], "share_usage": bool(m.get("share_usage"))})
            out["models"] = clean
        if "relay" in d:
            r = d["relay"]
            if not isinstance(r, dict) or not isinstance(r.get("service"), str) or not (r["service"].startswith("https://") or r["service"].startswith("http://127.0.0.1")) or len(r["service"]) > 200: raise ValueError("relay needs an https service address")
            pr = r.get("projects") if isinstance(r.get("projects"), dict) else {}
            out["relay"] = {"service": r["service"].rstrip("/"), "projects": {k: v for k, v in pr.items() if isinstance(k, str) and S.PID_RE.match(k) and isinstance(v, str) and 20 <= len(v) <= 200}}
        if "public_url" in d:
            u = d["public_url"]
            if not isinstance(u, str) or (u and not u.startswith(("https://", "http://"))) or len(u) > 300: raise ValueError("public_url must be an http(s) address")
            out["public_url"] = u.rstrip("/")
        return out

    def configure(self, **kw):
        with self.lock:
            new = self._clean(kw)
            was = self.running()
            self.cfg.update(new)
            self._save_cfg()
            if was and (not self.cfg["enabled"] or {"mode", "port"} & set(new)): self.stop()
            if not self.cfg["enabled"]: self._stop_engine()
            if self.cfg["enabled"] and (not self.running()) and ("enabled" in new or was): self.start()
            return self.status()

    def _save_cfg(self):
        os.makedirs(os.path.dirname(self.cfg_path), exist_ok=True)
        tmp = self.cfg_path + ".tmp"
        with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f: json.dump(self.cfg, f, indent=1)
        os.replace(tmp, self.cfg_path)

    # ------------------------------------------------------------------------------------------------ the relay (so members need no address of this Mac)
    def _service_call(self, method, path, body=None, token=None):
        import urllib.request, urllib.error
        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k): return None
        req = urllib.request.Request(self.cfg["relay"]["service"] + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                     headers={"Content-Type": "application/json", "Authorization": "Bearer " + token, "User-Agent": "Orbit-relay"})
        try:
            r = urllib.request.build_opener(_NoRedirect).open(req, timeout=20); status, raw = r.status, r.read(100_000)
        except urllib.error.HTTPError as e: status, raw = e.code, e.read(100_000)
        except (urllib.error.URLError, OSError, ValueError): raise S.CollabError("conflict", "could not reach the Orbit service; check the connection")
        try: j = json.loads(raw or b"{}")
        except ValueError: j = {}
        if status >= 400: raise S.CollabError("conflict", (j.get("error") if isinstance(j, dict) and isinstance(j.get("error"), str) else None) or f"the Orbit service answered {status}")
        return j

    def embed_token(self, pid):
        """A sign-in for the host's own Orbit window (the owner), kept in memory only: the shared page inside Orbit uses it through Orbit's own address, so no token is in the page."""
        st = self._on(); info = st.project_view_admin(pid)
        return st.add_device_for(pid, info["owner"], "Orbit window")["token"]

    def door_port(self):
        return int(self.cfg.get("_port") or self.cfg["port"]) if self.running() else None

    def relay_link(self, pid):
        return f"{self.cfg['relay']['service']}/r/{pid}" if pid in self.cfg["relay"]["projects"] else None

    def relay_audience(self, pid):
        """The audience a join proof must carry to be accepted for `pid` through the Orbit service: that project's page there. None unless the project is published."""
        if pid not in self.cfg["relay"]["projects"]: return None
        try: return CA.relay_audience(self.cfg["relay"]["service"], pid)
        except ValueError: return None

    def relay_status(self):
        with self.lock:
            return {"service": self.cfg["relay"]["service"], "projects": {pid: dict(self.relays[pid].status() if pid in self.relays else {"state": "stopped", "error": "", "since": 0, "served": 0}, link=self.relay_link(pid))
                                                                       for pid in self.cfg["relay"]["projects"]}}

    def _relay_start(self, pid):
        secret = self.cfg["relay"]["projects"].get(pid)
        if not secret or not self.running(): return
        old = self.relays.get(pid)
        if old is not None: old.stop()
        for srv in self.servers: srv.trust_relay = True
        rc = RL.RelayClient(self.cfg["relay"]["service"], pid, secret, self.cfg.get("_port") or self.cfg["port"], **({"ws_factory": self.relay_ws} if self.relay_ws else {})); self.relays[pid] = rc; rc.start()

    def _relay_stop_all(self):
        for rc in list(self.relays.values()): rc.stop()
        self.relays = {}

    def publish(self, pid):
        """Put a project on the web through the Orbit service: members open a link on the service and sign in; nothing on this Mac is exposed."""
        st = self._on(); info = st.project_view_admin(pid)
        if not self.running(): raise S.CollabError("conflict", "the shared-projects door is not running")
        tok = self.relay_token() if self.relay_token else None
        if not tok: raise S.CollabError("forbidden", "sign in to your Orbit account first (Settings > General > Orbit account)")
        r = self._service_call("POST", "/relay/projects", {"id": pid, "name": info["name"]}, tok)
        if not isinstance(r.get("secret"), str): raise S.CollabError("conflict", "the Orbit service sent an unexpected answer")
        with self.lock:
            self.cfg["relay"]["projects"][pid] = r["secret"]; self._save_cfg(); self._relay_start(pid)
        return {"link": self.relay_link(pid)}

    def unpublish(self, pid):
        st = self._on(); st.project_view_admin(pid)
        with self.lock:
            if pid not in self.cfg["relay"]["projects"]: raise S.CollabError("not_found", "that project is not published")
            rc = self.relays.pop(pid, None)
            if rc: rc.stop()
            del self.cfg["relay"]["projects"][pid]; self._save_cfg()
        tok = self.relay_token() if self.relay_token else None
        if tok:
            try: self._service_call("DELETE", f"/relay/projects/{pid}", None, tok)
            except S.CollabError: pass                       # the service keeps a stale row at worst; the secret is already gone here
        return {"ok": True}

    # ------------------------------------------------------------------------------------------------ the door
    def running(self): return bool(self.servers)

    def _store(self):
        if self.store is None: self.store = S.Store(os.path.join(self.root, "collab"), policy=self.policy)
        if self.engine is None and self.cfg["enabled"]:
            self.engine = T.TurnEngine(self.store, policy=self.policy, run=self.run, models=self._models, tools=self.tools, guard_ask=self.guard_ask)
            self.store.add_listener(self.engine.on_event)
            for pid in [x["id"] for x in self.store.all_projects()]: self.engine.recover(pid)
            self.store.add_listener(self._notice)
        return self.store

    def _models(self):
        return {m["handle"]: m for m in self.cfg.get("models", [])}

    def _models_public(self):
        out = []
        for m in self.cfg.get("models", []):
            row = {"handle": m["handle"], "label": m.get("label") or m["handle"], "payer": m.get("payer") or "the host"}
            if m.get("share_usage") and self.usage:
                try: row["usage"] = self.usage(m["id"])
                except Exception: row["usage"] = None
            out.append(row)
        return out

    def _notice(self, pid, e):
        """What the person who owns this Mac should hear about: someone's request that needs their answer, and someone joining."""
        if not self.notify: return
        try:
            st, p = self.store, e.get("payload") or {}
            owner = st.project_view_admin(pid)["owner"]; name = st.project_view_admin(pid)["name"]; names = st.member_names(pid)
            if e["type"] == "approval_request" and p.get("requested_by") != owner:
                self.notify(f"Needs your answer: {name}", f"{names.get(p.get('requested_by'), 'Someone')}'s request: {p.get('tool')} {str(p.get('args_summary') or '')[:120]}")
            elif e["type"] == "join": self.notify(f"{p.get('name', 'Someone')} joined {name}", "They can read every chat in the project.")
        except Exception: pass

    def _stop_engine(self):
        if self.engine is not None:
            self.engine.shutdown()
            for fn in (self.engine.on_event, self._notice):
                try: self.store.listeners.remove(fn)
                except (ValueError, AttributeError): pass
            self.engine = None

    def start(self):
        with self.lock:
            if self.running(): return
            if not self.cfg["enabled"]: raise S.CollabError("forbidden", "Shared projects are off")
            st, mode, port = self._store(), self.cfg["mode"], self.cfg["port"]
            addrs = self.remote.bind_addresses(mode) if self.remote and mode != "local" else ["127.0.0.1"]
            started = []
            try:
                for a in addrs:
                    srv = V.make_server(st, a, port)
                    port = srv.server_address[1]                    # a port of 0 is chosen once, then reused for the other address
                    started.append(srv)
            except OSError as e:
                for srv in started: srv.server_close()
                raise S.CollabError("conflict", f"could not open the shared-projects door on port {port}: {e}")
            hosts = self.remote.reachable_hosts(mode, port) if self.remote and mode != "local" else {f"127.0.0.1:{port}", f"localhost:{port}"}
            url = self.cfg["public_url"] or (self.remote.best_url(mode, port) if self.remote and mode != "local" else "") or f"http://127.0.0.1:{port}"
            for srv in started:
                srv.public_url, srv.allowed_hosts, srv.accounts, srv.models_provider = url, set(hosts), self.accounts, self._models_public
                srv.relay_audience = self.relay_audience
                t = threading.Thread(target=srv.serve_forever, daemon=True); t.start(); self.threads.append(t)
            self.servers = started
            self.cfg["_port"] = port
            for pid in list(self.cfg["relay"]["projects"]): self._relay_start(pid)

    def stop(self):
        with self.lock:
            self._relay_stop_all()
            for srv in self.servers:
                try: srv.shutdown(); srv.server_close()
                except Exception: pass
            self.servers, self.threads = [], []

    def status(self):
        with self.lock:
            on = self.cfg["enabled"]
            return {"enabled": on, "running": self.running(), "mode": self.cfg["mode"], "port": self.cfg.get("_port", self.cfg["port"]) if self.running() else self.cfg["port"],
                    "public_url": self.servers[0].public_url if self.running() else self.cfg["public_url"],
                    "projects": self._store().all_projects() if on else [], "proto": S.PROTO, "models": [dict(m) for m in self.cfg.get("models", [])]}

    def dashboard(self):
        """The project cards in Settings: for each project who is in it and who is here now, what happened in the last day, whether it is frozen, shared on the web, and how many
        invitations are still open. Counts and times only, no message text."""
        st = self.status(); out = []
        if not st["enabled"]: return {"status": st, "projects": []}
        store = self._store(); relays = self.relay_status()["projects"]; now = time.time(); here = {}
        for srv in list(self.servers):
            with srv.lock:
                for (pid, mid), n in srv.streams.items():
                    if n > 0: here.setdefault(pid, set()).add(mid)
                for (pid, mid), t in srv.polled.items():
                    if now - t < 15: here.setdefault(pid, set()).add(mid)
        for p in st["projects"]:
            pid = p["id"]
            try:
                act = store.activity(pid); owner = p["owner"]
                invites = [i for i in store.list_invites(pid, owner) if not i["revoked"] and i["uses_left"] != 0]
            except S.CollabError: continue
            r = relays.get(pid)
            out.append(dict(p, activity=act, here=len(here.get(pid, ())), open_invites=len(invites), web=({"state": r.get("state"), "link": r.get("link")} if r else None)))
        return {"status": st, "projects": out}

    # ------------------------------------------------------------------------------------------------ the person who owns this Mac
    def _on(self):
        if not self.cfg["enabled"]: raise S.CollabError("forbidden", "Shared projects are off")
        return self._store()

    def create_project(self, name, owner_name, working_dir):
        return self._on().create_project(name, owner_name, working_dir)

    def invite(self, pid, role="editor", grant=None, expires_in=None, uses=1, account_required=False, budget=None, files=None, for_account=None):
        """An invitation. `for_account` (an Orbit account id, acc_...) addresses it to that one account: nobody else can use it, the account needs no link secret (it can just
        open the project page and sign in), it is used once, and it lapses after 14 days unless `expires_in` says otherwise."""
        st = self._on()
        if for_account is not None:
            try: for_account = CA.clean_account_id(for_account)
            except ValueError as e: raise S.CollabError("bad_input", str(e))
            account_required, uses = True, 1
            if not expires_in: expires_in = 14 * 86400
        owner = st.project_view_admin(pid)["owner"]
        if grant is None:
            if role not in P.ROLES: raise S.CollabError("bad_input", "unknown role")
            grant = P.template(role, project=st.project_view_admin(pid)["working_dir"])
            if isinstance(files, dict): grant = dict(grant, **{f: files[f] for f in P.FILE_FLAGS if isinstance(files.get(f), bool)})
            if budget: grant = dict(grant, budget=dict(grant.get("budget") or {}, **{k: v for k, v in budget.items() if k in ("turns_per_hour", "turns_per_day")}))
        inv = st.create_invite(pid, owner, grant=grant, expires_in=expires_in, uses=uses, account_required=account_required, for_account=for_account)
        base = self.relay_link(pid) or self.status()["public_url"] or "http://127.0.0.1"          # a published project's links go through the service
        out = dict(inv, account_required=bool(account_required), **V.invite_links(base, pid, inv))
        if for_account: out.update(for_account=for_account, page_link=base.rstrip("/") + "/")       # an addressed invitation needs no secret: its account opens the project page and signs in
        return out

    def panic(self, pid):
        st = self._on(); st.panic(pid, st.project_view_admin(pid)["owner"])

    def open_url(self, pid, name="Host"):
        """An address that opens this project in the browser as its owner. The token is in the fragment, which a browser never sends to a server."""
        st = self._on(); info = st.project_view_admin(pid)
        dev = st.add_device_for(pid, info["owner"], "host's browser")
        base = self.status()["public_url"] or "http://127.0.0.1"
        return {"url": f"{base.rstrip('/')}/#p={pid}&t={dev['token']}&n={name}", "device": dev["device"]}

    def resume(self, pid):
        st = self._on(); st.resume(pid, st.project_view_admin(pid)["owner"])

    # -- local chats shared into a project, and taken out again
    def local_chats(self):
        self._on()
        return self.local.list() if self.local else []

    def share_preview(self, pid, sid):
        """What sharing a local chat would put in front of everyone in the project, before anything is shared."""
        self._on()
        if not self.local: raise S.CollabError("conflict", "no local chats here")
        try: title, msgs = L.read_session(L.session_file(self.local.folder, sid))
        except ValueError as e: raise S.CollabError("not_found", str(e))
        out, st = L.extract(msgs, self.local.marker)
        dropped = max(0, len(out) - S.MAX_IMPORT)
        if dropped: out = out[-S.MAX_IMPORT:]
        return {"title": title or sid, "messages": len(out), "user": st["user"], "assistant": st["assistant"], "tools_skipped": st["tools_skipped"],
                "images_skipped": st["images_skipped"], "chars": st["chars"], "dropped_oldest": dropped, "warnings": L.warnings([m["text"] for m in out]), "_messages": out}

    def share_chat(self, pid, sid, name=None, confirm_secrets=False):
        st = self._on()
        prev = self.share_preview(pid, sid)
        if prev["warnings"] and not confirm_secrets:
            kinds = ", ".join(sorted({w["kind"] for w in prev["warnings"]}))
            raise S.CollabError("conflict", f"this chat looks like it contains {kinds}; everyone in the project could read it. Share anyway only if that is fine")
        chat_id = "c" + __import__("secrets").token_hex(4)
        owner = st.project_view_admin(pid)["owner"]
        r = st.import_chat(pid, owner, chat_id, name or prev["title"], prev["_messages"], source={"title": prev["title"]})
        return dict(r, title=prev["title"], dropped_oldest=prev["dropped_oldest"])

    def remove_chat(self, pid, chat):
        st = self._on(); return st.remove_chat(pid, st.project_view_admin(pid)["owner"], chat)

    def project_chats(self, pid):
        st = self._on(); return st.project_view(pid, st.project_view_admin(pid)["owner"])["chats"]

    def set_project(self, pid, allow_export=None, name=None):
        st = self._on(); owner = st.project_view_admin(pid)["owner"]
        if allow_export is not None: st.set_allow_export(pid, owner, bool(allow_export))
        if name is not None: st.rename_project(pid, owner, name)
        return {"ok": True}

    def chat_payload(self, pid, chat):
        """A shared chat as the saved-file payload, for the owner to copy into a chat of their own."""
        st = self._on(); owner = st.project_view_admin(pid)["owner"]
        view = st.project_view(pid, owner); names = st.member_names(pid)
        cname = next((c["name"] for c in view["chats"] if c["id"] == chat), chat)
        return L.shared_chat_payload(view["name"], chat, cname, st.export_events(pid, owner, chat), names, names.get(owner, "the host"), __import__("time").time())

    def guard(self, pid):
        st = self._on()
        owner = st.project_view_admin(pid)["owner"]
        return {"guard": st.guard_config(pid), "models": list(self.guard_models() if self.guard_models else []), "two_person": st.project_view(pid, owner)["two_person"], "turn_mode": st.turn_mode(pid)}

    def recent_changes(self, pid, limit=10):
        """The latest answers that changed files, newest first, for the host's own view; `undoable` says whether Orbit still holds the file-tool changes."""
        st = self._on(); owner = st.project_view_admin(pid)["owner"]
        ev = [e for e in st.read(pid, owner, limit=10_000) if e["type"] == "turn_changes"][-limit:][::-1]
        held = set(self.engine.turn_undo) if self.engine is not None else set()
        names = st.member_names(pid)
        return [dict(e["payload"], seq=e["seq"], asked_by_name=names.get(e["payload"].get("asked_by"), e["payload"].get("asked_by_name")), can_undo=(pid, e["payload"].get("turn")) in held) for e in ev]

    def check(self, pid):
        """A plain health check of one project, for a person who wants to know whether it is set up properly: [{name, ok, detail}]. Nothing here changes anything."""
        st = self._on(); info = st.project_view_admin(pid); owner = info["owner"]; rows = []
        add = lambda name, ok, detail: rows.append({"name": name, "ok": bool(ok), "detail": detail})
        v = st.verify(pid); add("Record is intact", v["ok"], f"{v['events']} events, every link checks out" if v["ok"] else f"it breaks at event {v.get('at')}: {v.get('why')}")
        add("Working folder exists", os.path.isdir(info["working_dir"]), info["working_dir"])
        import collab_jail as J
        add("Commands run in a sandbox", J.available(), "members' commands are confined to the project folder" if J.available() else "no sandbox on this Mac, so members cannot run commands at all (they can still chat and use file tools)")
        add("The door is open", self.running(), (self.servers[0].public_url if self.running() else "turn it on in the settings above"))
        models = self.cfg.get("models", [])
        add("A model people can ask", bool(models), ", ".join("@" + m["handle"] for m in models) if models else "none yet: nobody can ask a model anything")
        g = st.guard_config(pid)
        add("Guard model", True, "on" if g.get("enabled") else "off (risky actions go straight to a person)")
        pp = st._proj(pid)
        with pp.lock:
            approvers = [m["name"] for m in pp.members.values() if m["state"] == "active" and st.grant_of(pid, m["id"]).get("approver")]
            active = sum(1 for m in pp.members.values() if m["state"] == "active")
        add("Someone can approve", bool(approvers), ", ".join(approvers) if approvers else "nobody can approve, so any action that needs a yes is refused")
        add("People", True, f"{active} active")
        add("Not frozen", not info["frozen"], "frozen: everything is stopped until you lift it" if info["frozen"] else "running normally")
        return rows

    def people(self, pid):
        """Everyone in a project and the open invitations, for the host's own window."""
        st = self._on(); owner = st.project_view_admin(pid)["owner"]; pp = st._proj(pid)
        with pp.lock:
            members = [{"id": m["id"], "name": m["name"], "role": m["role"], "state": m["state"], "account": bool(m.get("account")), "owner": m["id"] == owner,
                        "budget": dict(st.grant_of(pid, m["id"]).get("budget") or {}), "summary": P.summary(st.grant_of(pid, m["id"])),
                        "files": {f: bool(st.grant_of(pid, m["id"]).get(f)) for f in P.FILE_FLAGS}, "read_paths": list(st.grant_of(pid, m["id"])["read_paths"]), "write_paths": list(st.grant_of(pid, m["id"])["write_paths"]),
                        "deny_paths": list(st.grant_of(pid, m["id"])["deny_paths"])}
                       for m in pp.members.values() if m["state"] != "removed"]
        return {"members": members, "invites": [i for i in st.list_invites(pid, owner) if not i["revoked"] and (i["uses_left"] != 0)], "roles": [r for r in P.ROLES if r != "owner"]}

    def member_action(self, pid, member, action, value=None):
        st = self._on(); owner = st.project_view_admin(pid)["owner"]
        if action == "remove": st.remove_member(pid, owner, member)
        elif action in ("mute", "unmute"): st.set_member_state(pid, owner, member, "muted" if action == "mute" else "active")
        elif action == "revoke_invite": st.revoke_invite(pid, owner, member)
        elif action == "role":
            if value not in P.ROLES or value == "owner": raise S.CollabError("bad_input", "unknown role")
            old = st.grant_of(pid, member); g = P.template(value, project=st.project_view_admin(pid)["working_dir"]); g["budget"] = dict(old.get("budget") or {})
            st.set_grant(pid, owner, member, g)
        elif action == "files":
            if not isinstance(value, dict): raise S.CollabError("bad_input", "give the file settings")
            g = dict(st.grant_of(pid, member)); wd = st.project_view_admin(pid)["working_dir"]
            for f in P.FILE_FLAGS:
                if f in value:
                    if not isinstance(value[f], bool): raise S.CollabError("bad_input", f"{f} is on or off")
                    g[f] = value[f]
            for k in ("read_paths", "write_paths", "deny_paths"):
                if k in value:
                    if not isinstance(value[k], list) or len(value[k]) > 20 or not all(isinstance(x, str) and x.strip() for x in value[k]): raise S.CollabError("bad_input", f"{k} is a list of folders")
                    g[k] = [x if os.path.isabs(os.path.expanduser(x)) else os.path.join(wd, x) for x in (v.strip() for v in value[k])]     # a relative folder means inside the project folder
            st.set_grant(pid, owner, member, g)
        elif action == "budget":
            if not isinstance(value, dict): raise S.CollabError("bad_input", "give the limits")
            g = dict(st.grant_of(pid, member)); b = dict(g.get("budget") or {})
            for k in ("turns_per_hour", "turns_per_day"):
                if k in value:
                    if value[k] in (None, ""): b.pop(k, None)
                    else: b[k] = value[k]
            g["budget"] = b; st.set_grant(pid, owner, member, g)
        else: raise S.CollabError("bad_input", "unknown action")
        return {"ok": True}

    def backup_project(self, pid):
        st = self._on(); st.project_view_admin(pid)
        return B.backup(st, pid, os.path.join(self.root, "backups", "shared-projects"))

    def restore_project(self, path):
        st = self._on(); os.path.expanduser(path or "")
        r = B.restore(st.root, os.path.expanduser(path or ""))
        st.cache.pop(r["pid"], None)
        st.append_system(r["pid"], "config", {"restored_from_backup": True})
        return r

    def set_turn_mode(self, pid, mode):
        st = self._on(); return st.set_turn_mode(pid, st.project_view_admin(pid)["owner"], mode)

    def undo_turn(self, pid, turn, force=False):
        self._on(); st = self._store()
        if self.engine is None: raise S.CollabError("not_found", "Shared projects are off")
        st.project_view_admin(pid)
        if not isinstance(turn, (int, str)) or isinstance(turn, bool): raise S.CollabError("bad_input", "which turn?")
        return self.engine.undo_turn(pid, turn, force=bool(force))

    def set_two_person(self, pid, flags):
        st = self._on(); return st.set_two_person(pid, st.project_view_admin(pid)["owner"], flags)

    def set_guard(self, pid, cfg):
        st = self._on()
        if isinstance(cfg, dict) and cfg.get("enabled") and self.guard_models is not None:
            if cfg.get("model_id") not in {m["id"] for m in self.guard_models()}:
                raise S.CollabError("bad_input", "that model cannot act as the guard: it must be a plain model (not a coding agent) that is ready to use")
        return st.set_guard(pid, st.project_view_admin(pid)["owner"], cfg)
