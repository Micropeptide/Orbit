"""What each Claude account has used of its plan, as Claude Code itself reports it.

A subscription has a 5-hour window and a weekly one (and sometimes a weekly one for one model);
Claude Code learns the figures from every answer it gets and says so in a `rate_limit_event`.
Orbit keeps the latest per account, so asking costs nothing -- and `probe` asks Claude for them
with one tiny question when nothing recent is known. An account on usage-based billing has no
such windows: it says so instead.
"""
import datetime, json, os, subprocess, tempfile, threading, time

import claude_accounts as CA

_LOCK = threading.Lock()
MAX_AGE = 6 * 3600              # a figure older than this is shown as old, and asked for again on request
NAMES = {"five_hour": "5 hours", "seven_day": "week", "seven_day_opus": "week · Opus",
         "seven_day_sonnet": "week · Sonnet"}


def _path(root):
    d = os.path.join(root, "config", "claude")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "limits.json")


def _load(root):
    try:
        with open(_path(root)) as f: return json.load(f)
    except Exception:
        return {}


def _save(root, data):
    tmp = _path(root) + f".{os.getpid()}.tmp"
    with open(tmp, "w") as f: json.dump(data, f)
    os.replace(tmp, _path(root))


def note(root, account, info, now=None):
    """One `rate_limit_info` from Claude Code, kept for this account."""
    if not isinstance(info, dict) or not account: return
    now = now or time.time()
    wins = {}
    for k, w in (info.get("unifiedWindows") or {}).items():
        if isinstance(w, dict) and w.get("utilization") is not None:
            wins[k] = {"used": round(float(w["utilization"]) * 100, 1), "resets": w.get("resetsAt")}
    typ = info.get("rateLimitType")
    if typ in NAMES and info.get("utilization") is not None and typ not in wins:
        wins[typ] = {"used": round(float(info["utilization"]) * 100, 1), "resets": info.get("resetsAt")}
    with _LOCK:
        data = _load(root)
        row = data.get(account) or {}
        merged = {**(row.get("windows") or {}), **wins}
        row.update(at=now, windows=merged, status=info.get("status"), type=typ,
                   overage={"on": bool(info.get("overageInUse") or info.get("isUsingOverage")),
                            "status": info.get("overageStatus"), "resets": info.get("overageResetsAt")})
        data[account] = row
        _save(root, data)


def add_cost(root, account, session, total, resumed=False, now=None):
    """A run's `total_cost_usd` (what Claude Code works out for the session so far, at list prices) added
    to this account's month. Only the part since the last run of the same session counts."""
    if not account or not session or not isinstance(total, (int, float)) or total < 0: return
    now = now or time.time()
    month = time.strftime("%Y-%m", time.gmtime(now))          # the allowance resets on the 1st, UTC
    with _LOCK:
        data = _load(root)
        meta = data.setdefault("_sessions", {})
        last = float((meta.get(session) or {}).get("total") or 0)
        first_sight = session not in meta
        delta = total - last if total >= last else total
        meta[session] = {"total": total, "at": now}
        if len(meta) > 300:
            for k in sorted(meta, key=lambda k: meta[k]["at"])[:100]: meta.pop(k, None)
        row = data.setdefault(account, {})
        sp = row.get("spend") or {}
        if sp.get("month") != month: sp = {"month": month, "usd": 0.0, "runs": 0}
        # a resumed session seen for the first time has an unknown starting point (Claude Code restores
        # its running total): count it only from here. A session that began here counts from its first answer.
        if not (first_sight and resumed):
            sp["usd"] = round(sp.get("usd", 0.0) + max(0.0, delta), 6)
            sp["runs"] = sp.get("runs", 0) + 1
        row["spend"] = sp
        data[account] = row
        _save(root, data)


def note_usage(root, account, rate_limits, now=None):
    """`get_usage`'s rate_limits from a full login: the plan's windows (as percent) and a usage-based
    plan's monthly credits (amounts in minor units: cents)."""
    if not isinstance(rate_limits, dict) or not account: return
    now = now or time.time()
    wins = {}
    for k in ("five_hour", "seven_day", "seven_day_opus", "seven_day_sonnet"):
        w = rate_limits.get(k)
        if isinstance(w, dict) and w.get("utilization") is not None:
            try:
                resets = datetime.datetime.fromisoformat(str(w.get("resets_at")).replace("Z", "+00:00")).timestamp()
            except ValueError:
                resets = None
            wins[k] = {"used": round(float(w["utilization"]), 1), "resets": resets}
    ex = rate_limits.get("extra_usage")
    with _LOCK:
        data = _load(root)
        row = data.get(account) or {}
        if wins: row["windows"] = {**(row.get("windows") or {}), **wins}
        if isinstance(ex, dict) and ex.get("is_enabled") and ex.get("monthly_limit") is not None:
            row["credits"] = {"used": ex.get("used_credits") or 0, "limit": ex["monthly_limit"],
                              "pct": ex.get("utilization"), "currency": ex.get("currency") or "USD",
                              "decimals": ex.get("decimal_places", 2), "reached": bool(ex.get("spend_limit_reached")),
                              "at": now}
        row["at"] = max(row.get("at") or 0, now)
        data[account] = row
        _save(root, data)


