"""A backup of one shared project, and putting it back: the whole record (every event, hash-chained), the people and what each may do. Login tokens are not in it
(devices are emptied) and neither are invitations, so a backup that leaks lets nobody in; people come back with a new invitation or their Orbit account.

A restore checks the chain again from the file itself, refuses anything but the five expected names and sizes, and never overwrites a project that exists.
"""
import json, os, re, secrets, time, zipfile

import collab_store as S

NAMES = ("MANIFEST.json", "project.json", "members.json", "grants.json", "events.jsonl")
LIMITS = {"MANIFEST.json": 1 << 16, "project.json": 1 << 22, "members.json": 1 << 22, "grants.json": 1 << 22, "events.jsonl": 1 << 28}
FORMAT = 1


class BackupError(Exception):
    pass


def _safe(name):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name or "project").strip("._")[:40] or "project"


def backup(store, pid, dest_dir, now=time.time):
    v = store.verify(pid)
    if not v["ok"]: raise BackupError("this project's record does not check out (" + str(v.get("why")) + "), so it was not backed up")
    p = store._proj(pid)
    with p.lock:
        read = lambda n: open(os.path.join(p.path, n), "rb").read()
        members = json.loads(read("members.json") or b"{}")
        for m in members.values(): m["devices"] = []
        events = read("events.jsonl")
        last = json.loads(events.splitlines()[-1])["hash"] if events.strip() else S.GENESIS
        files = {"project.json": read("project.json"), "members.json": json.dumps(members, sort_keys=True).encode(), "grants.json": read("grants.json"), "events.jsonl": events,
                 "MANIFEST.json": json.dumps({"format": FORMAT, "pid": pid, "name": p.meta.get("name"), "events": v["events"], "last_hash": last, "created": now()}, sort_keys=True).encode()}
    os.makedirs(dest_dir, mode=0o700, exist_ok=True)
    out = os.path.join(dest_dir, f"{_safe(p.meta.get('name'))}-{pid}-{time.strftime('%Y%m%d-%H%M%S', time.localtime(now()))}.orbit-project.zip")
    tmp = out + ".tmp"
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as fh, zipfile.ZipFile(fh, "w", zipfile.ZIP_DEFLATED) as z:
        for n in NAMES: z.writestr(n, files[n])
    os.replace(tmp, out)
    return {"path": out, "events": v["events"], "pid": pid}


def _read_zip(path):
    if not os.path.isfile(path) or os.path.getsize(path) > (1 << 29): raise BackupError("that is not a backup file")
    try: z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError): raise BackupError("that is not a backup file")
    with z:
        infos = {i.filename: i for i in z.infolist()}
        if set(infos) != set(NAMES) or len(z.infolist()) != len(NAMES): raise BackupError("that is not an Orbit project backup")
        out = {}
        for n in NAMES:
            if infos[n].file_size > LIMITS[n]: raise BackupError("that backup is larger than a project can be")
            with z.open(n) as f:
                out[n] = f.read(LIMITS[n] + 1)
            if len(out[n]) > LIMITS[n]: raise BackupError("that backup is larger than a project can be")
    return out


def restore(root, path):
    """Put a backup back under `root` (the store's folder). -> {"pid", "name", "events"}. Refuses a damaged file or a project that already exists."""
    files = _read_zip(path)
    try: man = json.loads(files["MANIFEST.json"])
    except ValueError: raise BackupError("that backup's label is damaged")
    pid = man.get("pid") if isinstance(man, dict) else None
    if man.get("format") != FORMAT or not isinstance(pid, str) or not S.PID_RE.match(pid): raise BackupError("that backup is from a different version or damaged")
    prev, n = S.GENESIS, 0
    for i, ln in enumerate(files["events.jsonl"].decode("utf-8", "replace").splitlines(), 1):
        try: e = json.loads(ln)
        except ValueError: raise BackupError(f"the record is damaged at event {i}")
        h = e.pop("hash", None)
        if e.get("seq") != i or e.get("prev") != prev or S._sha(S._canon(e)) != h: raise BackupError(f"the record has been changed: it breaks at event {i}")
        prev, n = h, n + 1
    if prev != man.get("last_hash") or n != man.get("events"): raise BackupError("the record does not match its label: part of it is missing or was added")
    for name in ("project.json", "members.json", "grants.json"):
        try: ok = isinstance(json.loads(files[name] or b"{}"), dict)
        except ValueError: ok = False
        if not ok: raise BackupError(f"{name} is damaged")
    members = json.loads(files["members.json"] or b"{}")
    for m in members.values(): m["devices"] = []                                   # whatever the file says, nobody is let in by it
    files["members.json"] = json.dumps(members, sort_keys=True).encode()
    os.makedirs(root, mode=0o700, exist_ok=True)
    dest = os.path.join(root, pid)
    if os.path.exists(dest): raise BackupError("that project already exists here; it was not touched")
    tmp = os.path.join(root, ".restore-" + secrets.token_hex(4))
    os.mkdir(tmp, 0o700)
    try:
        for name in ("project.json", "members.json", "grants.json", "events.jsonl"):
            with os.fdopen(os.open(os.path.join(tmp, name), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as f: f.write(files[name])
        with os.fdopen(os.open(os.path.join(tmp, "invites.json"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f: f.write("{}")
        os.rename(tmp, dest)
    except BaseException:
        import shutil; shutil.rmtree(tmp, True); raise
    return {"pid": pid, "name": man.get("name"), "events": n}
