"""Terminals: a shell in a chat's folder, read as a stream and typed into from the page.
Who may open one is the part that matters most -- a terminal is a shell on this Mac --
so most of this checks the gate: you at the Mac yes, a paired device only when Settings
allows it, and never one limited to chats. The shells here run `sh` in a temporary folder.
"""
import importlib.machinery, importlib.util, json, os, shutil, sys, tempfile, time, types, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "bin"))

import term as TERM


def load_ui():
    loader = importlib.machinery.SourceFileLoader("orbit_ui_term", os.path.join(ROOT, "bin", "orbit-ui"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def read_until(t, want, secs=8):
    out, off, end = b"", 0, time.time() + secs
    while time.time() < end:
        data, off, alive = t.read(off, 0.5)
        out += data
        if want in out or not alive: break
    return out


class TestTheShell(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orbit-term-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        os.environ["SHELL_SAVED"] = os.environ.get("SHELL", "")
        os.environ["SHELL"] = "/bin/sh"              # quick to start, no profile of yours
        self.addCleanup(lambda: os.environ.__setitem__("SHELL", os.environ.pop("SHELL_SAVED")))

    def test_it_runs_in_the_folder_and_reports_its_exit(self):
        t = TERM.open_term(self.tmp, 80, 24)
        self.addCleanup(TERM.close_term, t.id)
        t.write("pwd; exit 4\n")
        out = read_until(t, b"\x00never")
        self.assertIn(os.path.basename(self.tmp).encode(), out)
        for _ in range(50):
            if not t.alive: break
            time.sleep(0.05)
        self.assertEqual((t.alive, t.code), (False, 4))

    def test_a_page_that_comes_back_reads_from_where_it_was(self):
        t = TERM.open_term(self.tmp, 80, 24)
        self.addCleanup(TERM.close_term, t.id)
        t.write("echo first-$((1+1))\n")
        read_until(t, b"first-2")
        _, mark, _ = t.read(0, 0)
        t.write("echo second-$((2+1))\n")
        later = read_until_from(t, mark, b"second-3")
        self.assertIn(b"second-3", later)
        self.assertNotIn(b"first-2\r", later)

    def test_resize_reaches_the_shell(self):
        t = TERM.open_term(self.tmp, 80, 24)
        self.addCleanup(TERM.close_term, t.id)
        t.resize(123, 40)
        t.write("stty size\n")
        self.assertIn(b"40 123", read_until(t, b"40 123"))

    def test_there_is_a_limit(self):
        self.addCleanup(lambda: [TERM.close_term(i) for i in list(TERM.TERMS)])
        for _ in range(TERM.MAX_TERMS - len(TERM.TERMS)):
            TERM.open_term(self.tmp)
        with self.assertRaises(RuntimeError):
            TERM.open_term(self.tmp)


def read_until_from(t, off, want, secs=8):
    out, end = b"", time.time() + secs
    while time.time() < end:
        data, off, alive = t.read(off, 0.5)
        out += data
        if want in out or not alive: break
    return out


class TestWhoMayOpenOne(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = load_ui()
        cls.ui.start_turn = lambda *a, **k: None

    def patch(self, obj, name, value):
        old = getattr(obj, name); setattr(obj, name, value); self.addCleanup(setattr, obj, name, old)

    def setUp(self):
        self.opened = []
        def fake_open(cwd, cols=100, rows=30, host="", sid=None):
            self.opened.append((cwd, host))
            return types.SimpleNamespace(view=lambda: {"id": "t1", "cwd": cwd})
        self.patch(self.ui.TERM, "open_term", fake_open)

    def call(self, path, body=None, loopback=True, setting=False, method="POST"):
        ui, out = self.ui, types.SimpleNamespace(code=None, body=None)
        self.patch(ui.q, "S", dict(ui.q.S, terminal_remote=setting))
        class Fake(ui.H):
            def __init__(self): self.path = path; self.headers = {}; self.command = method
            def _from_loopback(self): return loopback
            def _body(self): return body or {}
            def _send(self, code, b, ctype="application/json", headers=None):
                out.code, out.body = code, json.loads(b)
        f = Fake()
        (f._post if method == "POST" else f._get)(path)
        return out

    def test_you_at_the_mac_get_one(self):
        r = self.call("/api/term/open", {"cwd": tempfile.gettempdir()})
        self.assertEqual(r.code, 200)
        self.assertEqual(len(self.opened), 1)

    def test_a_paired_device_does_not_unless_settings_say_so(self):
        r = self.call("/api/term/open", {}, loopback=False)
        self.assertEqual(r.code, 403)
        self.assertEqual(self.opened, [])
        self.assertEqual(self.call("/api/term/list", loopback=False, method="GET").code, 403)
        r = self.call("/api/term/open", {"cwd": tempfile.gettempdir()}, loopback=False, setting=True)
        self.assertEqual(r.code, 200)

    def test_a_device_limited_to_chats_never_does(self):
        self.assertTrue(any("/api/term/open".startswith(p) for p in self.ui.H.ADMIN_PREFIXES))

    def test_a_folder_that_is_not_there_is_refused(self):
        r = self.call("/api/term/open", {"cwd": "/no/such/folder/anywhere"})
        self.assertEqual(r.code, 400)
        self.assertEqual(self.opened, [])

    def test_input_is_text_and_bounded(self):
        self.patch(self.ui.TERM, "get", lambda tid: types.SimpleNamespace(write=lambda d: True))
        self.assertEqual(self.call("/api/term/input", {"id": "t1", "data": 5}).code, 400)
        self.assertEqual(self.call("/api/term/input", {"id": "t1", "data": "x" * 70000}).code, 400)
        self.assertEqual(self.call("/api/term/input", {"id": "t1", "data": "ls\n"}).code, 200)


if __name__ == "__main__":
    unittest.main()
