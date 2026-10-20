"""Google's two agents, as chats signed in with your Google account: Antigravity (`agy`) and the
Gemini CLI. Stand-in programs answer, so nothing here needs either installed or signed in."""
import json, os, shutil, stat, sys, tempfile, textwrap, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))

import providers as P

FAKE = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json, sys
    a = sys.argv[1:]
    if a[:1] == ["models"]:
        print(json.dumps([{"slug": "gemini-3.8-flash", "displayName": "Gemini 3.8 Flash"},
                          {"slug": "gemini-4-argon", "displayName": "Gemini 4 Argon"}]))
        sys.exit(0)
    # the prompt is whatever follows -p; flags must all come before it
    i = a.index("-p")
    print("flags=" + " ".join(a[:i]) + " | prompt=" + " ".join(a[i + 1:]).splitlines()[0])
    print("second line")
''')


class Fake(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orbit-gcli-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.exe = os.path.join(self.tmp, "fake")
        open(self.exe, "w").write(FAKE)
        os.chmod(self.exe, os.stat(self.exe).st_mode | stat.S_IXUSR)
        saved = (P.which, dict(P._AGY))
        P.which = lambda name: self.exe if name in ("agy", "gemini") else None
        P._AGY.update(at=0.0, rows=[])
        def restore():
            P.which = saved[0]; P._AGY.clear(); P._AGY.update(saved[1])
        self.addCleanup(restore)

    def ask(self, backend, model, text="hello"):
        return P.cli_stream(backend, model, [{"role": "user", "content": text}], cwd=self.tmp)


class TestAntigravity(Fake):
    def test_models_come_from_the_cli_itself(self):
        self.assertEqual(P.agy_models(), [("gemini-3.8-flash", "Gemini 3.8 Flash"), ("gemini-4-argon", "Gemini 4 Argon")])

    def test_they_are_in_the_model_list_as_chats_on_your_google_login(self):
        rows = [m for m in P.cli_models() if m["provider"] == "agy-cli"]
        by = {m["model"]: m for m in rows}
        self.assertIn("gemini-3.8-flash", by)
        self.assertEqual(by["gemini-3.8-flash"]["kind"], "cli")
        self.assertIn("Antigravity", by["gemini-3.8-flash"]["label"])
        self.assertIn("default", by)                                   # and its own default

    def test_the_model_flag_comes_before_the_flag_that_takes_the_prompt(self):
        out = self.ask("agy-cli", "gemini-3.8-flash", "what is 2+2")
        self.assertIn("flags=--model gemini-3.8-flash | prompt=User: what is 2+2", out["content"])
        self.assertIn("second line", out["content"])                  # plain text, all of it, trimmed
        self.assertFalse(out["content"].endswith("\n"))

    def test_the_default_model_passes_no_flag(self):
        self.assertIn("flags= | prompt=User: hello", self.ask("agy-cli", "default")["content"])

    def test_not_installed_means_not_listed(self):
        P.which = lambda name: None
        P._AGY.update(at=0.0, rows=[])
        self.assertEqual([m for m in P.cli_models() if m["provider"] in ("agy-cli", "gemini-cli")], [])

    def test_an_unreadable_model_list_is_just_the_default(self):
        bad = os.path.join(self.tmp, "bad")
        open(bad, "w").write("#!/bin/sh\necho not json\n")
        os.chmod(bad, 0o755)
        P.which = lambda name: bad if name == "agy" else None
        self.assertEqual(P.agy_models(), [])
        self.assertEqual([m["model"] for m in P.cli_models() if m["provider"] == "agy-cli"], ["default"])


class TestGeminiCli(Fake):
    def test_its_models_and_the_flag_order(self):
        ms = [m["model"] for m in P.cli_models() if m["provider"] == "gemini-cli"]
        self.assertIn("gemini-3.8-flash", ms)
        out = self.ask("gemini-cli", "gemini-2.5-pro")
        self.assertIn("flags=-m gemini-2.5-pro | prompt=User: hello", out["content"])


if __name__ == "__main__":
    unittest.main()


class TestSigningIn(Fake):
    """Settings offers each Google agent's install and sign-in command, for Orbit's terminal."""
    def row(self, cid):
        return next(r for r in P.google_cli_status(fresh=True) if r["id"] == cid)

    def test_installed_and_signed_in_when_it_lists_models(self):
        r = self.row("agy-cli")
        self.assertEqual((r["installed"], r["signed_in"], r["models"]), (True, True, 2))
        self.assertEqual(r["login"], "agy")

    def test_installed_but_not_signed_in_lists_nothing(self):
        bad = os.path.join(self.tmp, "bad")
        open(bad, "w").write("#!/bin/sh\necho 'please sign in' >&2\nexit 1\n")
        os.chmod(bad, 0o755)
        P.which = lambda name: bad if name == "agy" else None
        r = self.row("agy-cli")
        self.assertEqual((r["installed"], r["signed_in"], r["models"]), (True, False, 0))

    def test_not_installed_says_how(self):
        P.which = lambda name: None
        r = self.row("agy-cli")
        self.assertEqual((r["installed"], r["signed_in"]), (False, None))
        self.assertIn("antigravity.google/cli/install.sh", r["install"])
        self.assertIn("gemini-cli", self.row("gemini-cli")["install"])
