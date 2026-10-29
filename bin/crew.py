"""Crew: a builder and a reviewer that keep improving a project, round after round, until you stop them.

A goal (qqcore.goal_*) is one chat working until a check says it is done, and stops after 20 turns.
A crew is the other thing you asked for: two (or more) chats on different models that never decide
they are finished.

    round N:  builder   builds or improves the project in its own folder, runs the tests, ends with
                        Done / Verified / Remaining
              checkpoint  git commit + tag crew-round-N (crew-best moves to the best-scored round)
              reviewer   inspects what is on disk like a sceptical judge, runs it, and answers in JSON:
                        a score, the issues, the next tasks
              -> the review becomes the builder's brief for round N+1

It keeps going through errors (waits, then tries again), quota limits, restarts of Orbit and a day or
two of context: the project, its notes (CREW_NOTES.md) and every review (CREW_REVIEWS.md) live in the
folder, so a fresh builder chat can pick up where the last one left off. It stops when you pause or
stop it, or at a limit you set (hours, rounds, tokens); otherwise it does not.

Who the chats are is up to you. Each side can be several chats, and a chat can be one you already have:

    builders   one or more; with several they take turns, round by round, in the same folder
    reviewers  zero or more; with several each scores the round and the scores are averaged; with none
               the builder's own chat steps back and reviews its work (one chat doing both jobs)
    a party is {"model": id} (a new chat is made for it) or {"sid": chat id} (that chat is used as it is)

A chat you designate is never renamed or replaced, and what Orbit changes about it (its folder,
that it may work without asking) is put back when the crew is stopped or removed.

This module is the plan and the loop. Everything that touches Orbit's chats goes through a `host`
(see Host below), so the loop is the same under test and in the app.
"""
import json, os, re, subprocess, threading, time, uuid

TURN_TIMEOUT_S = 3 * 3600           # one builder or reviewer answer: a long build is fine
BACKOFF_S = (60, 120, 300, 600, 1200, 1800)
MAX_FAILS = 16                      # failed turns in a row before it pauses and says so (about 7 hours of waiting: a night, or a usage window)
ROLLOVER_ROUNDS = 10                # a fresh builder chat this often, handing over through the notes in the folder
HISTORY_KEEP = 200
BRIEF_MAX = 14000                   # the brief goes into every prompt: long enough for a real specification
STALL_ROUNDS = 3                    # rounds without a better score before the reviewer is pointed somewhere new
REGRESSION_POINTS = 12              # a drop this far below the best score gets a "fix or revert" note

LENSES = (
    "correctness: bugs, wrong results, crashes, edge cases and anything that does not do what it claims",
    "the first five minutes of a new user: set-up, the first screen, wording, errors and empty states",
    "tests and reliability: what is untested, flaky, or breaks on bad input",
    "speed and cost: slow paths, wasted work, needless model calls",
    "security and robustness: secrets, unsafe input, files and network, failure modes",
    "simplicity: code that is bigger or cleverer than it needs to be, duplicated or dead code",
    "the demo and the docs: can a stranger understand, run and be impressed by it in two minutes",
    "ambition: the one feature or polish that would make a judge say 'wow', and whether it is within reach",
)

DEFAULT_CRITERIA = ("Judged as a hackathon entry: does it work end to end, is it original and technically ambitious, "
                    "is it polished enough to demo, and does it show off the platform it is built on?")


# ------------------------------------------------------------------ the run record

def _path(root):
    return os.path.join(root, "config", "crews.json")


def migrate(run):
    """A run saved before crews could have several chats (one "builder", one "reviewer") in today's shape.
    Their chats were made by the crew, so they are not "designated" ones."""
    if "builders" in run: return run
    b, r = run.pop("builder", None) or {}, run.pop("reviewer", None)
    run["builders"] = [{"model": b.get("model"), "sid": b.get("sid"), "existing": False,
                        "rounds": int(run.pop("builder_rounds", 0) or 0), "handover": bool(run.pop("handover", False))}]
    run["reviewers"] = [{"model": r.get("model"), "sid": r.get("sid"), "existing": False, "rounds": 0, "handover": False}] if r else []
    run.setdefault("saved_prefs", {})
    return run


def load(root):
    try: d = json.load(open(_path(root)))
    except (OSError, ValueError): d = {}
    d = d if isinstance(d, dict) else {}
    for r in d.values():
        if isinstance(r, dict): migrate(r)
    return d


