"""Models served from a cluster GPU: start and stop them, schedule when, watch them, and hear when they are up.

One entry per model server in config/model_servers.json. A server is a SLURM job that runs vLLM on a GPU node
(its folder on the cluster holds `serve.sbatch` and `model/`), reached from this Mac through an SSH tunnel
(Mac -> login node -> GPU node). The Manager keeps the picture current -- queued, loading, ready, stopped,
failed -- from the cluster itself, so a job started by hand, by the `hpc-llm` command or by a chat is seen
the same as one started here. Everything that touches the world (ssh, the tunnel, the model's own HTTP API,
notifications, e-mail) is passed in, so the logic here is tested without a cluster.
"""
import json, os, re, subprocess, threading, time, urllib.request
from datetime import datetime, timedelta

GRACE_S = 30 * 60            # a scheduled start or stop still happens when Orbit was off at the minute, up to this late
# How often to look at the cluster. Every look is an ssh login, and the login nodes block a client that connects too
# often (it cost this Mac its access to the cluster for a while), so: quickly only while something is changing,
# slowly when nothing is, and ever more slowly while the cluster does not answer.
POLL_S = {"queued": 20, "loading": 15, "stopping": 10, "ready": 90, "stopped": 180, "unknown": 30}
BACKOFF_S = (120, 300, 600, 900)
LOOP_S = 5

SETTINGS = {                 # what the model is served with, and what the job asks the cluster for
    "max_model_len": 262144,       # context length, in tokens
    "max_num_seqs": 32,            # requests it will work on at once
    "gpu_mem_util": 0.90,          # share of the GPU's memory vLLM may use
    "mtp_tokens": 2,               # speculative tokens per step (0: off)
    "eager": False,                # skip compiling and graph capture: starts sooner, answers slower
    "time_limit_h": 24,            # the job ends by itself after this long
    "gpus": 1, "cpus": 16, "mem_gb": 128,
    "idle_stop_min": 0,            # stop it after this long without a request (0: never)
    "keep_log": False,             # a full server and request log on the cluster (it has the text of chats), for this user only
    "error_log": True,             # keep the server's own messages (startup, warnings, errors) without any chat text: why a start failed
    "batched_tokens": 16384,       # prompt tokens read per step: higher reads a long prompt sooner
    "kv_cache_dtype": "auto",      # "fp8": the context memory takes half the space, so room for twice the context or answers
    "async_scheduling": False,     # overlaps the scheduler with the GPU: more throughput, newer and less proven with look-ahead
    "temperature": 0.6, "top_p": 0.95, "top_k": 20,    # sampling defaults, for requests that do not say (Qwen's advice for thinking)
    "keep_alive": False,           # start it again (twice a day at most) when it fails or stops answering
    "renew": False,                # start it again when its time limit ends it
    "renew_until": "",             # ...until this moment ("YYYY-MM-DDTHH:MM", local time); empty: until switched off
    "placement": "auto",           # where to run it: "auto" asks the scheduler where each choice would start and takes the soonest; "ask" lets a model
                                   # choose among those (and explain); "fixed" uses exactly the partition and memory set here
    "placement_model": "",         # the model that chooses for "ask" (empty: Orbit's helper model), e.g. a Sonnet
    "min_vram_gb": 60,             # the GPU memory the model needs: nodes whose GPUs have less are never used (a 40 GB card ran out of memory loading it, again and again; 0: no limit)
    "min_mem_gb": 48,              # the least host memory it may be given when that starts it sooner (the model sits on the GPU; measured: 6.4 GB resident in all)
    "partition": "",               # where the job may run (sbatch -p): empty = the cluster's router (campus); "pi_shared" reaches the big shared GPU pool
    "exclude_nodes": "",           # compute nodes the job must not run on (comma separated), e.g. one that cannot read the model files
    "load_timeout_min": 25,        # still loading after this long: the node is probably stuck: move to another one (0: never)
}
EVENTS = ("ready", "stopped", "failed")

DEFAULT_SERVER = {
    "id": "qwen", "label": "Qwen · HPC", "host": "hpc",
    "dir": "/path/to/project/user/Models/qwen-server", "job_name": "qwen-serve",
    "model": "qwen", "local_port": 8012, "key_name": "HPC_LLM_KEY", "provider": "hpc",
    "settings": dict(SETTINGS), "schedule": [],
    # e-mail is sent by the cluster itself (its `mail`), to the address the cluster delivers to
    "notify": {"desktop": True, "email": "user@mail.cluster.example.edu", "events": {"ready": True, "stopped": True, "failed": True}},
}


# ----------------------------------------------------------------------------------------- small pure helpers

def wait_until_ready(loading, cancel, emit=None, now=time.time, wait=None, max_s=2 * 3600):
    """Hold a chat's answer while its model server is still queued or loading, instead of letting it connect, fail and retry. `loading` is a
    callable giving the server's description (see Manager.loading_for) or None once it is not loading; `cancel` an Event. `emit("queued", ...)`
    says what it waits for, once per change of state. Returns True to go on (ready, or never loading, or the wait ran out: then the request is
    left to fail with its own message), False if cancelled."""
    info = loading()
    if not info: return True
    wait = wait or (lambda s: cancel.wait(s))
    t0, said = now(), None
    while info and not cancel.is_set():
        if now() - t0 >= max_s: return True
        key = (info["state"], info.get("node"))
        if emit and key != said:
            said = key
            where = f", on {info['node']}" if info.get("node") else ""
            what = ("starting up" + where) if info["state"] == "loading" else "waiting for the cluster to give it a GPU"
            emit("queued", {"msg": f"waiting for {info['label']} to finish loading ({what})", "behind": None})
        wait(5)
        info = loading()
    if emit: emit("dequeued", {"waited": round(now() - t0, 1)})
    return not cancel.is_set()


def _hm(s):
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(s or ""))
    if not m or int(m[1]) > 23 or int(m[2]) > 59: return None
    return int(m[1]), int(m[2])


def _secs(s):
    """SLURM time ('1-02:03:04', '02:03:04', '3:04', 'UNLIMITED') -> seconds, or None."""
    s = str(s or "").strip()
    if not s or s.upper() in ("UNLIMITED", "INVALID", "N/A", "NOT_SET"): return None
    days = 0
    if "-" in s: d, s = s.split("-", 1); days = int(d)
    parts = [int(x) for x in s.split(":")]
    while len(parts) < 3: parts.insert(0, 0)
    return days * 86400 + parts[0] * 3600 + parts[1] * 60 + parts[2]


def clean_settings(raw, base=None):
    """Settings from the form: only known keys, each of its own type and inside sensible bounds."""
    out = dict(base or SETTINGS)
    def num(k, lo, hi, cast=int):
        if k in raw:
            try: out[k] = min(hi, max(lo, cast(raw[k])))
            except (TypeError, ValueError): pass
    num("max_model_len", 1024, 4_000_000); num("max_num_seqs", 1, 1024); num("gpu_mem_util", 0.3, 0.98, float)
    num("mtp_tokens", 0, 8); num("time_limit_h", 1, 24 * 14); num("gpus", 1, 8); num("cpus", 1, 128)
    num("mem_gb", 4, 2048); num("idle_stop_min", 0, 24 * 60); num("batched_tokens", 2048, 262144)
    num("temperature", 0.0, 2.0, float); num("top_p", 0.05, 1.0, float); num("top_k", 0, 1000)
    if raw.get("kv_cache_dtype") in ("auto", "fp8"): out["kv_cache_dtype"] = raw["kv_cache_dtype"]
    for k in ("eager", "keep_log", "error_log", "async_scheduling", "keep_alive", "renew"):
        if k in raw: out[k] = bool(raw[k])
    if raw.get("placement") in ("auto", "ask", "fixed"): out["placement"] = raw["placement"]
    if "placement_model" in raw: out["placement_model"] = str(raw["placement_model"] or "").strip()[:80]
    num("min_mem_gb", 8, 2048)
    num("min_vram_gb", 0, 1000)
    if "partition" in raw:
        v = str(raw["partition"] or "").strip()
        out["partition"] = v if re.fullmatch(r"[A-Za-z0-9_]+(,[A-Za-z0-9_]+){0,3}", v) else ""
    if "exclude_nodes" in raw:
        v = ",".join(x for x in re.split(r"[\s,]+", str(raw["exclude_nodes"] or "")) if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,39}", x))[:200]
        out["exclude_nodes"] = v
    num("load_timeout_min", 0, 24 * 60)
    if "renew_until" in raw:
        v = str(raw["renew_until"] or "").strip()
        try: datetime.strptime(v, "%Y-%m-%dT%H:%M") if v else None; out["renew_until"] = v
        except ValueError: pass
    return out


