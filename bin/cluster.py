"""The cluster page: your jobs, the queue, the disk, the GPUs, your limits, and what just happened -- from the cluster itself.

One look is one ssh command (over the same shared connection the Cluster models panel uses) that prints a few sections; the
parsers here turn them into plain data, so the page and the tests never depend on a terminal. It uses Slurm's own commands
(squeue, sacct, sinfo), `quota` and `df`, and HPC's `h2` helper (GPUs free by model and node, your limits, why a job is
pending, a failed job's likely cause). Everything that reaches the world (ssh, notices) is passed in.

A cluster login is not free: the login nodes block a client that connects too often. So a look is cached for a short while,
the background watch asks only for the queue (every couple of minutes while something of yours is queued or running, rarely
otherwise) and backs off when the cluster does not answer.
"""
import json, os, re, shlex, threading, time

MIN_GAP_S = 8                  # a look this soon after another returns what it has
WATCH_BUSY_S, WATCH_IDLE_S = 90, 600
BACKOFF_S = (120, 300, 600, 900)
KEEP_EVENTS = 60
SECTIONS = ("host", "squeue", "sacct", "quota", "df", "gpus", "whoami", "sinfo")


# ---------------------------------------------------------------------------------------------------------- parsing

def split_sections(text):
    """The marked output of the look command -> {name: text}."""
    out, cur = {}, None
    for line in (text or "").splitlines():
        m = re.match(r"@@(\w+)\s*$", line)
        if m: cur = m[1]; out[cur] = []
        elif cur: out[cur].append(line)
    return {k: "\n".join(v).strip("\n") for k, v in out.items()}


def secs(s):
    """Slurm time ('1-02:03:04', '02:03:04', '3:04', 'UNLIMITED') -> seconds, or None."""
    s = str(s or "").strip()
    if not s or s.upper() in ("UNLIMITED", "INVALID", "N/A", "NOT_SET", "NONE", "UNKNOWN"): return None
    try:
        days = 0
        if "-" in s: d, s = s.split("-", 1); days = int(d)
        p = [int(float(x)) for x in s.split(":")]
        while len(p) < 3: p.insert(0, 0)
        return days * 86400 + p[0] * 3600 + p[1] * 60 + p[2]
    except ValueError:
        return None


def size_kb(tok):
    """'34104M', '1863G', '0K', '1.5T' -> kilobytes."""
    m = re.fullmatch(r"([\d.]+)\s*([KMGTP]?)B?", str(tok or "").strip(), re.I)
    if not m: return None
    return float(m[1]) * {"": 1, "K": 1, "M": 1024, "G": 1024 ** 2, "T": 1024 ** 3, "P": 1024 ** 4}[m[2].upper()]


def count(tok):
    """'456k', '5000k', '73877' -> a number."""
    m = re.fullmatch(r"([\d.]+)\s*([kKmM]?)", str(tok or "").strip())
    if not m: return None
    return float(m[1]) * {"": 1, "k": 1e3, "m": 1e6}[m[2].lower()]


def gres_gpus(g):
    m = re.search(r"gpu(?::[\w.-]+)?:(\d+)", str(g or ""))
    return int(m[1]) if m else 0


def parse_squeue(text):
    """squeue -o '%i|%j|%T|%P|%N|%M|%l|%C|%m|%b|%R|%V|%S' -> jobs."""
    jobs = []
    for line in (text or "").splitlines():
        f = line.split("|")
        if len(f) < 12: continue
        el, lim = secs(f[5]), secs(f[6])
        jobs.append({"id": f[0], "name": f[1], "state": f[2], "partition": f[3], "node": f[4] or None, "elapsed": el, "limit": lim,
                     "left": (lim - el) if (lim is not None and el is not None and f[2] == "RUNNING") else None,
                     "cpus": int(f[7]) if f[7].isdigit() else None, "mem": f[8], "gpus": gres_gpus(f[9]), "reason": f[10] if f[2] == "PENDING" else "",
                     "submitted": f[11], "start_est": f[12] if len(f) > 12 and f[12] not in ("N/A", "Unknown", "") else ""})
    return jobs


def parse_sacct(text):
    """sacct -X -P -o JobID,JobName,Partition,State,Elapsed,ExitCode,Start,End,AllocTRES,NodeList -> finished and recent jobs, newest first."""
    rows = []
    for line in (text or "").splitlines():
        f = line.split("|")
        if len(f) < 8: continue
        state = f[3].split()[0] if f[3] else ""
        tres = f[8] if len(f) > 8 else ""
        rows.append({"id": f[0], "name": f[1], "partition": f[2], "state": state, "state_text": f[3], "elapsed": secs(f[4]), "exit": f[5],
                     "start": f[6], "end": f[7], "gpus": gres_gpus(re.sub(r"gres/", "", tres.replace("gres/gpu=", "gpu:")).replace("gpu=", "gpu:")),
                     "node": (f[9] if len(f) > 9 else "") or None})
    rows.sort(key=lambda r: r["start"] if r["start"] not in ("Unknown", "None") else "9", reverse=True)
    return rows


def parse_quota(text):
    """`quota -s` -> [{filesystem, used_kb, quota_kb, limit_kb, files, files_quota, files_limit}]; a quota of 0 means none."""
    lines = [l for l in (text or "").splitlines() if l.strip()]
    out, i = [], 0
    pat = re.compile(r"(\d+[KMGTP]?)\s+(\d+[KMGTP]?)\s+(\d+[KMGTP]?)\s+(?:([A-Za-z][\w:]*)\s+)?(\d+[kKmM]?)\s+(\d+[kKmM]?)\s+(\d+[kKmM]?)")
    while i < len(lines):
        l = lines[i]
        if l.startswith("Disk quotas") or l.strip().startswith("Filesystem"): i += 1; continue
        fs, rest = (l.strip(), lines[i + 1] if i + 1 < len(lines) else "") if not pat.search(l) else (l.split()[0], l)
        m = pat.search(rest)
        if m:
            used, quota, limit = size_kb(m[1]), size_kb(m[2]), size_kb(m[3])
            out.append({"filesystem": fs, "used_kb": used, "quota_kb": quota, "limit_kb": limit, "grace": m[4] or "",
                        "files": count(m[5]), "files_quota": count(m[6]), "files_limit": count(m[7])})
            i += 1 if pat.search(l) else 2
        else:
            i += 1
    return out


def parse_df(text):
    """df -hPT -> [{mount, filesystem, size, used, avail, pct}]"""
    out = []
    for line in (text or "").splitlines()[1:]:
        f = line.split()
        if len(f) < 6 or not f[-2].endswith("%"): continue
        out.append({"mount": f[-1], "filesystem": f[0], "size": f[-5], "used": f[-4], "avail": f[-3], "pct": int(f[-2].rstrip("%"))})
    return out


def md_tables(text):
    """Markdown tables in `h2` output -> {heading: [row dicts]}."""
    tables, head, hdr = {}, "", None
    for line in (text or "").splitlines():
        if line.startswith("## "): head, hdr = line[3:].strip(), None; continue
        if not line.strip().startswith("|"): hdr = None if not line.strip() else hdr; continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if hdr is None: hdr = cells; tables[head] = []; continue
        if all(re.fullmatch(r":?-+:?", c) for c in cells if c): continue
        tables[head].append(dict(zip(hdr, cells)))
    return tables


def parse_gpus(text):
    """`h2 gpus` -> {models: [{model, vram, nodes, gpus, free}], nodes: [{node, model, free, total, state, idle_cpus, free_mem, partitions}], summary}."""
    t = md_tables(text)
    models = [{"model": r.get("Model"), "vram": r.get("VRAM"), "nodes": _int(r.get("Nodes")), "gpus": _int(r.get("GPUs")), "free": _int(r.get("Free"))}
              for r in next((v for k, v in t.items() if k.startswith("GPUs by model")), [])]
    nodes = []
    for r in next((v for k, v in t.items() if k.startswith("GPU nodes")), []):
        m = re.fullmatch(r"(\d+)/(\d+)", r.get("Free GPUs", ""))
        nodes.append({"node": r.get("Node"), "model": r.get("Model"), "free": int(m[1]) if m else None, "total": int(m[2]) if m else None,
                      "state": r.get("State"), "idle_cpus": r.get("Idle CPUs"), "free_mem": r.get("Free mem"), "partitions": r.get("Partitions")})
    m = re.search(r"(\d+) of (\d+) GPUs free", text or "")
    return {"models": models, "nodes": nodes, "free": int(m[1]) if m else None, "total": int(m[2]) if m else None}


def _int(v):
    try: return int(str(v).strip())
    except ValueError: return None


def parse_whoami(text):
    """`h2 whoami` -> account, fairshare and the per-user limits."""
    t = text or ""
    acct = re.search(r"Account:\s*(\w+)", t)
    fs = re.search(r"fairshare\s+([\d.]+)", t)
    lim = re.search(r"per user:\s*(\d+) CPUs,\s*(\d+) GPUs,\s*(\d+) nodes,\s*(\d+) running jobs", t)
    run = re.search(r"jobs run on (\w+): (\S+) max,\s*(\d+) nodes \((\d+) idle\),\s*(\d+) CPUs \((\d+) idle\),\s*(\d+) GPUs", t)
    return {"account": acct[1] if acct else None, "fairshare": float(fs[1]) if fs else None,
            "limits": ({"cpus": int(lim[1]), "gpus": int(lim[2]), "nodes": int(lim[3]), "running_jobs": int(lim[4])} if lim else None),
            "partition": ({"name": run[1], "max_time": run[2], "nodes": int(run[3]), "idle_nodes": int(run[4]), "cpus": int(run[5]),
                           "idle_cpus": int(run[6]), "gpus": int(run[7])} if run else None)}


