"""Orbit says it runs on Python 3.9 and newer. The dev machine runs a newer one, where syntax that older Pythons
cannot read (a quote reused inside an f-string, `match`, `except*`) goes unnoticed -- until someone with Apple's
Python 3.9 opens the Mac app and the server will not start. This parses every Python file Orbit ships with an
older interpreter when the machine has one."""
import glob, os, shutil, subprocess, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CANDIDATES = ("/usr/bin/python3", "/usr/local/bin/python3.9", "/usr/local/bin/python3.10", "/usr/local/bin/python3.11",
              "/opt/homebrew/bin/python3.9", "/opt/homebrew/bin/python3.10", "/opt/homebrew/bin/python3.11")
PARSE = "import ast,sys\nfor p in sys.argv[1:]:\n    ast.parse(open(p, encoding='utf-8').read(), p)\n"


def older_pythons():
    out = []
    for exe in CANDIDATES:
        if not os.path.exists(exe): continue
        try:
            v = subprocess.run([exe, "-c", "import sys;print('%d.%d' % sys.version_info[:2])"], capture_output=True, text=True,
                               timeout=20, stdin=subprocess.DEVNULL).stdout.strip()
        except Exception:
            continue
        if v and tuple(int(x) for x in v.split(".")) < (3, 12): out.append((exe, v))
    return out


def python_files():
    files = glob.glob(os.path.join(ROOT, "bin", "*.py")) + glob.glob(os.path.join(ROOT, "tests", "*.py"))
    for name in os.listdir(os.path.join(ROOT, "bin")):                  # the extension-less launchers that are Python
        p = os.path.join(ROOT, "bin", name)
        if os.path.isfile(p) and "." not in name:
            with open(p, "rb") as f:
                if b"python" in f.readline(): files.append(p)
    return sorted(files)


class OlderPython(unittest.TestCase):
    def test_everything_parses_on_the_oldest_python_here(self):
        olds = older_pythons()
        if not olds: self.skipTest("no Python older than 3.12 on this machine")
        files = python_files()
        self.assertGreater(len(files), 20)
        for exe, v in olds:
            r = subprocess.run([exe, "-c", PARSE, *files], capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
            self.assertEqual(r.returncode, 0, f"Python {v} cannot read Orbit:\n{r.stderr[-600:]}")


if __name__ == "__main__":
    unittest.main()
