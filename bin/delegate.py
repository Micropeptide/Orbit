"""Delegation: the expensive, intelligent model decides and does the hard parts; cheaper models do the rest.

With the setting on, a chat's model gets one more tool, `delegate`. The lead model hands it a small,
self-contained task and a tier (light or standard); Orbit picks the cheapest model that is ready for
that tier, runs the task in a chat of its own, and gives the answer back. If that model fails, the next
one is tried. The lead keeps what needs judgement -- design, subtle bugs, security, the final check --
and is told to verify what comes back.

This module is the policy: which models are workers, in what order, what the lead is told, and the
ledger of what was handed on. Starting the chats is in bin/orbit-ui (_Chats.delegate).
"""
import json, os, re, time

TIERS = ("light", "standard")
EAGERNESS = ("careful", "balanced", "high")
STREAK_AT = 6                  # direct tool calls in a row before the lead is reminded that a cheaper model could do this

# What each kind of model is for. First match wins; a model that matches nothing is not guessed at:
# it stays out of the roster until you place it in Settings. "lead" models are never given work.
_RULES = (
    ("light", r"luna"),
    ("lead", r"opus|muse-wonder|fable|gpt-[\d.]+-(sol|astra)|\bsol\b|astra|gemini-4|o[34]\b|mythos"),
    ("light", r"haiku|flash|luna|\bmini\b|mini-|nano|lite|deepseek-v4(\.\d)?-flash|glm-[\d.]+-flash|qwen3\.\d-flash|kimi-k2\.\d-flash|\bair\b"),
    ("standard", r"sonnet|deepseek-v4-pro|gemini-3[\d.]*-pro|gemini-2\.5-pro|muse-spark|gpt-5|kimi|glm-5|mimo|minimax|qwen\d?\.?\d*-(max|plus)|longcat|grok"),
)
# Contributor mode is cheaper because Meta may train on what you send: never picked on its own
_PRIVATE = re.compile(r"contributor", re.I)
# Within a tier, which cheap models to try first (cost, then speed): the owner's own examples lead
PREFER = (r"haiku", r"deepseek.*flash", r"flash", r"luna", r"mini|nano|lite", r"qwen", r"glm", r"kimi")
LOCAL_LAST = True           # a model on this Mac answers one request at a time and takes memory: last resort

COOLDOWN_S = 600            # a worker that just failed is left alone this long
LOG_KEEP = 60


PROVIDER_LABELS = {"claude": "Claude (your plan)", "codex": "Codex (your ChatGPT)", "antigravity": "Antigravity (your Google)",
                   "muse-code": "Muse Code", "meta": "Meta Model API", "opencode-go": "OpenCode Go", "opencode-zen": "OpenCode Zen",
                   "local": "This Mac (local model)", "deepseek": "DeepSeek", "gemini": "Gemini API", "anthropic": "Anthropic API"}


def provider_of(mid):
    """Which account/subscription a model id runs on: "claude", "codex", "antigravity", "opencode-go", ..."""
    mid = str(mid or "")
    head, _, rest = mid.partition(":")
    if head in ("harness", "harness-direct", "codex"):
        p = rest.split("/", 1)[0]
        return "codex" if head == "codex" and p == "chatgpt" else p
    return {"claude-cli": "claude", "codex-cli": "codex", "agy-cli": "antigravity", "muse-cli": "muse-code",
            "claude-qwen-cli": "local", "opencode-cli": "opencode-go"}.get(head, head)


def _duplicate(mid):
    """Entries that are the same model reached another way inside Orbit: its quick-call twin, and Codex's copy of an API provider's model."""
    mid = str(mid or "")
    if mid.startswith("harness-direct:"): return True
    return mid.startswith("codex:") and not mid.startswith("codex:chatgpt/")


def tier_of(mid, label=""):
    """"lead", "light", "standard" or None for a catalogue entry."""
    s = f"{mid} {label}".lower()
    for tier, pat in _RULES:
        if re.search(pat, s): return tier
    return None


