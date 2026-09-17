"""Cheaper hours: providers that charge less (or count less of a plan's allowance)
at certain times of day.

Policies live in `offpeak_policies.json` next to this file (researched from the
providers' own pricing pages, with sources and the date they were checked), and can be
overridden or extended in Orbit's config (`config/offpeak.json`, same shape). A policy
names the provider id in Orbit's provider list, the models it covers ("*" = all), its
time windows (in the timezone the provider states), and what you pay then as a
fraction of the normal price (0.5 = half price) -- or, for a subscription plan, how
much of the allowance a request uses.

    status(policy, now) -> {"active", "fraction", "label", "ends_at" | "starts_at", ...}
"""
import datetime as _dt, json, os, re

try:
    from zoneinfo import ZoneInfo
except ImportError:          # pragma: no cover
    ZoneInfo = None

HERE = os.path.dirname(os.path.abspath(__file__))
_CACHE = {"key": None, "policies": []}

TZ_ALIASES = {"UTC": "UTC", "GMT": "UTC", "Beijing": "Asia/Shanghai", "CST": "Asia/Shanghai", "China": "Asia/Shanghai",
              "Asia/Shanghai": "Asia/Shanghai", "PT": "America/Los_Angeles", "PST": "America/Los_Angeles",
              "ET": "America/New_York", "SGT": "Asia/Singapore"}


def _tz(name):
    raw = str(name or "UTC")
    m = re.search(r"UTC\s*([+-])\s*(\d{1,2})(?::(\d{2}))?", raw)
    if m:                                   # "UTC+8", "unstated (presumably UTC+8)"
        sign = 1 if m.group(1) == "+" else -1
        return _dt.timezone(sign * _dt.timedelta(hours=int(m.group(2)), minutes=int(m.group(3) or 0)))
    name = TZ_ALIASES.get(raw, raw)
    if ZoneInfo is None: return _dt.timezone.utc
    try: return ZoneInfo(name)
    except Exception: return _dt.timezone.utc


def load(root=None):
    """Built-in policies, with config/offpeak.json merged over them (by provider + applies_to)."""
    paths = [os.path.join(HERE, "offpeak_policies.json")]
    if root: paths.append(os.path.join(root, "config", "offpeak.json"))
    key = tuple((p, os.path.getmtime(p)) for p in paths if os.path.exists(p))
    if _CACHE["key"] == key: return _CACHE["policies"]
    merged = {}
    for p in paths:
        try: d = json.load(open(p))
        except (OSError, ValueError): continue
        for pol in d.get("policies") or []:
            if not pol.get("provider") or not pol.get("windows"): continue
            merged[(pol["provider"], pol.get("applies_to") or "")] = pol
    _CACHE.update(key=key, policies=list(merged.values()))
    return _CACHE["policies"]


def _hm(s):
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", str(s or ""))
    if not m or int(m.group(1)) > 24: raise ValueError(f"bad time {s!r}")
    return int(m.group(1)), int(m.group(2))


_WD = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _day_ok(days, d):
    """days: "daily", "weekdays", "weekends", "Mon-Fri", "Sat-Sun", "Mon,Wed", or a list of 0-6 (Mon=0).
    Words after the days ("daily incl. holidays") are ignored."""
    if isinstance(days, list): return d.weekday() in days
    t = str(days or "daily").strip().lower()
    if not t or t.startswith(("daily", "all", "every")): return True
    if t.startswith("weekday"): return d.weekday() < 5
    if t.startswith("weekend"): return d.weekday() >= 5
    m = re.match(r"^(mon|tue|wed|thu|fri|sat|sun)[a-z]*\s*-\s*(mon|tue|wed|thu|fri|sat|sun)", t)
    if m:
        a, b = _WD[m.group(1)], _WD[m.group(2)]
        return a <= d.weekday() <= b if a <= b else (d.weekday() >= a or d.weekday() <= b)
    names = re.findall(r"(mon|tue|wed|thu|fri|sat|sun)", t)
    if names: return d.weekday() in {_WD[n] for n in names}
    return True


def _intervals(win, around, before=1, after=1):
    """(start, end) datetimes of a window for the days around `around` (aware)."""
    tz = _tz(win.get("tz"))
    local = around.astimezone(tz)
    (sh, sm), (eh, em) = _hm(win["start"]), _hm(win["end"])
    out = []
    for delta in range(-before, after + 1):
        day = (local + _dt.timedelta(days=delta)).date()
        start = _dt.datetime(day.year, day.month, day.day, sh % 24, sm, tzinfo=tz)
        end = _dt.datetime(day.year, day.month, day.day, 0, 0, tzinfo=tz) + _dt.timedelta(hours=eh, minutes=em)
        if end <= start: end += _dt.timedelta(days=1)          # crosses midnight
        if _day_ok(win.get("days"), start): out.append((start, end))
    return out


