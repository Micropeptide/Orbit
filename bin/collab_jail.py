"""The execution jail: where a command run for a member of a shared project is allowed to touch things.

The permission rules (collab_policy.py) and the guard decide whether a command may run; the jail limits what it can do once it does -- including what
no rule can read in advance (`python x.py`, `bash -c`, a build script). It is the macOS sandbox (`sandbox-exec`) with a profile made for one turn:

  reads    the system, the project folder, this turn's scratch folder, and the places the host lists (the Python it runs with, tool folders);
           NOT the rest of the person's home folder, and never Orbit's own data or the key folders;
  writes   the project folder and this turn's scratch folder only (and /dev/null and the terminal); never a `.git/hooks` or `.git/config` (git would run them later, for the host);
  network  off, unless the member's grant has it;
  programs that drive the machine (osascript, open, security, launchctl, defaults, sudo, screencapture, the clipboard) do not run;
  environment  an allow-list: no tokens, no keys, no agent socket, a private HOME, TMPDIR in the scratch folder, git commits named for the member.

Where the sandbox does not exist, nothing runs: a shell command for a member without a jail is refused, never run without one.
"""
import os, re, shutil, stat, sys, tempfile

SANDBOX = "/usr/bin/sandbox-exec"
BLOCKED_PROGRAMS = ("/usr/bin/osascript", "/usr/bin/open", "/usr/bin/security", "/bin/launchctl", "/usr/bin/defaults", "/usr/bin/sudo", "/usr/bin/su", "/usr/sbin/screencapture",
                    "/usr/bin/screencapture", "/usr/bin/pbcopy", "/usr/bin/pbpaste", "/usr/bin/say", "/usr/sbin/systemsetup", "/usr/bin/dscl", "/usr/sbin/networksetup", "/usr/bin/tccutil",
                    "/usr/bin/sysadminctl", "/usr/sbin/diskutil", "/usr/bin/hdiutil")
KEEP_ENV = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "LC_MESSAGES", "TERM", "USER", "LOGNAME", "TZ", "SHELL", "COLUMNS", "LINES")
KEEP_FIXED = {"CI": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_EDITOR": ":", "EDITOR": ":", "PAGER": "cat", "GIT_PAGER": "cat", "PIP_NO_INPUT": "1", "HOMEBREW_NO_AUTO_UPDATE": "1",
              "DEBIAN_FRONTEND": "noninteractive", "PYTHONDONTWRITEBYTECODE": "1"}


def available(path=SANDBOX):
    return os.path.isfile(path) and os.access(path, os.X_OK)


def q(path):
    """A path as a quoted string in the profile language."""
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"'


def default_read_allow(home):
    """What the host's own tools need under the home folder: the Python this runs with, and the folders its PATH names (their toolchain roots)."""
    out = []
    for p in (sys.prefix, sys.base_prefix, os.path.dirname(os.path.realpath(sys.executable))):
        out.append(os.path.realpath(p))
    for d in (os.environ.get("PATH") or "").split(os.pathsep):
        d = os.path.realpath(d) if d else ""
        if d and d.startswith(home + os.sep):
            out.append(d)
            par = os.path.dirname(d)
            if par != home and par.startswith(home + os.sep): out.append(par)          # a toolchain root (a virtualenv, conda), never the home folder itself
    return [p for i, p in enumerate(out) if p and p not in out[:i]]