def save(root, runs):
    p = _path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as fh: json.dump(runs, fh, indent=1)
    os.replace(tmp, p)


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:40] or "project"


def party(x):
    """A builder or reviewer as the run keeps it: {"model", "sid", "existing", "effort", "rounds", "handover"}.
    A designated chat may also carry a model and an effort: it works on that model/effort for the run, and its
    own are put back when the crew stops."""
    if isinstance(x, str): x = {"model": x}
    x = dict(x or {})
    sid = (x.get("sid") or "").strip() or None
    return {"model": x.get("model") or None, "sid": sid, "existing": bool(sid and x.get("existing", True)),
            "effort": x.get("effort") or None, "rounds": 0, "handover": False}


def new_run(title, brief, folder, builders, reviewers, *, reference="", criteria="", hours=0, max_rounds=0, max_tokens=0,
            rollover=ROLLOVER_ROUNDS):
    builders = [party(b) for b in (builders if isinstance(builders, list) else [builders]) if b]
    reviewers = [party(r) for r in (reviewers if isinstance(reviewers, list) else [reviewers]) if r]
    if not builders: raise ValueError("a crew needs at least one builder")
    now = time.time()
    return {"id": uuid.uuid4().hex[:8], "title": str(title or "").strip()[:100] or "Crew", "brief": str(brief or "").strip()[:BRIEF_MAX],
            "folder": os.path.expanduser(str(folder or "")), "reference": os.path.expanduser(str(reference or "")),
            "criteria": str(criteria or "").strip()[:2000] or DEFAULT_CRITERIA,
            "builders": builders, "reviewers": reviewers,
            "state": "running", "reason": "", "phase": "idle", "round": 0,
            "created": now, "updated": now, "started": now,
            "limits": {"hours": float(hours or 0), "max_rounds": int(max_rounds or 0), "max_tokens": int(max_tokens or 0)},
            "rollover": max(2, int(rollover or ROLLOVER_ROUNDS)),
            "tokens": 0, "best": None, "best_round": 0, "since_best": 0, "fails": 0,
            "backlog": [], "notes": [], "history": [], "attention": "", "saved_prefs": {}}


def edit_run(run, *, brief=None, criteria=None, reference=None, title=None):
    """Change the instructions of a run that is under way. -> the note the builder is given (it reads the new brief from its
    next prompt on; an answer in progress is told at once). The brief is also written to CREW_BRIEF.md in the folder, so a
    session that takes over later reads the same thing."""
    changed = []
    if brief is not None and str(brief).strip():
        run["brief"] = str(brief).strip()[:BRIEF_MAX]; changed.append("the brief")
    if criteria is not None and str(criteria).strip():
        run["criteria"] = str(criteria).strip()[:2000]; changed.append("how it is judged")
    if reference is not None:
        run["reference"] = os.path.expanduser(str(reference).strip()); changed.append("the reference")
    if title is not None and str(title).strip():
        run["title"] = str(title).strip()[:100]
    run["updated"] = time.time()
    if not changed: return ""
    try:
        with open(os.path.join(run["folder"], "CREW_BRIEF.md"), "w") as f:
            f.write(f"# {run['title']}\n\n## Brief\n\n{run['brief']}\n\n## How it is judged\n\n{run['criteria']}\n")
    except OSError:
        pass
    note = (f"The person has changed {' and '.join(changed)}. Read CREW_BRIEF.md in the project folder: the new version replaces the old one "
            "from now on. Keep what you have built where it still fits.")
    run.setdefault("notes", []).append(note)
    return note


def builder_for(run, rnd):
    """Who builds round `rnd`: the builders take turns."""
    return run["builders"][(max(1, rnd) - 1) % len(run["builders"])]


def self_review(run):
    """No reviewer chat was given: the builder's own chat reviews its work."""
    return not run["reviewers"]


def public(run):
    """What the page needs: the run without the long texts."""
    r = {k: v for k, v in run.items() if k not in ("history",)}
    r["history"] = [{k: v for k, v in h.items() if k != "builder_text"} for h in run.get("history", [])[-30:]]
    r["last"] = (run.get("history") or [{}])[-1] if run.get("history") else None
    return r


# ------------------------------------------------------------------ prompts

