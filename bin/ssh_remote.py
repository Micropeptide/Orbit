"""Claude Code chats that run on another machine over SSH (a cluster's login node, a
lab server), as Claude Code's own SSH sessions do.

Each answer runs `claude` on the host, in the chat's folder there, with its
stream-json talking to Orbit through the SSH connection -- so it edits files and
runs commands where they live, and Orbit shows and approves everything as for a
local chat. Its models come from this Mac: an SSH reverse tunnel reaches Orbit's
gateway (which needs Orbit's token -- a shared login node has other users), so
provider keys never leave the Mac. Your Claude subscription token, when a chat uses
it, goes over the connection's input, never on a command line other users could
see in `ps`.

Login nodes have per-user process limits, and processes left behind pile up until
the node refuses new shells. So on the host `claude` runs in its own process group
under a small watchdog: when the SSH connection goes away -- Orbit stopped the
answer, or the network dropped -- the whole group is ended. Nothing stays behind.

Quick requests (checking a host, listing a folder) share one SSH connection
(ControlMaster), so a busy chat does not open dozens of connections -- clusters
block addresses that do.
"""
import base64, json, os, random, re, shlex, subprocess, threading, time

HOME = os.path.expanduser("~")
SSH_CONFIG = os.path.join(HOME, ".ssh", "config")
_PROBES = {}
_LOCK = threading.Lock()


def _control_path():
    d = os.path.join(HOME, ".ssh")
    return os.path.join(d, "cm-orbit-%C")


def base_opts(shared=True):
    opts = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=25",
            "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=4"]
    if shared:
        opts += ["-o", "ControlMaster=auto", "-o", f"ControlPath={_control_path()}", "-o", "ControlPersist=600"]
    else:
        opts += ["-o", "ControlMaster=no", "-o", "ControlPath=none"]
    return opts


def config_hosts():
    """Host names from ~/.ssh/config (not patterns), in file order."""
    out = []
    try:
        for line in open(SSH_CONFIG, encoding="utf-8", errors="replace"):
            m = re.match(r"^\s*Host\s+(.+)$", line, re.I)
            if not m: continue
            for h in m.group(1).split():
                if any(c in h for c in "*?!") or h in out: continue
                out.append(h)
    except OSError:
        pass
    return out


def valid_host(host):
    return bool(re.fullmatch(r"[A-Za-z0-9._@-]{1,120}", str(host or "")))


