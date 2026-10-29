"""Is there a newer Orbit? One read of the public release list, and what it means for this copy.

The Mac app already updates itself from its own menu; this is for everything else that shows Orbit -- the web page, a
browser, a copy run from source, the phone through its Mac -- so each can say "a new version is out" and where to get it.
It only ever reads (one GET of the public GitHub release list) and sends nothing about you or this machine: no id, no
version, no list of what you use. It never downloads or installs anything: the link opens the release page, and the Mac
app's own updater (which checks every download against the release's SHA256SUMS) does the installing.

Everything that reaches the world (the fetch, the clock) is passed in, so the tests never touch the network.
"""
import json, os, re, threading, time, urllib.request

REPO = "Micropeptide/Orbit"
TAG_PREFIX = "desktop-v"
FEED = f"https://api.github.com/repos/{REPO}/releases?per_page=20"
PAGE = f"https://github.com/{REPO}/releases"
DOWNLOAD_BASE = f"https://github.com/{REPO}/releases/download/"
MODES, INTERVALS, CHANNELS = ("notify", "off"), (1, 6, 24, 168), ("stable", "beta")
DEFAULTS = {"mode": "notify", "every_h": 24, "channel": "stable", "skipped": ""}
MIN_GAP_S = 20             # a manual check this soon after another returns what it has: the feed allows few reads an hour
NOTES_MAX = 1500

SEMVER = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z.-]+)?$")


# ---------------------------------------------------------------------------------------------------------- versions

def parse_version(v):
    """'1.2.3-beta.1' -> (1, 2, 3, ['beta', 1]); None when it is not a version."""
    m = SEMVER.match(str(v if v is not None else "").strip())
    if not m: return None
    pre = [int(x) if x.isdigit() else x for x in m[4].split(".")] if m[4] else []
    return int(m[1]), int(m[2]), int(m[3]), pre


def _cmp_pre(a, b):
    if not a and not b: return 0
    if not a: return 1                  # 1.0.0 is newer than 1.0.0-beta
    if not b: return -1
    for x, y in zip(a, b):
        if x == y: continue
        if isinstance(x, int) and isinstance(y, int): return -1 if x < y else 1
        if isinstance(x, int): return -1          # a number sorts below a word
        if isinstance(y, int): return 1
        return -1 if x < y else 1
    return (len(a) > len(b)) - (len(a) < len(b))


def compare(a, b):
    """-1, 0 or 1 by semantic-version precedence; None when either is not a version."""
    pa, pb = parse_version(a), parse_version(b)
    if pa is None or pb is None: return None
    if pa[:3] != pb[:3]: return -1 if pa[:3] < pb[:3] else 1
    return _cmp_pre(pa[3], pb[3])


def is_newer(candidate, current):
    return compare(candidate, current) == 1


def current_version(root, env=None):
    """The release this copy is: ORBIT_VERSION (the Mac app sets it), else the desktop app's package.json, else a VERSION file."""
    env = os.environ if env is None else env
    if parse_version(env.get("ORBIT_VERSION")): return str(env["ORBIT_VERSION"]).strip().lstrip("v")
    for rel, key in (("desktop/package.json", "version"), ("VERSION", None)):
        try:
            raw = open(os.path.join(root, rel), encoding="utf-8").read()
            v = json.loads(raw).get(key) if key else raw.strip()
            if parse_version(v): return str(v).lstrip("v")
        except (OSError, ValueError, AttributeError): pass
    return None


def install_kind(root, env=None):
    """'app' for the packaged Mac app, 'source' for a copy run from a folder (where updating is the person's own git or copy)."""
    env = os.environ if env is None else env
    return "app" if env.get("ORBIT_PACKAGED") == "1" or ".app/Contents/" in os.path.abspath(root) else "source"


# ---------------------------------------------------------------------------------------------------------- releases

def _safe_url(u, prefix, fallback):
    return u if isinstance(u, str) and u.startswith(prefix) else fallback


def pick(releases, channel="stable"):
    """The newest usable release in the feed, as plain data -- or None. A draft, another product's tag, an unparseable
    version, or (on the stable channel) a prerelease is passed over. Links are kept only when they stay on the project's own
    GitHub pages: the feed is data from the network, never trusted to send the person somewhere else."""
    best = None
    for r in releases if isinstance(releases, list) else []:
        if not isinstance(r, dict) or r.get("draft"): continue
        tag = str(r.get("tag_name") or "")
        if not tag.startswith(TAG_PREFIX): continue
        ver = tag[len(TAG_PREFIX):]
        pv = parse_version(ver)
        if pv is None: continue
        if (r.get("prerelease") or pv[3]) and channel != "beta": continue
        if best is None or compare(ver, best[0]) == 1: best = (ver, r)
    if best is None: return None
    ver, r = best
    dmg = sums = None
    for a in r.get("assets") or []:
        name, url = str(a.get("name") or ""), _safe_url(a.get("browser_download_url"), DOWNLOAD_BASE, "")
        if not url: continue
        if name.endswith(".dmg") and dmg is None: dmg = {"name": name, "url": url, "size": int(a.get("size") or 0)}
        elif name == "SHA256SUMS.txt": sums = url
    return {"version": ver, "tag": str(r.get("tag_name")), "name": str(r.get("name") or ""),
            "notes": str(r.get("body") or "")[:NOTES_MAX], "published": str(r.get("published_at") or ""),
            "prerelease": bool(r.get("prerelease") or parse_version(ver)[3]),
            "page": _safe_url(r.get("html_url"), f"https://github.com/{REPO}/releases", PAGE), "dmg": dmg, "sums": sums}