RULES = ("Work only inside the project folder (your shell may start somewhere else: use absolute paths under it, and never change the original project it came from). Never touch other projects, your own settings, or anything outside it. "
         "Never write an API key or any secret into a file (read keys from environment variables). Do not ask the person "
         "questions: you will not get an answer for hours, so decide, write your decision in CREW_NOTES.md, and carry on.")


STALL_S = 75 * 60                   # an answer that shows no sign of life this long is wedged (a dropped connection can leave the CLI waiting for ever)


class Stall:
    """Notices an answer that has stopped moving. `seen(fingerprint, now)` is True once the fingerprint (what the chat has written
    so far, and anything it is waiting on) has not changed for `limit` seconds."""
    def __init__(self, limit=STALL_S): self.limit, self.fp, self.since = limit, None, None

    def seen(self, fp, now):
        if fp != self.fp or self.since is None: self.fp, self.since = fp, now
        return now - self.since >= self.limit


def live(loaded, runner):
    """The run dict an edit must change. A running crew's Runner keeps its own copy of the run in memory and saves THAT copy
    after every step, so a change made to a freshly loaded copy (a note, an edit of the brief, pinned orders, a pause) is
    written over at its next save and never seen by the builder. While a runner is alive, change its dict."""
    t = getattr(runner, "thread", None)
    if runner is not None and t is not None and t.is_alive() and (getattr(runner, "run", None) or {}).get("id") == loaded.get("id"):
        return runner.run
    return loaded


def standing(run):
    """The person's standing orders: they stay in every prompt until changed, and outrank the reviewer's list. A note is read
    once and a long brief gets skimmed; the reviewer's own next-tasks list is what a builder tends to follow, so these go
    to both sides."""
    p = [str(x).strip() for x in run.get("pinned") or [] if str(x).strip()]
    if not p: return ""
    return ("STANDING ORDERS from the person (they outrank the reviewer's list below; a round that does not advance them "
            "does not count):\n" + "\n".join(f"{i}. {x}" for i, x in enumerate(p, 1)))


def build_prompt(run, rnd, builder=None):
    ref = (f"\nA reference exists at {run['reference']}. Read it for ideas if you like, but this is a fresh build: write "
           "everything new, in this folder, and do not copy its code." if run.get("reference") else "")
    head = (f"You are the BUILDER in a build, review, improve loop that runs for hours or days. This is round {rnd}.\n\n"
            f"Project: {run['title']}\nBrief: {run['brief']}\n\nProject folder: {run['folder']} (a git repository; the Mac "
            f"checkpoints it after every round).{ref}\n\nHow it will be judged: {run['criteria']}\n\n{RULES}\n")
    if rnd == 1 or not run.get("history"):
        task = ("Plan briefly, then build the first complete, working version: it must run end to end, have tests, and have a "
                "README that says how to run it. Create CREW_NOTES.md (what it is, how it is laid out, how to run and test it, "
                "decisions, open problems) and keep it current.")
        if run.get("notes"):
            task = "Notes from the person, which come first:\n" + "\n".join(f"- {n}" for n in run["notes"]) + "\n\n" + task
        if standing(run): task = standing(run) + "\n\n" + task
    else:
        last = run["history"][-1]
        issues = "\n".join(f"- [{i.get('severity', '?')}] {i.get('title', '')}: {i.get('fix') or i.get('detail', '')}"[:400]
                           for i in (last.get("issues") or [])[:8]) or "- (the reviewer listed none)"
        tasks = "\n".join(f"- {t}"[:300] for t in (run.get("backlog") or [])[:8]) or "- (none: choose the most valuable improvement yourself)"
        score = last.get("score")
        parts = [f"The reviewer scored round {last.get('round')} at {score if score is not None else '(no score)'} / 100.",
                 f"Reviewer's summary: {last.get('summary') or '(none)'}", f"Issues to fix, most important first:\n{issues}",
                 f"Next tasks:\n{tasks}"]
        if run.get("best") is not None and score is not None and score < run["best"] - REGRESSION_POINTS:
            parts.append(f"The score has dropped from its best ({run['best']}, round {run['best_round']}, git tag crew-best). "
                         "Work out what regressed (git diff crew-best) and fix it, or revert that part.")
        if run.get("notes"):
            parts.append("Notes from the person, which come first:\n" + "\n".join(f"- {n}" for n in run["notes"]))
        parts = standing(run) and [standing(run)] + parts or parts
        task = ("\n\n".join(parts) + "\n\nWork through the issues in order, then use what time is left on the next tasks. Keep the "
                "tests passing, add tests for what you fix, and update CREW_NOTES.md.")
    if (builder or {}).get("handover") or (len(run["builders"]) > 1 and rnd > 1 and not (builder or {}).get("rounds")):
        task = ("You are taking over from an earlier builder session (or another builder). Start by reading CREW_NOTES.md and "
                "CREW_REVIEWS.md in the folder and `git log`, then carry on.\n\n") + task
    return (head + "\n" + task + "\n\nA round is one focused increment, not the whole brief: pick the most valuable slice that you can "
            "finish completely in well under an hour of work (tests passing), do that, and stop. A reviewer looks at it next and tells you what "
            "to do after that; trying to finish everything in one round means no one sees anything for hours. When you finish the round, make "
            "sure everything is saved on disk, and end your answer with Done: (what you finished), Verified: (how you checked it, with the real "
            "command output), Remaining: (what is left).")