def run(host, script, timeout=60, shared=True):
    """Run a bash script on the host (sent on standard input). (rc, stdout, stderr)"""
    if not valid_host(host): return 2, "", "not a host name"
    argv = ["ssh", *base_opts(shared), host, "bash -s"]
    try:
        r = subprocess.run(argv, input=script, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"no answer from {host} within {timeout}s"
    except OSError as e:
        return 127, "", str(e)


_PROBE = r'''
emit() { printf '%s=%s\n' "$1" "$2"; }
emit hostname "$(hostname)"
emit home "$HOME"
emit os "$(uname -sm)"
best=""; bestv=""
for c in "$(command -v claude 2>/dev/null)" "$HOME/.local/bin/claude" $(ls -1d "$HOME"/.claude/remote/ccd-cli/* 2>/dev/null); do
  [ -n "$c" ] && [ -f "$c" ] && [ -x "$c" ] || continue
  v=$("$c" --version 2>/dev/null | head -1 | awk '{print $1}')
  [ -n "$v" ] || continue
  emit candidate "$c $v"
  if [ -z "$bestv" ] || [ "$(printf '%s\n%s\n' "$bestv" "$v" | sort -V | tail -1)" = "$v" ]; then best="$c"; bestv="$v"; fi
done
emit claude "$best"
emit claude_version "$bestv"
if [ -n "$best" ]; then emit logged_in "$("$best" auth status 2>/dev/null | grep -o '"loggedIn": *[a-z]*' | grep -o '[a-z]*$')"; fi
emit procs "$(ps -u "$(id -un)" --no-headers 2>/dev/null | wc -l | tr -d ' ')"
emit proc_limit "$(ulimit -u)"
emit setsid "$(command -v setsid)"
emit base64 "$(command -v base64)"
'''


def probe(host, max_age=300, refresh=False):
    """What the host offers: its name, the newest `claude` on it (on PATH, in
    ~/.local/bin, or the copies Claude's desktop app keeps), whether that is signed
    in, and how close you are to the process limit."""
    now = time.time()
    hit = _PROBES.get(host)
    if hit and not refresh and now - hit["at"] < max_age: return hit
    t0 = time.time()
    rc, out, err = run(host, _PROBE, timeout=60)
    info = {"host": host, "at": now, "ok": rc == 0, "secs": round(time.time() - t0, 1), "candidates": []}
    for line in out.splitlines():
        k, _, v = line.partition("=")
        if k == "candidate": info["candidates"].append(v)
        elif k: info[k] = v
    if rc != 0:
        tail = [l for l in (err or "").strip().splitlines() if l.strip()]
        info["error"] = (tail[-1] if tail else f"ssh exited {rc}")[:300]
    for k in ("procs", "proc_limit"):
        try: info[k] = int(info.get(k) or 0)
        except ValueError: info[k] = 0
    info["logged_in"] = info.get("logged_in") == "true"
    _PROBES[host] = info
    return info


def list_dir(host, path):
    """Folders (and a few files) in a folder on the host, for choosing where a chat works."""
    script = ('p=' + shlex.quote(path or "~") + '\n'
              'case "$p" in "~"|"~/"*) p="$HOME${p#\\~}";; esac\n'
              'cd "$p" 2>/dev/null || { echo "ERR=no such folder: $p"; exit 0; }\n'
              'echo "PWD=$(pwd)"\n'
              'ls -1pA 2>/dev/null | head -400\n')
    rc, out, err = run(host, script, timeout=45)
    if rc != 0: return {"error": (err.strip().splitlines() or [f"ssh exited {rc}"])[-1][:300]}
    lines = out.splitlines()
    res = {"path": "", "dirs": [], "files": []}
    for l in lines:
        if l.startswith("ERR="): return {"error": l[4:]}
        if l.startswith("PWD="): res["path"] = l[4:]; continue
        if l.endswith("/"): res["dirs"].append(l[:-1])
        elif l: res["files"].append(l)
    return res


# The remote side of one answer. Its first input line carries the environment
# (base64, so tokens never appear in the command line); the rest is Claude Code's
# stream-json. `claude` runs in its own session and process group; a watchdog ends
# that group when this shell loses its SSH connection (its parent changes), and the
# group also ends when `claude` does.
WRAPPER = r'''
IFS= read -r ORBIT_ENV_LINE || exit 90
eval "$(printf '%s' "$ORBIT_ENV_LINE" | base64 -d)"
unset ORBIT_ENV_LINE
case "$ORBIT_CWD" in "~"|"~/"*) ORBIT_CWD="$HOME${ORBIT_CWD#\~}";; esac
mkdir -p "$ORBIT_CWD" 2>/dev/null
cd "$ORBIT_CWD" 2>/dev/null || { echo "orbit: no such folder on $(hostname): $ORBIT_CWD" >&2; exit 91; }
[ -x "$ORBIT_CLAUDE" ] || { echo "orbit: Claude Code not found on $(hostname) at $ORBIT_CLAUDE" >&2; exit 92; }
exec 3<&0
if command -v setsid >/dev/null 2>&1; then setsid "$ORBIT_CLAUDE" "$@" <&3 &
elif command -v perl >/dev/null 2>&1; then perl -e 'setpgrp(0,0); exec @ARGV' "$ORBIT_CLAUDE" "$@" <&3 &
else "$ORBIT_CLAUDE" "$@" <&3 & fi
c=$!
exec 3<&-
sp=$(ps -o ppid= -p $$ 2>/dev/null | tr -d ' ')
(
  while kill -0 "$c" 2>/dev/null; do
    np=$(ps -o ppid= -p $$ 2>/dev/null | tr -d ' ')
    if [ "$np" != "$sp" ]; then
      kill -TERM -- "-$c" 2>/dev/null || kill -TERM "$c" 2>/dev/null
      sleep 5
      kill -KILL -- "-$c" 2>/dev/null
      exit 0
    fi
    sleep 5
  done
) </dev/null >/dev/null 2>&1 &
w=$!
wait "$c"; rc=$?
kill -TERM -- "-$c" 2>/dev/null
kill "$w" 2>/dev/null
exit $rc
'''


def env_line(env):
    """One line for the wrapper: `export K='v'` statements, base64-encoded."""
    body = "\n".join(f"export {k}={shlex.quote(str(v))}" for k, v in env.items()
                     if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k))
    return base64.b64encode(body.encode()).decode() + "\n"


