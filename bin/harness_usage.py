"""What each provider account has used, and roughly what is left.

Providers such as OpenCode Go give each model a monthly allowance in dollars,
with 20% of it usable in any 5 hours and 50% in any week, but offer no API to
ask how much is left. Every request through Orbit's gateway is recorded here
(tokens, model, account), priced with the provider's published prices, and
compared with those allowances. It is an estimate: use from other apps on the
same account is not counted.

Accounts that report their quota is used up are marked, so the gateway moves
on to the next account until the mark expires.
"""
import html, json, os, re, threading, time, urllib.error, urllib.request

WINDOWS = (("5h", 5 * 3600, 0.20), ("week", 7 * 86400, 0.50), ("month", 30 * 86400, 1.00))
_LOCK = threading.Lock()
_ROWS = {"path": None, "rows": None}


def _dir(root):
    d = os.path.join(root, "config", "claude")
    os.makedirs(d, exist_ok=True)
    return d


def _ledger(root):
    return os.path.join(_dir(root), "usage.jsonl")


def _load(root):
    path = _ledger(root)
    if _ROWS["path"] != path or _ROWS["rows"] is None:
        rows = []
        try:
            with open(path) as fh:
                for line in fh:
                    try: rows.append(json.loads(line))
                    except ValueError: pass
        except OSError:
            pass
        cutoff = time.time() - 31 * 86400
        _ROWS.update(path=path, rows=[r for r in rows if r.get("t", 0) >= cutoff])
    return _ROWS["rows"]


def record(root, provider, account, model, usage, t=None):
    """One request's tokens. usage: Anthropic-style counts."""
    u = usage or {}
    row = {"t": t or time.time(), "p": provider, "a": account, "m": model,
           "in": int(u.get("input_tokens") or 0), "out": int(u.get("output_tokens") or 0),
           "cr": int(u.get("cache_read_input_tokens") or 0), "cw": int(u.get("cache_creation_input_tokens") or 0)}
    if not (row["in"] or row["out"] or row["cr"]): return None
    row["usd"] = round(cost(root, provider, model, row), 6)
    with _LOCK:
        _load(root).append(row)
        with open(_ledger(root), "a") as fh:
            fh.write(json.dumps(row) + "\n")
    return row


# ------------------------------------------------------------------ prices and allowances

def _norm(label):
    s = re.sub(r"\(.*?\)", "", str(label or "")).strip().lower()
    s = re.sub(r"\bfree\b", "", s).strip()
    return re.sub(r"[\s_]+", "-", s)


def _dollars(s, pick=max):
    # "$15 $60 4x · Ends Sep 20" (peak / off-peak): cells can hold several amounts
    vals = [float(v) for v in re.findall(r"\$\s*([0-9]+(?:\.[0-9]+)?)(?=[^0-9.]|$)", (s or "").replace("$", " $"))]
    return pick(vals) if vals else None


def limits_path(root):
    return os.path.join(_dir(root), "opencode-go-limits.json")


def refresh_limits(root, timeout=30):
    """OpenCode Go's published prices and monthly allowances, per model."""
    req = urllib.request.Request("https://opencode.ai/docs/go/", headers={"User-Agent": "Mozilla/5.0"})
    page = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")
    i = page.find("Usage limits")
    out = {}
    for row in re.findall(r"<tr>(.*?)</tr>", page[i:i + 80000] if i >= 0 else page, re.S):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        if len(cells) < 6 or cells[0] == "Model": continue
        mid = _norm(cells[0])
        price = {"input": _dollars(cells[1]) or 0.0, "output": _dollars(cells[2]) or 0.0,
                 "cache_read": _dollars(cells[3]) or 0.0}
        monthly = None if "unlimited" in cells[5].lower() else _dollars(cells[5], min)   # peak allowance: conservative
        prev = out.get(mid)
        # peak/off-peak and long-context rows: keep the higher price, a conservative estimate
        if prev:
            price = {k: max(price[k], prev["price"][k]) for k in price}
            monthly = monthly if monthly is not None else prev.get("monthly")
        out[mid] = {"label": re.sub(r"\s*\(.*?\)", "", cells[0]).strip(), "price": price, "monthly": monthly}
    if out:
        tmp = limits_path(root) + ".tmp"
        with open(tmp, "w") as fh: json.dump({"at": time.time(), "models": out}, fh, indent=1)
        os.replace(tmp, limits_path(root))
    return len(out)


