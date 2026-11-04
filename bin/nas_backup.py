"""Backing up lab files from the clusters to the lab NAS.

Orbit never carries the data itself: for each folder it writes a small rsync script on the cluster and submits it as a batch job (so the
copy runs on a compute node, never on the login node), then reads how the job ended. The copy only ever ADDS: nothing on the NAS is deleted,
and a file that changed since the last copy keeps its old version in a dated folder. Raw and intermediate files (alignments, reads,
temporary folders) are left out by default: results, scripts and logs are what is kept.

Settings live in config/nas_backup.json; the cluster side (how to reach it, what its jobs must be called) comes from bin/cluster.py's
cluster objects. `cluster._ssh(command, timeout)` -> (code, text) is all this needs from one.
"""
import base64, json, os, re, shlex, stat, subprocess, tempfile, threading, time

KEEP_RUNS = 40
RETRY_S = 1800          # a cluster or the NAS that cannot be reached is tried again half an hour later, for as long as it takes
MAX_RETRIES = 200
UNREACHABLE = re.compile(r"timed out|timeout|connection (refused|reset|closed|timed)|no route|unreachable|could not resolve|no answer|ssh failed|network is down|temporarily unavailable|broken pipe|port 22|kex_exchange", re.I)
JOB_PREFIXES = ("orbit-nasbackup", "MP_nasbackup")          # Orbit's own jobs: the cluster page does not announce them as news

DEFAULT_EXCLUDE = [
    "*.bam", "*.bai", "*.csi", "*.cram", "*.crai", "*.sam", "*.sra", "*.fastq", "*.fastq.gz", "*.fq", "*.fq.gz", "*.fasta.gz.tmp",
    "*.tmp", "*.temp", "tmp/", "temp/", "tmp_*/", "scratch/", ".snakemake/", "work/", ".nextflow/", ".cache/", "__pycache__/", "*.pyc",
    "node_modules/", ".git/objects/", "core.[0-9]*", "*.sif", "envs/", "conda/", ".conda/", ".ipynb_checkpoints/",
]

DEFAULTS = {
    "enabled": False, "at": "02:30", "every_h": 168, "last_start": 0,        # once a week
    # mode "ssh": the cluster copies straight to the NAS; mode "mac": this Mac does, into a folder of the NAS mounted in Finder (mount)
    "dest": {"label": "NAS", "host": "", "port": 22, "user": "", "path": "", "host_key": "", "mode": "ssh", "mount": ""},
    "routes": [],        # copies between clusters: {id, label, from, host, port, user, path, host_key}
    "exclude": DEFAULT_EXCLUDE, "versions": True, "max_file_gb": 0, "sources": [], "runs": [],
}
# how each cluster's batch jobs must look (Cassini is a shared account: its jobs carry the MP_ prefix, stay on the one partition and off the GPU nodes)
CLUSTER_JOBS = {"cassini": {"exclude": "compute-6-[11,19,21-23]"}}


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s or "").lower()).strip("-")[:24] or "folder"


def clean_path(p):
    p = str(p or "").strip().rstrip("/") or ""
    if not re.fullmatch(r"/[\w.+@ ~-]+(/[\w.+@ ~-]+)*", p) or ".." in p.split("/"):
        raise ValueError("a folder is an absolute path such as /path/to/project/lab/me/results (no .. and no odd characters)")
    return p


def build_script(job, workdir, src, dest, cluster_id, label, exclude, dry=False, versions=True, max_file_gb=0, partition="", node_exclude="", stamp=None):
    """The batch script that copies one folder. `dest` is the NAS settings; with no host, its path is a folder the cluster can see itself."""
    stamp = stamp or time.strftime("%Y%m%d-%H%M%S")
    q = shlex.quote
    remote = bool(dest.get("host"))
    target = f"{dest['path'].rstrip('/')}/{cluster_id}/{label}"
    vdir = f"{dest['path'].rstrip('/')}/_versions/{stamp[:8]}/{cluster_id}/{label}"
    flags = ["-rltD", "--partial", "--no-owner", "--no-group", "--no-perms", "--stats", "--human-readable"]
    if dry: flags.append("-n")
    if versions: flags += ["--backup", "--backup-dir=" + q(vdir)]
    if max_file_gb: flags.append(f"--max-size={int(max_file_gb)}G")
    flags += ["--exclude=" + q(x) for x in exclude]
    head = ["#!/bin/bash", f"#SBATCH -J {job}", "#SBATCH -t 1-00:00:00", "#SBATCH -c 1", "#SBATCH --mem=2G",
            f"#SBATCH -o {workdir}/logs/%x_%j.out", f"#SBATCH -e {workdir}/logs/%x_%j.out"]
    if partition: head.append(f"#SBATCH -p {partition}")
    if node_exclude: head.append(f"#SBATCH --exclude={node_exclude}")
    body = ["set -u", f'export TMPDIR="{workdir}/tmp_$SLURM_JOB_ID"; mkdir -p "$TMPDIR"; trap \'rm -rf "$TMPDIR"\' EXIT',
            f'echo "[$(date -Is)] {"dry run: " if dry else ""}{cluster_id}:{src} -> {dest.get("label") or "NAS"}:{target} on $(hostname -s)"']
    if remote:
        body += [f'KH="{workdir}/known_hosts"; printf "%s\\n" {q(dest["host_key"])} > "$KH"',
                 f'SSH="ssh -i {workdir}/nas_key -p {int(dest["port"])} -o BatchMode=yes -o IdentitiesOnly=yes -o UserKnownHostsFile=$KH -o StrictHostKeyChecking=yes -o ConnectTimeout=20"',
                 f'DEST={q(dest["user"] + "@" + dest["host"] + ":" + target + "/")}']
        rsh = ['-e "$SSH"', "--rsync-path=" + q(f"mkdir -p {shlex.quote(target)} {shlex.quote(vdir)} && rsync")]
    else:
        body += [f'mkdir -p {q(target)} {q(vdir)}', f'DEST={q(target + "/")}']
        rsh = []
    body += [f'rsync {" ".join(flags + rsh)} {q(src.rstrip("/") + "/")} "$DEST"', 'rc=$?', 'echo "@@result rc=$rc"', 'exit $rc']
    return "\n".join(head + body) + "\n"


