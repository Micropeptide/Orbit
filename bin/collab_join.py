"""Joining someone else's shared project from this Orbit: read the invitation link, show the account (if signed in) to the host with a proof made for that
host alone, and give back the address that opens the project. Nothing here trusts the link beyond http(s) and its three plain fields."""
import json, re, urllib.error, urllib.parse, urllib.request

MAX_REPLY = 100_000
TIMEOUT_S = 15
PID_RE, IID_RE, SECRET_RE = re.compile(r"^p_[0-9a-f]{12}$"), re.compile(r"^i_[0-9a-f]{10}$"), re.compile(r"^[A-Za-z0-9_-]{16,80}$")


class JoinError(Exception):
    pass


RELAY_PATH = re.compile(r"^/r/p_[0-9a-f]{12}$")


def _origin(base):
    """The address of a host's door: scheme://host[:port], or for a project published through the Orbit service scheme://host/r/<project>."""
    u = urllib.parse.urlsplit(base or "")
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password or len(base) > 300 or u.query or u.fragment: raise JoinError("that does not look like a project address")
    path = u.path.rstrip("/")
    if path and not (u.scheme == "https" and RELAY_PATH.match(path)): raise JoinError("that does not look like a project address")
    return f"{u.scheme}://{u.netloc}{path}"


def parse_link(text):
    """-> {"base", "p", "i", "s"} from an invitation link: the web form (https://host/join?p=&i=&s=, or https://service/r/<project>/join?...) or the app form (orbit://join?host=&p=&i=&s=)."""
    text = (text or "").strip()
    u = urllib.parse.urlsplit(text)
    q = urllib.parse.parse_qs(u.query)
    one = lambda k: (q.get(k) or [""])[0]
    if u.scheme == "orbit" and u.netloc == "join": base = one("host")
    elif u.scheme in ("http", "https") and u.path.rstrip("/").endswith("/join"): base = f"{u.scheme}://{u.netloc}{u.path.rstrip('/')[:-len('/join')]}"
    else: raise JoinError("that is not an Orbit invitation link")
    out = {"base": _origin(base), "p": one("p"), "i": one("i"), "s": one("s")}
    if not (PID_RE.match(out["p"]) and IID_RE.match(out["i"]) and SECRET_RE.match(out["s"])): raise JoinError("that invitation link is damaged")
    return out


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json", "User-Agent": "Orbit-join"})
    try:
        r = _OPENER.open(req, timeout=TIMEOUT_S); status, raw = r.status, r.read(MAX_REPLY)
    except urllib.error.HTTPError as e: status, raw = e.code, e.read(MAX_REPLY)
    except (urllib.error.URLError, OSError, ValueError): raise JoinError("could not reach that host")
    try: return status, json.loads(raw or b"{}")
    except ValueError: return status, {}


def parse_project(text):
    """-> {"base", "p"} from a plain project address with no invitation in it: https://service/r/<project>[/] or orbit://join?host=<that>&p=<project>. For a project the host
    added this account to by its id: there is no secret to carry, the account is the key."""
    text = (text or "").strip()
    u = urllib.parse.urlsplit(text)
    q = urllib.parse.parse_qs(u.query)
    if u.scheme == "orbit" and u.netloc == "join": base, pid = (q.get("host") or [""])[0], (q.get("p") or [""])[0]
    elif u.scheme == "https" and not u.query and not u.fragment: base, pid = text.rstrip("/"), text.rstrip("/").rsplit("/", 1)[-1]
    else: raise JoinError("that is not a project address")
    base = _origin(base)
    if not RELAY_PATH.match(urllib.parse.urlsplit(base).path) or not PID_RE.match(pid) or not base.endswith("/" + pid): raise JoinError("that is not a project address")
    return {"base": base, "p": pid}


def join(link, name, accounts=None, post=_post):
    """Join with `link`. `accounts` (an accounts_client.Accounts) is shown to the host if signed in. -> {"url": the address that opens the project, "signed_in": bool}.
    A plain project address (no invitation) works for an account the host has already added or invited by its id: it signs in."""
    try: t = parse_link(link)
    except JoinError as first:
        try: t = dict(parse_project(link), i="", s="")
        except JoinError: raise first
    name = (name or "").strip()[:40] or "Guest"
    proof = accounts.join_proof(t["base"]) if accounts is not None else None
    if not t["i"]:                                                 # no invitation in the address: only the account can get in
        if not proof: raise JoinError("sign in to your Orbit account first (Settings > General > Orbit account), then paste the address again")
        status, j = post(f"{t['base']}/api/collab/p/{t['p']}/signin", {"account_token": proof, "name": name})
    else:
        body = {"p": t["p"], "i": t["i"], "s": t["s"], "name": name}
        if proof: body["account_token"] = proof
        status, j = post(t["base"] + "/api/collab/join", body)
    if status != 200 or not isinstance(j, dict) or not j.get("token"):
        msg = (j or {}).get("error") if isinstance(j, dict) else None
        raise JoinError(msg[:300] if isinstance(msg, str) and msg else "the host did not accept that invitation")
    frag = urllib.parse.urlencode({"t": j["token"], "p": j.get("project") or t["p"], "n": (j.get("member") or {}).get("name") or name})
    return {"url": f"{t['base']}/#{frag}", "signed_in": bool(proof)}
