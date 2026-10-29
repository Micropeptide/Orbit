#!/usr/bin/env python3
"""Fill the sandbox with invented demo data: mock models + demo chats.

Called by scripts/seed-demo (which starts the sandbox and the mock servers).
Everything here is invented -- no real names, paths or text. The chats are
written straight as session files (deterministic; no live turns), so the
sandbox is ready to be driven immediately.

Usage: seed_demo.py DATA MODEL_PORT
  DATA        the sandbox data folder (ORBIT_SANDBOX_DATA)
  MODEL_PORT  the port the mock model server listens on
"""
import json, os, sys, time, uuid

DATA, MODEL_PORT = sys.argv[1], int(sys.argv[2])
NOW = time.time()
SCHEMA = 2
MODEL = "mock:sonnet"          # provider "mock" (anthropic kind) + model "sonnet"
PROVIDER = "mock"

# a stable base time so the 1,700-message chat reads as a long, real conversation
BASE = NOW - 6 * 86400


def path(sp):
    return os.path.join(DATA, "sessions", sp + ".json")


def save(sp, title, msgs, **extra):
    payload = {"schema": SCHEMA, "title": title, "messages": msgs, "saved": NOW}
    payload.update(extra)
    tmp = path(sp) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f)
    os.replace(tmp, path(sp))
    return sp


def user(text, t):
    return {"role": "user", "content": text, "t": t}


def asst(text, t, think=None, model=MODEL):
    m = {"role": "assistant", "content": text, "t": t, "model": model,
         "secs": 2.0, "usage": {"input_tokens": 200, "output_tokens": 40}}
    if think:
        m["reasoning_content"] = think
    return m


def tool_call(t, name, inp, tid=None):
    tid = tid or "call_" + uuid.uuid4().hex[:8]
    m = {"role": "assistant", "content": "", "t": t, "model": MODEL,
         "secs": 1.0, "tool_runs": 1,
         "tool_calls": [{"id": tid, "name": name, "input": inp}]}
    return m, tid


def tool_result(tid, name, content, t, diff=None, images=None, ok=True):
    m = {"role": "tool", "tool_call_id": tid, "name": name, "t": t, "content": content}
    if diff:
        m["diff"] = diff
    if images:
        m["images"] = images
    if not ok:
        m["ok"] = False
    return m


# ---------------------------------------------------------------- mock models
def register_model():
    """Point a 'mock' provider at the mock server so chats can run on it."""
    mp = os.path.join(DATA, "config", "models.json")
    try:
        cfg = json.load(open(mp))
    except Exception:
        cfg = {"default": MODEL, "models": [], "hidden": [], "providers": {}}
    cfg.setdefault("providers", {})[PROVIDER] = {
        "label": "Mock Sonnet", "kind": "anthropic",
        "base_url": "http://127.0.0.1:%d" % MODEL_PORT, "key": "ORBIT_SANDBOX",
        "note": "a scripted stand-in for a model (seed-demo). The sandbox always sets "
                "ORBIT_SANDBOX=1, which doubles as the mock's dummy key (the server ignores it)."}
    have = {(m.get("provider"), m.get("model")) for m in cfg.get("models", [])}
    if (PROVIDER, "sonnet") not in have:
        cfg.setdefault("models", []).append(
            {"provider": PROVIDER, "model": "sonnet", "label": "Mock Sonnet",
             "context": 200000, "thinking": True})
    cfg["default"] = MODEL
    tmp = mp + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=1)
    os.replace(tmp, mp)


