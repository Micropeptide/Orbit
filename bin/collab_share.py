"""Files in a shared project: what a member can do with files themselves (not through a model), each part behind its own switch in their grant.

    files_download      download the files the models made in chats they can see, and files attached to chats
    files_browse        see and download files in the project folder (only where their read folders allow)
    files_edit          change text files in the project folder (only where their write folders allow)
    files_upload_chat   attach a file to a chat (the models and everyone in the chat can use it)
    files_upload_dir    put a file into the project folder (only where their write folders allow; nothing is overwritten)

Every path goes through the same permission engine as the models' tools (the folders granted, folders refused, files Orbit itself holds, keys and login files), by real
path, so a link cannot lead out. Uploads come in pieces (so they pass through the relay) and are checked for size at the end. Everything a member changes is written to the
project's record, with their name.
"""
import hashlib, json, os, re, secrets, shutil, time

import collab_store as S

HIDDEN = {".git", ".orbit-attachments"}
MAX_LIST = 500
MAX_DOWNLOAD = 100_000_000
MAX_EDIT = 1_000_000
MAX_CHAT_FILE = 25_000_000
MAX_DIR_FILE = 100_000_000
MAX_ATTACHED_TOTAL = 500_000_000
CHUNK = 400_000
UPLOADS_PER_MEMBER = 3
UID_RE = re.compile(r"^u_[0-9a-f]{12}$")
AID_RE = re.compile(r"^a_[0-9a-f]{12}$")


def clean_name(name):
    """A file name that is only a name: no folders, no hidden or reserved names, no control characters, not too long."""
    if not isinstance(name, str): raise S.CollabError("bad_input", "a file needs a name")
    n = re.sub(r"[\x00-\x1f\x7f/\\:*?\"<>|]", "_", name.replace("‮", "")).strip().strip(".")
    if not n or n in (".", "..") or len(n.encode()) > 200 or n.startswith("."): raise S.CollabError("bad_input", "that file name cannot be used")
    return n


def sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