def clean_schedule(rows):
    out = []
    for r in rows or []:
        start, stop = _hm(r.get("start")), _hm(r.get("stop"))
        if not (start or stop): continue
        e = {"id": str(r.get("id") or "s" + str(int(time.time() * 1000))[-8:]), "enabled": r.get("enabled", True) is not False,
             "start": "%02d:%02d" % start if start else "", "stop": "%02d:%02d" % stop if stop else ""}
        on = str(r.get("on") or "")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", on): e["on"] = on                     # one day only
        else: e["days"] = sorted({int(d) for d in (r.get("days") or range(7)) if str(d).isdigit() and 0 <= int(d) <= 6}) or list(range(7))
        for k in ("last_start", "last_stop"):
            if r.get(k): e[k] = str(r[k])
        out.append(e)
    return out


def due(entry, kind, now):
    """Is this schedule row's `kind` ('start' or 'stop') to happen now? -> the day key to remember, or None."""
    if not entry.get("enabled", True): return None
    hm = _hm(entry.get(kind))
    if not hm: return None
    dt = datetime.fromtimestamp(now)
    day = dt.strftime("%Y-%m-%d")
    if entry.get("on"):
        if entry["on"] != day: return None
    elif dt.weekday() not in (entry.get("days") or range(7)): return None
    at = dt.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
    if not (0 <= now - at.timestamp() < GRACE_S): return None
    if entry.get("last_" + kind) == day: return None
    if kind == "start":                       # past today's stop, a late start is pointless
        stop = _hm(entry.get("stop"))
        if stop and dt.replace(hour=stop[0], minute=stop[1], second=0, microsecond=0) <= dt and stop > hm: return None
    return day


def next_event(server, now):
    """The next scheduled start or stop: {kind, at, label} or None (looks a week ahead)."""
    best = None
    for e in server.get("schedule") or []:
        if not e.get("enabled", True): continue
        for kind in ("start", "stop"):
            hm = _hm(e.get(kind))
            if not hm: continue
            for add in range(0, 8):
                dt = (datetime.fromtimestamp(now) + timedelta(days=add)).replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
                if dt.timestamp() <= now: continue
                if e.get("on") and e["on"] != dt.strftime("%Y-%m-%d"): continue
                if not e.get("on") and dt.weekday() not in (e.get("days") or range(7)): continue
                if best is None or dt.timestamp() < best["at"]: best = {"kind": kind, "at": dt.timestamp()}
                break
    return best


def parse_metrics(text):
    """The numbers of vLLM's /metrics that tell how it is doing, summed over their labels; None where it has no such series.
    Histograms come as (sum, count)."""
    def total(name):
        t = 0.0; found = False
        for m in re.finditer(r"^%s(?:\{[^}]*\})?\s+([0-9.eE+-]+)\s*$" % re.escape(name), text or "", re.M):
            t += float(m[1]); found = True
        return t if found else None
    def hist(*names):
        for n in names:
            sm, ct = total(n + "_sum"), total(n + "_count")
            if sm is not None and ct is not None: return (sm, ct)
        return None
    return {"running": total("vllm:num_requests_running"), "waiting": total("vllm:num_requests_waiting"),
            "finished": total("vllm:request_success_total"), "prompt_tokens": total("vllm:prompt_tokens_total"),
            "generated_tokens": total("vllm:generation_tokens_total"),
            "kv_used": total("vllm:kv_cache_usage_perc") if total("vllm:kv_cache_usage_perc") is not None else total("vllm:gpu_cache_usage_perc"),
            "cache_queries": total("vllm:prefix_cache_queries_total"), "cache_hits": total("vllm:prefix_cache_hits_total"),
            "draft_tokens": total("vllm:spec_decode_num_draft_tokens_total"), "accepted_tokens": total("vllm:spec_decode_num_accepted_tokens_total"),
            "ttft": hist("vllm:time_to_first_token_seconds"),
            "itl": hist("vllm:inter_token_latency_seconds", "vllm:time_per_output_token_seconds"),
            "e2e": hist("vllm:e2e_request_latency_seconds"), "prefill": hist("vllm:request_prefill_time_seconds"),
            "queue": hist("vllm:request_queue_time_seconds"),
            "prompt_len": hist("vllm:request_prompt_tokens"), "gen_len": hist("vllm:request_generation_tokens")}


def derive_stats(now_m, prev_m, dt):
    """What the panel shows, from the latest /metrics and an earlier one: averages over what happened between them when
    something did, else over the whole run. -> {} when the server has no statistics (they were switched off)."""
    if not now_m or now_m.get("finished") is None and now_m.get("generated_tokens") is None and now_m.get("itl") is None: return {}
    def avg(key):
        a, b = now_m.get(key), (prev_m or {}).get(key)
        if not a: return None
        if b and a[1] > b[1]: return (a[0] - b[0]) / (a[1] - b[1])
        return a[0] / a[1] if a[1] else None
    def ratio(num, den):
        a, b = now_m.get(num), now_m.get(den)
        if a is None or not b: return None
        pa, pb = (prev_m or {}).get(num), (prev_m or {}).get(den)
        if pa is not None and pb and b > pb: return (a - pa) / (b - pb)
        return a / b
    itl, ttft = avg("itl"), avg("ttft")
    g, pg = now_m.get("generated_tokens"), (prev_m or {}).get("generated_tokens")
    return {"decode_tps": round(1 / itl, 1) if itl else None, "ttft_s": round(ttft, 2) if ttft is not None else None,
            "e2e_s": round(avg("e2e"), 1) if avg("e2e") is not None else None,
            "queue_s": round(avg("queue"), 2) if avg("queue") is not None else None,
            "prefill_tps": round(avg("prompt_len") / avg("prefill")) if avg("prompt_len") and avg("prefill") else None,
            "throughput_tps": round((g - pg) / dt, 1) if g is not None and pg is not None and dt and dt > 5 and g >= pg else None,
            "cache_hit": ratio("cache_hits", "cache_queries"), "accepted": ratio("accepted_tokens", "draft_tokens"),
            "kv_used": now_m.get("kv_used"), "running": now_m.get("running"), "waiting": now_m.get("waiting"),
            "finished": now_m.get("finished"), "prompt_tokens": now_m.get("prompt_tokens"), "generated_tokens": g,
            "mean_prompt": round(avg("prompt_len")) if avg("prompt_len") else None, "mean_output": round(avg("gen_len")) if avg("gen_len") else None}