def parse_sinfo(text):
    """sinfo -o '%P|%a|%l|%C' -> [{partition, up, max_time, cpus_alloc, cpus_idle, cpus_other, cpus_total}]"""
    out = []
    for line in (text or "").splitlines():
        f = line.split("|")
        c = re.fullmatch(r"(\d+)/(\d+)/(\d+)/(\d+)", f[3]) if len(f) > 3 else None
        if c: out.append({"partition": f[0].rstrip("*"), "up": f[1] == "up", "max_time": f[2], "cpus_alloc": int(c[1]), "cpus_idle": int(c[2]),
                          "cpus_other": int(c[3]), "cpus_total": int(c[4])})
    return out


def parse_host(text):
    f = (text or "").strip().split("|")
    return {"node": f[0], "processes": _int(f[1]) if len(f) > 1 else None, "process_limit": _int(f[2]) if len(f) > 2 else None,
            "load": f[3].strip() if len(f) > 3 else None}


REFRESH_DEFAULT = {"on": True, "every_h": 24, "at": "03:00", "remeasure": True}
SAME_KB, SAME_FILES, MAX_AGE_S = 100 * 1024, 200, 7 * 86400     # "nothing changed": less drift than this in a quota, and measured within a week


def next_refresh(last, every_h, at, now):
    """When the slow readings are next due. Every 24 h or more it is at a fixed time of day (`at`, local), that many whole days after the
    last refresh; shorter, it is simply that many hours after. With no refresh yet, the first is at the next such time."""
    every_h = max(1, int(every_h))
    if every_h < 24: return (last or now) + every_h * 3600
    try: hh, mm = (int(x) for x in str(at).split(":"))
    except ValueError: hh, mm = 3, 0
    base = time.localtime(last or now)
    days = every_h // 24 if last else 0
    t = time.mktime((base.tm_year, base.tm_mon, base.tm_mday + days, hh, mm, 0, 0, 0, -1))
    if not last and t <= now: t = time.mktime((base.tm_year, base.tm_mon, base.tm_mday + 1, hh, mm, 0, 0, 0, -1))
    return t


def dismissed(problem, record):
    """Was this problem dismissed, and is it still the same one? It comes back when it got worse (or just different): another level, a value
    two points further, other jobs."""
    if not record: return False
    if record.get("level") != problem["level"]: return False
    if problem.get("value") is not None and abs(problem["value"] - (record.get("value") if record.get("value") is not None else -99)) >= 2: return False
    return set(problem.get("ids") or ()) == set(record.get("ids") or ())


def snapshot_from(text, project_dir="", ignore=(), now=None):
    """The whole look -> what the page shows."""
    s = split_sections(text)
    jobs = parse_squeue(s.get("squeue"))
    df = parse_df(s.get("df"))
    quota = parse_quota(s.get("quota"))
    storage = []
    for q in quota:
        label = "Home" if "/home" in q["filesystem"] else "Scratch" if "scratch" in q["filesystem"] else q["filesystem"]
        cap = q["quota_kb"] or q["limit_kb"]
        storage.append({**q, "label": label, "pct": round(100.0 * q["used_kb"] / cap) if (cap and q["used_kb"] is not None) else None,
                        "files_pct": round(100.0 * q["files"] / (q["files_quota"] or q["files_limit"])) if (q["files"] is not None and (q["files_quota"] or q["files_limit"])) else None})
    homes = [x for x in storage if x["label"] == "Home"]
    storage = ([homes[0]] if homes else []) + [x for x in storage if x["label"] != "Home"]       # the same home is listed once per server
    shared = [d for d in df if project_dir and d["mount"] == project_dir]
    return {"host": parse_host(s.get("host")), "jobs": jobs, "recent": parse_sacct(s.get("sacct")), "storage": storage, "shared": shared,
            "gpus": parse_gpus(s.get("gpus")), "account": parse_whoami(s.get("whoami")), "partitions": parse_sinfo(s.get("sinfo")),
            "problems": problems_of(jobs, parse_sacct(s.get("sacct")), storage, shared, parse_whoami(s.get("whoami")), ignore, now)}


def problems_of(jobs, recent, storage, shared, account, ignore=(), now=None):
    """What deserves a look, in plain words, worst first."""
    out = []
    for d in shared:
        if d["pct"] >= 90: out.append({"key": "disk:lab", "value": d["pct"], "level": "bad" if d["pct"] >= 95 else "warn", "text": f"The lab's project disk is {d['pct']}% full: {d['avail']} left of {d['size']}."})
    for q in storage:
        if q.get("pct") is not None and q["pct"] >= 85: out.append({"key": "quota:" + q["label"], "value": q["pct"], "level": "bad" if q["pct"] >= 95 else "warn", "text": f"{q['label']} is {q['pct']}% of its quota."})
        if q.get("files_pct") is not None and q["files_pct"] >= 85: out.append({"key": "files:" + q["label"], "value": q["files_pct"], "level": "warn", "text": f"{q['label']} has used {q['files_pct']}% of its file-count quota."})
    waiting = [j for j in jobs if j["state"] == "PENDING" and j["name"] not in ignore and not j["name"].startswith(DU_JOB)]
    if waiting:
        oldest = waiting[0]
        out.append({"key": "pending", "ids": sorted(j["id"] for j in waiting), "level": "info", "text": f"{len(waiting)} job{'s' if len(waiting) > 1 else ''} waiting for the cluster ({oldest['reason'] or 'queued'})."})
    def recent_enough(r):              # the last day, where it is known: older news is in the list below
        if not now: return True
        try: return now - time.mktime(time.strptime(r["start"], "%Y-%m-%dT%H:%M:%S")) < 86400
        except (TypeError, ValueError): return True
    bad = [r for r in recent[:15] if r["state"] in ("FAILED", "OUT_OF_MEMORY", "NODE_FAIL", "TIMEOUT") and r["name"] not in ignore and recent_enough(r)]
    if bad: out.append({"key": "failed", "ids": sorted(r["id"] for r in bad), "level": "warn", "text": f"{len(bad)} job{'s' if len(bad) > 1 else ''} from the last day did not finish well: " + ", ".join(f"{r['name']} ({r['state'].lower().replace('_', ' ')})" for r in bad[:3]) + "."})
    lim = (account or {}).get("limits") or {}
    if lim.get("gpus") is not None and sum(j["gpus"] for j in jobs if j["state"] == "RUNNING") >= lim["gpus"]:
        out.append({"key": "gpus", "level": "info", "text": f"All {lim['gpus']} GPUs you may use at once are in use."})
    order = {"bad": 0, "warn": 1, "info": 2}
    return sorted(out, key=lambda p: order[p["level"]])


# ---------------------------------------------------------------------------------------- reading errors in a job's output

# (pattern, kind, what it means, what usually helps)
ERROR_PATTERNS = (
    (r"CUDA out of memory|OutOfMemoryError|CUDA error: out of memory", "gpu_oom", "the GPU ran out of memory",
     "use a smaller batch or sequence length, or ask for a GPU with more memory (the GPUs table shows what exists)"),
    (r"oom-kill|Out of memory: Killed|oom_kill|MemoryError|std::bad_alloc|Cannot allocate memory|\bKilled\b", "oom", "the job ran out of memory",
     "ask for more memory (--mem=...) or hold less data in memory at once"),
    (r"No space left on device|Disk quota exceeded|Errno 122|Errno 28", "disk", "the disk is full or over its quota",
     "free space in the folder the job writes to, or write to scratch"),
    (r"ModuleNotFoundError|ImportError: No module|ImportError: cannot import", "module", "a Python package is missing",
     "load the module or activate the environment inside the job script, not only in your login shell"),
    (r"command not found|No such file or directory", "missing", "a program or a file was not found",
     "check the path, the working directory and the modules the job script loads"),
    (r"Permission denied", "perm", "permission was denied", "check the file's owner and mode, and where the job writes"),
    (r"Segmentation fault|core dumped|SIGSEGV", "segv", "the program crashed (segmentation fault)", "usually a bug or a library mismatch: run it again with the same modules, or on a smaller input"),
    (r"DUE TO TIME LIMIT|TIME LIMIT", "time", "the job reached its time limit", "ask for more time (-t) or make the job save its state and resume"),
    (r"Connection (refused|timed out|reset)|Could not resolve host|Network is unreachable", "network", "a network connection failed",
     "compute nodes can lack outside network: download what you need on a login node first"),
    (r"slurmstepd: error|srun: error", "slurm", "Slurm reported an error", "read the line it gives"),
    (r"Traceback \(most recent call last\)|^\w*Error: ", "error", "the program raised an error", "the last lines of the traceback say where"),
)
_SEVERE = {"gpu_oom", "oom", "disk", "segv", "slurm"}


def scan_text(text):
    """Errors in the end of a job's output -> [{kind, what, fix, line}], most telling first. One finding per kind; the line is the last one that matched."""
    found = {}
    for line in (text or "").splitlines():
        for pat, kind, what, fix in ERROR_PATTERNS:
            if re.search(pat, line):
                found[kind] = {"kind": kind, "what": what, "fix": fix, "line": line.strip()[:200]}
                break
    order = {k[1]: i for i, k in enumerate(ERROR_PATTERNS)}
    return sorted(found.values(), key=lambda f: order[f["kind"]])