def limits_meta(root):
    try: return json.load(open(limits_path(root)))
    except (OSError, ValueError): return None


_LIMITS = {}


def limits(root):
    path = limits_path(root)
    try: mt = os.path.getmtime(path)
    except OSError: return {}
    hit = _LIMITS.get(path)
    if hit and hit[0] == mt: return hit[1]
    try: rows = json.load(open(path)).get("models") or {}
    except (OSError, ValueError): rows = {}
    _LIMITS[path] = (mt, rows)
    return rows


def limit_for(root, model):
    """OpenCode Go's row for a model id ("muse-spark-1.3-contributor" is listed as "Muse Spark 1.3")."""
    rows = limits(root)
    m = str(model or "").lower()
    if m in rows: return rows[m]
    near = [k for k in rows if m.startswith(k + "-")]
    return rows[max(near, key=len)] if near else {}


def _models_dev_cost(root, provider, model):
    try:
        import harness
        d = json.load(open(os.path.join(root, "config", "models-dev.json")))
        m = ((d.get(harness.MODELS_DEV_ID.get(provider, provider)) or {}).get("models") or {}).get(model) or {}
        return m.get("cost") or {}
    except (OSError, ValueError, ImportError):
        return {}


def cost(root, provider, model, row):
    """Dollars for one request's tokens (prices are per million tokens)."""
    price = None
    if provider in ("opencode-go",):
        price = limit_for(root, model).get("price")
    price = price or _models_dev_cost(root, provider, model)
    if not price: return 0.0
    return (row.get("in", 0) * float(price.get("input") or 0) + row.get("out", 0) * float(price.get("output") or 0)
            + row.get("cr", 0) * float(price.get("cache_read") or 0)
            + row.get("cw", 0) * float(price.get("cache_write") or price.get("input") or 0)) / 1e6


def summary(root, provider, account=None, model=None, now=None):
    """Spend in each window, and what is left of the allowance where one is known."""
    now = now or time.time()
    rows = [r for r in _load(root) if r.get("p") == provider and (account is None or r.get("a") == account)
            and (model is None or r.get("m") == model)]
    monthly = limit_for(root, model).get("monthly") if (model and provider == "opencode-go") else None
    out = {"requests": len(rows), "windows": {}}
    for name, secs, share in WINDOWS:
        spent = sum(r.get("usd", 0) for r in rows if now - r.get("t", 0) <= secs)
        w = {"spent": round(spent, 4), "tokens": sum(r.get("in", 0) + r.get("out", 0) + r.get("cr", 0)
                                                     for r in rows if now - r.get("t", 0) <= secs)}
        if monthly:
            allow = monthly * share
            w.update(allowance=round(allow, 2), left_pct=max(0, round(100 * (1 - spent / allow))))
        out["windows"][name] = w
    if monthly: out["monthly"] = monthly
    return out


# ------------------------------------------------------------------ used-up accounts

def _state_path(root):
    return os.path.join(_dir(root), "accounts-state.json")


def _state(root):
    try: return json.load(open(_state_path(root)))
    except (OSError, ValueError): return {}


QUOTA_WORDS = ("quota", "exceeded", "insufficient", "credit", "balance", "exhausted", "usage limit",
               "subscription limit", "weekly limit", "monthly limit", "hour limit")