REVIEW_JSON = ('{"score": 0-100, "summary": "two sentences", "issues": [{"severity": "high|medium|low", "title": "...", '
               '"detail": "what is wrong and how you saw it", "fix": "what to do"}], "next_tasks": ["the next most valuable '
               'improvements, most important first"]}')


def review_prompt(run, rnd, reviewer_no=0):
    lens = LENSES[(rnd - 1 + reviewer_no) % len(LENSES)] if (run.get("since_best", 0) >= STALL_ROUNDS or reviewer_no) else ""
    scores = [h.get("score") for h in run.get("history", [])[-4:] if h.get("score") is not None]
    trend = f" Recent scores: {', '.join(str(s) for s in scores)}." if scores else ""
    focus = (f"\n{'Look hard at one thing this round' if reviewer_no else 'The score has stopped rising, so look hard at one thing this round'}: {lens}." if lens else "")
    who = ("You built this project earlier in this chat. Step back now and judge it as a stranger would, with none of the builder's "
           "loyalty: " if self_review(run) else "A different model builds it; you only judge. ")
    return (f"You are the REVIEWER in a build, review, improve loop that runs for hours or days. This is round {rnd}.{trend}\n\n"
            f"Project: {run['title']}\nBrief: {run['brief']}\nProject folder: {run['folder']}\n\nHow it will be judged: "
            f"{run['criteria']}\n\n{who}Do not edit the project's files in this step.\n\n"
            + (standing(run) + "\nScore the round on these first: work that ignores them earns at most 60, and your next_tasks must "
               "start with whatever of them is still open.\n\n" if standing(run) else "") +
            "Review what is actually on disk, not what anyone says about it: read the code, run the tests, run the project and "
            "use it the way a user and a judge would. Be a sceptic. Trust evidence you produced yourself over claims in the "
            "README or in the builder's report. There is always a most valuable next improvement; if it is already very good, "
            f"name stretch goals and risks.{focus}\n\nScore it 0 to 100 against the criteria (an honest score: most unfinished "
            "work is below 70; 90 and up means a judge would pick it). Then end your answer with ONE JSON object and nothing "
            f"after it, of this shape:\n{REVIEW_JSON}\n\n{RULES}")


def combine_reviews(parts):
    """Several reviewers' parsed reviews as one: the mean score, every issue once, every task once."""
    scores = [p["score"] for p in parts if p.get("score") is not None]
    issues, seen = [], set()
    for p in parts:
        for i in p.get("issues") or []:
            k = re.sub(r"\W+", " ", (i.get("title") or i.get("fix") or "").lower()).strip()[:60]
            if k and k not in seen: seen.add(k); issues.append(i)
    tasks, tseen = [], set()
    for p in parts:
        for t in p.get("next_tasks") or []:
            k = re.sub(r"\W+", " ", t.lower()).strip()[:60]
            if k and k not in tseen: tseen.add(k); tasks.append(t)
    summary = parts[0]["summary"] if len(parts) == 1 else " ".join(
        f"Reviewer {n + 1} ({p['score'] if p.get('score') is not None else '—'}): {p['summary']}" for n, p in enumerate(parts))
    return {"score": round(sum(scores) / len(scores)) if scores else None, "summary": summary[:900], "issues": issues[:14],
            "next_tasks": tasks[:14], "parsed": any(p.get("parsed") for p in parts),
            "each": [p.get("score") for p in parts]}