def _spans(policy, now, before=2, after=8):
    """The policy's cheaper periods near `now`, touching windows joined (Friday 18:00-24:00
    and all of Saturday are one period)."""
    spans = []
    for win in policy.get("windows") or []:
        try: spans += _intervals(win, now, before, after)
        except ValueError: continue
    spans.sort()
    merged = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            if e > merged[-1][1]: merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return merged


def fraction(policy):
    """What you pay then, as a fraction of the normal price (the lowest of its parts)."""
    d = policy.get("discount") or {}
    vals = [v for k, v in d.items() if isinstance(v, (int, float))]
    return min(vals) if vals else None


def status(policy, now=None):
    now = now or _dt.datetime.now(_dt.timezone.utc)
    if now.tzinfo is None: now = now.replace(tzinfo=_dt.timezone.utc)
    eff, ends = policy.get("effective"), policy.get("ends")
    try:
        if eff and now.date() < _dt.date.fromisoformat(eff): return {"active": False, "not_yet": True, "starts_at": eff}
        if ends and now.date() > _dt.date.fromisoformat(ends): return {"active": False, "ended": True}
    except ValueError:
        pass
    frac = fraction(policy)
    current, upcoming = None, None
    for s, e in _spans(policy, now):
        if s <= now < e: current = (s, e)
        elif s > now and upcoming is None: upcoming = (s, e)
    quota = "quota_multiplier" in (policy.get("discount") or {})
    what = (f"{round((1 - frac) * 100)}% off" if frac is not None and frac < 1 and not quota else
            ("half usage" if frac == 0.5 else f"{frac:g}× usage") if quota and frac is not None else "cheaper")
    full = "full rate" if quota else "full price"
    out = {"active": bool(current), "fraction": frac, "quota": quota, "what": what,
           "windows": [f"{w['start']}–{w['end']} {w.get('tz', 'UTC')}" + ("" if w.get("days") in (None, "daily") else f" ({w['days']})")
                       for w in policy.get("windows") or []],
           "peak": policy.get("peak_label")}
    # the cheaper periods of the coming week, in this Mac's time zone
    local = []
    for s_, e_ in _spans(policy, now, before=0, after=7)[:10]:
        if e_ <= now: continue
        ls, le = s_.astimezone(), e_.astimezone()
        same = ls.date() == le.date() or (le - ls) <= _dt.timedelta(hours=24) and le.hour == 0 and le.minute == 0
        local.append(f"{ls.strftime('%a %H:%M')}–{le.strftime('%H:%M' if same else '%a %H:%M')}")
    out["windows_local"] = local
    # the next 24 hours, for a timeline: [[start, end], ...] as timestamps
    horizon = now + _dt.timedelta(hours=24)
    out["spans"] = [[max(a, now).timestamp(), min(b, horizon).timestamp()]
                    for a, b in _spans(policy, now, before=1, after=2) if b > now and a < horizon]
    out["peak"] = policy.get("peak_label")
    if current:
        out["ends_at"] = current[1].timestamp()
        end = current[1].astimezone()
        day = "" if end.date() == now.astimezone().date() else end.strftime("%a ")
        out["label"] = f"{what} now · until {day}{end.strftime('%H:%M')}"
    elif upcoming:
        out["starts_at"] = upcoming[0].timestamp()
        st_ = upcoming[0].astimezone()
        day = "" if st_.date() == now.astimezone().date() else st_.strftime("%a ")
        out["label"] = f"{full} now · {what} from {day}{st_.strftime('%H:%M')}"
    else:
        out["label"] = full
    return out


def _model_ok(policy, model):
    ms = policy.get("models") or ["*"]
    m = str(model or "").lower()
    for pat in ms:
        pat = str(pat).lower()
        if pat == "*" or pat == m or (pat.endswith("*") and m.startswith(pat[:-1])): return True
    return False


def for_model(provider, model, root=None, now=None):
    """The time-based pricing of one provider's model, or None if it has none."""
    for pol in load(root):
        if pol.get("provider") != provider: continue
        if not _model_ok(pol, model): continue
        if any(str(x).lower() == str(model).lower() for x in pol.get("exclude") or []): continue
        st = status(pol, now)
        if st.get("ended"): continue
        return {**st, "provider": provider, "applies_to": pol.get("applies_to"), "sources": pol.get("sources") or [],
                "quote": pol.get("quote"), "checked_at": pol.get("checked_at"), "note": pol.get("note"),
                "discount": pol.get("discount")}
    return None


def summary(root=None, now=None):
    """Every policy with its state now, for Settings."""
    out = []
    for pol in load(root):
        st = status(pol, now)
        out.append({**{k: pol.get(k) for k in ("provider", "applies_to", "models", "exclude", "windows", "discount",
                                                 "effective", "ends", "sources", "quote", "note", "checked_at")}, "status": st})
    return out