class FileShare:
    def __init__(self, store, policy, now=time.time):
        self.st, self.policy, self.now = store, policy, now

    # -- the shared checks
    def _ctx(self, pid, member, flag, write=False):
        p = self.st._proj(pid); self.st._active(p, member, write=write)
        g = self.st.grant_of(pid, member)
        if g.get("expires_at") and self.now() > g["expires_at"]: raise S.CollabError("forbidden", "your access to this project has ended")
        if not g.get(flag): raise S.CollabError("forbidden", "the host has not allowed you to do that")
        if write and p.meta["frozen"] and not g["can_change_grants"]: raise S.CollabError("forbidden", "the project is frozen")
        return p, g, p.meta["working_dir"]

    def _rel(self, rel):
        if rel in (None, ""): return ""
        if not isinstance(rel, str) or "\x00" in rel or len(rel) > 2000 or os.path.isabs(rel): raise S.CollabError("bad_input", "that is not a path in the project")
        parts = [x for x in rel.replace("\\", "/").split("/") if x not in ("", ".")]
        if any(x == ".." or x in HIDDEN for x in parts): raise S.CollabError("forbidden", "that path is not available")
        return "/".join(parts)

    def _path(self, g, wd, rel, mode):
        rel = self._rel(rel); full = os.path.join(wd, rel) if rel else wd
        ok, why, layer, real = self.policy.check_path(g, full, mode, wd)
        if not ok: raise S.CollabError("forbidden", "you are not allowed there")                                  # no reason: it would tell what exists
        wdr = os.path.realpath(wd)
        if real and not (real == wdr or real.startswith(wdr + os.sep)): raise S.CollabError("forbidden", "you are not allowed there")        # inside the project folder only
        if real and any(x in HIDDEN for x in os.path.relpath(real, wdr).split(os.sep)): raise S.CollabError("forbidden", "that path is not available")
        return real, rel

    def _ancestor_of_grant(self, g, real):
        return any(x == real or x.startswith(real.rstrip(os.sep) + os.sep) for x in g["read_paths"] + g["write_paths"])

    # -- browsing
    def list_dir(self, pid, member, rel=""):
        p, g, wd = self._ctx(pid, member, "files_browse")
        full = os.path.join(wd, self._rel(rel)); real = os.path.realpath(full); wdr = os.path.realpath(wd)
        if not (real == wdr or real.startswith(wdr + os.sep)) or not os.path.isdir(real): raise S.CollabError("not_found", "no such folder")
        if any(x in HIDDEN for x in os.path.relpath(real, wdr).split(os.sep)): raise S.CollabError("forbidden", "that path is not available")
        here_ok = self.policy.check_path(g, real, "read", wd)[0]
        if not here_ok and not self._ancestor_of_grant(g, real): raise S.CollabError("forbidden", "you are not allowed there")
        out = []
        try: names = sorted(os.listdir(real), key=lambda n: (not os.path.isdir(os.path.join(real, n)), n.lower()))
        except OSError: raise S.CollabError("not_found", "no such folder")
        for n in names:
            if n in HIDDEN or n.startswith(".") and n not in (".gitignore", ".env.example"): continue
            fp = os.path.join(real, n)
            try: st = os.lstat(fp)
            except OSError: continue
            if os.path.islink(fp) and not os.path.exists(fp): continue
            rp = os.path.realpath(fp); isdir = os.path.isdir(fp)
            readable = self.policy.check_path(g, rp, "read", wd)[0] and (rp == wdr or rp.startswith(wdr + os.sep))
            if not readable and not (isdir and self._ancestor_of_grant(g, rp)): continue
            e = {"name": n, "type": "dir" if isdir else "file", "size": None if isdir else os.path.getsize(fp), "mtime": st.st_mtime}
            if not isdir:
                e["editable"] = bool(g["files_edit"] and e["size"] <= MAX_EDIT and self.policy.check_path(g, rp, "write", wd)[0])
            out.append(e)
            if len(out) >= MAX_LIST: break
        base = os.path.relpath(real, wdr); base = "" if base == "." else base
        return {"path": base, "entries": out, "can_upload": bool(g["files_upload_dir"] and self.policy.check_path(g, real, "write", wd)[0]), "truncated": len(out) >= MAX_LIST}

    # -- what the models made, and what was attached
    def _generated_set(self, pid, member):
        """{relative path: info} for files the models created or changed in chats this member can see, newest first."""
        out, pp = {}, self.st._proj(pid)
        for e in reversed(self.st.read(pid, pp.meta["owner"], limit=10_000)):                  # the unfiltered record, then only the chats this member can see
            if e["type"] != "turn_changes" or (e["chat"] is not None and not self.st._chat_visible(pp, e["chat"], member)): continue
            pl = e["payload"] or {}
            for kind in ("created", "modified"):
                for rel in pl.get(kind) or []:
                    if isinstance(rel, str) and rel not in out: out[rel] = {"path": rel, "kind": kind, "model": pl.get("model"), "by": pl.get("asked_by_name"), "ts": e["ts"], "chat": e["chat"]}
        return out

    def _attachments(self, pid):
        try: return json.load(open(os.path.join(self.st._proj(pid).path, "attachments.json")))
        except (OSError, ValueError): return {}

    def generated(self, pid, member):
        p = self.st._proj(pid); self.st._active(p, member); g = self.st.grant_of(pid, member)
        if not (g["files_download"] or g["files_browse"]): raise S.CollabError("forbidden", "the host has not allowed you to do that")
        wd, files = p.meta["working_dir"], []
        if g["files_download"]:
            for rel, info in self._generated_set(pid, member).items():
                fp = os.path.join(wd, rel)
                if os.path.isfile(fp) and not os.path.islink(fp) and self._gen_ok(g, wd, rel): files.append(dict(info, size=os.path.getsize(fp)))
        atts = []
        if g["files_download"]:
            for aid, a in self._attachments(pid).items():
                if self.st._chat_visible(p, a["chat"], member): atts.append({"id": aid, "name": a["name"], "size": a["size"], "by": a.get("by_name"), "ts": a["ts"], "chat": a["chat"]})
        return {"files": files[:300], "attachments": sorted(atts, key=lambda a: -a["ts"])[:300]}

    def _gen_ok(self, g, wd, rel):
        g2 = dict(g, read_paths=list(g["read_paths"]) + [wd])                    # a file a model made here is shareable, but still never a refused folder, a key file or something of Orbit's own
        try:
            real, _ = self._path(g2, wd, rel, "read")
            return True
        except S.CollabError: return False

    # -- downloading
    def open_file(self, pid, member, rel):
        """-> (absolute path, download name, size). A file in the project folder (files_browse, within the read folders) or one a model made in a chat they can see (files_download)."""
        p = self.st._proj(pid); self.st._active(p, member); g = self.st.grant_of(pid, member); wd = p.meta["working_dir"]
        rel = self._rel(rel)
        if not rel: raise S.CollabError("bad_input", "which file?")
        real = None
        if g["files_browse"]:
            try: real, _ = self._path(g, wd, rel, "read")
            except S.CollabError: real = None
        if real is None and g["files_download"] and rel in self._generated_set(pid, member) and self._gen_ok(g, wd, rel): real, _ = self._path(dict(g, read_paths=list(g["read_paths"]) + [wd]), wd, rel, "read")
        if real is None: raise S.CollabError("forbidden", "you are not allowed to download that")
        if not os.path.isfile(real): raise S.CollabError("not_found", "no such file")
        size = os.path.getsize(real)
        if size > MAX_DOWNLOAD: raise S.CollabError("too_large", "that file is too large to download here")
        return real, os.path.basename(real), size

    def open_attachment(self, pid, member, aid):
        p = self.st._proj(pid); self.st._active(p, member); g = self.st.grant_of(pid, member)
        if not g["files_download"]: raise S.CollabError("forbidden", "the host has not allowed you to do that")
        a = self._attachments(pid).get(aid) if isinstance(aid, str) and AID_RE.match(aid) else None
        if a is None or not self.st._chat_visible(p, a["chat"], member): raise S.CollabError("not_found", "no such attachment")
        path = os.path.join(p.meta["working_dir"], ".orbit-attachments", aid, a["name"])
        if not os.path.isfile(path) or os.path.islink(path): raise S.CollabError("not_found", "that attachment is gone")
        return path, a["name"], os.path.getsize(path)

    # -- editing text
    def read_text(self, pid, member, rel):
        p, g, wd = self._ctx(pid, member, "files_edit")
        real, rel = self._path(g, wd, rel, "write")
        if not os.path.isfile(real): raise S.CollabError("not_found", "no such file")
        if os.path.getsize(real) > MAX_EDIT: raise S.CollabError("too_large", "that file is too large to edit here")
        raw = open(real, "rb").read()
        try:
            if b"\x00" in raw: raise UnicodeDecodeError("x", b"", 0, 1, "binary")
            text = raw.decode("utf-8")
        except UnicodeDecodeError: raise S.CollabError("bad_input", "that is not a text file")
        return {"path": rel, "content": text, "sha": hashlib.sha256(raw).hexdigest()}

    def write_text(self, pid, member, rel, content, base_sha):
        p, g, wd = self._ctx(pid, member, "files_edit", write=True)
        real, rel = self._path(g, wd, rel, "write")
        if not os.path.isfile(real): raise S.CollabError("not_found", "no such file (uploads make new files)")
        if not isinstance(content, str) or len(content.encode()) > MAX_EDIT or "\x00" in content: raise S.CollabError("too_large", "that text is too large or not text")
        if not isinstance(base_sha, str) or sha_file(real) != base_sha: raise S.CollabError("conflict", "the file changed since you opened it; open it again")
        st = os.stat(real); tmp = real + f".orbit-{secrets.token_hex(3)}.tmp"
        try:
            with open(tmp, "wb") as f: f.write(content.encode())
            os.chmod(tmp, st.st_mode & 0o777); os.replace(tmp, real)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
        new = sha_file(real)
        self.st.append_system(pid, "file_edit", {"by": member, "path": rel, "before": base_sha[:12], "after": new[:12]})
        return {"path": rel, "sha": new}

    # -- uploading, in pieces
    def _upath(self, p): return os.path.join(p.path, "uploads")

    def begin_upload(self, pid, member, name, size, target, dir_="", chat="main", text=""):
        flag = {"chat": "files_upload_chat", "dir": "files_upload_dir"}.get(target) if isinstance(target, str) else None
        if flag is None: raise S.CollabError("bad_input", "an upload goes to the chat or the project folder")
        p, g, wd = self._ctx(pid, member, flag, write=True)
        name = clean_name(name)
        if not isinstance(dir_, str) or not isinstance(chat, str): raise S.CollabError("bad_input", "the folder and the chat are text")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0: raise S.CollabError("bad_input", "the size is a number of bytes")
        if size > (MAX_CHAT_FILE if target == "chat" else MAX_DIR_FILE): raise S.CollabError("too_large", "that file is too large")
        meta = {"member": member, "name": name, "size": size, "target": target, "got": 0, "n": 0, "created": self.now()}
        if target == "chat":
            if not g["can_post"]: raise S.CollabError("forbidden", "you cannot post here")
            if not isinstance(chat, str) or chat not in p.meta["chats"] or not self.st._chat_visible(p, chat, member): raise S.CollabError("not_found", "you cannot use that chat")
            used = sum(a["size"] for a in self._attachments(pid).values())
            if used + size > MAX_ATTACHED_TOTAL: raise S.CollabError("too_large", "this project's attachments are full")
            meta.update(chat=chat, text=text if isinstance(text, str) else "")
        else:
            real, rel = self._path(g, wd, dir_, "write")
            if not os.path.isdir(real): raise S.CollabError("not_found", "no such folder")
            meta["dir"] = rel
        up = self._upath(p); os.makedirs(up, mode=0o700, exist_ok=True)
        now = self.now()
        for fn in os.listdir(up):                                                         # forget half-finished uploads after a day
            fp = os.path.join(up, fn)
            try:
                if now - os.path.getmtime(fp) > 86400: os.unlink(fp)
            except OSError: pass
        mine = 0
        for fn in os.listdir(up):
            if fn.endswith(".json"):
                try: mine += json.load(open(os.path.join(up, fn)))["member"] == member
                except (OSError, ValueError, KeyError): pass
        if mine >= UPLOADS_PER_MEMBER: raise S.CollabError("rate_limited", "finish or wait for your other uploads first")
        uid = "u_" + secrets.token_hex(6)
        open(os.path.join(up, uid + ".part"), "wb").close(); self._save_meta(p, uid, meta)
        return {"id": uid, "chunk": CHUNK}

    def _save_meta(self, p, uid, meta):
        tmp = os.path.join(self._upath(p), uid + ".json.tmp")
        with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f: json.dump(meta, f)
        os.replace(tmp, os.path.join(self._upath(p), uid + ".json"))

    def _load_up(self, pid, member, uid):
        p = self.st._proj(pid); self.st._active(p, member, write=True)
        if not isinstance(uid, str) or not UID_RE.match(uid): raise S.CollabError("not_found", "no such upload")
        try: meta = json.load(open(os.path.join(self._upath(p), uid + ".json")))
        except (OSError, ValueError): raise S.CollabError("not_found", "no such upload")
        if meta["member"] != member: raise S.CollabError("not_found", "no such upload")
        return p, meta

    def chunk(self, pid, member, uid, n, data):
        p, meta = self._load_up(pid, member, uid)
        if not isinstance(n, int) or n != meta["n"]: raise S.CollabError("conflict", f"send piece {meta['n']} next")
        if not isinstance(data, (bytes, bytearray)) or len(data) > CHUNK + 1000 or not data: raise S.CollabError("bad_input", "a piece is up to %d bytes" % CHUNK)
        if meta["got"] + len(data) > meta["size"]: raise S.CollabError("too_large", "more data than the size you said")
        with open(os.path.join(self._upath(p), uid + ".part"), "ab") as f: f.write(data)
        meta["got"] += len(data); meta["n"] += 1; self._save_meta(p, uid, meta)
        return {"got": meta["got"]}

    def finish_upload(self, pid, member, uid):
        p, meta = self._load_up(pid, member, uid)
        part = os.path.join(self._upath(p), uid + ".part")
        flag = "files_upload_chat" if meta["target"] == "chat" else "files_upload_dir"
        p2, g, wd = self._ctx(pid, member, flag, write=True)                              # the switch is checked again: it may have been turned off meanwhile
        if os.path.getsize(part) != meta["size"]: raise S.CollabError("conflict", "the file is not complete")
        try:
            if meta["target"] == "dir":
                real, rel = self._path(g, wd, meta["dir"], "write")
                if not os.path.isdir(real): raise S.CollabError("not_found", "no such folder")
                dest, base, ext, k = os.path.join(real, meta["name"]), *os.path.splitext(meta["name"]), 1
                while os.path.lexists(dest): k += 1; dest = os.path.join(real, f"{base} ({k}){ext}")
                ok, why, layer, rr = self.policy.check_path(g, dest, "write", wd)
                if not ok: raise S.CollabError("forbidden", "you are not allowed there")
                shutil.move(part, dest); os.chmod(dest, 0o644)
                self.st.append_system(pid, "file_upload", {"by": member, "target": "dir", "path": os.path.relpath(dest, os.path.realpath(wd)), "size": meta["size"], "sha": sha_file(dest)[:12]})
                out = {"path": os.path.relpath(dest, os.path.realpath(wd))}
            else:
                aid = "a_" + secrets.token_hex(6); adir = os.path.join(wd, ".orbit-attachments", aid); os.makedirs(adir, mode=0o755)
                dest = os.path.join(adir, meta["name"]); shutil.move(part, dest); os.chmod(dest, 0o644)
                idx = self._attachments(pid); idx[aid] = {"name": meta["name"], "size": meta["size"], "chat": meta["chat"], "by": member, "by_name": self.st.member_names(pid).get(member), "ts": self.now()}
                tmp = os.path.join(p.path, "attachments.json.tmp")
                with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f: json.dump(idx, f)
                os.replace(tmp, os.path.join(p.path, "attachments.json"))
                self.st.attach_message(pid, member, meta["chat"], {"id": aid, "name": meta["name"], "size": meta["size"]}, meta.get("text") or "")
                out = {"attachment": aid, "path": f".orbit-attachments/{aid}/{meta['name']}"}
        finally:
            for fn in (uid + ".json", uid + ".part"):
                try: os.unlink(os.path.join(self._upath(p), fn))
                except OSError: pass
        return out

    def abort_upload(self, pid, member, uid):
        p, meta = self._load_up(pid, member, uid)
        for fn in (uid + ".json", uid + ".part"):
            try: os.unlink(os.path.join(self._upath(p), fn))
            except OSError: pass
        return {"ok": True}