def fetch_feed(url=FEED, timeout=10):
    """The one read: a GET with a plain agent string and nothing else."""
    req = urllib.request.Request(url, headers={"User-Agent": "Orbit-update-check", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read(2_000_000).decode("utf-8", "replace"))


def friendly_error(e):
    s = str(e)
    if "403" in s or "429" in s: return "GitHub is limiting reads for now; try again later."
    if "404" in s: return "The release list was not found."
    if isinstance(e, ValueError): return "The release list was not understood."
    return "Could not reach the release list (offline?)."


# ---------------------------------------------------------------------------------------------------------- the state

class Updates:
    """What this copy knows about releases: preferences, the last answer, and when to ask again."""

    def __init__(self, path, root, fetch=None, now=time.time, env=None):
        self.path, self.root, self.fetch, self.now, self.env = path, root, fetch or fetch_feed, now, env
        self.lock = threading.RLock()         # check() answers with status() from inside its own lock
        self.busy = False
        self.d = self._load()

    # -- storage
    def _load(self):
        try: d = json.load(open(self.path, encoding="utf-8"))
        except (OSError, ValueError): d = {}
        d = d if isinstance(d, dict) else {}
        prefs = dict(DEFAULTS)
        prefs.update(self._clean(d.get("prefs") if isinstance(d.get("prefs"), dict) else {}))
        def num(x):
            try: return float(x or 0)
            except (TypeError, ValueError): return 0.0
        return {"prefs": prefs, "tried": num(d.get("tried")), "checked": num(d.get("checked")),
                "latest": d.get("latest") if isinstance(d.get("latest"), dict) else None, "error": str(d.get("error") or "")}

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            json.dump(self.d, open(tmp, "w", encoding="utf-8"), indent=1)
            os.replace(tmp, self.path)
        except OSError: pass

    @staticmethod
    def _clean(p):
        out = {}
        if p.get("mode") in MODES: out["mode"] = p["mode"]
        if p.get("every_h") in INTERVALS: out["every_h"] = p["every_h"]
        if p.get("channel") in CHANNELS: out["channel"] = p["channel"]
        if "skipped" in p: out["skipped"] = str(p["skipped"])[:40] if parse_version(p["skipped"]) or not p["skipped"] else ""
        return out

    # -- reading
    def current(self): return current_version(self.root, self.env)

    def next_check(self):
        if self.d["prefs"]["mode"] == "off": return None
        return self.d["tried"] + self.d["prefs"]["every_h"] * 3600

    def due(self):
        nxt = self.next_check()
        return nxt is not None and self.now() >= nxt

    def status(self, kick=False):
        """What the page shows. kick=True also starts a background check when one is due, without waiting for it."""
        if kick and self.due() and not self.busy:
            threading.Thread(target=self.check, kwargs={"force": False}, daemon=True).start()
        with self.lock:
            cur, latest, prefs = self.current(), self.d["latest"], dict(self.d["prefs"])
            newer = bool(latest and cur and is_newer(latest["version"], cur))
            return {"current": cur, "kind": install_kind(self.root, self.env), "prefs": prefs, "checked": self.d["checked"] or None,
                    "latest": latest, "newer": newer, "skipped": bool(newer and latest["version"] == prefs["skipped"]),
                    "error": self.d["error"], "next_check": self.next_check(), "checking": self.busy, "page": PAGE}

    # -- doing
    def check(self, force=True):
        """Ask for the release list now (unless one was asked for a moment ago, or the person turned checking off and this is not a
        manual check). An error keeps the last good answer and says what went wrong."""
        with self.lock:
            if self.busy: return self.status()
            if not force and self.d["prefs"]["mode"] == "off": return self.status()
            if self.now() - self.d["tried"] < MIN_GAP_S: return self.status()
            self.busy, self.d["tried"] = True, self.now()
            channel = self.d["prefs"]["channel"]
        try:
            latest, err = pick(self.fetch(), channel), ""
        except Exception as e:                                    # offline, rate-limited, malformed: never takes the page down
            latest, err = None, friendly_error(e)
        with self.lock:
            self.busy = False
            if err: self.d["error"] = err
            else: self.d.update(latest=latest, checked=self.now(), error="")
            self._save()
        return self.status()

    def configure(self, **kw):
        with self.lock:
            self.d["prefs"].update(self._clean(kw))
            self._save()
        return self.status()

    def skip(self, version=None):
        """Stop reminding about one version (the newest known one when none is named)."""
        with self.lock:
            v = version or (self.d["latest"] or {}).get("version") or ""
            self.d["prefs"]["skipped"] = v if parse_version(v) else ""
            self._save()
        return self.status()