# ------------------------------------------------------------------ reading a review

def _json_objects(text):
    """Every balanced {...} in the text, last first."""
    out, depth, start, instr, esc = [], 0, None, False, False
    for i, ch in enumerate(text or ""):
        if instr:
            if esc: esc = False
            elif ch == "\\": esc = True
            elif ch == '"': instr = False
            continue
        if ch == '"' and depth: instr = True
        elif ch == "{":
            if depth == 0: start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                out.append(text[start:i + 1]); start = None
    return out[::-1]


def parse_review(text):
    """{"score", "summary", "issues", "next_tasks", "parsed"}: tolerant of prose around the JSON and of
    a reviewer that forgot the JSON altogether (its whole answer becomes the summary)."""
    text = str(text or "")
    for chunk in _json_objects(text):
        try: d = json.loads(chunk)
        except ValueError: continue
        if not isinstance(d, dict) or not ({"score", "issues", "next_tasks"} & set(d)): continue
        score = d.get("score")
        try: score = max(0, min(100, int(round(float(score))))) if score is not None else None
        except (TypeError, ValueError): score = None
        issues = []
        for i in d.get("issues") or []:
            if isinstance(i, dict):
                issues.append({"severity": str(i.get("severity") or "medium").lower()[:8], "title": str(i.get("title") or "")[:160],
                               "detail": str(i.get("detail") or "")[:600], "fix": str(i.get("fix") or "")[:400]})
            elif isinstance(i, str):
                issues.append({"severity": "medium", "title": i[:160], "detail": "", "fix": ""})
        tasks = [str(t)[:300] for t in (d.get("next_tasks") or []) if str(t).strip()]
        return {"score": score, "summary": str(d.get("summary") or "")[:600], "issues": issues[:12], "next_tasks": tasks[:12], "parsed": True}
    m = re.search(r"\bscore\b\W{0,12}(\d{1,3})\b", text, re.I)
    return {"score": min(100, int(m.group(1))) if m else None, "summary": " ".join(text.split())[:600], "issues": [],
            "next_tasks": [], "parsed": False}


_SEV = {"high": 0, "medium": 1, "low": 2}


def merge_backlog(issues, tasks, cap=12):
    """The reviewer's issues (worst first) then its next tasks, without repeats."""
    items = []
    for i in sorted(issues or [], key=lambda i: _SEV.get(i.get("severity"), 1)):
        core = (i.get("fix") or i.get("title") or "").strip()
        items.append((core, core + (f"  ({i['title']})" if i.get("fix") and i.get("title") else "")))
    items += [(str(t).strip(), str(t).strip()) for t in tasks or []]
    out, seen = [], set()
    for core, shown in items:
        key = re.sub(r"\W+", " ", core.lower()).strip()[:80]
        if core and key not in seen:
            seen.add(key); out.append(shown)
    return out[:cap]


# ------------------------------------------------------------------ the folder

def _git(folder, *args, timeout=120):
    return subprocess.run(["git", "-c", "user.name=Orbit Crew", "-c", "user.email=crew@orbit.local", *args], cwd=folder,
                          capture_output=True, text=True, timeout=timeout)


def prepare_folder(run):
    """The folder exists and is a git repository with a notes file; True if it is ready."""
    folder = run["folder"]
    os.makedirs(folder, exist_ok=True)
    try:
        if not os.path.isdir(os.path.join(folder, ".git")): _git(folder, "init", "-q")
        ign = os.path.join(folder, ".gitignore")
        if not os.path.exists(ign):
            with open(ign, "w") as f: f.write("node_modules/\n.venv/\n__pycache__/\n.env\n*.pyc\n.DS_Store\ndist/\n")
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def checkpoint(run, rnd, note=""):
    """Commit what the builder left and tag the round. -> the commit hash, or "" when there was nothing new."""
    folder = run["folder"]
    try:
        _git(folder, "add", "-A")
        dirty = _git(folder, "status", "--porcelain").stdout.strip()
        if dirty:
            _git(folder, "commit", "-q", "-m", f"crew round {rnd}" + (f": {note}" if note else ""))
        head = _git(folder, "rev-parse", "--short", "HEAD").stdout.strip()
        if head:
            _git(folder, "tag", "-f", f"crew-round-{rnd}")
        return head if dirty else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def tag_best(run):
    try: _git(run["folder"], "tag", "-f", "crew-best", f"crew-round-{run['best_round']}")
    except (OSError, subprocess.SubprocessError): pass


