"""What is left of a shared model, in a form people in a shared project can read. The host decides per model whether to show it; this module only turns
the figures Orbit already keeps for its providers (a plan's 5-hour and weekly windows, an account's monthly allowance, a spend ledger) into one short statement."""
import datetime, time

LOW_PCT = 15                      # at or below this share left the statement is marked "low"
NAMES = {"rolling": "5-hour window", "weekly": "week", "monthly": "month"}


def _when(iso, now):
    try: t = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError): return None, ""
    secs = t - now
    if secs <= 0: return t, "now"
    if secs < 5400: return t, f"in {max(1, round(secs / 60))} min"
    if secs < 172800: return t, f"in {round(secs / 3600)} h"
    return t, f"in {round(secs / 86400)} days"


def from_windows(live, now=None):
    """live: {"rolling"|"weekly"|"monthly": {"status", "percent" (used), "resetsAt"}} -> {"left_pct", "window", "resets", "state", "label"}, or None without figures.
    The tightest window decides, because that is the one that stops people first."""
    now = now or time.time()
    best = None
    for key in ("rolling", "weekly", "monthly"):
        w = (live or {}).get(key)
        if not isinstance(w, dict): continue
        try: used = float(w.get("percent"))
        except (TypeError, ValueError): continue
        left = max(0.0, min(100.0, 100.0 - used))
        if w.get("status") == "rate-limited": left = 0.0
        if best is None or left < best[0]: best = (left, key, w)
    if not best: return None
    left, key, w = best
    t, rel = _when(w.get("resetsAt"), now)
    state = "out" if left <= 0 else "low" if left <= LOW_PCT else "ok"
    label = (f"used up for this {NAMES[key]}" if state == "out" else f"{round(left)}% left in the {NAMES[key]}") + (f", resets {rel}" if rel else "")
    return {"left_pct": round(left), "window": key, "resets": t, "state": state, "label": label}


def unlimited(why="runs on this Mac"):
    return {"left_pct": None, "unlimited": True, "state": "ok", "label": "no limit (" + why + ")"}


def from_spend(summary):
    """The spend ledger of a provider with no published allowance: only what was used lately, no 'left'."""
    if not summary or not summary.get("requests"): return None
    d = (summary.get("windows") or {}).get("day") or (summary.get("windows") or {}).get("5h") or {}
    w = next(iter((summary.get("windows") or {}).values()), {})
    left = w.get("left_pct")
    if left is not None:
        state = "out" if left <= 0 else "low" if left <= LOW_PCT else "ok"
        return {"left_pct": left, "state": state, "label": f"{left}% of the allowance left"}
    toks = (d or w).get("tokens")
    return {"left_pct": None, "state": "ok", "label": f"{toks:,} tokens used lately" if toks else "no allowance published"}