def read_login(root, account, claude, usage_dir, timeout=45):
    """Read an account's usage through its full login (no model call: `get_usage` answers right after
    start-up). Returns the view, or {"error": ...}."""
    import queue
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_OAUTH_TOKEN"}
    env["CLAUDE_CONFIG_DIR"] = usage_dir
    try:
        p = subprocess.Popen([claude, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                              "--model", "haiku", "--setting-sources", "", "--strict-mcp-config", "--mcp-config",
                              '{"mcpServers":{}}'], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, cwd=tempfile.gettempdir(), text=True)
    except OSError as e:
        return {"error": str(e)}
    q = queue.Queue()
    threading.Thread(target=lambda: [q.put(l) for l in p.stdout] or q.put(None), daemon=True).start()
    try:
        for rid, sub in (("i", "initialize"), ("u", "get_usage")):
            p.stdin.write(json.dumps({"type": "control_request", "request_id": rid, "request": {"subtype": sub}}) + "\n")
            p.stdin.flush()
            if sub == "initialize": time.sleep(1.2)
        t0 = time.time()
        while time.time() - t0 < timeout:
            try: l = q.get(timeout=2)
            except queue.Empty: continue
            if l is None: break
            try: ev = json.loads(l)
            except ValueError: continue
            if ev.get("type") == "control_response" and (ev.get("response") or {}).get("request_id") == "u":
                resp = (ev["response"].get("response") or {})
                note_usage(root, account, resp.get("rate_limits"))
                return view(root, account)
    except (BrokenPipeError, OSError):
        pass
    finally:
        try: p.kill()
        except Exception: pass
    return {"error": "Claude gave no usage figures (is that login still signed in?)"}


def view(root, account, now=None):
    """What is known for one account, ready to show, or None."""
    now = now or time.time()
    row = _load(root).get(account)
    if not row: return None
    wins = []
    for k in ("five_hour", "seven_day", "seven_day_opus", "seven_day_sonnet"):
        w = (row.get("windows") or {}).get(k)
        if not w: continue
        resets = w.get("resets")
        gone = bool(resets) and float(resets) < now       # that window has since reset: the figure is out of date
        wins.append({"key": k, "name": NAMES[k], "used": 0.0 if gone else w["used"], "resets": resets,
                     "stale": gone})
    ov = row.get("overage") or {}
    sp = row.get("spend") or {}
    month = time.strftime("%Y-%m", time.gmtime(now))
    spend = {"usd": sp.get("usd", 0.0) if sp.get("month") == month else 0.0, "runs": sp.get("runs", 0) if sp.get("month") == month else 0,
             "month": month}
    # when the month's allowance renews: what Claude reported, else the 1st of next month (UTC)
    nxt = ov.get("resets")
    if not nxt:
        y, m = int(month[:4]), int(month[5:])
        nxt = time.mktime(time.strptime(f"{y + (m == 12)}-{1 if m == 12 else m + 1}-01", "%Y-%m-%d")) - time.timezone
    cr = row.get("credits")
    credits = None
    if cr:
        d = 10 ** int(cr.get("decimals", 2))
        credits = {"used": cr["used"] / d, "limit": cr["limit"] / d, "pct": cr.get("pct"), "currency": cr.get("currency", "USD"),
                   "reached": cr.get("reached"), "age": round(now - (cr.get("at") or now))}
    return {"account": account, "at": row.get("at"), "age": round(now - (row.get("at") or now)),
            "status": row.get("status"), "windows": wins,
            "usage_based": bool(not wins and (ov.get("on") or credits)), "overage": ov, "spend": spend, "renews": nxt,
            "credits": credits}


def _iso(epoch):
    try: return datetime.datetime.fromtimestamp(float(epoch), datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError): return None