def cause_of(state, exit_code="", findings=()):
    """How a job ended, in words: {title, fix, kind}. The scheduler's state first, the exit code next, then what the output says."""
    state = (state or "").upper()
    code = str(exit_code or "").split(":")[0]
    if state == "OUT_OF_MEMORY": return {"kind": "oom", "title": "It ran out of memory", "fix": "ask for more memory (--mem=...) or hold less data at once"}
    if state == "TIMEOUT": return {"kind": "time", "title": "It reached its time limit", "fix": "ask for more time (-t), or make the job save its state and resume"}
    if state == "NODE_FAIL": return {"kind": "node", "title": "The node it ran on failed", "fix": "nothing in the job is wrong: submit it again"}
    if state == "CANCELLED": return {"kind": "cancelled", "title": "It was cancelled", "fix": ""}
    if findings:
        f = sorted(findings, key=lambda f: (f["kind"] not in _SEVERE,))[0]
        return {"kind": f["kind"], "title": f["what"][0].upper() + f["what"][1:], "fix": f["fix"], "line": f.get("line", "")}
    if code == "127": return {"kind": "missing", "title": "A command was not found (exit code 127)", "fix": "check the modules and the PATH inside the job script"}
    if code == "137": return {"kind": "oom", "title": "It was killed (exit code 137), most often for memory", "fix": "ask for more memory (--mem=...)"}
    if code == "139": return {"kind": "segv", "title": "The program crashed (segmentation fault)", "fix": "try the same input on a smaller case, with the same modules"}
    if state == "FAILED": return {"kind": "failed", "title": "It failed" + (f" (exit code {code})" if code and code != "0" else ""), "fix": "read the end of its output"}
    return {"kind": "ok" if state == "COMPLETED" else "other", "title": state.lower().replace("_", " ").capitalize() if state else "", "fix": ""}


def efficiency_of(text, mem_req_mb=None):
    """`sacct -j ID -n -P -o JobID,State,Elapsed,AllocCPUS,ReqMem,MaxRSS,TotalCPU` (steps included) -> how much of what was asked for was used."""
    elapsed, cpus, req, rss, cpu_s = None, None, None, 0.0, 0.0
    for line in (text or "").splitlines():
        f = line.split("|")
        if len(f) < 7: continue
        if "." not in f[0]:                               # the job itself
            elapsed, cpus = secs(f[2]), _int(f[3])
            m = re.fullmatch(r"([\d.]+)([KMGT]?)([nc]?)", f[4].strip())
            if m: req = float(m[1]) * {"": 1, "K": 1 / 1024, "M": 1, "G": 1024, "T": 1024 ** 2}[m[2]] * ((cpus or 1) if m[3] == "c" else 1)
        kb = size_kb(f[5]) if f[5].strip() else None
        if kb: rss = max(rss, kb / 1024)                  # MB
        t = secs(f[6]) if f[6].strip() else None
        if t is None and re.fullmatch(r"[\d:.]+", f[6].strip()):
            parts = f[6].strip().split(":"); t = sum(float(x) * m for x, m in zip(reversed(parts), (1, 60, 3600)))
        if t: cpu_s = max(cpu_s, t)
    cpu_eff = round(100.0 * cpu_s / (elapsed * cpus)) if (elapsed and cpus and cpu_s) else None
    mem_eff = round(100.0 * rss / req) if (req and rss) else None
    notes = []
    if mem_eff is not None and mem_eff >= 90: notes.append("It came close to the memory it asked for: give it more next time so a slightly bigger input does not kill it.")
    if mem_eff is not None and mem_eff < 25 and req and req >= 8192: notes.append(f"It used {mem_eff}% of the memory it asked for ({int(req / 1024)} G): asking for less starts sooner.")
    if cpu_eff is not None and cpu_eff < 25 and cpus and cpus >= 4: notes.append(f"It used {cpu_eff}% of {cpus} CPUs: the program may not use more than one, so ask for fewer.")
    return {"elapsed": elapsed, "cpus": cpus, "mem_requested_mb": round(req) if req else None, "mem_used_mb": round(rss) if rss else None,
            "mem_eff": mem_eff, "cpu_eff": cpu_eff, "notes": notes}


def gb(tok):
    m = re.fullmatch(r"([\d.]+)([KMGT]?)B?", str(tok or "").strip())
    return float(m[1]) * {"K": 1 / 1024 ** 2, "M": 1 / 1024, "": 1, "G": 1, "T": 1024}[m[2]] if m else None


def fits(gpu_nodes, gpus=1, mem_gb=0, cpus=0, model=""):
    """Which GPU nodes could start a job asking for this right now -> [{node, model, free_gpus, free_mem, idle_cpus}], roomiest first."""
    out = []
    for n in gpu_nodes or []:
        if model and model.lower() not in str(n.get("model", "")).lower(): continue
        if (n.get("state") or "").startswith(("drain", "down", "idle+drain")) or "drain" in (n.get("state") or ""): continue
        idle = re.match(r"(\d+)", str(n.get("idle_cpus") or ""))
        mem = gb(n.get("free_mem"))
        if (n.get("free") or 0) >= gpus and (mem is None or mem >= mem_gb) and (not idle or int(idle[1]) >= cpus):
            out.append({"node": n["node"], "model": n.get("model"), "free_gpus": n.get("free"), "free_mem": n.get("free_mem"), "idle_cpus": n.get("idle_cpus")})
    return sorted(out, key=lambda x: -(x["free_gpus"] or 0))


def parse_ps(text):
    """`ps -u $USER -o pid=,etime=,stat=,args=` -> processes, with the ones that keep the login itself alive marked."""
    out = []
    for line in (text or "").splitlines():
        m = re.match(r"\s*(\d+)\s+(\S+)\s+(\S+)\s+(.*)$", line)
        if not m: continue
        et = m[2]; d = 0
        if "-" in et: d, et = et.split("-", 1); d = int(d)
        parts = [int(x) for x in et.split(":")]
        while len(parts) < 3: parts.insert(0, 0)
        age = d * 86400 + parts[0] * 3600 + parts[1] * 60 + parts[2]
        args = m[4]
        system = bool(re.match(r"(sshd|\(sd-pam\)|/usr/lib/systemd|-?bash\b|ps |head |sort |-?zsh|sshd-session)", args))
        out.append({"pid": int(m[1]), "age": age, "state": m[3], "cmd": args[:160], "system": system})
    return out


def disk_level(pct):
    return "bad" if pct is not None and pct >= 95 else "warn" if pct is not None and pct >= 85 else "ok"


# ------------------------------------------------------------------------------------------------- how you have used the cluster

HIST_FIELDS = "JobID,JobName%30,Partition,State,Elapsed,ExitCode,Submit,Start,End,AllocTRES%80,AllocCPUS"


def history_command(days):
    return f"sacct -S now-{int(days)}days -u $USER -X -n -P -o {HIST_FIELDS} 2>&1 | tail -n 3000"


def _t(x):
    try: return time.mktime(time.strptime(x, "%Y-%m-%dT%H:%M:%S"))
    except (TypeError, ValueError): return None


def tres_gpus(tres):
    m = re.search(r"gres/gpu(?::[\w.-]+)?[=:](\d+)", str(tres or ""))
    return int(m[1]) if m else 0