def classify_ssh(ps_text, host, hostnames, ports):
    """Orbit's and other programs' ssh logins to the cluster, from `ps -axo pid,etime,command`.
    -> [{pid, age, kind, mine, what}]; kind: monitor (the one shared connection Orbit looks with), tunnel (a model's
    port to this Mac), chat (a chat's Claude Code running on the cluster), other (some other program: not touched)."""
    names = {host, *hostnames}
    out = []
    for line in (ps_text or "").splitlines():
        m = re.match(r"\s*(\d+)\s+(\S+)\s+(.*)$", line)
        if not m: continue
        pid, age, cmd = int(m[1]), m[2], m[3]
        if not (re.match(r"(?:\S*/)?ssh\b", cmd) or cmd.startswith("ssh:")): continue
        if cmd.startswith("ssh: "):
            if "cm-orbit-" in cmd: out.append({"pid": pid, "age": age, "kind": "monitor", "mine": True, "what": "the shared connection Orbit looks at the cluster with"})
            continue
        if not any(n and n in cmd for n in names): continue
        tp = next((p for p in ports if f"-L {p}:127.0.0.1:" in cmd), None)
        if tp: out.append({"pid": pid, "age": age, "kind": "tunnel", "mine": True, "port": tp, "what": f"the tunnel to a model, on port {tp}"})
        elif "exec bash -c" in cmd and " orbit " in cmd: out.append({"pid": pid, "age": age, "kind": "chat", "mine": True, "what": "a chat running Claude Code on the cluster"})
        elif "cm-orbit-" in cmd: out.append({"pid": pid, "age": age, "kind": "monitor", "mine": True, "what": "a look at the cluster"})
        else: out.append({"pid": pid, "age": age, "kind": "other", "mine": False, "what": "another program (Claude app, Codex, a terminal…)"})
    return out


# --------------------------------------------------------------------------------------------- the real world