def pick_port():
    return random.randint(30000, 59999)


def popen(host, claude_path, cwd, claude_args, env, forward=None):
    """Start `claude` on the host. forward=(remote_port, local_port) opens a reverse
    tunnel to this Mac for the answer's model requests. Returns the Popen; the
    environment line is already written to its input."""
    if not valid_host(host): raise ValueError(f"not a host name: {host}")
    opts = base_opts(shared=False) + ["-T", "-o", "ExitOnForwardFailure=yes"]
    if forward:
        opts += ["-R", f"{int(forward[0])}:127.0.0.1:{int(forward[1])}"]
    remote = "exec bash -c " + shlex.quote(WRAPPER) + " orbit " + " ".join(shlex.quote(a) for a in claude_args)
    proc = subprocess.Popen(["ssh", *opts, host, remote], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, start_new_session=True)
    full = {"ORBIT_CLAUDE": claude_path, "ORBIT_CWD": cwd or "~", **env}
    try:
        proc.stdin.write(env_line(full).encode()); proc.stdin.flush()
    except (BrokenPipeError, OSError):
        pass
    return proc


# environment a remote Claude Code needs from Orbit's (the rest is the host's own)
FORWARD_ENV_PREFIXES = ("ANTHROPIC_", "CLAUDE_CODE_", "DISABLE_", "MCP_TOOL_TIMEOUT", "BASH_DEFAULT_TIMEOUT_MS")


def remote_env(env):
    return {k: v for k, v in env.items() if k.startswith(FORWARD_ENV_PREFIXES)
            and k not in ("CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_EXECPATH")}


def fetch_transcript(host, cwd, session, since=0.0):
    """A Claude session's transcript on the host, if it changed after `since` (its
    modification time there). Returns (mtime, text or None), or (None, None)."""
    if not re.fullmatch(r"[0-9a-fA-F-]{8,64}", str(session or "")): return None, None
    script = ('c=' + shlex.quote(cwd or "~") + '\n'
              'case "$c" in "~"|"~/"*) c="$HOME${c#\\~}";; esac\n'
              'cd "$c" 2>/dev/null || exit 0\n'
              'enc=$(pwd | sed "s/[^A-Za-z0-9]/-/g")\n'
              'f="$HOME/.claude/projects/$enc/' + session + '.jsonl"\n'
              '[ -f "$f" ] || exit 0\n'
              'm=$(stat -c %Y "$f" 2>/dev/null || stat -f %m "$f")\n'
              'echo "META=$m"\n'
              'if [ "$m" -gt ' + str(int(since or 0)) + ' ]; then cat "$f"; fi\n')
    rc, out, err = run(host, script, timeout=120)
    if rc != 0 or not out.startswith("META="): return None, None
    head, _, body = out.partition("\n")
    try: mtime = float(head[5:])
    except ValueError: return None, None
    return mtime, (body if body.strip() else None)
