"""Bionic: the model host on this Mac.

Bionic runs local models with LM Studio's runtime and keeps them under
~/.lmstudio, so it already speaks the OpenAI API that the rest of Orbit speaks.
The catch is that the API is only there while Bionic's local server is switched
on, and it starts switched off. This module finds Bionic, asks it what it has,
and turns the server on when a Bionic model is actually picked.

Nothing here downloads a model, and nothing loads or unloads one: Bionic itself
brings a model into memory when the first request for it arrives, and drops it
on its own terms. Listing is read from the `lms` command Bionic ships with, so
it works while the server is off; when the server is on, what it is serving is
read straight from it.
"""
import json, os, subprocess, time, urllib.error, urllib.request

HOME = os.path.expanduser("~/.lmstudio")
LMS = os.path.join(HOME, "bin", "lms")
APP = "/Applications/Bionic.app"
DEFAULT_PORT = 1234
LIST_TTL = 60.0            # `lms` spawns a big binary; the picker asks often
PROBE_TTL = 5.0

_LIST = {"at": 0.0, "rows": []}
_PROBE = {"at": 0.0, "port": 0, "ids": []}
_PORT = {"at": 0.0, "n": 0}
_PS = {"at": 0.0, "rows": []}
PORT_TTL = 300.0
PS_TTL = 5.0


def installed():
    """Bionic is on this Mac (its CLI is what everything else here needs)."""
    return os.path.isfile(LMS) and os.access(LMS, os.X_OK)


def _lms(args, timeout=25):
    """One `lms ... --json` call. None when Bionic is missing or says nothing."""
    if not installed(): return None
    try:
        r = subprocess.run([LMS, *args, "--json"], capture_output=True, text=True,
                           timeout=timeout)
    except Exception:
        return None
    out = (r.stdout or "").strip()
    if not out: return None
    try: return json.loads(out)
    except ValueError: return None


def port():
    """The port Bionic's server uses — the one it was last started on, which is
    not always 1234. Asking costs a process, so the answer is kept for a while."""
    now = time.time()
    if _PORT["n"] and now - _PORT["at"] < PORT_TTL:
        return _PORT["n"]
    d = _lms(["server", "status"], timeout=10)
    n = int((d or {}).get("port") or DEFAULT_PORT)
    _PORT.update(at=now, n=n)
    return n


def base_url(p=None):
    return f"http://127.0.0.1:{int(p or DEFAULT_PORT)}/v1"


def serving(p=None, timeout=1.0):
    """The model ids the server is serving right now, or [] if it is not up.

    A plain HTTP probe: far cheaper than `lms`, and the honest answer to
    "can Orbit reach it this second".
    """
    p = int(p or DEFAULT_PORT)
    now = time.time()
    if _PROBE["port"] == p and now - _PROBE["at"] < PROBE_TTL:
        return list(_PROBE["ids"])
    ids = []
    try:
        with urllib.request.urlopen(base_url(p) + "/models", timeout=timeout) as r:
            ids = [m.get("id") for m in (json.load(r).get("data") or []) if m.get("id")]
    except Exception:
        ids = []
    _PROBE.update(at=now, port=p, ids=ids)
    return list(ids)


def status():
    """{"installed", "running", "port"} — what Bionic's own server says, and if it
    cannot be asked, what answers on the usual port."""
    st = {"installed": installed(), "running": False, "port": DEFAULT_PORT}
    if not st["installed"]:
        return st
    st["port"] = port()
    st["running"] = bool(serving(st["port"]))
    st["loaded"] = loaded()
    return st