def live(root, account):
    """The same figures in the shape Orbit already shows for OpenCode Go accounts
    (rolling = the 5-hour window, weekly), or None when nothing is known."""
    v = view(root, account)
    if not v or (not v["windows"] and not v.get("credits")): return None
    out = {}
    cr = v.get("credits")
    if cr and cr.get("pct") is not None:
        out["monthly"] = {"status": "rate-limited" if cr.get("reached") else "ok", "percent": float(cr["pct"]),
                          "resetsAt": _iso(v.get("renews"))}
    for w in v["windows"]:
        slot = {"five_hour": "rolling", "seven_day": "weekly"}.get(w["key"])
        if not slot: continue
        out[slot] = {"status": "rate-limited" if w["used"] >= 100 else "ok", "percent": w["used"],
                     "resetsAt": _iso(w["resets"])}
    return out or None


def _day(t):
    try: return time.strftime("%b %d", time.localtime(float(t)))
    except (TypeError, ValueError): return "?"


def _money(x, cur="USD"):
    return ("$" if cur == "USD" else cur + " ") + f"{x:,.2f}"


def spend_line(v):
    """"≈ $3.20 this month through Orbit", or "" when nothing is counted yet."""
    sp = (v or {}).get("spend") or {}
    if not sp.get("runs"): return ""
    return f"≈ ${sp['usd']:.2f} this month through Orbit (list prices)"


def summary(v):
    """One line per account, in words."""
    if not v: return "no figures yet"
    def when(w):
        try: return time.strftime("%a %H:%M", time.localtime(float(w["resets"])))
        except (TypeError, ValueError): return "?"
    if v["usage_based"]:
        cr = v.get("credits")
        if cr:
            bits = [f"monthly credits: {_money(cr['used'], cr['currency'])} of {_money(cr['limit'], cr['currency'])} used "
                    f"({cr['pct']:g}%), renews {_day(v.get('renews'))}" + (" — limit reached" if cr.get("reached") else "")]
        else:
            bits = ["usage-based billing: no 5-hour or weekly window, a monthly allowance that renews " + _day(v.get("renews"))]
        if spend_line(v): bits.append(spend_line(v))
        return " · ".join(bits)
    if not v["windows"]: return spend_line(v) or "no figures yet"
    out = " · ".join(f"{w['name']}: {w['used']:g}% used" + (f", resets {when(w)}" if w["resets"] else "")
                     for w in v["windows"])
    return out + (" · " + spend_line(v) if spend_line(v) else "")


def probe(root, secrets, account, claude, timeout=60):
    """Ask Claude for this account's figures with one tiny question on the smallest model. Returns
    the view, or {"error": ...}."""
    env = {**os.environ, **CA.env_for(secrets, next((a for a in CA.accounts(root) if a["id"] == account), CA.accounts(root)[0]))}
    try:
        r = subprocess.run([claude, "-p", "Reply OK", "--output-format", "stream-json", "--verbose", "--model", "haiku",
                            "--setting-sources", "", "--disable-slash-commands", "--max-turns", "1",
                            "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}'],
                           env=env, cwd=tempfile.gettempdir(), capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return {"error": "no answer from Claude in %d seconds" % timeout}
    except OSError as e:
        return {"error": str(e)}
    got = False
    for line in r.stdout.splitlines():
        try: ev = json.loads(line)
        except ValueError: continue
        if ev.get("type") == "rate_limit_event":
            note(root, account, ev.get("rate_limit_info")); got = True
        elif ev.get("type") == "result" and ev.get("is_error"):
            return {"error": str(ev.get("result") or "Claude refused the question")[:200]}
    if not got:
        return {"error": (r.stderr or "Claude sent no usage figures").strip()[:200]}
    return view(root, account)


_ASKED = {}


def refresh(root, secrets, account, claude, force=False, max_age=600):
    """Bring one account's figures up to date and return its view (or {"error": ...}). An account with a
    usage login is read straight from it, which costs nothing; others are asked with one tiny question,
    and only when forced or when nothing is known (what answers report is kept as they come)."""
    a = next((x for x in CA.accounts(root) if x["id"] == account), None)
    if not a or not claude: return view(root, account)
    v = view(root, account)
    d = a.get("usage_dir")
    if d and os.path.isdir(d):
        age = ((v or {}).get("credits") or {}).get("age") or 0
        if force or not v or not v.get("credits") or age > max_age:
            return read_login(root, account, claude, d)
        return v
    if force or not v:
        return probe(root, secrets, account, claude)
    return v


def refresh_soon(root, secrets, claude, max_age=900):
    """Keep the usage-login accounts' figures fresh in the background, for the places that only read
    what is kept (the provider line). At most once per account per max_age."""
    for a in CA.accounts(root):
        d = a.get("usage_dir")
        if not d or not os.path.isdir(d): continue
        if time.time() - _ASKED.get(a["id"], 0) < max_age: continue
        _ASKED[a["id"]] = time.time()
        threading.Thread(target=lambda i=a["id"]: refresh(root, secrets, i, claude, force=True), daemon=True).start()