def build_transfer_script(job, workdir, route, direction, src, dst, dry=False, partition="", node_exclude="", exclude=()):
    """The batch script for one copy between clusters through a restricted key. push: `src` on this cluster -> `dst` on the far one;
    pull: `src` on the far one -> `dst` on this cluster. Only plain rsync options: the far end's gate refuses the rest (--rsync-path,
    --backup-dir...). Never deletes."""
    q = shlex.quote
    head = ["#!/bin/bash", f"#SBATCH -J {job}", "#SBATCH -t 1-00:00:00", "#SBATCH -c 1", "#SBATCH --mem=2G",
            f"#SBATCH -o {workdir}/logs/%x_%j.out", f"#SBATCH -e {workdir}/logs/%x_%j.out"]
    if partition: head.append(f"#SBATCH -p {partition}")
    if node_exclude: head.append(f"#SBATCH --exclude={node_exclude}")
    far = f'{route["user"]}@{route["host"]}'
    body = ["set -u", f'KH="{workdir}/known_hosts_{route["id"]}"; printf "%s\\n" {q(route["host_key"])} > "$KH"',
            f'SSH="ssh -i {workdir}/{route["id"]}_key -p {int(route["port"])} -o BatchMode=yes -o IdentitiesOnly=yes -o UserKnownHostsFile=$KH -o StrictHostKeyChecking=yes -o ConnectTimeout=20"',
            f'echo "[$(date -Is)] {"dry run: " if dry else ""}{direction} {src} -> {dst} via {route.get("label") or route["id"]} on $(hostname -s)"']
    flags = ["-rltD", "--partial", "--no-owner", "--no-group", "--no-perms", "--stats", "--human-readable"] + (["-n"] if dry else []) + ["--exclude=" + q(x) for x in exclude]
    if direction == "push": s_, d_ = q(src.rstrip("/") + "/"), q(f"{far}:{dst.rstrip('/')}/")
    else:
        body.append(f"mkdir -p {q(dst)}")
        s_, d_ = q(f"{far}:{src.rstrip('/')}/"), q(dst.rstrip("/") + "/")
    body += [f'rsync {" ".join(flags)} -e "$SSH" {s_} {d_}', 'rc=$?', 'echo "@@result rc=$rc"', 'exit $rc']
    return "\n".join(head + body) + "\n"


def parse_log(text):
    """The end of a backup job's output -> {rc, files, bytes, error}."""
    t = text or ""
    m = re.search(r"@@result rc=(\d+)", t)
    f = re.search(r"Number of (?:regular )?files transferred: ([\d,]+)", t)
    b = re.search(r"Total transferred file size: ([\d.,]+[KMGTP]?)(?: bytes)?", t)
    err = [l.strip() for l in t.splitlines() if re.search(r"(rsync|ssh|Permission denied|error|failed)", l, re.I) and not l.startswith("@@") and "files transferred" not in l]
    return {"rc": int(m[1]) if m else None, "files": int(f[1].replace(",", "")) if f else None, "bytes": b[1] if b else None, "error": (err[-1][:240] if err else "")}


LOGIN_TEMPLATE = """# NAS login. You fill this in; only Orbit on this Mac reads it. Nothing else is told the password.
#
# It is used once per cluster, to put that cluster's backup key on the NAS (Cluster page > Back up to the NAS >
# "Authorize"). After that the clusters copy with their keys, so you can delete the password line.
# This file is left out of Orbit's own backups and cannot be read by the models.
#
# One line each, no quotes:
user=
password=
"""