def start(timeout=30):
    """Switch Bionic's server on and wait for it to answer. Already-on is a
    success. Returns (ok, message)."""
    if not installed():
        return False, "Bionic is not installed on this Mac"
    st = status()
    if st["running"]:
        return True, f"already running on port {st['port']}"
    try:
        r = subprocess.run([LMS, "server", "start"], capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    _PORT["at"] = 0.0                       # it may have come up on another port
    p = port()
    deadline = time.time() + 10
    while time.time() < deadline:
        _PROBE["at"] = 0.0
        if serving(p): return True, f"started on port {p}"
        time.sleep(0.5)
    tail = ((r.stderr or r.stdout or "").strip().splitlines() or [""])[-1]
    return False, tail[:200] or "the server did not come up"


def ensure():
    """Make sure a Bionic model can be reached, starting the server if it is off.
    Returns the base URL, or "" when Bionic cannot serve."""
    if not installed(): return ""
    p = port()
    if serving(p): return base_url(p)
    ok, _ = start()
    return base_url(port()) if ok else ""


def loaded(max_age=PS_TTL):
    """What Bionic is holding in this Mac's memory right now:
    [{"model", "label", "context", "bytes"}]. Empty when it is holding nothing."""
    if not installed(): return []
    now = time.time()
    if now - _PS["at"] < max_age:
        return [dict(r) for r in _PS["rows"]]
    rows = []
    for r in (_lms(["ps"], timeout=15) or []):
        if not isinstance(r, dict) or not r.get("modelKey"): continue
        used = r.get("lastUsedTime")
        rows.append({"model": r["modelKey"], "label": _label(r),
                     "context": int(r.get("contextLength") or 0),
                     "bytes": int(r.get("sizeBytes") or 0),
                     # when anything last asked it something (Orbit, Bionic itself,
                     # anything else on this Mac), and whether it is answering now
                     "used_at": (float(used) / 1000 if used else None),
                     "busy": str(r.get("status") or "").lower() not in ("idle", "")})
    _PS.update(at=now, rows=rows)
    return [dict(r) for r in rows]


def is_loaded(model):
    """This model's weights are in memory, so the next request answers straight away."""
    return any(r["model"] == model for r in loaded())


def load(model, timeout=600):
    """Put a model in memory now, so the next message does not wait for it.
    Bionic picks the context length and placement it would pick anyway."""
    if not installed(): return False, "Bionic is not installed on this Mac"
    if not model: return False, "no model named"
    if is_loaded(model): return True, "already in memory"
    if not ensure(): return False, "Bionic's server would not start"
    try:
        r = subprocess.run([LMS, "load", model, "-y"], capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    _PS["at"] = 0.0
    _LIST["at"] = 0.0
    if r.returncode:
        tail = ((r.stderr or r.stdout or "").strip().splitlines() or [""])[-1]
        return False, tail[:200] or "it would not load"
    return True, model + " is in memory"


def idle_models(minutes):
    """Models nobody has used for this many minutes and that are not answering now —
    the ones whose memory can be given back without interrupting anything."""
    if minutes <= 0: return []
    now = time.time()
    out = []
    for r in loaded(max_age=0):
        if r["busy"]: continue
        used = r.get("used_at")
        if used and (now - used) / 60.0 < minutes: continue
        if not used: continue                 # never used: it was loaded for a reason
        out.append({**r, "idle_min": (now - used) / 60.0})
    return out


def unload(model=""):
    """Give a model's memory back. Bionic is an app you use yourself, so this only ever
    happens when you ask for it. Returns (ok, message)."""
    if not installed(): return False, "Bionic is not installed on this Mac"
    args = ["unload", model] if model else ["unload", "--all"]
    try:
        r = subprocess.run([LMS, *args], capture_output=True, text=True, timeout=60)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    _PS["at"] = 0.0
    _LIST["at"] = 0.0
    if r.returncode:
        tail = ((r.stderr or r.stdout or "").strip().splitlines() or [""])[-1]
        return False, tail[:200] or "it would not unload"
    return True, (model or "everything") + " unloaded"


def _label(row):
    name = (row.get("displayName") or row.get("modelKey") or "").strip()
    return name or row.get("modelKey") or "?"


def models(max_age=LIST_TTL):
    """Every model Bionic has on disk, whether or not its server is on.

    [{"model", "label", "context", "vision", "tools", "loaded"}] — text models
    only; an embedding model is not something you can hold a conversation with.
    """
    if not installed(): return []
    now = time.time()
    if now - _LIST["at"] < max_age and _LIST["rows"]:
        return [dict(r) for r in _LIST["rows"]]
    have = _lms(["ls"], timeout=25)
    if not isinstance(have, list): return [dict(r) for r in _LIST["rows"]]
    live = {}
    for r in (_lms(["ps"], timeout=15) or []):
        if isinstance(r, dict) and r.get("modelKey"): live[r["modelKey"]] = r
    rows = []
    for r in have:
        if not isinstance(r, dict) or r.get("type") != "llm": continue
        key = r.get("modelKey")
        if not key: continue
        loaded = live.get(key) or {}
        ctx = loaded.get("contextLength") or r.get("maxContextLength") or 131072
        rows.append({"model": key, "label": _label(r), "context": int(ctx),
                     "vision": bool(r.get("vision")), "tools": bool(r.get("trainedForToolUse")),
                     "loaded": bool(loaded)})
    _LIST.update(at=now, rows=rows)
    return [dict(r) for r in rows]


def catalogue_models():
    """Bionic's models in the shape Orbit's model registry uses."""
    return [{"provider": "bionic", "model": r["model"], "label": r["label"],
             "context": r["context"], "thinking": True, "vision": r["vision"],
             "tools": r["tools"]}
            for r in models()]