def median(v):
    v = sorted(v)
    return None if not v else v[len(v) // 2] if len(v) % 2 else (v[len(v) // 2 - 1] + v[len(v) // 2]) / 2


def summarize_history(text):
    """sacct rows of the last days -> GPU- and CPU-hours, how many ended well, and per job name how long it usually waits and runs."""
    jobs = []
    for line in (text or "").splitlines():
        f = line.split("|")
        if len(f) < 11: continue
        st = f[3].split()[0] if f[3] else ""
        sub, start = _t(f[6]), _t(f[7])
        el = secs(f[4]) or 0
        cpus = _int(f[10]) or 0
        jobs.append({"id": f[0], "name": f[1], "state": st, "elapsed": el, "wait": (start - sub) if (sub and start and start >= sub) else None,
                     "gpus": tres_gpus(f[9]), "cpus": cpus, "start": start, "day": time.strftime("%Y-%m-%d", time.localtime(start)) if start else None})
    ran = [j for j in jobs if j["start"]]
    names = {}
    for j in ran: names.setdefault(j["name"], []).append(j)
    by_name = sorted(({"name": n, "jobs": len(v), "ok": sum(1 for j in v if j["state"] == "COMPLETED"),
                       "failed": sum(1 for j in v if j["state"] in ("FAILED", "OUT_OF_MEMORY", "NODE_FAIL", "TIMEOUT")),
                       "median_wait": median([j["wait"] for j in v if j["wait"] is not None]), "median_run": median([j["elapsed"] for j in v]),
                       "gpu_hours": round(sum(j["gpus"] * j["elapsed"] for j in v) / 3600, 1)} for n, v in names.items()),
                     key=lambda r: (-r["gpu_hours"], -r["jobs"]))
    daily = {}
    for j in ran:
        d = daily.setdefault(j["day"], {"day": j["day"], "jobs": 0, "gpu_hours": 0.0, "cpu_hours": 0.0})
        d["jobs"] += 1; d["gpu_hours"] += j["gpus"] * j["elapsed"] / 3600; d["cpu_hours"] += j["cpus"] * j["elapsed"] / 3600
    return {"jobs": len(jobs), "ran": len(ran), "completed": sum(1 for j in ran if j["state"] == "COMPLETED"),
            "failed": sum(1 for j in ran if j["state"] in ("FAILED", "OUT_OF_MEMORY", "NODE_FAIL", "TIMEOUT")),
            "cancelled": sum(1 for j in ran if j["state"].startswith("CANCELLED")),
            "gpu_hours": round(sum(j["gpus"] * j["elapsed"] for j in ran) / 3600, 1), "cpu_hours": round(sum(j["cpus"] * j["elapsed"] for j in ran) / 3600),
            "median_wait": median([j["wait"] for j in ran if j["wait"] is not None]), "by_name": by_name[:25],
            "daily": [dict(d, gpu_hours=round(d["gpu_hours"], 1), cpu_hours=round(d["cpu_hours"])) for d in sorted(daily.values(), key=lambda d: d["day"])]}


# ------------------------------------------------------------------------- what is using the disk (measured by a small job)

DU_JOB = "orbit-du-"                     # the name of the measuring jobs: Orbit's own, never announced as news
DU_DIR = "$HOME/.orbit/du"


def du_key(path):
    import hashlib
    return hashlib.sha1(path.encode()).hexdigest()[:10]


# One pass over every file of a place (a person's own, never the lab-wide one): the biggest files, the kinds of file, and what has not been
# touched for a year. Written for POSIX awk. The kind is the last extension, or the last two for .gz/.bz2/.xz/.zst (fastq.gz, tar.gz).
FILES_AWK = r"""BEGIN{FS="\t"; old=now-31536000}
{ s=$1; m=$2; f=$3; n++; tot+=s
  e="(none)"; if (match(f, /\.[^.]+$/)) { e=tolower(substr(f, RSTART+1)); b=substr(f, 1, RSTART-1)
    if ((e=="gz"||e=="bz2"||e=="xz"||e=="zst") && match(b, /\.[^.]+$/)) e=tolower(substr(b, RSTART+1)) "." e }
  c[e]++; z[e]+=s; if (m<old) { oc++; oz+=s }
  if (s>=1048576) print s "\t" int(m) "\t" $4 > big }
END{ for (e in c) print e "\t" c[e] "\t" z[e] > ext; print n+0 "\t" tot+0 "\t" oc+0 "\t" oz+0 > sum }"""


def du_script(key, path, parallel=4, files=True):
    """The batch job that measures what is directly inside `path`: size, path, owner and kind of each entry, a few at a time, written as it goes
    (so the page can show a partial answer) and sorted when finished; with `files`, then one pass over all its files for the biggest ones, the
    kinds of file and the old ones. On a big shared disk this takes minutes to hours; it runs on a compute node."""
    q = shlex.quote(path)
    scan = """
find __Q__ -xdev -type f -printf '%s\\t%T@\\t%f\\t%p\\n' 2>/dev/null | awk -v now=$(date +%s) -v big="$O/$K.big" -v ext="$O/$K.ext0" -v sum="$O/$K.sum" '__AWK__'
sort -rn "$O/$K.big" | head -n 60 > "$O/$K.files"; sort -t"$(printf '\\t')" -k3,3 -rn "$O/$K.ext0" | head -n 40 > "$O/$K.ext"; rm -f "$O/$K.big" "$O/$K.ext0"
""".replace("__Q__", q).replace("__AWK__", FILES_AWK.replace("'", "'\\''")) if files else ""
    return f"""#!/bin/bash
O="$HOME/.orbit/du"; mkdir -p "$O"; K={key}
rm -f "$O/$K.tsv" "$O/$K.done" "$O/$K.files" "$O/$K.ext" "$O/$K.sum"; : > "$O/$K.tmp"
date +%s > "$O/$K.start"
ls -A {q} 2>/dev/null | wc -l > "$O/$K.total"
find {q} -mindepth 1 -maxdepth 1 -print0 2>/dev/null | xargs -0 -P {int(parallel)} -n 1 sh -c 'k=$(du -sk -x "$0" 2>/dev/null | cut -f1); t=f; [ -d "$0" ] && t=d; printf "%s\\t%s\\t%s\\t%s\\n" "${{k:-0}}" "$0" "$(stat -c %U "$0" 2>/dev/null)" "$t" >> "$HOME/.orbit/du/{key}.tmp"'
{scan}sort -rn "$O/$K.tmp" > "$O/$K.tsv"; rm -f "$O/$K.tmp"; date +%s > "$O/$K.done"
"""


def parse_files(text):
    """bytes TAB mtime TAB path -> the biggest files, largest first."""
    out = []
    for line in (text or "").splitlines():
        f = line.split("\t")
        if len(f) >= 3 and f[0].isdigit(): out.append({"kb": int(f[0]) // 1024, "mtime": int(f[1]) if f[1].isdigit() else None, "path": f[2]})
    return sorted(out, key=lambda r: -r["kb"])


def parse_ext(text):
    """kind TAB count TAB bytes -> [{ext, count, kb}], largest first."""
    out = []
    for line in (text or "").splitlines():
        f = line.split("\t")
        if len(f) >= 3 and f[1].isdigit() and f[2].isdigit(): out.append({"ext": f[0], "count": int(f[1]), "kb": int(f[2]) // 1024})
    return sorted(out, key=lambda r: -r["kb"])


def parse_sum(text):
    """files TAB bytes TAB old files TAB old bytes -> totals, or None."""
    f = (text or "").strip().split("\t")
    if len(f) < 4 or not all(x.isdigit() for x in f[:4]): return None
    return {"files": int(f[0]), "kb": int(f[1]) // 1024, "old_files": int(f[2]), "old_kb": int(f[3]) // 1024}


def parse_du(tsv):
    """size_kb TAB path TAB owner TAB kind -> rows, largest first."""
    rows = []
    for line in (tsv or "").splitlines():
        f = line.split("\t")
        if len(f) >= 2 and f[0].isdigit():
            rows.append({"kb": int(f[0]), "path": f[1], "owner": f[2] if len(f) > 2 else "", "kind": f[3] if len(f) > 3 else ""})
    rows.sort(key=lambda r: -r["kb"])
    return rows


def rank_people(rows):
    """Rows of top-level folders on a shared disk -> who uses it: [{owner, kb, folders: [path...]}], biggest first."""
    by = {}
    for r in rows:
        o = r.get("owner") or "(unknown)"
        d = by.setdefault(o, {"owner": o, "kb": 0, "folders": []})
        d["kb"] += r["kb"]; d["folders"].append(r["path"])
    return sorted(by.values(), key=lambda d: -d["kb"])


# ------------------------------------------------------------------------------------------------------ the commands

SLOW_SECTIONS = ("quota", "df", "whoami")      # read from the disks and the account database: slow on a busy login node, and slow to change


def look_command(project_dir="", slow=True):
    """One ssh command that prints every section the page needs. The slow ones (quotas, disk sizes, limits) only when asked for, and every
    command has its own time limit so one stuck disk cannot take the whole answer with it."""
    df = "timeout 25 df -hPT $HOME" + (" " + shlex.quote(project_dir) if project_dir else "") + " 2>&1"
    fast = ('echo @@host; echo "$(hostname -s)|$(ps -u $USER --no-headers | wc -l)|$(ulimit -u)|$(uptime | sed \'s/.*load average: //\')"; '
            'echo @@squeue; timeout 20 squeue -u $USER -h -o "%i|%j|%T|%P|%N|%M|%l|%C|%m|%b|%R|%V|%S" 2>&1; '
            'echo @@sacct; timeout 20 sacct -S now-3days -u $USER -X -n -P -o JobID,JobName%30,Partition,State,Elapsed,ExitCode,Start,End,AllocTRES%80,NodeList 2>&1 | tail -n 60; '
            'echo @@gpus; timeout 20 h2 gpus 2>&1 | head -60; '
            'echo @@sinfo; timeout 15 sinfo -h -o "%P|%a|%l|%C" 2>&1 | head -12')
    if not slow: return fast
    return (fast + '; echo @@quota; timeout 25 quota -s 2>&1 | head -30; '
            'echo @@df; ' + df + '; '
            'echo @@whoami; timeout 25 h2 whoami 2>&1 | head -40')


PS_COMMAND = "ps -u $USER -o pid=,etime=,stat=,args= --sort=-etime 2>&1 | head -60"


def outputs_command(ids):
    """The end of the output of each of these (running) jobs, marked by job."""
    ids = [i for i in ids if re.fullmatch(r"\d+(_\d+)?", i)]
    return ('for j in ' + " ".join(ids) + '; do p=$(scontrol show job -o $j 2>/dev/null | tr " " "\n" | grep "^StdOut=" | head -1 | cut -d= -f2); '
            'echo "@@out $j"; [ -n "$p" ] && [ -f "$p" ] && tail -n 80 "$p" 2>/dev/null; done')


def efficiency_command(jid):
    return "sacct -j " + shlex.quote(jid) + " -n -P -o JobID,State,Elapsed,AllocCPUS,ReqMem,MaxRSS,TotalCPU 2>&1"


QUEUE_COMMAND = 'squeue -u $USER -h -o "%i|%j|%T|%P|%N|%M|%l|%C|%m|%b|%R|%V|%S" 2>&1'


def ended_command(ids):
    return "sacct -X -n -P -o JobID,JobName%30,Partition,State,Elapsed,ExitCode,Start,End,AllocTRES%80,NodeList -j " + ",".join(i for i in ids if re.fullmatch(r"\d+(_\d+)?", i)) + " 2>&1"


# -------------------------------------------------------------------------------------------------------- the manager

class Cluster:
    """What is known about the cluster, from looks at it. `world.ssh(host, command)` -> (code, text)."""
    def __init__(self, path, world, now=time.time, notify=None, own_jobs=lambda: set(), explain_with=None):
        self.path, self.w, self.now = path, world, now
        self.explain_with = explain_with      # text -> a short plain-language explanation (a model), or None
        self.notify = notify or (lambda title, text: None)
        self.own_jobs = own_jobs              # job names that belong to another panel (the model servers): it says their news itself
        self.lock = threading.RLock()
        self.cfg = self._load()
        self.snap, self.snap_at, self.error = None, 0.0, ""
        self.hist_cache, self.du_marks = {}, {}
        self.slow_text, self.slow_at, self.du_cache = {}, 0.0, {}     # the slow sections of the last look, when they were read; the last disk measurements
        self._load_cache()
        self.fails, self.next_look, self.page_seen = 0, 0.0, 0.0
        self.known = {}                        # job id -> {name, state} at the last queue look
        self.flagged = set()                   # (job id, kind) already said, so an error is not announced again and again
        self.disk_state = {}                   # what each disk's level was at the last look
        self.next_scan = 0.0
        self.events = self._load_events()

    # --- config and events
    def _load(self):
        try: d = json.load(open(self.path))
        except (OSError, ValueError): d = {}
        d.setdefault("host", "hpc"); d.setdefault("project_dir", ""); d.setdefault("watch", True)
        d.setdefault("notify", {})
        for k, v in {"started": False, "finished": True, "failed": True, "errors": True, "disk": True, "pending": True, "digest": True}.items(): d["notify"].setdefault(k, v)
        d["refresh"] = {**REFRESH_DEFAULT, **(d.get("refresh") if isinstance(d.get("refresh"), dict) else {})}      # when the slow readings are read again by themselves
        d.setdefault("explain", True)               # a failed job's cause, explained in plain words by Orbit's helper model
        return d

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f: json.dump(self.cfg, f, indent=1)
        os.replace(tmp, self.path)

    def _events_path(self): return os.path.join(os.path.dirname(self.path), "cluster-events.json")

    def _load_events(self):
        try: return json.load(open(self._events_path()))[-KEEP_EVENTS:]
        except (OSError, ValueError): return []

    def _add_event(self, kind, text, job=None, detail="", cause=None):
        with self.lock:
            self.events.append({"t": self.now(), "kind": kind, "text": text, "job": job, **({"detail": detail[-3000:]} if detail else {}), **({"cause": cause} if cause else {})})
            self.events = self.events[-KEEP_EVENTS:]
            tmp = self._events_path() + ".tmp"
            try:
                with open(tmp, "w") as f: json.dump(self.events, f)
                os.replace(tmp, self._events_path())
            except OSError: pass

    def update(self, d):
        with self.lock:
            if "project_dir" in d: self.cfg["project_dir"] = str(d["project_dir"] or "").strip()[:200] if re.fullmatch(r"(/[\w.-]+)*", str(d["project_dir"] or "").strip()) else self.cfg["project_dir"]
            if "watch" in d: self.cfg["watch"] = bool(d["watch"])
            if "explain" in d: self.cfg["explain"] = bool(d["explain"])
            if isinstance(d.get("refresh"), dict):
                r, n = self.cfg["refresh"], d["refresh"]
                if "on" in n: r["on"] = bool(n["on"])
                if "remeasure" in n: r["remeasure"] = bool(n["remeasure"])
                if re.fullmatch(r"\d+", str(n.get("every_h", ""))): r["every_h"] = max(1, min(24 * 30, int(n["every_h"])))
                if re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", str(n.get("at", ""))): r["at"] = n["at"]
                if not self.cfg.get("last_refresh"): self.cfg["last_refresh"] = self.now()
            if isinstance(d.get("notify"), dict):
                for k in ("started", "finished", "failed", "errors", "disk", "pending", "digest"):
                    if k in d["notify"]: self.cfg["notify"][k] = bool(d["notify"][k])
            self._save()

    # --- looking
    def look(self, force=False, slow=False, cached=False):
        """The whole picture (cached for a few seconds). The queue and GPUs are read each time; quotas, disk sizes and limits are slow to read
        and slow to change, so the last reading is kept (with its time) and only read again when `slow` is asked for, or never read."""
        with self.lock:
            self.page_seen = self.now()
            if cached and self.snap: return self.public()          # the page opening: what was last read, at once
            if not force and self.snap and self.now() - self.snap_at < MIN_GAP_S and not slow: return self.public()
            need_slow = slow or not self.slow_text
        code, out = self.w.ssh(self.cfg["host"], look_command(self.cfg.get("project_dir", ""), slow=need_slow), 75)
        with self.lock:
            if code or "@@squeue" not in out:
                self.error = (out or "no answer")[:200]; self.fails += 1
                self.next_look = self.now() + BACKOFF_S[min(self.fails, len(BACKOFF_S)) - 1]
            else:
                self.error, self.fails = "", 0
                sec = split_sections(out)
                if need_slow and any(k in sec for k in SLOW_SECTIONS):
                    self.slow_text = {k: sec[k] for k in SLOW_SECTIONS if k in sec}; self.slow_at = self.now(); self._save_cache()
                text = out if need_slow else out + "".join(f"\n@@{k}\n{v}" for k, v in self.slow_text.items())
                self.snap = snapshot_from(text, self.cfg.get("project_dir", ""), self.own_jobs(), self.now()); self.snap_at = self.now()
                self.snap["slow_at"] = self.slow_at
                self._see_jobs(self.snap["jobs"], full=True)
                if need_slow: self._see_disks(self.snap)
                self._forget_dismissals()
                self._save_cache()
        return self.public()

    # --- the last reading is kept on disk, so the page has something to show the moment it opens (with the time it was read)
    def _cache_path(self): return os.path.join(os.path.dirname(self.path), "cluster-last.json")

    def _save_cache(self):
        try:
            tmp = self._cache_path() + ".tmp"
            with open(tmp, "w") as f: json.dump({"snap": self.snap, "snap_at": self.snap_at, "slow_text": self.slow_text, "slow_at": self.slow_at, "du": self.du_cache, "hist": self.hist_cache, "marks": self.du_marks}, f)
            os.replace(tmp, self._cache_path())
        except OSError: pass

    def _load_cache(self):
        try: c = json.load(open(self._cache_path()))
        except (OSError, ValueError): return
        self.snap, self.snap_at = c.get("snap"), c.get("snap_at") or 0.0
        self.slow_text, self.slow_at, self.du_cache = c.get("slow_text") or {}, c.get("slow_at") or 0.0, c.get("du") or {}
        self.hist_cache, self.du_marks = c.get("hist") or {}, c.get("marks") or {}

    # --- warnings can be put away; they come back when they change
    def dismiss(self, key):
        with self.lock:
            p = next((p for p in (self.snap or {}).get("problems", []) if p.get("key") == key), None)
            if not p: raise ValueError("that warning is not there any more")
            self.cfg.setdefault("dismissed", {})[key] = {"level": p["level"], "value": p.get("value"), "ids": p.get("ids") or []}
            self._save()
        return self.public()

    def restore(self, key=None):
        with self.lock:
            if key is None: self.cfg["dismissed"] = {}
            else: self.cfg.setdefault("dismissed", {}).pop(key, None)
            self._save()
        return self.public()

    def _forget_dismissals(self):
        """A warning that is gone is forgotten: if it comes back later, it is news again."""
        keys = {p.get("key") for p in (self.snap or {}).get("problems", [])}
        gone = [k for k in self.cfg.get("dismissed", {}) if k not in keys]
        for k in gone: self.cfg["dismissed"].pop(k, None)
        if gone: self._save()

    def public(self):
        with self.lock:
            snap = self.snap
            if snap:
                rec = self.cfg.get("dismissed", {})
                snap = dict(snap, problems=[dict(p, dismissed=dismissed(p, rec.get(p.get("key")))) for p in snap.get("problems", [])])
            return {"snapshot": snap, "at": self.snap_at, "error": self.error, "config": self.cfg, "events": list(reversed(self.events[-30:])),
                    "model_server_jobs": sorted(self.own_jobs()), "now": self.now(), "next_refresh": self.refresh_at(), "history": self.hist_cache}

    # --- the watch: the queue only, and what changed
    def watch_once(self):
        jobs_code, out = self.w.ssh(self.cfg["host"], QUEUE_COMMAND, 40)
        if jobs_code:
            with self.lock:
                self.fails += 1; self.next_look = self.now() + BACKOFF_S[min(self.fails, len(BACKOFF_S)) - 1]; self.error = (out or "")[:200]
            return
        with self.lock: self.fails, self.error = 0, ""
        self._see_jobs(parse_squeue(out), full=False)

    def _see_jobs(self, jobs, full):
        """Compare with what was there: a job that started, or went away (then ask how it ended)."""
        with self.lock:
            now_ids = {j["id"]: j for j in jobs}
            first = not self.known and not self.events
            gone = [i for i in self.known if i not in now_ids]
            for i, j in now_ids.items():
                old = self.known.get(i)
                if old is None and not first: self._add_event("submitted", f"{j['name']} ({i}) was submitted", i)
                elif old and old["state"] == "PENDING" and j["state"] == "RUNNING":
                    self._add_event("started", f"{j['name']} ({i}) started on {j['node'] or 'a node'}", i)
                    if self.cfg["notify"].get("started") and not self._own(j["name"]): self.notify(f"Job started: {j['name']}", f"{i} is running on {j['node'] or 'a node'}")
            for i, j in now_ids.items():
                if j["state"] == "PENDING" and ("p", i) not in self.flagged and not self._own(j["name"]):
                    waited = self._waited(j.get("submitted"))
                    if waited is not None and waited >= 4 * 3600:
                        self.flagged.add(("p", i))
                        text = f"{j['name']} ({i}) has waited {int(waited // 3600)} h for the cluster ({j['reason'] or 'queued'})"
                        self._add_event("pending", text, i)
                        if self.cfg["notify"].get("pending"): self.notify("A job has waited a long time", text + ". Open the cluster page for why and what would start it sooner.")
            names = {i: self.known[i]["name"] for i in gone}
            self.known = {i: {"name": j["name"], "state": j["state"]} for i, j in now_ids.items()}
        if gone: self._how_ended(gone, names)

    def _how_ended(self, ids, names):
        code, out = self.w.ssh(self.cfg["host"], ended_command(ids), 40)
        rows = {r["id"]: r for r in parse_sacct(out)} if not code else {}
        for i in ids:
            r = rows.get(i)
            state = r["state"] if r else "ENDED"
            ok = state == "COMPLETED"
            took = f" after {_dur(r['elapsed'])}" if r and r.get("elapsed") is not None else ""
            text = f"{names.get(i, i)} ({i}) {'finished' if ok else state.lower().replace('_', ' ')}{took}" + ("" if ok or not r else f" (exit code {r['exit']})")
            detail, cause = "", None
            if not ok and state not in ("CANCELLED", "ENDED") and not self._own(names.get(i)):
                detail, cause = self._triage(i, state, r["exit"] if r else "")
            kind = "finished" if ok else "failed" if state in ("FAILED", "OUT_OF_MEMORY", "NODE_FAIL", "TIMEOUT") else "ended"
            self._add_event(kind, text + (f": {cause['title'].lower()}" if cause and cause.get("title") else ""), i, detail=detail, cause=cause)
            n = self.cfg["notify"]
            if self._own(names.get(i)): continue
            if (ok and n.get("finished")) or (not ok and state != "CANCELLED" and n.get("failed")):
                self.notify(("Job finished: " if ok else "Job did not finish: ") + names.get(i, i),
                            text + (f". {cause['title']}. {cause['fix'][:1].upper() + cause['fix'][1:] + '.' if cause.get('fix') else ''}" if cause and cause.get("title") else ""))

    def _triage(self, jid, state, exit_code):
        """Why a job went wrong: the cluster's own `h2 diagnose`, what the output says, and (if switched on) a model's plain explanation."""
        try:
            code, diag = self.w.ssh(self.cfg["host"], "h2 diagnose " + shlex.quote(jid) + " 2>&1 | head -70", 60)
        except Exception:
            code, diag = 1, ""
        diag = diag if not code else ""
        cause = cause_of(state, exit_code, scan_text(diag))
        detail = diag
        if self.cfg.get("explain") and self.explain_with and diag:
            try:
                said = (self.explain_with("A Slurm job on a university cluster failed. State: %s, exit code %s.\n\nThe cluster's diagnosis, with the end of its output:\n%s\n\n"
                                         "In two or three plain sentences: what most likely went wrong, and the one change most likely to fix it. "
                                         "If the evidence does not say, say so. No preamble." % (state, exit_code or "?", diag[-6000:])) or "").strip()
                if said: cause["explained"] = said[:700]
            except Exception: pass
        return detail, cause

    def loop(self, stop=None):
        while not (stop and stop.is_set()):
            try:
                if self.cfg.get("watch") and self.now() >= self.next_look:
                    self.watch_once()
                    busy = any(j["state"] in ("PENDING", "RUNNING") and not self._own(j["name"]) for j in self.known_list()) or self.now() - self.page_seen < 600
                    gap = WATCH_BUSY_S if busy else WATCH_IDLE_S
                    with self.lock: self.next_look = max(self.next_look, self.now() + gap)
                self.maybe_digest()
                self.maybe_refresh()
                if self.cfg.get("watch") and self.now() >= self.next_scan:
                    self.scan_running()
                    with self.lock: self.next_scan = self.now() + 300
            except Exception as e:
                with self.lock: self.error = f"{type(e).__name__}: {e}"; self.next_look = self.now() + 300
            time.sleep(5)

    def refresh_at(self):
        r = self.cfg["refresh"]
        return next_refresh(self.cfg.get("last_refresh") or 0, r["every_h"], r["at"], self.now()) if r.get("on") else None

    def maybe_refresh(self):
        at = self.refresh_at()
        if at is None: return
        if not self.cfg.get("last_refresh"):
            with self.lock: self.cfg["last_refresh"] = self.now(); self._save()      # the clock starts now: the first refresh is at the next such time
            return
        if self.now() >= at: self.refresh_all()

    def _mark(self, which):
        """What is known about a place when it is measured, to tell later whether anything changed (a quota says it exactly for home and scratch)."""
        m = {"t": self.now()}
        q = next((x for x in (self.snap or {}).get("storage", []) if x["label"].lower() == str(which)), None)
        if q: m.update(used_kb=q.get("used_kb"), files=q.get("files"))
        return m

    def unchanged(self, which):
        """Is the last measurement of this place still true? -> (True, why) only when it is clear. Home and scratch: their quota has not moved
        (the numbers are exact and cost nothing, the look has just read them). Any other place: nothing in it was modified since, to a few levels
        down (one cheap find that stops at the first hit). Anything measured more than a week ago is measured again anyway."""
        with self.lock: st, mk = self.du_cache.get(str(which)), self.du_marks.get(str(which))
        if not st or not st.get("done"):          # what is kept may be from before the measuring job finished: read it now
            try: st = self.du_status(which, refresh=True)
            except Exception: st = None
        if st and st.get("running"): return True, "being measured now"
        if not st or not st.get("done") or not st.get("measured_at"): return False, "never measured"
        if self.now() - st["measured_at"] > MAX_AGE_S: return False, "last measured over a week ago"
        q = next((x for x in (self.snap or {}).get("storage", []) if x["label"].lower() == str(which)), None)
        if q and mk and mk.get("used_kb") is not None and q.get("used_kb") is not None:
            ok = abs(q["used_kb"] - mk["used_kb"]) < SAME_KB and abs((q.get("files") or 0) - (mk.get("files") or 0)) < SAME_FILES
            return ok, "the quota has not moved" if ok else "the quota moved"
        if q: return False, "no earlier quota to compare"
        code, out = self.w.ssh(self.cfg["host"], f"timeout 25 find {shlex.quote(st['path'])} -maxdepth 4 -newermt @{int(st['measured_at'])} -print -quit 2>/dev/null | head -n 1; true", 40)
        if code: return False, "could not check"
        return (not out.strip()), ("nothing modified since" if not out.strip() else "something was modified")

    def refresh_all(self):
        """Read every slow thing again: quotas, disks, limits, the usage history, the folder breakdowns last looked at (and, if wanted, measure
        my own folders afresh: never the lab-wide one, which loads the shared disk). Quiet: it is not news."""
        with self.lock: self.cfg["last_refresh"] = self.now(); self._save()           # first, so a failure is not retried every few seconds
        done = []
        try: self.look(force=True, slow=True); done.append("disks and limits")
        except Exception: pass
        with self.lock: days = sorted(set([7] + [h["days"] for h in self.hist_cache.values()])); keys = list(self.du_cache)
        for d in days:
            try: self.history(d, refresh=True); done.append(f"history ({d} d)")
            except Exception: pass
        for k in keys:
            try: self.du_status(k, refresh=True)
            except Exception: pass
        if keys: done.append("folder breakdowns")
        if self.cfg["refresh"].get("remeasure"):
            roots = self.du_roots()
            # only the person's own places, and folders looked into inside them: never the lab-wide count, never other people's folders
            with self.lock:
                own = [self.du_cache[k]["path"].rstrip("/") + "/" for k in ("home", "scratch", "mine") if k in self.du_cache]
                drilled = [k for k, v in sorted(self.du_cache.items(), key=lambda kv: -(kv[1].get("read_at") or 0))
                           if k not in roots and any(v.get("path", "").startswith(o) for o in own)][:6]
            # and the biggest folders directly inside those places (a gigabyte or more, the largest five of each), so the person need not open each
            with self.lock:
                big = [r["path"] for k in ("home", "scratch", "mine") for r in [x for x in (self.du_cache.get(k) or {}).get("rows", []) if x["kind"] == "d" and x["kb"] >= 1048576][:5]]
            drilled = list(dict.fromkeys(drilled + [b for b in big if b not in roots]))[:14]
            places = [k for k in ("home", "scratch", "mine") if k in roots] + drilled
            started, same = [], []
            for k in places:
                try:
                    skip, _ = self.unchanged(k)
                    if skip: same.append(k)
                    else: self.du_start(k); started.append(k)
                except Exception: pass
            if started: done.append("measuring " + ", ".join(started))
            if same: done.append("unchanged, not measured again: " + ", ".join(same))
        self._add_event("refresh", "Read again by schedule: " + ", ".join(done or ["nothing could be read"]), None)

    def _own(self, name):
        """A job Orbit started for itself (a model server, a disk measurement): its news is not announced here."""
        return str(name).startswith(DU_JOB) or name in self.own_jobs()

    def known_list(self):
        with self.lock: return [dict(v, id=k) for k, v in self.known.items()]

    def _waited(self, submitted):
        try: return self.now() - time.mktime(time.strptime(submitted, "%Y-%m-%dT%H:%M:%S"))
        except (TypeError, ValueError): return None

    def _see_disks(self, snap):
        """A disk crossing 85% or 95%: said once when it gets worse, and a day's reading is kept so growth shows."""
        levels = {}
        for q in snap.get("storage", []):
            if q.get("pct") is not None: levels[q["label"]] = q["pct"]
        for d in snap.get("shared", []): levels["Project disk"] = d["pct"]
        for name, pct in levels.items():
            new, old = disk_level(pct), self.disk_state.get(name, "ok")
            if new != "ok" and (old == "ok" or (old == "warn" and new == "bad")):
                text = f"{name} is {pct}% full"
                self._add_event("disk", text, None)
                if self.cfg["notify"].get("disk"): self.notify("Cluster disk: " + name, text + ". Open the cluster page to see how much room is left.")
            self.disk_state[name] = new
        day = time.strftime("%Y-%m-%d", time.localtime(self.now()))
        hist = self._history()
        if not hist or hist[-1]["day"] != day:
            hist.append({"day": day, "levels": levels, "used_kb": {q["label"]: q["used_kb"] for q in snap.get("storage", []) if q.get("used_kb") is not None}})
            try:
                tmp = self._history_path() + ".tmp"
                with open(tmp, "w") as f: json.dump(hist[-120:], f)
                os.replace(tmp, self._history_path())
            except OSError: pass

    def _history_path(self): return os.path.join(os.path.dirname(self.path), "cluster-history.json")

    def _history(self):
        try: return json.load(open(self._history_path()))
        except (OSError, ValueError): return []

    def growth(self):
        """How each disk changed over the last week -> {label: kb}, from the daily readings."""
        h = self._history()
        if len(h) < 2: return {}
        old, new = h[max(0, len(h) - 8)], h[-1]
        return {k: v - old["used_kb"][k] for k, v in new["used_kb"].items() if k in old["used_kb"]}

    def scan_running(self):
        """Read the end of every running job's output and say what looks wrong, once per kind per job."""
        with self.lock: ids = [i for i, j in self.known.items() if j["state"] == "RUNNING" and not self._own(j["name"])]
        if not ids: return
        code, out = self.w.ssh(self.cfg["host"], outputs_command(ids), 60)
        if code: return
        chunks = re.split(r"^@@out (\S+)\s*$", out, flags=re.M)
        for jid, text in zip(chunks[1::2], chunks[2::2]):
            for f in scan_text(text):
                if f["kind"] in ("error",) and any(x["kind"] != "error" for x in scan_text(text)): continue       # a traceback of a worse kind is already said
                key = (jid, f["kind"])
                if key in self.flagged: continue
                self.flagged.add(key)
                name = (self.known.get(jid) or {}).get("name", jid)
                text_ = f"{name} ({jid}): {f['what']}. Its output says: {f['line']}"
                self._add_event("error", text_, jid, detail=text[-1500:], cause={"kind": f["kind"], "title": f["what"], "fix": f["fix"]})
                if self.cfg["notify"].get("errors"): self.notify(f"A running job shows an error: {name}", f"{f['what'][0].upper() + f['what'][1:]}. {f['fix'][:1].upper() + f['fix'][1:]}." if f["fix"] else f["what"])

    def processes(self):
        """Your processes on the login node (the number that decides whether it can start a shell), oldest first."""
        code, out = self.w.ssh(self.cfg["host"], PS_COMMAND, 30)
        if code: raise RuntimeError(out[:200] or "the cluster did not answer")
        return parse_ps(out)

    def stop_process(self, pid):
        pid = int(pid)
        mine = {p["pid"]: p for p in self.processes()}
        if pid not in mine: raise ValueError("that is not one of your processes on the login node")
        if mine[pid]["system"]: raise ValueError("that process keeps your login working: leave it")
        code, out = self.w.ssh(self.cfg["host"], f"kill {pid} 2>&1", 30)
        if code: raise RuntimeError(out[:200] or "kill failed")
        self._add_event("process", f"You stopped process {pid} ({mine[pid]['cmd'][:60]})", None)
        return True

    def history(self, days=7, refresh=False):
        """The usage summary of the last `days`: the kept one (with the time it was read) unless a refresh is asked for or there is none."""
        days = max(1, min(90, int(days or 7)))
        with self.lock: cached = self.hist_cache.get(str(days))
        if cached and not refresh: return dict(cached, cached=True)
        code, out = self.w.ssh(self.cfg["host"], history_command(days), 90)
        if code: raise RuntimeError(out[:200] or "the cluster did not answer")
        res = dict(summarize_history(out), days=days, read_at=self.now())
        with self.lock: self.hist_cache[str(days)] = res; self._save_cache()
        return dict(res, cached=False)

    def digest_text(self, since):
        """What happened since `since`, in a few lines, for the morning notice -> text or ''."""
        with self.lock: ev = [e for e in self.events if e["t"] >= since and e["kind"] in ("finished", "failed", "error", "pending", "disk")]
        done = [e for e in ev if e["kind"] == "finished"]; bad = [e for e in ev if e["kind"] in ("failed", "error")]
        parts = []
        if done: parts.append(f"{len(done)} job{'s' if len(done) > 1 else ''} finished")
        if bad: parts.append(f"{len(bad)} went wrong: " + "; ".join(e["text"].split(" after ")[0] for e in bad[:2]))
        extra = [e["text"] for e in ev if e["kind"] in ("disk", "pending")][:1]
        snap = self.snap or {}
        jobs = [j for j in snap.get("jobs", []) if not self._own(j["name"])]
        if jobs: parts.append(f"{sum(1 for j in jobs if j['state'] == 'RUNNING')} running, {sum(1 for j in jobs if j['state'] == 'PENDING')} waiting")
        probs = [p["text"] for p in snap.get("problems", []) if p["level"] == "bad"][:1]
        return ". ".join(parts + extra + probs)

    def maybe_digest(self):
        """Once a morning (from 8:00), one notice about the night: what finished, what went wrong, what is still going."""
        if not self.cfg["notify"].get("digest", True): return
        lt = time.localtime(self.now()); day = time.strftime("%Y-%m-%d", lt)
        if lt.tm_hour < 8 or self.cfg.get("last_digest") == day: return
        text = self.digest_text(self.now() - 14 * 3600)
        with self.lock: self.cfg["last_digest"] = day; self._save()
        if text: self.notify("Cluster this morning", text)

    def du_roots(self):
        pd = self.cfg.get("project_dir") or ""
        return {"home": "$HOME", "scratch": "$SCRATCH", **({"mine": shlex.quote(pd) + "/$USER", "lab": shlex.quote(pd)} if pd else {})}

    def _du_target(self, which):
        """A named place ('home', 'scratch', 'mine', 'lab') or a folder under one of them (checked on the cluster) -> the shell word for it."""
        roots = self.du_roots()
        if which in roots: return roots[which]
        if not re.fullmatch(r"/[\w./+@-]+", str(which)) or ".." in str(which): raise ValueError("not a folder path")
        return shlex.quote(str(which))

    def du_start(self, which):
        """Measure what is directly inside a place, as a small batch job (never on the login node). -> {job, path}"""
        target = self._du_target(which)
        guard = ('P=$(readlink -f -- ' + target + ' 2>/dev/null) || exit 4; case "$P" in "$HOME"|"$HOME"/*|"$SCRATCH"|"$SCRATCH"/*'
                 + ("|" + shlex.quote(self.cfg["project_dir"]) + "|" + shlex.quote(self.cfg["project_dir"]) + "/*" if self.cfg.get("project_dir") else "")
                 + ') ;; *) echo "not inside your home, scratch or the lab folder"; exit 3;; esac; ')
        code, path = self.w.ssh(self.cfg["host"], guard + 'echo "$P"', 30)
        path = path.strip().splitlines()[-1] if path.strip() else ""
        if code or not path.startswith("/"): raise ValueError(path or "that folder cannot be measured")
        key = du_key(path)
        code, run = self.w.ssh(self.cfg["host"], f'squeue -u $USER -h -n {DU_JOB}{key} -o "%i"', 30)
        if not code and run.strip(): return {"job": run.split()[0], "path": path, "already": True}
        import base64
        b64 = base64.b64encode(du_script(key, path, 2 if which == "lab" else 4, files=(which != "lab")).encode()).decode()
        cmd = (f'mkdir -p {DU_DIR} && printf %s {b64} | base64 -d > {DU_DIR}/{key}.sh && '
               f'sbatch --parsable -J {DU_JOB}{key} -t 12:00:00 -c 4 --mem=2G -o /dev/null {DU_DIR}/{key}.sh')
        code, out = self.w.ssh(self.cfg["host"], cmd, 40)
        jid = out.strip().split(";")[0].strip()
        if code or not jid.isdigit(): raise RuntimeError("the cluster refused the measuring job: " + out[:200])
        with self.lock:
            self.du_cache.pop(str(which), None)                                          # the old reading is stale from now on
            self.du_marks[str(which)] = self._mark(which); self._save_cache()
        self._add_event("measure", f"Measuring what is inside {path} (job {jid}); it can take a while on a big disk", jid)
        return {"job": jid, "path": path}

    def du_status(self, which, refresh=False):
        """What a measurement has so far: rows, how far along, when it was measured, and (for the lab folder) who uses it.
        The last reading is kept here, with the time it was read: it is returned as it is unless `refresh` is asked for (or there is none),
        because reading the cluster for it can take many seconds on a busy login node."""
        target = self._du_target(which)
        ck = str(which)
        with self.lock: cached = self.du_cache.get(ck)
        if cached and not refresh: return dict(cached, cached=True)
        # one ssh call: resolve the folder, then read its measurement (the key is a hash of the resolved path, as du_key makes it)
        cmd = ('P=$(timeout 20 readlink -f -- ' + target + ' 2>/dev/null) || exit 4; echo "@@path"; echo "$P"; K=$(printf %s "$P" | sha1sum | cut -c1-10); '
               f'O={DU_DIR}; echo "@@state"; for f in start done total; do printf "%s=" $f; cat $O/$K.$f 2>/dev/null || echo; done; '
               f'echo "@@job"; timeout 20 squeue -u $USER -h -n {DU_JOB}$K -o "%i|%T" 2>&1; echo "@@tsv"; cat $O/$K.tsv 2>/dev/null; echo "@@tmp"; cat $O/$K.tmp 2>/dev/null; echo "@@files"; cat $O/$K.files 2>/dev/null; echo "@@ext"; cat $O/$K.ext 2>/dev/null; echo "@@sum"; cat $O/$K.sum 2>/dev/null; true')
        code, out = self.w.ssh(self.cfg["host"], cmd, 60)
        if code: raise RuntimeError(out[:200] or "the cluster did not answer")
        sec = split_sections(out)
        path = (sec.get("path") or "").strip()
        if not path.startswith("/"): raise ValueError(path or "unknown folder")
        key = du_key(path)
        st = dict(re.findall(r"(\w+)=(\d*)", sec.get("state", "")))
        job = (sec.get("job") or "").strip()
        final = parse_du(sec.get("tsv"))
        rows = final or parse_du(sec.get("tmp"))
        total = int(st.get("total") or 0)
        res = {"path": path, "key": key, "rows": rows[:80], "entries": len(rows), "total_entries": total, "total_kb": sum(r["kb"] for r in rows),
               "running": bool(job) and "|" in job, "job": job.split("|")[0] if "|" in job else "", "done": bool(final),
               "measured_at": int(st["done"]) if st.get("done") else None, "started_at": int(st["start"]) if st.get("start") else None,
               "people": rank_people(rows)[:30] if which == "lab" else None, "read_at": self.now(),
               "files": parse_files(sec.get("files"))[:50], "ext": parse_ext(sec.get("ext"))[:25], "summary": parse_sum(sec.get("sum"))}
        with self.lock: self.du_cache[ck] = res; self._save_cache()
        return dict(res, cached=False)

    def efficiency(self, jid):
        jid = str(jid)
        if not re.fullmatch(r"\d+(_\d+)?", jid): raise ValueError("not a job id")
        code, out = self.w.ssh(self.cfg["host"], efficiency_command(jid), 40)
        if code: raise RuntimeError(out[:200] or "the cluster did not answer")
        return efficiency_of(out)

    def where_to_run(self, gpus=1, mem_gb=0, cpus=0, model=""):
        s = (self.snap or {}).get("gpus") or {}
        res = fits(s.get("nodes"), int(gpus or 1), float(mem_gb or 0), int(cpus or 0), str(model or ""))
        lim = (((self.snap or {}).get("account") or {}).get("limits") or {}).get("gpus")
        return {"nodes": res, "gpu_limit": lim, "over_limit": bool(lim is not None and int(gpus or 1) > lim)}

    def ask_text(self, jid):
        """What a chat needs to help with one job: its record, the cluster's diagnosis, and the end of its output."""
        jid = str(jid)
        ev = next((e for e in reversed(self.events) if e.get("job") == jid and e.get("detail")), None)
        job = next((j for j in ((self.snap or {}).get("jobs") or []) + ((self.snap or {}).get("recent") or []) if j["id"] == jid), None)
        parts = [f"Help me with Slurm job {jid} on HPC."]
        if job: parts.append("Record: " + json.dumps({k: v for k, v in job.items() if v not in (None, "")}))
        if ev: parts.append("What Orbit saw: " + ev["text"] + ("\nLikely cause: " + ev["cause"]["title"] + ". " + ev["cause"].get("fix", "") if ev.get("cause") else "") + "\n\nDiagnosis and the end of its output:\n" + ev["detail"])
        else:
            try: parts.append("Diagnosis:\n" + self.explain(jid, "diagnose"))
            except Exception as e: parts.append(f"(could not fetch the diagnosis: {e})")
        parts.append("What went wrong, and what exactly should I change? If a job script is involved, ask me for it.")
        return "\n\n".join(parts)

    # --- things you do
    def _own_job_ids(self):
        code, out = self.w.ssh(self.cfg["host"], 'squeue -u $USER -h -o "%i"', 30)
        return set(out.split()) if not code else set()

    def cancel(self, jid):
        jid = str(jid)
        if not re.fullmatch(r"\d+(_\d+)?", jid): raise ValueError("not a job id")
        if jid.split("_")[0] not in {i.split("_")[0] for i in self._own_job_ids()}: raise ValueError("that is not one of your jobs in the queue")
        code, out = self.w.ssh(self.cfg["host"], "scancel " + shlex.quote(jid), 30)
        if code: raise RuntimeError(out[:200] or "scancel failed")
        self._add_event("cancelled", f"You cancelled job {jid}", jid)
        return self.look(force=True)

    def explain(self, jid, kind):
        """`h2 why-pending` for a job waiting, `h2 diagnose` for one that went wrong: the cluster's own explanation."""
        jid = str(jid)
        if not re.fullmatch(r"\d+(_\d+)?", jid): raise ValueError("not a job id")
        cmd = {"why": "h2 why-pending ", "diagnose": "h2 diagnose ", "job": "h2 job "}.get(kind)
        if not cmd: raise ValueError("unknown question")
        code, out = self.w.ssh(self.cfg["host"], cmd + shlex.quote(jid) + " 2>&1 | head -80", 60)
        if code: raise RuntimeError(out[:200] or "the cluster did not answer")
        return out

    def output(self, jid, lines=120):
        """The end of a job's output file (the job must still be known to the scheduler)."""
        jid = str(jid)
        if not re.fullmatch(r"\d+(_\d+)?", jid): raise ValueError("not a job id")
        n = max(10, min(400, int(lines)))
        cmd = ('p=$(scontrol show job -o ' + shlex.quote(jid) + ' 2>/dev/null | tr " " "\\n" | grep "^StdOut=" | head -1 | cut -d= -f2); '
               '[ -n "$p" ] && [ -f "$p" ] && { echo "== $p"; tail -n ' + str(n) + ' "$p"; } || echo "(no output file: the job is no longer in the scheduler\'s memory, or it writes nowhere)"')
        code, out = self.w.ssh(self.cfg["host"], cmd, 40)
        if code: raise RuntimeError(out[:200] or "the cluster did not answer")
        return out

    def summary_text(self):
        """The picture as plain text, for a chat about it."""
        s = (self.snap or {})
        lines = ["HPC right now (read %ds ago):" % int(self.now() - self.snap_at) if self.snap else "HPC (no look yet):"]
        for j in s.get("jobs", []): lines.append(f"- job {j['id']} {j['name']}: {j['state']}{(' on ' + j['node']) if j['node'] else ''}{(' (' + j['reason'] + ')') if j['reason'] else ''}, {j['gpus']} GPU, {j['cpus']} CPU")
        if not s.get("jobs"): lines.append("- no jobs in the queue")
        for q in s.get("storage", []): lines.append(f"- {q['label']}: {q['pct']}% of its quota" if q.get("pct") is not None else f"- {q['label']}: {q['filesystem']}")
        for d in s.get("shared", []): lines.append(f"- project disk {d['mount']}: {d['pct']}% full, {d['avail']} free")
        g = s.get("gpus") or {}
        if g.get("total"): lines.append(f"- GPUs: {g['free']} of {g['total']} free: " + ", ".join(f"{m['model']} {m['free']}/{m['gpus']}" for m in g["models"]))
        for p in s.get("problems", []): lines.append("! " + p["text"])
        return "\n".join(lines)


def _dur(t):
    t = int(t or 0)
    return f"{t // 3600} h {t % 3600 // 60} min" if t >= 3600 else f"{t // 60} min {t % 60} s" if t >= 60 else f"{t} s"


# ---------------------------------------------------------------------------------- a cluster that is only in memory

class SimCluster:
    """For a sandbox copy of Orbit: a cluster with invented jobs, disks and GPUs. Nothing here runs a command."""
    def __init__(self, now=time.time):
        self.now, self.t0, self.cancelled = now, now(), set()

    def ssh(self, host, cmd, timeout=30):
        if cmd.startswith("scancel"): self.cancelled.add(cmd.split()[-1].strip("'")); return 0, ""
        if cmd.startswith("P=$(timeout 20 readlink"): return 0, "@@path\n/path/to/project/lab\n@@state\nstart=\ndone=\ntotal=\n@@job\n@@tsv\n@@tmp\n"
        if cmd.startswith("P=$(readlink"): return 0, "/path/to/project/lab"
        if cmd.startswith("squeue -u $USER -h -o \"%i\""): return 0, "\n".join(j.split("|")[0] for j in self._queue())
        if cmd == QUEUE_COMMAND: return 0, "\n".join(self._queue())
        if cmd.startswith("sacct"): return 0, self._sacct()
        if cmd.startswith("h2 "): return 0, "## Job 7001: demo\n\n- **state:** PENDING\n\n### Why it is pending\n\n- **SLURM reason:** Resources\n\nWaiting for resources (simulated)."
        if "du -sh" in cmd: return 0, "41G\t/u/home/demo"
        if "StdOut" in cmd: return 0, "== /u/home/demo/slurm-7002.out\nstep 1 done\nstep 2 done\n(simulated output)"
        return 0, self._look()

    def _queue(self):
        up = int(self.now() - self.t0)
        rows = ["7001|align-reads|PENDING|campus||0:00|1-00:00:00|8|32G|gres/gpu:1|Resources|2026-01-01T09:00:00|2026-01-01T11:00:00",
                "7002|train-model|RUNNING|campus|g12|%d:%02d:%02d|1-00:00:00|16|64G|gres/gpu:1|None|2026-01-01T08:00:00|N/A" % (up // 3600, up % 3600 // 60, up % 60)]
        return [r for r in rows if r.split("|")[0] not in self.cancelled]

    def _sacct(self):
        return ("7000|index-genome|campus|COMPLETED|00:42:10|0:0|2026-01-01T06:00:00|2026-01-01T06:42:10|billing=8,cpu=8,gres/gpu=0,mem=32G|n21\n"
                "6999|qc-run|campus|FAILED|00:00:31|1:0|2026-01-01T05:00:00|2026-01-01T05:00:31|billing=4,cpu=4,mem=16G|n22\n"
                "6998|train-model|campus|TIMEOUT|1-00:00:00|0:0|2025-12-31T05:00:00|2026-01-01T05:00:00|billing=16,cpu=16,gres/gpu=1,mem=64G|g12")

    def _look(self):
        return ("@@host\nlogin1|12|1024|0.31, 0.22, 0.20\n@@squeue\n" + "\n".join(self._queue()) + "\n@@sacct\n" + self._sacct() +
                "\n@@quota\nDisk quotas for user demo (uid 1000): \n     Filesystem   space   quota   limit   grace   files   quota   limit   grace\n"
                "10.0.0.1:/u/home/a\n                 34104M  57221M  57221M            456k   5000k   5000k        \n"
                "10.0.0.2:/scratch\n                 374G      0K   1863G           73877       0       0        \n"
                "@@df\nFilesystem Type Size Used Avail Use% Mounted on\n10.0.0.3:/path/to/project/lab nfs 63T 61T 2.2T 97% /path/to/project/lab\n"
                "@@gpus\n## GPUs by model (live)\n\n| Model | VRAM | CUDA | Nodes | GPUs | Free |\n| --- | --- | --- | ---: | ---: | ---: |\n"
                "| RTX6000 | vmem97G | cc_12_0 | 3 | 17 | 4 |\n| A100 | vmem40G | cc_8_0 | 1 | 4 | 0 |\n\n16 of 21 GPUs free on 4 nodes.\n\n## GPU nodes\n\n"
                "| Node | Model | Free GPUs | State | Idle CPUs | Free mem | Partitions |\n| --- | --- | ---: | --- | ---: | ---: | --- |\n"
                "| g11 | RTX6000 | 1/8 | mixed | 114/128 | 199G | campus |\n| g12 | RTX6000 | 3/7 | mixed | 96/128 | 83G | campus |\n"
                "@@whoami\n## demo on the cluster\n\nAccount: pi_lab.\n\n### pi_lab, fairshare 0.226323\n- jobs run on campus: 24h max, 126 nodes (58 idle), 6112 CPUs (3495 idle), 13 GPUs; per user: 1024 CPUs, 2 GPUs, 16 nodes, 100 running jobs\n"
                "@@sinfo\ncampus*|up|1-00:00:00|2617/3495/0/6112\n")