# ---------------------------------------------------------------- demo chats
def chat_long():
    """A ~1,700-message chat: a long, evolving conversation with tool runs."""
    sp = "demo-long"
    msgs = [{"role": "system", "content": "You are Orbit, a careful coding assistant.", "t": BASE}]
    t = BASE
    topics = ["set up the project", "add a test", "fix the flake", "refactor the loader",
              "add a CLI flag", "write the docs", "profile the hot path", "add caching",
              "handle the edge case", "bump the retry limit", "add a timeout", "clean up the log"]
    n = 0
    while len(msgs) < 1700:
        topic = topics[n % len(topics)]
        msgs.append(user("On %s: please continue (pass %d)." % (topic, n // len(topics) + 1), t)); t += 45
        if n % 40 == 39:   # every 40th turn the model writes a file (a tool call with a diff)
            mod = (n // 40) % 12
            m, tid = tool_call(t, "Write", {"file_path": "src/mod_%d.py" % mod,
                                            "content": "def f%d():\n    return %d\n" % (mod, n)})
            msgs.append(m); t += 3
            msgs.append(tool_result(tid, "Write", "wrote src/mod_%d.py" % mod, t + 1,
                                    diff={"path": "src/mod_%d.py" % mod,
                                          "diff": "+def f%d():\n+    return %d" % (mod, n),
                                          "added": 2, "removed": 0}))
            t += 30
        else:
            msgs.append(asst("Done with %s. Next I will %s." % (topic, topics[(n + 1) % len(topics)]), t))
            t += 40
        n += 1
    save(sp, "Long build-out: 1,700 turns", msgs, model=MODEL, project="demo-long")
    return sp


def chat_tools():
    """Tool calls with diffs and a plot image."""
    sp = "demo-tools"
    t = NOW - 3600
    msgs = [{"role": "system", "content": "You are Orbit.", "t": t}]
    msgs.append(user("Add a retry helper and show me the change.", t)); t += 5
    m, tid = tool_call(t, "Write", {"file_path": "src/retry.py",
                                    "content": "def retry(fn, n=3):\n    for i in range(n):\n        try:\n            return fn()\n        except Exception:\n            if i == n - 1: raise\n"})
    msgs.append(m); t += 2
    msgs.append(tool_result(tid, "Write", "wrote src/retry.py", t,
                            diff={"path": "src/retry.py",
                                  "diff": "+def retry(fn, n=3):\n+    for i in range(n):\n+        try:\n+            return fn()\n+        except Exception:\n+            if i == n - 1: raise",
                                  "added": 6, "removed": 0})); t += 4
    m, tid = tool_call(t, "Edit", {"file_path": "src/retry.py",
                                   "old_string": "n=3", "new_string": "n=5"}); t += 2
    msgs.append(m)
    msgs.append(tool_result(tid, "Edit", "edited src/retry.py", t,
                            diff={"path": "src/retry.py", "diff": "-def retry(fn, n=3):\n+def retry(fn, n=5):",
                                  "added": 1, "removed": 1})); t += 4
    m, tid = tool_call(t, "Bash", {"command": "python -m pytest -q"}); t += 2
    msgs.append(m)
    msgs.append(tool_result(tid, "Bash", "12 passed in 1.4s", t)); t += 4
    m, tid = tool_call(t, "Plot", {"figure": "latency by retry count"}); t += 2
    msgs.append(m)
    msgs.append(tool_result(tid, "Plot", "rendered latency.png", t,
                            images=["demo-latency.png"])); t += 4
    msgs.append(asst("Added retry with backoff, bumped the default to 5, tests pass, and here is the latency plot.", t))
    save(sp, "Retry helper with diffs and a plot", msgs, model=MODEL, project="demo-tools")
    return sp


def chat_failed():
    """An answer that failed (a tool error + a model error)."""
    sp = "demo-failed"
    t = NOW - 1800
    msgs = [{"role": "system", "content": "You are Orbit.", "t": t}]
    msgs.append(user("Run the deploy script.", t)); t += 5
    m, tid = tool_call(t, "Bash", {"command": "./deploy.sh"}); t += 2
    msgs.append(m)
    msgs.append(tool_result(tid, "Bash", "deploy.sh: line 12: /opt/bin/svc: Permission denied", t, ok=False)); t += 4
    m, tid = tool_call(t, "Bash", {"command": "sudo -n true"}); t += 2
    msgs.append(m)
    msgs.append(tool_result(tid, "Bash", "sudo: a password is required", t, ok=False)); t += 4
    msgs.append({"role": "assistant", "content": "", "t": t, "model": MODEL, "secs": 0.4,
                 "error": "the model stopped mid-answer (mock: scripted failure)"}); t += 2
    save(sp, "Deploy that failed (tool + model errors)", msgs, model=MODEL, project="demo-failed")
    return sp


def chat_queue_goal():
    """A chat with a goal and a scheduled (queued) message."""
    sp = "demo-goal"
    t = NOW - 900
    msgs = [{"role": "system", "content": "You are Orbit.", "t": t}]
    msgs.append(user("Keep improving the parser until the benchmark is green.", t)); t += 5
    msgs.append(asst("I will work on the parser in rounds and report the benchmark each time.", t)); t += 6
    goal = {"text": "Make the parser benchmark green (>= 99.9% on the held-out set)",
            "created": t, "rounds": 2, "status": "active"}
    queue = [{"id": "q_" + uuid.uuid4().hex[:8], "text": "Summarize the benchmark trend and stop",
              "at": NOW + 3600, "repeat": None, "model": MODEL}]
    save(sp, "Parser goal with a scheduled follow-up", msgs, model=MODEL,
         project="demo-goal", goal=goal, queue=queue)
    return sp


def chat_plain(project=None):
    t = NOW - 300
    msgs = [{"role": "system", "content": "You are Orbit.", "t": t}]
    msgs.append(user("What is the cleanest way to name a module for a retry helper?", t)); t += 3
    msgs.append(asst("I would call it retry.py with a single retry(fn, n) function; the name says what it does and the default is visible at the call site.", t))
    return save("demo-plain", "Naming a retry helper", msgs, model=MODEL, project=project)


def main():
    os.makedirs(os.path.join(DATA, "sessions"), exist_ok=True)
    register_model()
    # a couple of demo projects
    pp = os.path.join(DATA, "config", "projects.json")
    try:
        projects = json.load(open(pp))
    except Exception:
        projects = {}
    for name, color in (("demo-long", "#2d7d4f"), ("demo-tools", "#2c5bf0"),
                        ("demo-failed", "#d1343f"), ("demo-goal", "#9a6510")):
        if name not in projects:
            projects[name] = {"created": NOW, "order": len(projects), "name": name,
                              "color": color, "description": "seed-demo project", "source": "seed"}
    tmp = pp + ".tmp"
    with open(tmp, "w") as f:
        json.dump(projects, f, indent=1)
    os.replace(tmp, pp)

    made = []
    made.append(("long", chat_long()))
    made.append(("tools", chat_tools()))
    made.append(("failed", chat_failed()))
    made.append(("goal", chat_queue_goal()))
    made.append(("plain", chat_plain()))
    # a crew run (the crew backend reads config/crews.json)
    cp = os.path.join(DATA, "config", "crews.json")
    try:
        crews = json.load(open(cp))
    except Exception:
        crews = {}
    cid = "demo-crew"
    if cid not in crews:
        crews[cid] = {"id": cid, "title": "Demo crew: harden the loader",
                      "brief": "Make the file loader handle the edge cases and keep the tests green.",
                      "folder": "demo", "reference": "", "criteria": "tests pass",
                      "builders": [{"chat": made[1][1]}], "reviewers": [{"chat": made[4][1]}],
                      "state": "done", "reason": "finished (seed-demo)", "phase": "review",
                      "round": 2, "created": NOW - 7200, "updated": NOW - 3600,
                      "started": NOW - 7200, "limits": {"rounds": 3}, "tokens": 12000,
                      "best": 2, "best_round": 2, "since_best": 0, "fails": 0,
                      "backlog": [], "notes": [], "history": [
                          {"round": 1, "state": "build", "at": NOW - 7200},
                          {"round": 2, "state": "review", "at": NOW - 3600}],
                      "attention": [], "saved_prefs": {}}
    tmp = cp + ".tmp"
    with open(tmp, "w") as f:
        json.dump(crews, f, indent=1)
    os.replace(tmp, cp)

    print("seeded %d demo chats + mock model + crew" % len(made))
    for k, sp in made:
        print("  %-7s %s" % (k, sp))


if __name__ == "__main__":
    main()