def read_login(path):
    """The user and password from the login file -> (user, password); '' for what is not filled in."""
    out = {}
    try:
        for line in open(path, encoding="utf-8").read().splitlines():
            if line.lstrip().startswith("#") or "=" not in line: continue
            k, v = line.split("=", 1)
            v = v.rstrip("\r\n") if k.strip().lower() == "password" else v.strip()
            if v.strip() or k.strip().lower() not in out: out[k.strip().lower()] = v          # an empty line left from the template does not hide a filled one
    except OSError:
        pass
    return out.get("user", ""), out.get("password", "")


def ssh_with_password(user, host, port, known_hosts_line, password_file, remote_command, timeout=40):
    """One ssh command with a password, without the password ever being on a command line, in the environment or in a log: ssh asks a tiny
    helper script for it (SSH_ASKPASS), and the helper reads it from the login file at that moment."""
    tmp = tempfile.mkdtemp(prefix="orbit-nas-"); os.chmod(tmp, 0o700)
    try:
        kh = os.path.join(tmp, "known_hosts"); open(kh, "w").write(known_hosts_line + "\n")
        ask = os.path.join(tmp, "ask.py")
        open(ask, "w").write("#!/usr/bin/env python3\nimport sys\npw = ''\nfor l in open(%r, encoding='utf-8'):\n    if l.split('=', 1)[0].strip().lower() == 'password' and '=' in l and l.split('=', 1)[1].strip():\n"
                             "        pw = l.split('=', 1)[1].rstrip('\\r\\n')\nsys.stdout.write(pw)\n" % password_file)
        os.chmod(ask, 0o700)
        env = {**os.environ, "SSH_ASKPASS": ask, "SSH_ASKPASS_REQUIRE": "force", "DISPLAY": os.environ.get("DISPLAY") or ":0"}
        r = subprocess.run(["ssh", "-p", str(port), "-o", "PubkeyAuthentication=no", "-o", "PreferredAuthentications=password,keyboard-interactive",
                            "-o", "NumberOfPasswordPrompts=1", "-o", "StrictHostKeyChecking=yes", "-o", "UserKnownHostsFile=" + kh,
                            "-o", "ConnectTimeout=15", f"{user}@{host}", remote_command], capture_output=True, text=True, timeout=timeout, env=env, stdin=subprocess.DEVNULL)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (subprocess.TimeoutExpired, OSError) as e:
        return 255, f"ssh failed: {e}"
    finally:
        for f in os.listdir(tmp):
            try: os.remove(os.path.join(tmp, f))
            except OSError: pass
        try: os.rmdir(tmp)
        except OSError: pass