def settings(S):
    d = (S or {}).get("delegation")
    d = d if isinstance(d, dict) else {}
    tiers = d.get("tiers") if isinstance(d.get("tiers"), dict) else {}
    return {"enabled": bool(d.get("enabled")), "overrides": dict(d.get("overrides") or {}),
            # your own order, per tier: when a tier has a list, only those models, in that order
            "tiers": {t: [str(x) for x in (tiers.get(t) or []) if str(x).strip()] for t in TIERS},
            "exclude_providers": [str(x) for x in (d.get("exclude_providers") or [])],
            "subagents": d.get("subagents", True) is not False,
            "allow_changes": bool(d.get("allow_changes", False)),
            "eagerness": d.get("eagerness") if d.get("eagerness") in EAGERNESS else "high",
            "escalate": d.get("escalate", True) is not False,
            "max_workers": max(1, min(int(d.get("max_workers") or 6), 20))}


def roster(catalogue, S, is_local=lambda mid: False, cooling=None):
    """Every ready model with the tier it would work in: [{"id", "label", "tier", "auto", "local", "private", "cooling"}].
    `overrides` (Settings) put a model in a tier or "off"; "lead" keeps a model for the lead only."""
    over = settings(S)["overrides"]
    cooling = cooling or {}
    out = []
    excluded = set(settings(S)["exclude_providers"])
    for m in catalogue or []:
        if m.get("ready") is False or m.get("switch"): continue
        mid, label = m.get("id") or "", m.get("label") or ""
        if _duplicate(mid): continue
        auto = tier_of(mid, label)
        tier = over.get(mid) if over.get(mid) in ("light", "standard", "lead", "off") else auto
        if tier is None: continue
        prov = provider_of(mid)
        out.append({"id": mid, "label": label or mid, "tier": tier, "auto": auto, "local": bool(is_local(mid)),
                    "provider": prov, "excluded": prov in excluded,
                    "private": bool(_PRIVATE.search(mid)) and over.get(mid) not in ("light", "standard"),
                    "cooling": cooling.get(mid, 0) > time.time(), "offpeak": bool((m.get("offpeak") or {}).get("active"))})
    return out


def _rank(entry):
    s = f"{entry['id']} {entry['label']}".lower()
    pref = next((i for i, p in enumerate(PREFER) if re.search(p, s)), len(PREFER))
    # cheaper hours first, then the preferred families, on-line models before this Mac's
    # ...and a model reached through the harness before the same one through its CLI: the harness reports its usage and honours accounts
    return (not entry["offpeak"], pref, entry["local"] if LOCAL_LAST else False, not entry["id"].startswith("harness:"))


def pick(rows, tier, avoid=(), S=None):
    """Worker model ids for a tier, best first.

    If you have written an order for the tier in Settings, that is the list: those models, in that order, the ones
    that are ready and not cooling off. Otherwise it is automatic: the cheapest of the tier's models, never a provider
    you excluded. "standard" falls back on the light list last; "light" never goes up, because a task that is worth a
    standard model is not worth a wrong answer from a light one."""
    tier = tier if tier in TIERS else "light"
    mine = settings(S)["tiers"] if S is not None else {t: [] for t in TIERS}
    by_id = {r["id"]: r for r in rows}
    out = []
    for t in ([tier] + (["light"] if tier == "standard" else [])):
        if mine.get(t):
            for mid in mine[t]:
                r = by_id.get(mid)
                if r and not r["cooling"] and mid not in avoid and mid not in out: out.append(mid)
            continue
        cands = [r for r in rows if r["tier"] == t and not r["cooling"] and not r["private"] and not r["excluded"]
                 and r["id"] not in avoid]
        out += [r["id"] for r in sorted(cands, key=_rank) if r["id"] not in out]
    return out


# ------------------------------------------------------------------ what the lead is told