class Jail:
    def __init__(self, cwd, *, home=None, allow_network=False, deny_read=(), read_allow=None, author=None, sandbox=SANDBOX):
        self.home = os.path.realpath(os.path.expanduser(home or "~"))
        if not isinstance(cwd, str) or not os.path.isabs(cwd): raise ValueError("the working folder must be an absolute path")
        self.cwd = os.path.realpath(cwd)
        if not os.path.isdir(self.cwd) or self.cwd == os.sep or self.cwd == self.home: raise ValueError("the working folder must be a real folder (not the disk root or the home folder)")
        self.allow_network, self.author, self.sandbox = bool(allow_network), (str(author) if author else None), sandbox
        self.deny_read = [os.path.realpath(p) for p in deny_read]
        self.read_allow = [os.path.realpath(p) for p in (default_read_allow(self.home) if read_allow is None else read_allow)]
        self.tmp = self.profile_path = None

    # ------------------------------------------------------------------------------------------------ the profile
    def profile_text(self):
        t = self.tmp or "/nonexistent-scratch"
        reads = [self.cwd, t] + self.read_allow
        lines = ["(version 1)", "(deny default)", '(import "system.sb")', "(allow process-exec*)", "(allow process-fork)", "(allow signal (target self))", "(allow sysctl-read)",
                 "(allow file-read*)",
                 f"(deny file-read* (subpath {q(self.home)}))",
                 f"(allow file-read* {' '.join('(subpath ' + q(p) + ')' for p in reads)})"]
        if self.deny_read: lines.append(f"(deny file-read* {' '.join('(subpath ' + q(p) + ')' for p in self.deny_read)})")
        lines += [f"(allow file-write* (subpath {q(self.cwd)}) (subpath {q(t)}) (literal \"/dev/null\") (regex #\"^/dev/tty\") (regex #\"^/dev/fd/\"))",
                  '(allow file-write* (regex #"^/(private/)?var/folders/[^/]+/[^/]+/T/xcrun_db"))',      # Apple's developer-tools shim (git, make) keeps one cache file here
                  # git runs hooks and reads core.* settings when the HOST next uses the repository: a member must not be able to leave code there, in this
                  # repository or any nested one (so a member cannot `git init` here either: a repository is made by the host)
                  '(deny file-write* (regex #"/\\.git/hooks(/|$)") (regex #"/\\.git/config$"))',
                  f"(deny process-exec {' '.join('(literal ' + q(p) + ')' for p in BLOCKED_PROGRAMS)})",
                  "(allow network*)" if self.allow_network else "(deny network*)"]
        return "\n".join(l for l in lines if l) + "\n"

    # ------------------------------------------------------------------------------------------------ one turn's life
    def open(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="orbit-jail-")); os.chmod(self.tmp, 0o700)
        os.makedirs(os.path.join(self.tmp, "home"), exist_ok=True)
        fd, self.profile_path = tempfile.mkstemp(prefix="orbit-jail-", suffix=".sb")
        with os.fdopen(fd, "w") as f: f.write(self.profile_text())
        os.chmod(self.profile_path, 0o600)
        return self

    def close(self):
        if self.tmp: shutil.rmtree(self.tmp, ignore_errors=True)
        if self.profile_path:
            try: os.unlink(self.profile_path)
            except OSError: pass
        self.tmp = self.profile_path = None

    def __enter__(self): return self.open()
    def __exit__(self, *a): self.close()

    # ------------------------------------------------------------------------------------------------ running things
    def argv_shell(self, command):
        return [self.sandbox, "-f", self.profile_path, "/bin/sh", "-c", command]

    def argv_exec(self, args):
        return [self.sandbox, "-f", self.profile_path, *args]

    def env(self, base=None):
        """The environment for a jailed command: an allow-list of the base one plus our own values. Nothing that looks like a secret survives."""
        base = os.environ if base is None else base
        e = {k: v for k, v in base.items() if k in KEEP_ENV or k.startswith("LC_")}
        e.update(KEEP_FIXED)
        e["HOME"] = os.path.join(self.tmp, "home"); e["TMPDIR"] = self.tmp + "/"
        if self.author:
            slug = re.sub(r"[^a-z0-9]+", "-", self.author.lower()).strip("-") or "member"
            e.update(GIT_AUTHOR_NAME=self.author, GIT_COMMITTER_NAME=self.author, GIT_AUTHOR_EMAIL=f"{slug}@shared.orbit.invalid", GIT_COMMITTER_EMAIL=f"{slug}@shared.orbit.invalid")
        return e