class World:
    """ssh, the tunnel, the model's HTTP API, secrets, notifications and e-mail, as they are on this Mac."""
    def __init__(self, secrets_path):
        self.secrets_path = secrets_path

    def ssh(self, host, cmd, timeout=30):
        try:
            # one connection, kept for a few minutes and shared by every look: not a new login each time
            r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-o", "ControlMaster=auto",
                                "-o", "ControlPath=~/.ssh/cm-orbit-%C", "-o", "ControlPersist=300", host, cmd],
                               capture_output=True, text=True, timeout=timeout)
            return r.returncode, r.stdout.strip()
        except (subprocess.TimeoutExpired, OSError) as e:
            return 255, f"ssh failed: {e}"

    def ps(self):
        return subprocess.run(["ps", "-axo", "pid,etime,command"], capture_output=True, text=True).stdout

    def kill(self, pid):
        try: os.kill(int(pid), 15)
        except OSError: pass

    def monitor_exit(self, host):
        """Ends the shared connection (its master process), if there is one."""
        subprocess.run(["ssh", "-o", "ControlPath=~/.ssh/cm-orbit-%C", "-O", "exit", host], capture_output=True, text=True, timeout=15)

    def tunnel_pids(self, local_port):
        r = subprocess.run(["pgrep", "-f", "--", f"-L {int(local_port)}:127.0.0.1:"], capture_output=True, text=True)
        return r.stdout.split()

    def tunnel_open(self, host, local_port, node, port):
        # Mac -> login node -> GPU node: the GPU node does not take this Mac's key, the login node's reaches it
        subprocess.run(["ssh", "-f", "-tt", "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=30",
                        "-o", "ServerAliveCountMax=4", "-L", f"{int(local_port)}:127.0.0.1:{int(port)}", host,
                        f"exec ssh -N -o BatchMode=yes -o ExitOnForwardFailure=yes -L {int(port)}:127.0.0.1:{int(port)} {node}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=40)

    def tunnel_close(self, local_port):
        for p in self.tunnel_pids(local_port):
            subprocess.run(["kill", p])

    def http(self, local_port, path, key=""):
        rq = urllib.request.Request(f"http://127.0.0.1:{int(local_port)}{path}", headers={"Authorization": "Bearer " + key} if key else {})
        with urllib.request.urlopen(rq, timeout=6) as r:
            return r.read().decode("utf-8", "replace")

    def complete(self, local_port, key, content, max_tokens):
        """One chat request, to time it: -> (seconds, prompt tokens, completion tokens)."""
        body = json.dumps({"model": "qwen", "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens,
                           "temperature": 0, "chat_template_kwargs": {"enable_thinking": False}}).encode()
        rq = urllib.request.Request(f"http://127.0.0.1:{int(local_port)}/v1/chat/completions", data=body,
                                    headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        t = time.time()
        with urllib.request.urlopen(rq, timeout=300) as r: d = json.loads(r.read().decode())
        u = d.get("usage") or {}
        return time.time() - t, u.get("prompt_tokens", 0), u.get("completion_tokens", 0)

    def set_secret(self, name, value):
        try: d = json.load(open(self.secrets_path))
        except (OSError, ValueError): d = {}
        if value: d[name] = value
        else: d.pop(name, None)
        tmp = self.secrets_path + ".tmp"
        with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f: json.dump(d, f, indent=1)
        os.replace(tmp, self.secrets_path)

    def desktop(self, title, text):
        script = f'display notification {json.dumps(str(text)[:200])} with title {json.dumps(str(title)[:80])}'
        try: subprocess.Popen(["/usr/bin/osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError: pass

    def email(self, host, to, subject, body):
        """Sent from the cluster, by its own `mail`: not from this Mac and not from any account of yours."""
        import shlex
        if not re.fullmatch(r"[\w.+-]+@[\w.-]+", to): raise RuntimeError("that is not an e-mail address")
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-o", "ControlMaster=auto",
                            "-o", "ControlPath=~/.ssh/cm-orbit-%C", "-o", "ControlPersist=300", host,
                            f"mail -s {shlex.quote(subject)} {shlex.quote(to)}"],
                           input=body, capture_output=True, text=True, timeout=60)
        if r.returncode: raise RuntimeError((r.stderr or r.stdout or "the cluster did not send it").strip()[:300])


class SimWorld(World):
    """A cluster that exists only in memory, for a sandbox copy of Orbit: a job that queues for a few seconds, loads, answers,
    and ends by its time limit, with numbers that move. Nothing here touches ssh, a tunnel, a key file or a mail command.
    ORBIT_SIM_SPEED=10 makes it ten times faster."""
    QUEUE_S, LOAD_S = 8, 20

    def __init__(self, secrets_path, now=time.time):
        super().__init__(secrets_path)
        self.now, self.speed = now, float(os.environ.get("ORBIT_SIM_SPEED") or 1)
        self.jobs, self.next_id, self.tunnel, self.log = {}, 900, False, []

    def _t(self, j): return (self.now() - j["t0"]) * self.speed

    def _state(self, j):
        if j.get("ended"): return j["ended"]
        t = self._t(j)
        if t >= j["limit_s"]: j["ended"] = "TIMEOUT"
        elif j.get("cancel_at") is not None: return "COMPLETING" if (self.now() - j["cancel_at"]) * self.speed < 4 else self._end(j, "CANCELLED")
        elif t < self.QUEUE_S: return "PENDING"
        else: return "RUNNING"
        return j.get("ended") or "RUNNING"

    def _end(self, j, how):
        j["ended"] = how
        return how

    def ssh(self, host, cmd, timeout=30):
        self.log.append(cmd)
        if cmd.startswith("squeue"):
            rows = []
            for jid, j in self.jobs.items():
                st = self._state(j)
                if st in ("TIMEOUT", "CANCELLED"): continue
                el = 0 if st == "PENDING" else max(0, int(self._t(j) - self.QUEUE_S))
                lim = j["limit_s"]
                rows.append("%s|%s|%d:%02d:%02d|%d-%02d:%02d:%02d|%s|%s|2026-01-01T00:00:00" % (
                    jid, st, el // 3600, el % 3600 // 60, el % 60, lim // 86400, lim % 86400 // 3600, lim % 3600 // 60, lim % 60,
                    "simnode1" if st != "PENDING" else "", "Resources" if st == "PENDING" else "None"))
            return 0, "\n".join(rows)
        if cmd.startswith("sbatch"):
            m = re.search(r"-t (\d+):", cmd)
            jid = str(self.next_id); self.next_id += 1
            env = dict(re.findall(r"([A-Z_]+)=([^,\s]+)", cmd.split("--export=")[-1].split(" ")[0]))
            self.jobs[jid] = {"t0": self.now(), "limit_s": int(m[1] if m else 24) * 3600, "env": env}
            return 0, jid
        if cmd.startswith("scancel"):
            for j in self.jobs.values():
                if not j.get("ended") and j.get("cancel_at") is None: j["cancel_at"] = self.now()
            return 0, ""
        if cmd.startswith("cat "):
            jid = cmd.split("/run/")[-1].split()[0]
            j = self.jobs.get(jid)
            return (0, "simnode1 27000 simkey") if j and self._state(j) == "RUNNING" else (1, "")
        if cmd.startswith("sacct"):
            last = list(self.jobs.values())[-1:] or [{}]
            return 0, "%s|00:10:00|0:0" % (last[0].get("ended") or "COMPLETED")
        if "mail -s" in cmd or cmd.startswith("mkdir") or cmd.startswith("ls"): return 0, ""
        return 0, ""

    def _ready_job(self):
        for j in self.jobs.values():
            if self._state(j) == "RUNNING" and self._t(j) >= self.QUEUE_S + self.LOAD_S: return j

    def tunnel_pids(self, local_port): return ["sim"] if self.tunnel else []
    def tunnel_open(self, host, local_port, node, port): self.tunnel = True
    def tunnel_close(self, local_port): self.tunnel = False
    def ps(self): return ""
    def kill(self, pid): pass
    def monitor_exit(self, host): pass
    def set_secret(self, name, value): pass

    def http(self, local_port, path, key=""):
        j = self._ready_job()
        if not j: raise OSError("connection refused")
        up = self._t(j) - self.QUEUE_S - self.LOAD_S
        if path.startswith("/v1/models"): return json.dumps({"data": [{"id": "qwen", "max_model_len": int(j["env"].get("MAXLEN") or 262144)}]})
        n = int(up / 7)
        return ("vllm:num_requests_running 0\nvllm:num_requests_waiting 0\nvllm:kv_cache_usage_perc 0.07\n"
                "vllm:request_success_total{finished_reason=\"stop\"} %d\nvllm:generation_tokens_total %d\nvllm:prompt_tokens_total %d\n"
                "vllm:inter_token_latency_seconds_sum %.2f\nvllm:inter_token_latency_seconds_count %d\n"
                "vllm:time_to_first_token_seconds_sum %.2f\nvllm:time_to_first_token_seconds_count %d\n"
                "vllm:prefix_cache_queries_total %d\nvllm:prefix_cache_hits_total %d\n"
                % (n, n * 220, n * 9000, n * 220 * 0.02, n * 220, n * 0.9, max(n, 1), n * 9000, int(n * 9000 * 0.8)))

    def complete(self, local_port, key, content, max_tokens):
        if not self._ready_job(): raise OSError("connection refused")
        return (0.3 if len(content) < 1000 else 2.9, 25000 if len(content) > 1000 else 20, max_tokens if len(content) < 1000 else 4)

    def desktop(self, title, text): self.log.append("desktop: %s" % title)
    def email(self, host, to, subject, body): self.log.append("mail to %s: %s" % (to, subject))


# ---------------------------------------------------------------------------------------------- the manager

class Manager:
    def __init__(self, path, world, now=time.time, on_window=None, advise=None):
        self._feat_cache = {}                          # cluster host -> (time, set of GPU memory sizes in GB the nodes have)
        self.path, self.w, self.now = path, world, now
        self.advise = advise               # (prompt, model) -> text: a model that chooses where to run (placement "ask"), or None
        self.on_window = on_window         # called with (server, tokens) when the model says how much it holds
        self.lock = threading.RLock()
        self.rt = {}                     # server id -> what is known right now (not saved)
        self.cfg = self._load()

    # --- config
    def _load(self):
        try: d = json.load(open(self.path))
        except (OSError, ValueError): d = {}
        if not d.get("servers"):
            d = {"servers": [json.loads(json.dumps(DEFAULT_SERVER))]}
        for x in d["servers"]:       # a config saved before a setting existed gets that setting's default, not a KeyError
            x["settings"] = {**SETTINGS, **(x.get("settings") or {})}
            x.setdefault("notify", json.loads(json.dumps(DEFAULT_SERVER["notify"])))
        return d

    def save(self):
        with self.lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f: json.dump(self.cfg, f, indent=1, ensure_ascii=False)
            os.replace(tmp, self.path)

    def server(self, sid):
        for s in self.cfg["servers"]:
            if s["id"] == sid: return s
        raise KeyError(sid)

    # --- reading the cluster
    def _job(self, s):
        rc, out = self.w.ssh(s["host"], f"squeue -u $USER -h -n {s['job_name']} -o '%i|%T|%M|%l|%N|%R|%V'")
        if rc: return {"error": out}
        line = next((l for l in out.splitlines() if l.count("|") >= 6), "")
        if not line: return None
        jid, state, elapsed, limit, node, reason, submitted = line.split("|", 6)
        return {"id": jid, "state": state, "elapsed": _secs(elapsed), "limit": _secs(limit), "node": node, "reason": reason}

    def _ended(self, s, jid):
        rc, out = self.w.ssh(s["host"], f"sacct -j {jid} -X -n -P -o State,Elapsed,ExitCode")
        if rc or not out: return "", ""
        st, el, ec = (out.splitlines()[0].split("|") + ["", "", ""])[:3]
        return st.split()[0] if st else "", f"{st} after {el}, exit code {ec}"

    def status(self, sid, fresh=False):
        """What is known about one server now, safe to show (never the key)."""
        s = self.server(sid)
        with self.lock:
            raw = self.rt.get(sid) or {"state": "unknown"}
            # an allowlist: the key and the port, and internal bookkeeping, are not for the page
            r = {k: raw.get(k) for k in ("state", "reason", "jid", "node", "elapsed", "limit", "t_job", "t_submit", "t_ready",
                                         "info", "stats", "error", "mail_error", "started_by", "checked", "last_active", "health", "bench", "restarted", "renewed", "placement")}
        r["id"], r["next"] = sid, next_event(s, self.now())
        st = s.get("settings") or {}
        r["renew"] = {"on": bool(st.get("renew")), "until": st.get("renew_until") or ""}
        if r.get("t_job") is not None and r.get("limit") is not None:
            r["left"] = max(0, r["limit"] - (r.get("elapsed") or 0) - (self.now() - r["t_job"]))
        return r

    def refresh(self, sid):
        """Look now, when someone asks -- but not more than once every 10 seconds."""
        if self.now() - (self.rt.get(sid) or {}).get("checked", 0) < 10: return self.status(sid)
        return self.tick(sid)

    # --- one look at the cluster, and what follows from it
    def tick(self, sid):
        s = self.server(sid)
        with self.lock:
            rt = self.rt.setdefault(sid, {"state": "unknown"})
            prev = rt.get("state")
        job = self._job(s)
        if job and job.get("error"):                       # the cluster could not be reached: say so, keep the rest
            with self.lock:
                rt["fails"] = rt.get("fails", 0) + 1
                rt.update(state=prev if prev not in (None, "unknown") else "unreachable", error=job["error"], checked=self.now(),
                          next_poll=self.now() + BACKOFF_S[min(rt["fails"], len(BACKOFF_S)) - 1])
            return self.status(sid)
        rt["fails"] = 0
        now = self.now()
        if job is None:
            self._no_job(s, rt, prev, now)
        else:
            self._with_job(s, rt, prev, job, now)
        rt["checked"] = now
        rt["next_poll"] = now + POLL_S.get(rt.get("state"), 30)
        self._idle_check(s, rt, now)
        return self.status(sid)

    def _no_job(self, s, rt, prev, now):
        jid = rt.get("jid"); ended = rt.get("last_end", "")
        if prev in ("queued", "loading", "ready", "stopping") and jid:
            how, detail = self._ended(s, jid)
            asked = prev == "stopping" or rt.get("asked_stop")
            bad = how in ("FAILED", "NODE_FAIL", "OUT_OF_MEMORY", "BOOT_FAIL") or (how == "CANCELLED" and not asked and prev != "ready")
            kind = "failed" if bad else "stopped"
            reason = (rt.get("stop_reason") or "you stopped it") if asked else "its time limit ran out" if how == "TIMEOUT" else detail or "it ended"
            if kind == "failed" and not asked and not rt.get("t_ready") and (rt.get("elapsed") or 0) < 900:       # it never answered: that node, or that kind of GPU, is not for it
                cause = self._cause(s, jid)
                with self.lock:
                    rt["fast_fails"] = (rt.get("fast_fails") or 0) + 1
                    if rt.get("node"): rt.setdefault("bad_nodes", {})[rt["node"]] = now + self.BAD_NODE_S
                reason = f"{reason}; it ended after {int((rt.get('elapsed') or 0) // 60)} min on {rt.get('node') or 'a node'} without answering" + (f" ({cause})" if cause else "")
            self.event(s, kind, reason, rt)
            ended = ("timeout" if (how == "TIMEOUT" and not asked) else
                     "failed" if (kind == "failed" or (asked is False and how not in ("COMPLETED", "TIMEOUT", "CANCELLED"))) else "stopped")
        with self.lock:
            if rt.get("state") != "stopped":
                self.w.tunnel_close(s["local_port"]); self.w.set_secret(s["key_name"], "")
            rt.update(state="stopped", jid=None, node=None, port=None, key=None, elapsed=None, limit=None, t_job=None,
                      info=None, metrics=None, asked_stop=False, error="", key_set=None, health=None, h_fails=0, last_end=ended)

    def _with_job(self, s, rt, prev, job, now):
        with self.lock:
            rt.update(jid=job["id"], node=job["node"] or None, elapsed=job["elapsed"], limit=job["limit"], t_job=now, error="")
            if rt.get("jid_seen") != job["id"]: rt.update(jid_seen=job["id"], t_submit=rt.get("t_submit") or now, t_ready=None, notified=set())
        if job["state"] in ("PENDING", "CONFIGURING"):
            with self.lock: rt.update(state="queued", reason=job["reason"])
            return
        if job["state"] not in ("RUNNING", "COMPLETING"):
            with self.lock: rt.update(state="stopping" if job["state"] == "COMPLETING" else "queued", reason=job["state"])
            return
        if rt.get("asked_stop"):
            with self.lock: rt["state"] = "stopping"
            return
        rc, out = self.w.ssh(s["host"], f"cat {s['dir']}/run/{job['id']} 2>/dev/null")
        parts = out.split() if not rc else []
        if len(parts) < 3:                                  # started, but has not written where it listens yet
            with self.lock: rt["state"] = "loading"
            self._load_watch(s, rt, job, now)
            return
        node, port, key = parts[0], parts[1], parts[2]
        with self.lock: rt.update(node=node, port=port, key=key)
        if not self.w.tunnel_pids(s["local_port"]):
            try: self.w.tunnel_open(s["host"], s["local_port"], node, port)
            except Exception as e:
                with self.lock: rt.update(state="loading", error=f"could not open the tunnel: {e}"); return
        if rt.get("key_set") != (job["id"], key):
            self.w.set_secret(s["key_name"], key); rt["key_set"] = (job["id"], key)
        info = None
        try:
            d = json.loads(self.w.http(s["local_port"], "/v1/models", key))
            m = (d.get("data") or [{}])[0]
            info = {"id": m.get("id"), "max_model_len": m.get("max_model_len")}
        except Exception:
            info = None
        if info:
            with self.lock: rt.update(state="ready", info=info)
            if self.on_window and info.get("max_model_len") and rt.get("window_told") != (job["id"], info["max_model_len"]):
                rt["window_told"] = (job["id"], info["max_model_len"])
                try: self.on_window(s, int(info["max_model_len"]))
                except Exception: pass
            self.read_metrics(s, rt)
            if not rt.get("t_ready"):
                rt["t_ready"] = now; rt["last_active"] = now; rt["fast_fails"] = 0
                self.event(s, "ready", "", rt)
        else:
            with self.lock: rt["state"] = "loading"
            self._load_watch(s, rt, job, now)

    LOAD_MOVES = 2                                           # how many times in a row it is moved off a node that does not finish loading
    BAD_NODE_S = 6 * 3600                                    # and how long it then stays away from that node

    def _load_watch(self, s, rt, job, now):
        """A job that is still loading long after it should have answered is usually on a node that cannot read the model files (seen: a node
        whose reads of the project disk stalled, the process in uninterruptible I/O wait for 17 minutes). Move it: remember the node as bad for a
        few hours, cancel the job and submit it again with that node excluded."""
        st = rt.get("settings_used") or s["settings"]
        lim, took, node = int(st.get("load_timeout_min") or 0) * 60, job.get("elapsed"), job.get("node")
        if not lim or took is None or took < lim or not node or rt.get("asked_stop"): return
        if (rt.get("load_moves") or 0) >= self.LOAD_MOVES:
            with self.lock: rt["error"] = f"still loading after {int(took // 60)} min on {node}; it was already moved {self.LOAD_MOVES} times, so it is left alone"
            return
        with self.lock:
            rt.setdefault("bad_nodes", {})[node] = now + self.BAD_NODE_S
            moves = rt["load_moves"] = (rt.get("load_moves") or 0) + 1
        self.event(s, "failed", f"it was still loading on {node} after {int(took // 60)} min (that node is probably not reading the model files); "
                                f"trying another node ({moves} of {self.LOAD_MOVES})", rt)
        self.w.ssh(s["host"], f"scancel {job['id']}")
        self.start(s["id"], why=f"moved off {node}, which did not finish loading", moving=True)

    def read_metrics(self, s, rt):
        """The model's own statistics, over the tunnel (no ssh): kept as the latest and one from about a minute earlier."""
        if rt.get("state") != "ready": return
        key = rt.get("key")
        try: met = parse_metrics(self.w.http(s["local_port"], "/metrics", key or ""))
        except Exception: return
        now = self.now()
        hist = rt.setdefault("m_hist", [])
        hist.append((now, met))
        while len(hist) > 2 and now - hist[1][0] > 90: hist.pop(0)        # keep one old enough to measure against
        old = hist[0] if len(hist) > 1 and now - hist[0][0] >= 20 else (None, None)
        with self.lock:
            rt["metrics"] = met
            rt["stats"] = derive_stats(met, old[1], (now - old[0]) if old[0] else 0) or {"off": True}
        rt["m_at"] = now

    def health(self, s, rt):
        """Does it really answer? /v1/models is answered by a server whose GPU has hung; a one-word request is not."""
        now = self.now()
        if rt.get("state") != "ready" or now - rt.get("h_at", 0) < 180: return
        rt["h_at"] = now
        try:
            dt, _, _ = self.w.complete(s["local_port"], rt.get("key") or "", "Say OK.", 2)
            rt["health"] = {"ok": True, "s": round(dt, 2), "at": now}; rt["h_fails"] = 0
        except Exception as e:
            rt["h_fails"] = rt.get("h_fails", 0) + 1
            rt["health"] = {"ok": False, "error": f"{type(e).__name__}", "at": now, "fails": rt["h_fails"]}
            if rt["h_fails"] == 3: self.event(s, "failed", "it is up but stopped answering requests", rt)

    def speed_test(self, sid):
        """Three requests that give the numbers to compare settings with: how fast one answer is written, how fast a long
        prompt is read cold, and how fast the same prompt is the second time (its cache)."""
        import random
        s = self.server(sid); rt = self.rt.get(sid) or {}
        if rt.get("state") != "ready": raise RuntimeError("it is not ready")
        key, port = rt.get("key") or "", s["local_port"]
        dt, _, c = self.w.complete(port, key, "Count from 1 to 200, separated by spaces.", 300)
        rnd = random.Random(7); words = " ".join("".join(rnd.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(5)) for _ in range(9000))
        cold, p, _ = self.w.complete(port, key, words + "\n\nReply with the single word OK.", 4)
        warm, _, _ = self.w.complete(port, key, words + "\n\nReply with the single word OK.", 4)
        res = {"at": self.now(), "decode_tps": round(c / max(dt - 0.15, 0.05), 1), "prompt_tokens": p,
               "cold_s": round(cold, 2), "warm_s": round(warm, 2), "prefill_tps": round(p / cold) if cold else None}
        with self.lock: rt["bench"] = res
        return res

    def renew(self, s, rt):
        """When the job's time limit (24 h) ends it, start it again: until the moment you set, or until you switch it off.
        A job you stopped, or one that failed, is not renewed here (see keep_alive for failures)."""
        st = s.get("settings") or {}
        if not st.get("renew") or rt.get("state") != "stopped" or rt.get("last_end") != "timeout": return
        now = self.now()
        if now < rt.get("renew_retry", 0): return
        until = st.get("renew_until") or ""
        if until:
            try: end = datetime.strptime(until, "%Y-%m-%dT%H:%M").timestamp()
            except ValueError: end = None
            if end is not None and now >= end:
                with self.lock:
                    rt["last_end"] = ""                                     # said once, not again
                    s["settings"]["renew"] = False; self.save()
                try: self.w.desktop(f"{s['label']} will not be renewed", "Its time limit ended it, and the renewal period you set is over.")
                except Exception: pass
                return
        try:
            self.start(s["id"], why="renewed after the time limit")
            rt["renewed"] = {"at": now}
            try: self.w.desktop(f"{s['label']} is being renewed", "Its time limit ended it; a new job is starting.")
            except Exception: pass
        except Exception as e:
            rt["renew_retry"] = now + 120                                   # the cluster said no: try again in two minutes
            rt["error"] = f"could not renew: {e}"

    def keep_alive(self, s, rt):
        """With keep_alive on: a server that died (not one you stopped) or stopped answering is started again, twice a day at most."""
        if not (s.get("settings") or {}).get("keep_alive"): return
        day = datetime.fromtimestamp(self.now()).strftime("%Y-%m-%d")
        done = rt.setdefault("restarts", {})
        if done.get("day") != day: done.clear(); done["day"] = day; done["n"] = 0
        sick = (rt.get("state") == "stopped" and rt.get("last_end") == "failed") or (rt.get("state") == "ready" and rt.get("h_fails", 0) >= 3)
        if not sick or done["n"] >= 2: return
        if (rt.get("fast_fails") or 0) >= 2:                  # it keeps ending without ever answering: starting it again would only repeat that (and send another mail)
            rt["error"] = f"it ended {rt['fast_fails']} times in a row without ever answering, so it is not started again by itself: start it yourself once the cause (see the events) is dealt with"
            return
        done["n"] += 1
        rt["restarted"] = {"at": self.now(), "n": done["n"]}
        try:
            if rt.get("state") == "ready":
                self.stop(s["id"], why="not answering")
                for _ in range(20):
                    if self.tick(s["id"]).get("state") == "stopped": break
                    time.sleep(3)
            self.start(s["id"], why="restarted after a failure")
        except Exception as e:
            rt["error"] = f"could not restart: {e}"

    def _idle_check(self, s, rt, now):
        mins = float((s.get("settings") or {}).get("idle_stop_min") or 0)
        if not mins or rt.get("state") != "ready": return
        met = rt.get("metrics") or {}
        sig = (met.get("finished"), met.get("running"), met.get("generated_tokens"))
        if sig != rt.get("activity_sig") or (met.get("running") or 0) > 0:
            rt["activity_sig"], rt["last_active"] = sig, now
        elif now - rt.get("last_active", now) > mins * 60:
            rt["idle_stopped"] = True
            self.stop(s["id"], why=f"nothing asked of it for {int(mins)} minutes")

    # --- scheduled starts and stops
    def run_schedule(self):
        now = self.now()
        for s in self.cfg["servers"]:
            changed = False
            for e in s.get("schedule") or []:
                for kind in ("start", "stop"):
                    day = due(e, kind, now)
                    if not day: continue
                    e["last_" + kind] = day; changed = True
                    state = (self.rt.get(s["id"]) or {}).get("state")
                    try:
                        if kind == "start" and state in ("stopped", "unknown", None): self.start(s["id"], why="scheduled")
                        elif kind == "stop" and state in ("queued", "loading", "ready"): self.stop(s["id"], why="scheduled")
                    except Exception as ex:
                        self.event(s, "failed", f"the scheduled {kind} did not happen: {ex}", self.rt.setdefault(s["id"], {}))
            if changed: self.save()

    # --- starting and stopping
    PLACE_PARTS = ("", "pi_shared")        # the router's default (campus for this account) and the larger shared pool

    def _vram_constraint(self, s, st):
        """The sbatch constraint that keeps the job to nodes whose GPUs have the memory the model needs ('vmem97G|vmem80G'), read from the nodes' own features.
        '' when nothing is required or the cluster would not say; an error when no GPU on the cluster is big enough (starting would only fail again)."""
        need = int(st.get("min_vram_gb") or 0)
        if not need: return ""
        now = self.now(); c = self._feat_cache.get(s["host"])
        if not c or now - c[0] > 3600:
            rc, out = self.w.ssh(s["host"], "sinfo -h -o '%f' 2>/dev/null | sort -u", 40)
            sizes = set()
            if not rc:
                for line in out.splitlines():
                    if ",gpu," in "," + line.strip() + ",": sizes |= {int(x) for x in re.findall(r"vmem(\d+)G", line)}
            c = self._feat_cache[s["host"]] = (now, sizes)
        if not c[1]: return ""
        ok = sorted(n for n in c[1] if n >= need)
        if not ok: raise RuntimeError(f"no GPU on the cluster has {need} GB of memory (the largest has {max(c[1])} GB): lower 'GPU memory the model needs' in the server's settings, or use a smaller model")
        return "|".join(f"vmem{n}G" for n in ok)

    def _cause(self, s, jid):
        """The one or two lines of a failed job's error log that say why (out of memory, an unsupported GPU, ...); '' when there is none."""
        if not str(jid).isdigit(): return ""
        rc, out = self.w.ssh(s["host"], f"grep -h -i -m6 'out of memory\\|not compatible\\|RuntimeError\\|ValueError\\|no space\\|Killed' {s['dir']}/logs/errors.{jid}.log 2>/dev/null | grep -v 'File \"' | tail -2 | cut -c1-170", 30)
        return " ".join(out.split()) if not rc else ""

    def _bad_on_cluster(self, s):
        """Nodes a job itself found unusable (written by serve.sbatch to run/badnodes) in the last six hours."""
        rc, out = self.w.ssh(s["host"], f"cat {s['dir']}/run/badnodes 2>/dev/null | tail -50", 30)
        if rc: return []
        cut, nodes = self.now() - self.BAD_NODE_S, set()
        for line in out.splitlines():
            f = line.split()
            if len(f) >= 2 and re.fullmatch(r"[A-Za-z0-9\-]{2,20}", f[0]) and f[1].isdigit() and int(f[1]) >= cut: nodes.add(f[0])
        return sorted(nodes)

    def plan(self, s, st, skip=()):
        """Where and when the job would start with each partition and memory choice, from the scheduler itself (`sbatch --test-only` submits
        nothing). -> [{partition, mem_gb, start (epoch), node}] (only the choices that got an estimate), plus the free-GPU table as text."""
        mem = int(st["mem_gb"]); mems = sorted({mem, min(mem, int(st.get("min_mem_gb") or mem))}, reverse=True)
        combos = [(p, m) for p in self.PLACE_PARTS for m in mems]
        ex = (" --exclude=" + ",".join(skip)) if skip else ""
        cons = self._vram_constraint(s, st)
        base = f"-t {int(st['time_limit_h'])}:00:00 -c {st['cpus']} --gres=gpu:{st['gpus']}{ex}" + (f" --constraint='{cons}'" if cons else "")
        cmd = "; ".join(f'echo "@@{i}"; timeout 30 sbatch --test-only{" -p " + p if p else ""} {base} --mem={m}G {s["dir"]}/serve.sbatch 2>&1 | tail -n 3'
                        for i, (p, m) in enumerate(combos)) + '; echo "@@gpus"; timeout 20 h2 gpus 2>&1 | head -40'
        rc, out = self.w.ssh(s["host"], cmd, 150)
        if rc: return [], ""
        parts = re.split(r"^@@(\w+)\s*$", out, flags=re.M)
        got = dict(zip(parts[1::2], parts[2::2]))
        cands = []
        for i, (p, m) in enumerate(combos):
            mt = re.search(r"to start at (\S+) using \d+ processors on nodes (\S+) in partition (\S+)", got.get(str(i), ""))
            if not mt: continue
            try: t = time.mktime(time.strptime(mt[1], "%Y-%m-%dT%H:%M:%S"))
            except ValueError: continue
            cands.append({"partition": mt[3], "ask": p, "mem_gb": m, "start": t, "node": mt[2]})
        return cands, got.get("gpus", "")

    @staticmethod
    def choose(cands):
        """The soonest start; within five minutes of each other the router's own partition, then the more generous memory."""
        if not cands: return None
        return min(cands, key=lambda c: (round(c["start"] / 300), bool(c.get("ask")), -c["mem_gb"]))

    def _place(self, s, st, skip):
        """-> (partition, mem_gb, record) for this start; the settings as they are when it cannot be planned or is fixed."""
        mem = int(st["mem_gb"])
        if st.get("partition") or st.get("placement") == "fixed": return st.get("partition") or "", mem, None
        try: cands, gpus = self.plan(s, st, skip)
        except Exception: return "", mem, None
        best = self.choose(cands)
        if not best: return "", mem, None
        how, why = "auto", ""
        if st.get("placement") == "ask" and self.advise and len(cands) > 1:
            now = self.now()
            lines = "\n".join(f"[{i}] partition={c['partition']} memory={c['mem_gb']}G -> starts in about {max(0, int((c['start'] - now) // 60))} min on {c['node']}" for i, c in enumerate(cands))
            prompt = ("Choose where to run a model server job (one GPU, up to 24 h, it should start as soon as possible, "
                      "and must stay up: the shared pool does not preempt).\nOptions, each the scheduler's own estimate:\n" + lines +
                      "\n\nFree GPUs now:\n" + gpus[:1800] + (f"\n\nAvoid nodes that failed recently: {', '.join(skip)}." if skip else "") +
                      '\n\nAnswer with JSON only: {"choice": <number>, "why": "<one sentence>"}')
            try:
                txt = self.advise(prompt, st.get("placement_model") or "")
                mt = re.search(r"\{.*\}", txt, re.S); j = json.loads(mt[0]) if mt else {}
                if isinstance(j.get("choice"), int) and 0 <= j["choice"] < len(cands): best, how, why = cands[j["choice"]], "model", str(j.get("why") or "")[:200]
                else: how = "auto (the model's answer could not be used)"
            except Exception: how = "auto (the model did not answer)"
        rec = {"how": how, "why": why, "chosen": {k: best[k] for k in ("partition", "mem_gb", "start", "node")},
               "options": [{k: c[k] for k in ("partition", "mem_gb", "start", "node")} for c in cands], "at": self.now()}
        return best.get("ask") or "", int(best["mem_gb"]), rec

    def start(self, sid, why="", overrides=None, moving=False):
        s = self.server(sid)
        st = dict(s["settings"]); st.update(clean_settings(overrides or {}, st))
        job = self._job(s)
        if job and not job.get("error") and not moving: raise RuntimeError("it is already queued or running")
        n = s.get("notify") or {}
        events = ":".join(k for k in EVENTS if (n.get("events") or {}).get(k, True))
        env = [f"MAXLEN={st['max_model_len']}", f"SEQS={st['max_num_seqs']}", f"GPUUTIL={st['gpu_mem_util']}",
               f"MTP={st['mtp_tokens']}", f"TLIMIT_H={int(st['time_limit_h'])}", f"BATCHED={st['batched_tokens']}",
               f"GPUS={st['gpus']}", f"TEMP={st['temperature']}", f"TOPP={st['top_p']}", f"TOPK={st['top_k']}"] \
              + (["EAGER=1"] if st["eager"] else []) + (["ASYNC=1"] if st["async_scheduling"] else []) \
              + ([f"KVDTYPE={st['kv_cache_dtype']}"] if st["kv_cache_dtype"] != "auto" else []) \
              + ([f"MINVRAM_GB={int(st['min_vram_gb'])}"] if st.get("min_vram_gb") else []) \
              + (["KEEPLOG=1"] if st.get("keep_log") else []) + ([] if st.get("error_log", True) else ["ERRLOG=0"]) \
              + ([f"NOTIFY_TO={n['email']}", f"NOTIFY_EVENTS={events}", "MODEL_LABEL=" + re.sub(r"[^A-Za-z0-9]+", "_", s["label"]).strip("_")]
                 if (n.get("email") and events and re.fullmatch(r"[\w.+-]+@[\w.-]+", n["email"])) else [])
        with self.lock: bad = [n for n, until in ((self.rt.get(sid) or {}).get("bad_nodes") or {}).items() if until > self.now()]
        skip = sorted(set([x for x in str(st.get("exclude_nodes") or "").split(",") if x] + bad + self._bad_on_cluster(s)))
        cons = self._vram_constraint(s, st)                 # raises when no GPU on the cluster is big enough
        if cons: env.append(f"CONSTRAINT={cons}")
        part, mem_gb, placed = self._place(s, st, skip)
        flags = f"-t {int(st['time_limit_h'])}:00:00 -c {st['cpus']} --mem={mem_gb}G --gres=gpu:{st['gpus']}" + (f" --constraint='{cons}'" if cons else "")
        if skip: flags += " --exclude=" + ",".join(skip)
        if part: flags += " -p " + part
        rc, out = self.w.ssh(s["host"], f"sbatch --parsable --export='ALL,{','.join(env)}' {flags} {s['dir']}/serve.sbatch")
        jid = out.split(";")[0].strip()
        if rc or not jid.isdigit(): raise RuntimeError("the cluster refused the job: " + out[:200])
        with self.lock:
            keep = {k: (self.rt.get(sid) or {}).get(k) for k in ("restarts", "bench", "bad_nodes", "fast_fails") + (("load_moves",) if moving else ()) if (self.rt.get(sid) or {}).get(k)}
            self.rt[sid] = {**keep, "state": "queued", "jid": jid, "jid_seen": jid, "t_submit": self.now(), "asked_stop": False, "last_end": "",
                            "t_ready": None, "notified": set(), "started_by": why or "you", "settings_used": st, "placement": placed}
        return self.tick(sid)

    def loading_for(self, provider):
        """The server that serves this provider's models, if it is queued or loading right now: a chat that wants it should wait, not
        connect and fail again and again -> {id, label, state, node, elapsed, reason}, or None."""
        for s in self.cfg["servers"]:
            if (s.get("provider") or "") != provider: continue
            st = self.status(s["id"])
            if st.get("state") in ("queued", "loading"):
                return {"id": s["id"], "label": s["label"], "state": st["state"], "node": st.get("node"), "elapsed": st.get("elapsed"),
                        "reason": st.get("reason") or "", "since": st.get("t_submit")}
        return None

    def server_log(self, sid, lines=150):
        """The end of the newest server log kept on the cluster (the error log, or the full log if that is what is kept), and its name."""
        s = self.server(sid)
        lines = max(10, min(1000, int(lines or 150)))
        rc, out = self.w.ssh(s["host"], f"L=$(ls -t {s['dir']}/logs/errors.*.log {s['dir']}/logs/serve.*.log 2>/dev/null | head -1); "
                                        f'[ -n "$L" ] && {{ echo "@@$(basename $L)"; tail -n {lines} "$L"; }}')
        if rc: raise RuntimeError(out[:200] or "the cluster did not answer")
        if not out.startswith("@@"): return {"name": "", "text": ""}
        head, _, text = out.partition("\n")
        return {"name": head[2:].strip(), "text": text}

    def stop(self, sid, why=""):
        s = self.server(sid)
        with self.lock:
            rt = self.rt.setdefault(sid, {"state": "unknown"})
            rt["asked_stop"], rt["stop_reason"] = True, why or "you stopped it"
        self.w.ssh(s["host"], f"scancel -u $USER -n {s['job_name']}")
        return self.tick(sid)

    def restart(self, sid, overrides=None):
        self.stop(sid, why="restarting")
        for _ in range(20):                                   # the old job has to be gone before a new one is allowed
            if self.tick(sid).get("state") == "stopped": break
            time.sleep(3)
        return self.start(sid, why="restart", overrides=overrides)

    # --- the logins to the cluster
    def connections(self, sid=None):
        s = self.server(sid) if sid else self.cfg["servers"][0]
        names = {x["host"] for x in self.cfg["servers"]} | {"login.cluster.example.edu", "hpc", "hpcalt"}      # "hpcalt" is a second name for the same login in ~/.ssh/config
        return classify_ssh(self.w.ps(), s["host"], names, [x["local_port"] for x in self.cfg["servers"]])

    def close_connections(self, sid=None, chats=False):
        """Closes Orbit's own logins to the cluster: the shared one and the model tunnels, and -- only when asked --
        the chats' Claude Code sessions there (that cuts a chat off mid-answer). Other programs' logins are left alone.
        The next look opens a fresh connection by itself. -> how many were closed."""
        host = (self.server(sid) if sid else self.cfg["servers"][0])["host"]
        n = 0
        mine = [c for c in self.connections(sid) if c["mine"] and (chats or c["kind"] != "chat")]
        if any(c["kind"] == "monitor" for c in mine):
            try: self.w.monitor_exit(host)
            except Exception: pass
        for c in mine:
            self.w.kill(c["pid"]); n += 1
        for x in self.cfg["servers"]:
            if x["host"] == host and any(c["kind"] == "tunnel" and c.get("port") == x["local_port"] for c in mine):
                with self.lock: (self.rt.get(x["id"]) or {}).pop("key_set", None)
        with self.lock:
            for x in self.cfg["servers"]: (self.rt.get(x["id"]) or {}).update(fails=0, next_poll=0)      # look again right away
        return n

    # --- telling you
    def event(self, s, kind, detail, rt):
        """Something worth hearing happened: a desktop notice, and an e-mail where asked for. Once per job and kind."""
        key = (rt.get("jid") or rt.get("jid_seen"), kind)
        with self.lock:
            seen = rt.setdefault("notified", set())
            if key in seen: return
            seen.add(key)
        label = s["label"]
        ctx = (rt.get("info") or {}).get("max_model_len") or (rt.get("settings_used") or s["settings"]).get("max_model_len")
        took = (rt.get("t_ready") or self.now()) - (rt.get("t_submit") or self.now())
        if kind == "ready":
            subject = f"{label} is ready"
            lines = [f"{label} is up and answering.", f"Context length: {ctx:,} tokens" if isinstance(ctx, int) else "",
                     f"Node: {rt.get('node') or '?'}", f"Job: {rt.get('jid')}", f"Took {int(took // 60)} min from request to ready",
                     f"The job ends by itself after {s['settings']['time_limit_h']} h."]
        elif kind == "stopped":
            subject = f"{label} stopped"
            lines = [f"{label} has stopped: {detail}.", f"Job: {rt.get('jid')}"]
        else:
            subject = f"{label} failed"
            lines = [f"{label} did not stay up: {detail}.", f"Job: {rt.get('jid')}"]
        body = "\n".join(l for l in lines if l)
        n = s.get("notify") or {}
        if not (n.get("events") or {}).get(kind, True): return
        if n.get("desktop", True):
            try: self.w.desktop(subject, body.splitlines()[0])
            except Exception: pass
        # the e-mail for these three is sent by the job itself, on the cluster, so it arrives with this Mac off

    def test_email(self, sid):
        s = self.server(sid)
        to = (s.get("notify") or {}).get("email")
        if not to: raise RuntimeError("no e-mail address is set")
        self.w.email(s["host"], to, f"[Orbit] test: {s['label']}",
                     "This is a test from Orbit's model-server panel, sent by the cluster. If you can read it, notices will arrive.\n\n— Orbit")
        return to

    # --- editing
    def update(self, sid, d):
        with self.lock:
            s = self.server(sid)
            if "label" in d and str(d["label"]).strip(): s["label"] = str(d["label"]).strip()[:60]
            if "settings" in d: s["settings"] = clean_settings(d["settings"] or {}, s["settings"])
            if "schedule" in d: s["schedule"] = clean_schedule(d["schedule"])
            if "notify" in d:
                n, o = d["notify"] or {}, s.setdefault("notify", {})
                if "email" in n: o["email"] = str(n["email"] or "").strip()[:200]
                if "desktop" in n: o["desktop"] = bool(n["desktop"])
                if "events" in n: o["events"] = {k: bool((n["events"] or {}).get(k)) for k in EVENTS}
            self.save()

    def add(self, d):
        """Another model on the same cluster: its own folder (serve.sbatch and model/), job name and local port."""
        label = str(d.get("label") or "").strip()
        folder = str(d.get("dir") or "").strip().rstrip("/")
        if not label or not folder.startswith("/") or re.search(r"[^\w./-]", folder):
            raise ValueError("give it a name and the full path of its folder on the cluster")
        base = self.cfg["servers"][0]
        sid = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") or "model"
        while any(x["id"] == sid for x in self.cfg["servers"]): sid += "-2"
        port = max(x["local_port"] for x in self.cfg["servers"]) + 1
        s = json.loads(json.dumps(base))
        s.update(id=sid, label=label, dir=folder, job_name=("srv-" + sid)[:24], local_port=port,
                 model=str(d.get("model") or sid), key_name="MODELSERVER_KEY_" + re.sub(r"\W", "_", sid).upper(),
                 provider="", schedule=[])
        s["settings"] = dict(SETTINGS)
        # the same launch script as the first server's, in the new folder, unless it already has one
        self.w.ssh(s["host"], f"mkdir -p {folder} && [ -f {folder}/serve.sbatch ] || cp {base['dir']}/serve.sbatch {folder}/serve.sbatch")
        with self.lock:
            self.cfg["servers"].append(s); self.save()
        return s

    def remove(self, sid):
        if len(self.cfg["servers"]) <= 1: raise ValueError("keep at least one server")
        if (self.rt.get(sid) or {}).get("state") not in (None, "unknown", "stopped"): raise ValueError("stop it first")
        with self.lock:
            self.cfg["servers"] = [x for x in self.cfg["servers"] if x["id"] != sid]; self.save(); self.rt.pop(sid, None)

    def public(self):
        """Everything the panel shows."""
        out = []
        for s in self.cfg["servers"]:
            row = json.loads(json.dumps({k: s[k] for k in ("id", "label", "host", "dir", "model", "local_port", "settings", "schedule", "notify")}))
            row["status"] = self.status(s["id"])
            out.append(row)
        try: conns = self.connections()
        except Exception: conns = []
        return {"servers": out, "defaults": SETTINGS, "now": self.now(), "connections": conns}

    # --- the loop that keeps it all current
    def loop(self, stop=None):
        while not (stop and stop.is_set()):
            for s in list(self.cfg["servers"]):
                rt = self.rt.setdefault(s["id"], {"state": "unknown"})
                if rt.get("state") == "ready" and self.now() - rt.get("m_at", 0) >= 10:
                    try: self.read_metrics(s, rt)
                    except Exception: pass
                try: self.health(s, rt); self.keep_alive(s, rt); self.renew(s, rt)
                except Exception: pass
                if self.now() < rt.get("next_poll", 0): continue
                try: self.tick(s["id"])
                except Exception as e:
                    with self.lock: rt["error"] = f"{type(e).__name__}: {e}"; rt["next_poll"] = self.now() + 60
            try: self.run_schedule()
            except Exception: pass
            time.sleep(LOOP_S)