DELEGATE_DESCRIPTION = (
    "Hand a small, self-contained task to a cheaper model and get its answer back, so you keep your own effort for the "
    "parts that need judgement. Orbit picks the worker. DELEGATE: searching or reading many files and reporting what "
    "matters, summarising long text or logs, boilerplate and mechanical edits you can describe exactly, writing a first draft "
    "of tests or docs, running a command and reporting the result, looking things up, reformatting or converting data. "
    "KEEP: design and architecture, anything ambiguous, subtle bugs, security-sensitive changes, deciding between options, "
    "and the final check of everything. The worker has not seen this conversation: put everything it needs in `task` "
    "(paths, what 'done' looks like, the format you want back). Its answer can be wrong: check what you rely on (read the "
    "diff, run the tests). Several independent tasks can run side by side: delegate each with wait=false, then collect them "
    "with chat_wait.")

WORKER_INSTRUCTIONS = (
    "You are a worker doing one task handed to you by a more capable lead model. Do exactly that task with the information "
    "given; do not widen it or make decisions that were not asked for. Be brief: return the result, then anything you could "
    "not do or are unsure of. Do not guess: if you could not verify something, say so. You cannot hand the task on or ask the lead questions; if the task cannot be done as written, "
    "say why and stop. End your answer with one line, `Confidence: high|medium|low`, then say anything you did not check.")


_POLICY = {
    "careful": (
        "Delegation is on. You may hand clearly mechanical or read-only jobs (searching, summarising, boilerplate, running a "
        "command and reporting) to a cheaper model with the `delegate` tool. Keep everything else for yourself."),
    "balanced": (
        "Delegation is on: you are the lead and cheaper models are your hands. Use the `delegate` tool for small, "
        "well-specified, mechanical or read-only tasks (searching, reading and summarising, boilerplate, running commands "
        "and reporting, first drafts). Keep design, ambiguous or subtle problems, security-sensitive work, decisions and the "
        "final verification for yourself."),
    "high": (
        "DELEGATION IS ON, and you are the lead. Before you act on any request, sort it:\n"
        "- EASY: a lookup; reading, searching or summarising files, logs, pages or papers; running a command or the tests and "
        "reporting; a mechanical or boilerplate edit; converting or formatting data; fetching or downloading; a first draft of "
        "docs or tests; anything a careful assistant could do from a clear description. Hand the WHOLE of it to `delegate` "
        "(tier light) in your first step, instead of doing it yourself, then check the result and answer.\n"
        "- MIXED: split off the easy, independent pieces and delegate them side by side (wait=false for each, collect with "
        "chat_wait) while you work on the hard part. Use tier standard for pieces that need some care.\n"
        "- HARD: design, ambiguous requirements, subtle bugs, security-sensitive changes, choosing between options, and the "
        "final verification. Do these yourself.\n"
        "If a task can be described fully in a few sentences and checked by looking at what comes back, delegate it: doing "
        "easy work yourself spends your best effort where it is not needed. Put everything the worker needs in `task` (it has "
        "not seen this conversation) and say what to return. A worker can be wrong or overconfident: read its report for its "
        "confidence line, and check what you rely on (read the diff, run the tests). Never pass its answer on unread."),
}


def policy(eagerness="high"):
    """What the lead is told about delegating. "high" (the default once delegation is on) makes it a triage step."""
    return _POLICY.get(eagerness) or _POLICY["high"]


def triage(eagerness="high"):
    """The line put in front of every new request (UserPromptSubmit hook), or "" when the setting leaves it out."""
    if eagerness not in ("high", "balanced"): return ""
    return "Delegation triage for this request. " + policy(eagerness).replace(
        "DELEGATION IS ON, and you are the lead. Before you act on any request, sort it:", "Sort the request before you act:")


def lead_note(eagerness="high"):
    """The same, for the lead's own instructions."""
    return policy(eagerness)


STREAK_NOTE = ("Reminder: you have made {n} tool calls in a row yourself. If what is left is mechanical, read-only or "
               "self-contained (reading or searching more files, running checks, boilerplate, a first draft), hand it to a "
               "cheaper model now with the `delegate` tool (wait=false for independent pieces) and keep your effort for the "
               "parts that need judgement.")


