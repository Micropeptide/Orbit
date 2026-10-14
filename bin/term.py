"""Terminals in a chat's folder: a login shell on a pseudo-terminal that the page reads
as a stream and types into. They outlive the page -- reload, or open Orbit in another
window, and the same shell is there with what it printed -- and end with the server.

Only you at the Mac get one unless Settings says otherwise (see orbit-ui); this module
does not check, it only runs them.
"""
import atexit, fcntl, os, pty, shlex, signal, struct, termios, threading, time, uuid, warnings

KEEP = 512 * 1024         # what a page that comes back can still read, per terminal
MAX_TERMS = 8

TERMS = {}
_LOCK = threading.Lock()


def _shell():
    sh = os.environ.get("SHELL") or "/bin/zsh"
    return sh if os.path.exists(sh) else "/bin/sh"


class Term:
    def __init__(self, cwd, cols=100, rows=30, host="", sid=None, title=None):
        self.id = uuid.uuid4().hex[:12]
        self.cwd, self.host, self.sid = cwd, host or "", sid
        self.title = title or (f"{host}:{os.path.basename(cwd.rstrip('/')) or cwd}" if host
                               else os.path.basename(cwd.rstrip("/")) or cwd)
        self.started = time.time()
        self.buf = bytearray()
        self.total = 0              # bytes ever printed; offsets the page reads from count these
        self.alive = True
        self.code = None
        self.cond = threading.Condition()
        sh = _shell()
        if host:
            argv = ["/usr/bin/ssh", "-t", host, f"cd {shlex.quote(cwd)} 2>/dev/null; exec $SHELL -l"]
        else:
            argv = [sh, "-l"]
        env = dict(os.environ, TERM="xterm-256color", COLORTERM="truecolor", ORBIT_TERMINAL="1")
        env.pop("ORBIT_UI_PORT", None)
        start_in = cwd if (not host and os.path.isdir(cwd)) else os.path.expanduser("~")
        # everything the child needs is worked out here: after the fork it only changes
        # folder and execs (the server has threads, so the child must not do more)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            pid, fd = pty.fork()
        if pid == 0:
            try:
                os.chdir(start_in)
                os.execve(argv[0], argv, env)
            finally:
                os._exit(127)
        self.pid, self.fd = pid, fd
        self.resize(cols, rows)
        threading.Thread(target=self._pump, daemon=True, name=f"term-{self.id}").start()

    def _pump(self):
        while True:
            try:
                chunk = os.read(self.fd, 65536)
            except OSError:
                chunk = b""
            if not chunk:
                break
            with self.cond:
                self.buf += chunk
                self.total += len(chunk)
                if len(self.buf) > KEEP:
                    del self.buf[:len(self.buf) - KEEP]
                self.cond.notify_all()
        try:
            _, status = os.waitpid(self.pid, 0)
            self.code = os.waitstatus_to_exitcode(status)
        except Exception:
            self.code = None
        try: os.close(self.fd)
        except OSError: pass
        with self.cond:
            self.alive = False
            self.cond.notify_all()

    def read(self, since, timeout=15.0):
        """(bytes printed after offset `since`, the offset to ask from next, still running).
        Waits up to `timeout` for something new. A page that fell further behind than what
        is kept gets what is kept."""
        with self.cond:
            if self.total <= since and self.alive:
                self.cond.wait(timeout)
            start = max(since, self.total - len(self.buf))
            data = bytes(self.buf[len(self.buf) - (self.total - start):]) if self.total > start else b""
            return data, self.total, self.alive

    def write(self, data):
        if not self.alive: return False
        if isinstance(data, str): data = data.encode("utf-8", "replace")
        view = memoryview(data)
        while view:
            try:
                n = os.write(self.fd, view)
            except BlockingIOError:
                time.sleep(0.01); continue
            except OSError:
                return False
            view = view[n:]
        return True

    def resize(self, cols, rows):
        cols = max(10, min(int(cols or 100), 500)); rows = max(3, min(int(rows or 30), 300))
        try:
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except OSError:
            pass

    def close(self):
        if self.alive:
            for sig in (signal.SIGHUP, signal.SIGTERM):
                try: os.killpg(os.getpgid(self.pid), sig)
                except Exception:
                    try: os.kill(self.pid, sig)
                    except Exception: pass
                time.sleep(0.15)
                if not self.alive: break

    def view(self):
        return {"id": self.id, "title": self.title, "cwd": self.cwd, "host": self.host, "sid": self.sid,
                "alive": self.alive, "code": self.code, "started": self.started}


def open_term(cwd, cols=100, rows=30, host="", sid=None):
    with _LOCK:
        for t in [t for t in TERMS.values() if not t.alive]:
            TERMS.pop(t.id, None)              # ended ones make room
        if len(TERMS) >= MAX_TERMS:
            raise RuntimeError(f"{MAX_TERMS} terminals are open — close one first")
        t = Term(cwd, cols, rows, host=host, sid=sid)
        TERMS[t.id] = t
        return t


def get(tid):
    return TERMS.get(tid or "")


def close_term(tid):
    t = TERMS.pop(tid or "", None)
    if t: t.close()
    return t is not None


def listing():
    return [t.view() for t in sorted(TERMS.values(), key=lambda t: t.started)]


@atexit.register
def _close_all():
    for t in list(TERMS.values()):
        try: t.close()
        except Exception: pass