def log_review(run, entry):
    """CREW_REVIEWS.md: every review, in the folder, so a new session can read what happened."""
    try:
        with open(os.path.join(run["folder"], "CREW_REVIEWS.md"), "a") as f:
            f.write(f"\n## Round {entry['round']} — score {entry.get('score')}\n\n{entry.get('summary') or ''}\n\n")
            for i in entry.get("issues") or []:
                f.write(f"- [{i.get('severity')}] {i.get('title')}: {i.get('fix') or i.get('detail')}\n")
            if entry.get("next_tasks"):
                f.write("\nNext:\n" + "\n".join(f"- {t}" for t in entry["next_tasks"]) + "\n")
    except OSError:
        pass


# ------------------------------------------------------------------ the loop

class Host:
    """What the loop needs from Orbit. The app's adapter is in bin/orbit-ui; tests give a fake.

    create_chat(title, model, instructions, folder) -> sid
    turn(sid, text, timeout_s, cancel, key=None, settle=False) -> {"answer", "failed", "cancelled", "timed_out", "tokens", "attention"}
    stop_chat(sid)           stop the chat's answer now
    notify(title, message)   tell the person (best effort)
    sleep(seconds, cancel)   wait, waking early when `cancel` is set
    """


def limits_hit(run, now=None):
    lim, now = run.get("limits") or {}, now or time.time()
    if lim.get("hours") and now - run["started"] >= lim["hours"] * 3600:
        return f"reached its {lim['hours']:g}-hour limit"
    if lim.get("max_rounds") and run["round"] >= lim["max_rounds"]:
        return f"reached its {lim['max_rounds']}-round limit"
    if lim.get("max_tokens") and run["tokens"] >= lim["max_tokens"]:
        return f"used its {lim['max_tokens']:,}-token limit"
    return ""


def _chat_instructions(role, run):
    return (f"You are the {role} of a long-running build, review, improve loop for the project “{run['title']}”. "
            "Messages arrive from the Crew, not from a person; answer them in full. " + RULES)


def ensure_chat(run, host, entry, role, commit=None):
    """The chat for one builder or reviewer: the one you designated (put to work in the folder, its old
    settings kept to restore), or a new one made for it. A designated chat may work on a model and effort
    you chose; its own are restored with the rest when the crew stops."""
    if entry.get("sid"):
        if entry.get("existing") and entry["sid"] not in run["saved_prefs"]:
            run["saved_prefs"][entry["sid"]] = host.adopt_chat(entry["sid"], run["folder"], entry.get("model"), entry.get("effort"))
            if commit: commit()                       # what to put back must survive a restart
        return entry["sid"]
    if not entry.get("model"):
        raise ValueError(f"the {role} has neither a chat nor a model")
    entry["sid"] = host.create_chat(f"{run['title']} · {role}", entry["model"], _chat_instructions(role.upper(), run), run["folder"], entry.get("effort"))
    entry["rounds"] = 0
    if commit: commit()
    if role == "builder" and run.get("history"): entry["handover"] = True      # a new session after rounds: it reads the notes first
    return entry["sid"]


def release_chats(run, host):
    """Put back what adopting a designated chat changed (its folder and permissions)."""
    for sid, saved in list((run.get("saved_prefs") or {}).items()):
        try: host.release_chat(sid, saved)
        except Exception: pass
    run["saved_prefs"] = {}