class Streak:
    """Counts a lead's direct tool calls since it last delegated, and says when to remind it."""
    def __init__(self, at=STREAK_AT): self.at, self.n = max(2, int(at)), 0

    def call(self, tool):
        """-> a reminder to show the lead, or "". `tool` is the tool the lead just used."""
        if re.search(r"(^|__)delegate$|chat_wait$", str(tool or "")):
            self.n = 0
            return ""
        self.n += 1
        return STREAK_NOTE.format(n=self.n) if self.n >= self.at and (self.n - self.at) % 8 == 0 else ""

    def reset(self): self.n = 0


_CONF = re.compile(r"confidence\s*[:=-]\s*(high|medium|low)", re.I)


def confidence(answer):
    """The worker's own confidence ("high", "medium", "low"), or "" when it gave none."""
    m = None
    for m in _CONF.finditer(str(answer or "")): pass
    return m.group(1).lower() if m else ""


def should_escalate(tier, answer, settings_):
    """A light worker that says it is not sure gets its task tried again by a standard one, once."""
    return bool(settings_.get("escalate", True)) and tier == "light" and confidence(answer) == "low"


def worker_message(task, context="", write=False):
    parts = [str(task).strip()]
    if str(context or "").strip(): parts.append("Context:\n" + str(context).strip())
    parts.append("You may change files." if write else "Read-only: look and report, do not change anything.")
    return "\n\n".join(parts)


# ------------------------------------------------------------------ the ledger

def _path(root):
    return os.path.join(root, "config", "delegation.json")


def load(root):
    try: d = json.load(open(_path(root)))
    except (OSError, ValueError): d = {}
    d = d if isinstance(d, dict) else {}
    d.setdefault("stats", {}); d.setdefault("log", []); d.setdefault("cool", {})
    return d


def _save(root, d):
    os.makedirs(os.path.dirname(_path(root)), exist_ok=True)
    tmp = _path(root) + ".tmp"
    with open(tmp, "w") as f: json.dump(d, f, indent=1)
    os.replace(tmp, _path(root))


def cooling(root):
    return {k: v for k, v in load(root)["cool"].items() if v > time.time()}


def record(root, model, task, ok, secs=0, tokens=0, parent=None, error="", tier="", note=""):
    d = load(root)
    s = d["stats"].setdefault(model, {"tasks": 0, "tokens": 0, "fails": 0})
    if ok: s["tasks"] += 1; s["tokens"] += int(tokens or 0); s["secs"] = round(s.get("secs", 0) + float(secs or 0), 1)
    else:
        s["fails"] += 1
        d["cool"][model] = time.time() + COOLDOWN_S          # leave it alone for a while
    d["log"].append({"t": round(time.time(), 1), "model": model, "task": " ".join(str(task).split())[:100], "ok": bool(ok),
                     "secs": round(secs, 1), "tokens": int(tokens or 0), "parent": parent, "error": str(error)[:160],
                     "tier": tier, "note": str(note)[:80]})
    del d["log"][:-LOG_KEEP]
    _save(root, d)
    return d


def note_turn(root, delegated):
    """A lead's answer that used tools ended: did it hand anything on? (How eagerly delegation is really used.)"""
    d = load(root)
    t = d.setdefault("turns", {"with": 0, "without": 0})
    t["with" if delegated else "without"] += 1
    _save(root, d)


def summary(root):
    d = load(root)
    tasks = sum(s["tasks"] for s in d["stats"].values())
    fails = sum(s["fails"] for s in d["stats"].values())
    t = d.get("turns") or {"with": 0, "without": 0}
    seen = t["with"] + t["without"]
    return {"stats": d["stats"], "log": d["log"][-20:][::-1], "tasks": tasks, "fails": fails,
            "tokens": sum(s["tokens"] for s in d["stats"].values()),
            "turns": {"delegated": t["with"], "total": seen, "share": round(t["with"] / seen, 3) if seen else None}}