def quota_block(status, raw, retry_after=None):
    """How long an account should be skipped after this error reply, in seconds — or
    None when the error says nothing about the account (a bad request, a brief blip).

    OpenCode Go answers a used-up allowance with 429 {"error": {"type":
    "GoUsageLimitError", ...}, "metadata": {"limitName": "5 hour"|"weekly"|"monthly"}}
    and a retry-after header; a plain RateLimitError is only a short wait."""
    try:
        j = json.loads(raw) if isinstance(raw, str) and raw.strip().startswith("{") else {}
    except ValueError:
        j = {}
    err = j.get("error") if isinstance(j.get("error"), dict) else {}
    etype, msg = str(err.get("type") or ""), (str(err.get("message") or "") + " " + str(raw or "")).lower()
    try: wait = float(retry_after) if retry_after not in (None, "") else None
    except (TypeError, ValueError): wait = None
    limit = str((j.get("metadata") or {}).get("limitName") or "").lower()
    if etype in ("GoUsageLimitError", "FreeUsageLimitError", "BlackUsageLimitError") or status == 402:
        if wait: return wait
        return 7 * 86400 if "week" in (limit or msg) else 30 * 86400 if "month" in (limit or msg) else 5 * 3600
    if etype == "RateLimitError":
        return min(wait or 60, 3600)
    if status == 429 and any(w in msg for w in QUOTA_WORDS):
        if wait: return wait
        return 7 * 86400 if "week" in msg else 30 * 86400 if "month" in msg else 5 * 3600 if "hour" in msg else 3600
    if status in (401, 403) and any(w in msg for w in ("quota", "subscription", "insufficient", "balance", "credit")):
        return wait or 3600
    return None


def is_quota_error(status, message):
    """A reply that means this account cannot be used for now (as opposed to a bad request)."""
    return quota_block(status, message) is not None


def mark_exhausted(root, provider, account, message="", hours=None, seconds=None):
    msg = (message or "").lower()
    if seconds is not None:
        hours = float(seconds) / 3600
    if hours is None:
        hours = 24 * 7 if "week" in msg else 24 * 30 if "month" in msg else 5 if ("5" in msg and "hour" in msg) else 1
    with _LOCK:
        st = _state(root)
        st.setdefault(provider, {})[account] = {"until": time.time() + hours * 3600, "why": str(message)[:200],
                                                "at": time.time()}
        tmp = _state_path(root) + ".tmp"
        with open(tmp, "w") as fh: json.dump(st, fh, indent=1)
        os.replace(tmp, _state_path(root))


def clear_exhausted(root, provider, account):
    with _LOCK:
        st = _state(root)
        (st.get(provider) or {}).pop(account, None)
        tmp = _state_path(root) + ".tmp"
        with open(tmp, "w") as fh: json.dump(st, fh, indent=1)
        os.replace(tmp, _state_path(root))


def exhausted(root, provider, account, now=None):
    """None, or {"until", "why"} while the mark lasts."""
    e = (_state(root).get(provider) or {}).get(account)
    if e and e.get("until", 0) > (now or time.time()): return e
    return None


# ------------------------------------------------------------------ OpenCode Go: the account's real usage

_GO_LIVE = {}


def go_usage(key, account=None, root=None, provider="opencode-go", max_age=60, timeout=15):
    """OpenCode Go's own account usage: {"rolling"|"weekly"|"monthly": {"status", "percent",
    "resetsAt"}} (rolling = the 5-hour window), or {"error": ...}. The account shares one
    allowance across models. Cached for a minute. An account reported rate-limited is
    marked, so the gateway skips it until it resets."""
    import hashlib, datetime
    if not key: return None
    ck = hashlib.sha256(key.encode()).hexdigest()[:16]
    hit = _GO_LIVE.get(ck)
    if hit and time.time() - hit[0] < max_age: return hit[1]
    req = urllib.request.Request("https://opencode.ai/zen/go/v1/usage",
                                 headers={"Authorization": "Bearer " + key, "User-Agent": "orbit/1.0",
                                          "x-opencode-client": "orbit"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = (json.load(r) or {}).get("usage") or {}
    except urllib.error.HTTPError as e:
        try: body = e.read().decode("utf-8", "replace")
        except Exception: body = ""
        msg = body
        try: msg = json.loads(body)["error"]["message"]
        except Exception: pass
        out = {"error": f"{e.code}: {str(msg)[:160]}"}
    except Exception as e:
        out = {"error": type(e).__name__}
    if root and account and "error" not in out:
        worst = None
        for w in ("rolling", "weekly", "monthly"):
            v = out.get(w) or {}
            if v.get("status") == "rate-limited" and v.get("resetsAt"):
                try:
                    t = datetime.datetime.fromisoformat(v["resetsAt"].replace("Z", "+00:00")).timestamp()
                    worst = max(worst or 0, t)
                except ValueError:
                    pass
        if worst:
            mark_exhausted(root, provider, account, "OpenCode Go usage limit", seconds=max(60, worst - time.time()))
    _GO_LIVE[ck] = (time.time(), out)
    return out