class NasBackup:
    def __init__(self, path, clusters, now=time.time, notify=None, login_path=None):
        self.path, self.clusters, self.now = path, clusters, now        # clusters: {id: cluster.Cluster}
        self.login_path = login_path or os.path.join(os.path.dirname(path), "nas_login.txt")
        self.notify = notify or (lambda title, text: None)
        self.lock = threading.RLock()
        self.cfg = self._load()
        self._told, self._homes = set(), {}

    # --- settings
    def _load(self):
        try: d = json.load(open(self.path))
        except (OSError, ValueError): d = {}
        for k, v in DEFAULTS.items():
            d.setdefault(k, json.loads(json.dumps(v)))
        for k, v in DEFAULTS["dest"].items(): d["dest"].setdefault(k, v)
        return d

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f: json.dump(self.cfg, f, indent=1)
        os.replace(tmp, self.path)

    def update(self, d):
        with self.lock:
            c = self.cfg
            if "enabled" in d: c["enabled"] = bool(d["enabled"])
            if re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", str(d.get("at", ""))): c["at"] = d["at"]
            if re.fullmatch(r"\d+", str(d.get("every_h", ""))): c["every_h"] = max(1, min(24 * 30, int(d["every_h"])))
            if "versions" in d: c["versions"] = bool(d["versions"])
            if re.fullmatch(r"\d+", str(d.get("max_file_gb", ""))): c["max_file_gb"] = max(0, min(10000, int(d["max_file_gb"])))
            if isinstance(d.get("exclude"), list):
                c["exclude"] = [str(x).strip() for x in d["exclude"] if re.fullmatch(r"[\w.*?\[\]/+@-]{1,80}", str(x).strip())][:80]
            n = d.get("dest")
            if isinstance(n, dict):
                dd = c["dest"]
                if "host" in n:
                    if str(n["host"]).strip() and not re.fullmatch(r"[A-Za-z0-9.-]{1,120}", str(n["host"]).strip()): raise ValueError("that is not a host name or address")
                    dd["host"] = str(n["host"]).strip()
                if "port" in n:
                    if not re.fullmatch(r"\d{1,5}", str(n["port"])) or not 0 < int(n["port"]) < 65536: raise ValueError("a port is a number such as 22")
                    dd["port"] = int(n["port"])
                if "user" in n:
                    if str(n["user"]).strip() and not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", str(n["user"]).strip()): raise ValueError("a user name has letters, digits and . _ - only")
                    dd["user"] = str(n["user"]).strip()
                if "path" in n: dd["path"] = clean_path(n["path"]) if str(n["path"]).strip() else ""
                if "label" in n: dd["label"] = re.sub(r"[^\w .-]", "", str(n["label"]))[:40] or "NAS"
                if "mode" in n:
                    if n["mode"] not in ("ssh", "mac"): raise ValueError("mode is ssh (the cluster copies) or mac (this Mac copies into a mounted NAS folder)")
                    dd["mode"] = n["mode"]
                if "mount" in n:
                    mt = str(n["mount"]).strip().rstrip("/")
                    if mt and (not mt.startswith("/Volumes/") or ".." in mt.split("/")): raise ValueError("the mounted folder is under /Volumes/, such as /Volumes/backup/yourname")
                    dd["mount"] = mt
                if "host_key" in n:
                    k = str(n["host_key"]).strip()
                    if k and not re.fullmatch(r"\S+ ssh-(ed25519|rsa|ecdsa-sha2-nistp\d+) [A-Za-z0-9+/=]+", k): raise ValueError("that is not an ssh host key line")
                    dd["host_key"] = k
            if isinstance(d.get("routes"), list):
                out = []
                for r in d["routes"][:12]:
                    rid = slug(r.get("id") or r.get("label"))
                    if str(r.get("from")) not in self.clusters: raise ValueError(f"no cluster called {r.get('from')!r}")
                    if not re.fullmatch(r"[A-Za-z0-9.-]{1,120}", str(r.get("host") or "")): raise ValueError("a route needs the host of the far end")
                    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", str(r.get("user") or "")): raise ValueError("a route needs the user on the far end")
                    port = int(r.get("port") or 22)
                    if not 0 < port < 65536: raise ValueError("a port is a number such as 22")
                    k = str(r.get("host_key") or "").strip()
                    if k and not re.fullmatch(r"\S+ ssh-(ed25519|rsa|ecdsa-sha2-nistp\d+) [A-Za-z0-9+/=]+", k): raise ValueError("that is not an ssh host key line")
                    out.append({"id": rid, "label": re.sub(r"[^\w .>→-]", "", str(r.get("label") or rid))[:50], "from": r["from"], "host": r["host"], "port": port,
                                "user": r["user"], "path": clean_path(r.get("path")) if r.get("path") else "", "host_key": k})
                c["routes"] = out
            if isinstance(d.get("sources"), list):
                out, seen = [], set()
                for s in d["sources"][:40]:
                    cid = str(s.get("cluster") or "")
                    if cid not in self.clusters: raise ValueError(f"no cluster called {cid!r}")
                    p = clean_path(s.get("path"))
                    lab = slug(s.get("label") or os.path.basename(p))
                    sid = f"{cid}-{lab}"
                    if sid in seen: raise ValueError(f"two folders would be called {lab} on {cid}: give one another label")
                    seen.add(sid); out.append({"id": sid, "cluster": cid, "path": p, "label": lab})
                c["sources"] = out
            self._save()

    # --- where things go on a cluster
    def _cl(self, cid):
        cl = self.clusters.get(cid)
        if cl is None: raise ValueError(f"no cluster called {cid!r}")
        return cl

    def _workdir(self, cid):
        cl = self._cl(cid)
        dirs = [d for d in (cl.cfg.get("job_dirs") or []) if d]
        if dirs: return dirs[0].rstrip("/") + "/nasbackup"
        home = self._homes.get(cid)
        if not home:                              # #SBATCH lines are not expanded by the shell: the real path is needed
            code, out = cl._ssh("echo $HOME", 30)
            home = out.strip().splitlines()[-1] if out.strip() else ""
            if code or not home.startswith("/"): raise RuntimeError(f"could not reach {cid}: {(out or 'no answer')[:160]}")
            self._homes[cid] = home
        return home + "/.orbit/nasbackup"

    def _job_name(self, cid, sid):
        pre = self._cl(cid).cfg.get("job_prefix") or ""
        return f"{pre}nasbackup_{sid}" if pre else f"orbit-nasbackup-{sid}"

    def _ready(self, cid, need_key=True):
        d = self.cfg["dest"]
        if d.get("mode") == "mac":
            if not d.get("mount") or not os.path.isdir(d["mount"]): raise ValueError("the NAS folder is not mounted on this Mac: connect to the NAS in Finder (Go > Connect to Server) first")
            return
        if not d["path"]: raise ValueError("say which folder on the NAS the backups go in")
        if d["host"] and not d["user"]: raise ValueError("say which user the NAS knows you as")
        if d["host"] and not d["host_key"]: raise ValueError("trust the NAS first: its fingerprint has not been confirmed")

    # --- one-time setup, each a thing you press
    def scan_host(self):
        """The NAS's host key as this Mac sees it, with its fingerprint, to be confirmed by eye before it is trusted."""
        d = self.cfg["dest"]
        if not d["host"]: raise ValueError("no NAS host is set")
        try:
            r = subprocess.run(["ssh-keyscan", "-T", "8", "-t", "ed25519", "-p", str(d["port"]), d["host"]], capture_output=True, text=True, timeout=20)
        except (subprocess.TimeoutExpired, OSError) as e:
            raise RuntimeError(f"could not reach the NAS: {e}")
        line = next((l for l in r.stdout.splitlines() if " ssh-ed25519 " in l), "")
        if not line: raise RuntimeError("the NAS did not give a host key (is it on the campus network or the VPN, and is that the ssh port?)")
        fp = subprocess.run(["ssh-keygen", "-lf", "-"], input=line + "\n", capture_output=True, text=True, timeout=10).stdout.strip()
        return {"line": line.strip(), "fingerprint": fp}

    def login_file(self):
        """Make the login file if there is none (private to you), and say whether it is filled in. Never the password itself."""
        if not os.path.exists(self.login_path):
            os.makedirs(os.path.dirname(self.login_path), exist_ok=True)
            fd = os.open(self.login_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f: f.write(LOGIN_TEMPLATE)
        else:
            os.chmod(self.login_path, 0o600)
        user, pw = read_login(self.login_path)
        return {"path": self.login_path, "user_set": bool(user), "password_set": bool(pw)}

    def authorize(self, cid):
        """Put this cluster's key on the NAS, using the login file's password once, then prove the cluster can log in with the key alone."""
        d = self.cfg["dest"]
        if not d["host"]: raise ValueError("no NAS address is set")
        if not d["host_key"]: raise ValueError("trust the NAS first: look at its fingerprint and confirm it")
        info = self.login_file(); user, pw = read_login(self.login_path)
        if not user or not pw: raise ValueError(f"fill in your user and password in {self.login_path} first")
        with self.lock:
            if not d["user"]: d["user"] = user; self._save()
        pub = self.setup_key(cid)["public_key"]
        opts = "no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty "
        line = shlex.quote(opts + pub)
        rc, out = ssh_with_password(user, d["host"], d["port"], d["host_key"], self.login_path,
                                    f"umask 077; mkdir -p ~/.ssh; touch ~/.ssh/authorized_keys; grep -qxF {line} ~/.ssh/authorized_keys || echo {line} >> ~/.ssh/authorized_keys; echo AUTHORIZED")
        if rc or "AUTHORIZED" not in out:
            raise RuntimeError("the NAS did not take the key: " + (out.replace(pw, "***") if pw else out)[-200:])
        wd = self._workdir(cid)
        code, res = self._cl(cid)._ssh(
            f'printf "%s\\n" {shlex.quote(d["host_key"])} > "{wd}/known_hosts"; ssh -i "{wd}/nas_key" -p {int(d["port"])} -o BatchMode=yes -o IdentitiesOnly=yes '
            f'-o UserKnownHostsFile="{wd}/known_hosts" -o StrictHostKeyChecking=yes -o ConnectTimeout=15 {shlex.quote(d["user"] + "@" + d["host"])} "echo KEY_OK" 2>&1', 40)
        if "KEY_OK" not in res: raise RuntimeError(f"the key is on the NAS but {cid} could not log in with it: " + (res or "no answer")[-200:])
        return {"ok": True, "cluster": cid, "message": f"{cid} can now copy to the NAS with its key"}

    def setup_key(self, cid):
        """Make the key this cluster copies with (only if there is none) and return its public half, to be added to the NAS user's authorized keys."""
        wd = self._workdir(cid)
        cmd = (f'mkdir -p "{wd}/logs" && chmod 700 "{wd}" && [ -f "{wd}/nas_key" ] || '
               f'ssh-keygen -q -t ed25519 -N "" -C "orbit-nasbackup@{cid}" -f "{wd}/nas_key"; cat "{wd}/nas_key.pub"')
        code, out = self._cl(cid)._ssh(cmd, 40)
        pub = next((l for l in out.splitlines() if l.startswith("ssh-ed25519 ")), "")
        if code or not pub: raise RuntimeError("could not make the key on the cluster: " + (out or "no answer")[:200])
        return {"public_key": pub, "where": f"{wd}/nas_key"}

    # --- running
    def run(self, only=None, dry=False, reason="manual"):
        """Submit a copy job for each folder (or just `only`) -> [{source, job, ...}]."""
        with self.lock:
            srcs = [s for s in self.cfg["sources"] if not only or s["id"] == only]
            if not srcs: raise ValueError("no folders to back up: add some first" if not only else "no such folder")
            for s in srcs: self._ready(s["cluster"])
            started = []
            for s in srcs:
                try:
                    started.append(self._run_mac(s, dry, reason) if self.cfg["dest"].get("mode") == "mac" else self._submit(s, dry, reason))
                    self.cfg.setdefault("retry", {}).pop(s["id"], None); self.cfg.setdefault("retry_n", {}).pop(s["id"], None)
                except (RuntimeError, ValueError) as e:
                    started.append(self._record(s, "", "failed", dry, reason, error=str(e)))
                    self._retry_later(s, dry, reason, str(e))
            if reason == "schedule": self.cfg["last_start"] = self.now()
            self._save()
            return started

    def _retry_later(self, s, dry, reason, why):
        """A scheduled run that failed because something could not be reached is tried again in half an hour, and again, until it works."""
        if not reason.startswith("schedule") or not UNREACHABLE.search(why or ""): return
        counts = self.cfg.setdefault("retry_n", {})
        n = counts.get(s["id"], 0) + 1
        if n <= MAX_RETRIES:
            counts[s["id"]] = n
            self.cfg.setdefault("retry", {})[s["id"]] = {"at": self.now() + RETRY_S, "n": n, "dry": bool(dry), "why": (why or "")[:160]}

    def _record(self, s, job, state, dry, reason, error=""):
        r = {"source": s["id"], "cluster": s["cluster"], "path": s["path"], "job": job, "state": state, "dry": bool(dry), "reason": reason,
             "started": self.now(), "error": error}
        self.cfg["runs"] = (self.cfg["runs"] + [r])[-KEEP_RUNS:]
        return r

    def _submit(self, s, dry, reason):
        cid, cl, c, d = s["cluster"], self._cl(s["cluster"]), self.cfg, self.cfg["dest"]
        wd = self._workdir(cid)
        job = self._job_name(cid, s["id"].split("-", 1)[1] if "-" in s["id"] else s["id"])
        if d["host"]:
            code, out = cl._ssh(f'[ -f "{wd}/nas_key" ] && echo ok', 30)
            if code == 255 or (code and UNREACHABLE.search(out or "")): raise RuntimeError(f"could not reach {cid}: {(out or 'no answer')[:160]}")
            if code or "ok" not in out: raise ValueError(f"{cid} has no key for the NAS yet: use Set up the key")
        script = build_script(job, wd, s["path"], d, cid, s["label"], c["exclude"], dry=dry, versions=c["versions"], max_file_gb=c["max_file_gb"],
                              partition=(cl.cfg.get("partitions") if cl.cfg.get("profile") == "slurm" else ""), node_exclude=CLUSTER_JOBS.get(cid, {}).get("exclude", ""))
        b64 = base64.b64encode(script.encode()).decode()
        cmd = f'mkdir -p "{wd}/logs" && printf %s {b64} | base64 -d > "{wd}/{s["id"]}.sh" && sbatch --parsable "{wd}/{s["id"]}.sh"'
        code, out = cl._ssh(cmd, 60)
        jid = out.strip().split(";")[0].strip().splitlines()[-1] if out.strip() else ""
        if code or not jid.isdigit(): raise RuntimeError("the cluster refused the backup job: " + (out or "no answer")[:200])
        return self._record(s, jid, "submitted", dry, reason)

    # --- the NAS mounted on this Mac: the Mac pulls from the cluster and writes into the mounted folder (the data streams through, nothing is kept here)
    def _run_mac(self, s, dry, reason):
        cl, c, d = self._cl(s["cluster"]), self.cfg, self.cfg["dest"]
        target = os.path.join(d["mount"], s["cluster"], s["label"])
        vdir = os.path.join(d["mount"], "_versions", time.strftime("%Y%m%d"), s["cluster"], s["label"])
        os.makedirs(target, exist_ok=True)
        flags = ["-rltD", "--partial", "--no-owner", "--no-group", "--no-perms", "--stats", "--human-readable"] + (["-n"] if dry else [])
        if c["versions"]: os.makedirs(vdir, exist_ok=True); flags += ["--backup", "--backup-dir=" + vdir]
        if c["max_file_gb"]: flags.append(f"--max-size={int(c['max_file_gb'])}G")
        flags += ["--exclude=" + x for x in c["exclude"]]
        r = self._record(s, "", "running", dry, reason)
        r["via"] = "mac"
        cmd = ["rsync"] + flags + ["-e", "ssh -o BatchMode=yes -o ConnectTimeout=20", f"{cl.cfg['host']}:{s['path'].rstrip('/')}/", target + "/"]
        def work():
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=12 * 3600)
                out = p.stdout + p.stderr + f"\n@@result rc={p.returncode}\n"
            except (subprocess.TimeoutExpired, OSError) as e:
                out = f"rsync failed: {e}\n@@result rc=255\n"
            self._finish(r, out)
        threading.Thread(target=work, daemon=True).start()
        return r

    def _finish(self, r, log):
        res = parse_log(log); ok = res["rc"] in (0, 24)
        with self.lock:
            r.update(files=res["files"], bytes=res["bytes"], ended=self.now(), state="done" if ok else "failed", log=log[-1500:],
                     error="" if ok else (res["error"] or f"rsync exited with {res['rc']}"))
            self._save()
        key = r.get("job") or r["source"] + str(r["started"])
        if key in self._told: return
        self._told.add(key)
        what = "would copy" if r.get("dry") else "copied"
        where = f"{r['cluster']}:{r['path']}"
        if ok: self.notify("NAS backup " + ("checked" if r.get("dry") else "done"), f"{where} — {what} {r['files'] if r['files'] is not None else '?'} files ({r['bytes'] or '?'})")
        else: self.notify("NAS backup failed", f"{where} — {r['error']}")

    # --- copies between clusters, through a restricted key (see the far end's gate)
    def _route(self, rid):
        r = next((x for x in self.cfg["routes"] if x["id"] == rid), None)
        if not r: raise ValueError("no such route")
        return r

    def route_scan(self, rid):
        r = self._route(rid)
        try:
            p = subprocess.run(["ssh-keyscan", "-T", "8", "-t", "ed25519", "-p", str(r["port"]), r["host"]], capture_output=True, text=True, timeout=20)
        except (subprocess.TimeoutExpired, OSError) as e:
            raise RuntimeError(f"could not reach {r['host']}: {e}")
        line = next((l for l in p.stdout.splitlines() if " ssh-ed25519 " in l), "")
        if not line: raise RuntimeError("it did not give a host key (is it on the campus network or the VPN, and is that the ssh port?)")
        fp = subprocess.run(["ssh-keygen", "-lf", "-"], input=line + "\n", capture_output=True, text=True, timeout=10).stdout.strip()
        return {"line": line.strip(), "fingerprint": fp}

    def route_key(self, rid):
        """Make the key this route copies with, on the cluster it starts from, and return its public half (for the far end's authorized keys)."""
        r = self._route(rid); wd = self._workdir(r["from"])
        cmd = (f'mkdir -p "{wd}/logs" && chmod 700 "{wd}" && [ -f "{wd}/{rid}_key" ] || '
               f'ssh-keygen -q -t ed25519 -N "" -C "orbit-{rid}@{r["from"]}" -f "{wd}/{rid}_key"; cat "{wd}/{rid}_key.pub"')
        code, out = self._cl(r["from"])._ssh(cmd, 40)
        pub = next((l for l in out.splitlines() if l.startswith("ssh-ed25519 ")), "")
        if code or not pub: raise RuntimeError("could not make the key on the cluster: " + (out or "no answer")[:200])
        return {"public_key": pub, "where": f"{wd}/{rid}_key"}

    def transfer(self, rid, direction, src, dst, dry=False):
        """Submit one copy between clusters as a batch job on the cluster it starts from."""
        r = self._route(rid)
        if direction not in ("push", "pull"): raise ValueError("push or pull")
        if not r["host_key"]: raise ValueError("trust the far end first: its fingerprint has not been confirmed")
        src, dst = clean_path(src), clean_path(dst)
        cid = r["from"]; cl = self._cl(cid); wd = self._workdir(cid)
        code, out = cl._ssh(f'[ -f "{wd}/{rid}_key" ] && echo ok', 30)
        if code == 255 or (code and UNREACHABLE.search(out or "")): raise RuntimeError(f"could not reach {cid}: {(out or 'no answer')[:160]}")
        if code or "ok" not in out: raise ValueError(f"{cid} has no key for this route yet: make it first")
        pre = cl.cfg.get("job_prefix") or ""
        job = f"{pre}xfer_{rid}" if pre else f"orbit-xfer-{rid}"
        script = build_transfer_script(job, wd, r, direction, src, dst, dry=dry, partition=(cl.cfg.get("partitions") if cl.cfg.get("profile") == "slurm" else ""),
                                       node_exclude=CLUSTER_JOBS.get(cid, {}).get("exclude", ""), exclude=self.cfg["exclude"])
        b64 = base64.b64encode(script.encode()).decode()
        name = f"xfer-{rid}-{int(self.now())}"
        code, out = cl._ssh(f'mkdir -p "{wd}/logs" && printf %s {b64} | base64 -d > "{wd}/{name}.sh" && sbatch --parsable "{wd}/{name}.sh"', 60)
        jid = out.strip().split(";")[0].strip().splitlines()[-1] if out.strip() else ""
        if code or not jid.isdigit(): raise RuntimeError("the cluster refused the copy job: " + (out or "no answer")[:200])
        with self.lock:
            rec = {"source": "route:" + rid, "cluster": cid, "path": f"{direction} {src} -> {dst}", "job": jid, "state": "submitted", "dry": bool(dry),
                   "reason": "manual", "started": self.now(), "error": "", "route": rid}
            self.cfg["runs"] = (self.cfg["runs"] + [rec])[-KEEP_RUNS:]; self._save()
        return rec

    def refresh(self):
        """Look at the jobs still going and say how the ones that ended did."""
        with self.lock: open_ = [r for r in self.cfg["runs"] if r["state"] in ("submitted", "running") and r.get("job")]
        with self.lock:                      # a copy this Mac was making when Orbit stopped did not finish: say so rather than leave it running for ever
            for r in self.cfg["runs"]:
                if r.get("via") == "mac" and r["state"] == "running" and not r.get("job") and self.now() - r["started"] > 13 * 3600:
                    r.update(state="failed", error="it did not finish (Orbit was restarted while it ran?)")
        for r in open_:
            try: self._check(r)
            except Exception: pass
        with self.lock: self._save()
        return self.status()

    def _check(self, r):
        cl, jid = self._cl(r["cluster"]), r["job"]
        code, out = cl._ssh(f'squeue -j {jid} -h -o "%T" 2>/dev/null; echo "@@acct"; sacct -j {jid} -X -n -P -o State,ExitCode 2>/dev/null | head -1', 40)
        if code: return
        live = out.split("@@acct")[0].strip()
        if live:
            r["state"] = "running" if live.startswith("RUNNING") else "submitted"; return
        acct = (out.split("@@acct")[1] if "@@acct" in out else "").strip()
        wd = self._workdir(r["cluster"])
        code, log = cl._ssh(f'tail -n 60 "{wd}/logs/"*_{jid}.out 2>/dev/null', 40)
        res = parse_log(log)
        ok = res["rc"] in (0, 24)                 # 24: some files vanished while it ran, which is only to be expected on a busy cluster
        with self.lock:
            r.update(files=res["files"], bytes=res["bytes"], ended=self.now(), state="done" if ok else "failed",
                     error="" if ok else (res["error"] or (f"rsync exited with {res['rc']}" if res["rc"] is not None else f"the job ended: {acct.split('|')[0] or 'unknown'}")),
                     log=log[-1500:])
        if not ok and r.get("reason", "").startswith("schedule") and r.get("source") and not r.get("route"):
            s = next((x for x in self.cfg["sources"] if x["id"] == r["source"]), None)
            if s: self._retry_later(s, r.get("dry"), r["reason"], r.get("error") + " " + (log or "")[-300:])
        if r["job"] not in self._told:
            self._told.add(r["job"])
            what = "would copy" if r["dry"] else "copied"
            kind = "Copy" if r.get("route") else "NAS backup"
            where = r["path"] if r.get("route") else f"{r['cluster']}:{r['path']}"
            if ok: self.notify(kind + (" checked" if r["dry"] else " done"), f"{where} — {what} {r['files'] if r['files'] is not None else '?'} files ({r['bytes'] or '?'})")
            else: self.notify(kind + " failed", f"{where} — {r['error']}")

    def status(self):
        with self.lock:
            cfg = json.loads(json.dumps(self.cfg))
            nxt = None
            if cfg["enabled"] and cfg["sources"]:
                import cluster as CLU
                nxt = CLU.next_refresh(cfg.get("last_start") or 0, cfg["every_h"], cfg["at"], self.now())
            latest = {}
            for r in cfg["runs"]: latest[r["source"]] = r
            return {"config": cfg, "clusters": [{"id": k, "label": c.cfg.get("label") or k} for k, c in self.clusters.items()],
                    "latest": latest, "next": nxt, "now": self.now(), "default_exclude": DEFAULT_EXCLUDE}

    # --- the schedule
    def maybe_run(self):
        c = self.cfg
        if not c["enabled"] or not c["sources"]: return
        try: self._ready(None)
        except ValueError: return
        for sid, rt in list((c.get("retry") or {}).items()):          # what could not be reached last time
            if self.now() >= rt["at"]:
                with self.lock: c["retry"].pop(sid, None)
                if any(s["id"] == sid for s in c["sources"]): self.run(only=sid, dry=rt.get("dry", False), reason="schedule-retry")
        if not c.get("last_start"):
            with self.lock: c["last_start"] = self.now(); self._save()      # the clock starts when it is switched on
            return
        import cluster as CLU
        if self.now() >= CLU.next_refresh(c["last_start"], c["every_h"], c["at"], self.now()):
            self.run(reason="schedule")

    def loop(self, stop=None):
        while not (stop and stop.is_set()):
            try:
                self.maybe_run()
                self.refresh()
            except Exception:
                pass
            time.sleep(60)