class Runner:
    """One crew run's loop, in a thread. `store` is a callable returning the live run dict and a
    `commit()` that saves it; the run dict is the single source of truth (it survives a restart)."""

    def __init__(self, run, host, commit):
        self.run, self.host, self.commit = run, host, commit
        self.cancel = threading.Event()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self.loop, daemon=True, name=f"crew-{self.run['id']}")
        self.thread.start()

    def stop_now(self):
        self.cancel.set()
        for entry in self.run["builders"] + self.run["reviewers"]:
            if entry.get("sid"):
                try: self.host.stop_chat(entry["sid"])
                except Exception: pass

    def _set(self, **kw):
        self.run.update(kw, updated=time.time())
        self.commit()

    def _active(self):
        return self.run["state"] == "running" and not self.cancel.is_set()

    def _pause(self, why, notify=True):
        self._set(state="paused", reason=why, attention="")
        if notify:
            try: self.host.notify(f"Crew “{self.run['title']}” paused", why)
            except Exception: pass

    def _turn(self, role, entry, text, key=None):
        """One answer from a chat; failures wait and retry, so a quota limit or a network drop costs time, not the run."""
        run = self.run
        while self._active():
            sid = ensure_chat(run, self.host, entry, role, self.commit)
            res = self.host.turn(sid, text, TURN_TIMEOUT_S, self.cancel, key=key, settle=(role == "builder"))
            run["tokens"] += int(res.get("tokens") or 0)
            if res.get("attention") and not run.get("attention"):
                self._set(attention=res["attention"])
                try: self.host.notify(f"Crew “{run['title']}” needs you", res["attention"])
                except Exception: pass
            elif not res.get("attention") and run.get("attention"):
                self._set(attention="")
            if res.get("cancelled") or not self._active(): return None
            if res.get("failed") or res.get("timed_out") or not str(res.get("answer") or "").strip():
                run["fails"] += 1
                why = res.get("failed") or ("no answer in time" if res.get("timed_out") else "an empty answer")
                self._set(reason=f"{role} failed ({why}); retrying — {run['fails']} in a row")
                if run["fails"] >= MAX_FAILS:
                    self._pause(f"{role} failed {run['fails']} times in a row ({why}). Resume when it is fixed.")
                    return None
                self.host.sleep(BACKOFF_S[min(run["fails"] - 1, len(BACKOFF_S) - 1)], self.cancel)
                continue
            run["fails"] = 0
            return str(res["answer"])
        return None

    def loop(self):
        run = self.run
        try:
            if not prepare_folder(run):
                return self._pause(f"could not prepare the folder {run['folder']}")
            while self._active():
                why = limits_hit(run)
                if why:
                    release_chats(run, self.host)
                    return self._set(state="done", reason=why)
                rnd = run["round"] + 1
                if run["phase"] in ("idle", "build"):
                    b = builder_for(run, rnd)
                    if not b.get("existing") and b.get("sid") and b.get("rounds", 0) >= run["rollover"]:
                        b["sid"] = None                               # a fresh session; it reads the notes in the folder
                    if not b.get("sid") and run["history"]: b["handover"] = True
                    self._set(phase="build", reason="")
                    ans = self._turn("builder", b, build_prompt(run, rnd, b), f"{run['id']}:{rnd}:build")
                    if ans is None: continue
                    run["notes"] = []                                  # the person's notes were read
                    checkpoint(run, rnd, _first_line(ans))
                    b["rounds"] = b.get("rounds", 0) + 1
                    b["handover"] = False
                    run["builder_text"] = ans[-1500:]
                    self._set(phase="review")
                if run["phase"] == "review":
                    # no reviewer chat: the builder's own chat steps back and reviews (one chat, both jobs)
                    judges = run["reviewers"] or [builder_for(run, rnd)]
                    parts = []
                    for n, j in enumerate(judges):
                        ans = self._turn("reviewer", j, review_prompt(run, rnd, n), f"{run['id']}:{rnd}:review:{n}")
                        if ans is None: break
                        parts.append(parse_review(ans))
                    if len(parts) < len(judges): continue            # paused or stopped part way: the round is reviewed again
                    rev = combine_reviews(parts)
                    entry = {"round": rnd, "t": round(time.time(), 1), "score": rev["score"], "summary": rev["summary"],
                             "issues": rev["issues"], "next_tasks": rev["next_tasks"], "each": rev["each"],
                             "builder": (run.get("builder_text") or "")[-600:]}
                    run["history"].append(entry)
                    del run["history"][:-HISTORY_KEEP]
                    log_review(run, entry)
                    if rev["score"] is not None and (run["best"] is None or rev["score"] > run["best"]):
                        run.update(best=rev["score"], best_round=rnd, since_best=0)
                        tag_best(run)
                    else:
                        run["since_best"] += 1
                    run["backlog"] = merge_backlog(rev["issues"], rev["next_tasks"]) or run["backlog"]
                    self._set(phase="idle", round=rnd, reason="")
        except Exception as e:                                     # a bug here must not end a run that should last for days
            self._pause(f"the loop hit an error: {type(e).__name__}: {e}")


def _first_line(text):
    for line in str(text or "").splitlines():
        line = line.strip(" #*-")
        if line: return line[:90]
    return ""
