"""Antigravity in a chat: a headless run cannot ask, so the chat's autonomy decides what it may do,
and a refusal is said out loud instead of being left for the model to guess around.

REGRESSION: "How do you think of BlotScribe here: <folder>" -- Antigravity ran `ls` on the folder, its
permission check refused (nobody to ask), and the answer was written about the project's name alone,
with nothing in the chat to say the folder had never been read."""
import json, os, shutil, stat, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))

import qqcore as q          # noqa: F401,E402
import providers as P       # noqa: E402


class TestFlags(unittest.TestCase):
    def test_each_autonomy_maps_to_what_antigravity_can_do_headless(self):
        self.assertEqual(P.agy_permission_flags("ask"), [])
        self.assertEqual(P.agy_permission_flags(None), [])
        self.assertEqual(P.agy_permission_flags("auto"), ["--mode", "auto", "--dangerously-skip-permissions"])
        self.assertEqual(P.agy_permission_flags("full"), ["--dangerously-skip-permissions"])

    def test_plan_mode_only_reads_whatever_the_autonomy(self):
        for a in ("ask", "auto", "full"):
            self.assertEqual(P.agy_permission_flags(a, read_only=True), ["--mode", "plan"])


REFUSED = {"event": "step_update", "step_update": {
    "state": "ERROR", "step_type": "tool", "tool_name": "run_command",
    "tool_info": {"name": "run_command", "parameters": {"CommandLine": "ls -la /Users/x/blotscribe"},
                  "error": {"type": "TOOL_ERROR", "message": 'permission check failed for unsandboxed "ls": user denied permission to run command'}}}}


class TestDenials(unittest.TestCase):
    def test_a_refused_command_is_recognised(self):
        self.assertEqual(P.agy_denials(REFUSED), ["ls -la /Users/x/blotscribe"])

    def test_other_events_and_other_errors_are_not(self):
        self.assertEqual(P.agy_denials({"event": "result", "result": {}}), [])
        other = json.loads(json.dumps(REFUSED))
        other["step_update"]["tool_info"]["error"]["message"] = "no such file"
        self.assertEqual(P.agy_denials(other), [])
        ok = json.loads(json.dumps(REFUSED)); ok["step_update"]["state"] = "DONE"
        self.assertEqual(P.agy_denials(ok), [])


FAKE_AGY = r"""#!%(py)s
import json, os, sys
open(os.environ["FAKE_AGY_LOG"], "a").write(json.dumps(sys.argv[1:]) + "\n")
def out(o): print(json.dumps(o), flush=True)
out({"event": "init", "conversation_id": "c1", "init": {}})
if os.environ.get("FAKE_AGY_DENY") and "--dangerously-skip-permissions" not in sys.argv:
    out(%(refused)s)
    out({"event": "result", "result": {"status": "SUCCESS", "response": "Without reading it: probably a blot tool.", "denied_actions": [{"action": "command"}]}})
else:
    out({"event": "result", "result": {"status": "SUCCESS", "response": "Read the folder: it is a blot tool."}})
"""


class TestRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orbit-agy-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.log = os.path.join(self.tmp, "argv.log")
        exe = os.path.join(self.tmp, "agy")
        with open(exe, "w") as f: f.write(FAKE_AGY % {"py": sys.executable, "refused": repr(REFUSED)})
        os.chmod(exe, os.stat(exe).st_mode | stat.S_IXUSR)
        for p in (mock.patch.object(P, "which", lambda name: exe if name == "agy" else None),
                  mock.patch.dict(os.environ, {"FAKE_AGY_LOG": self.log, "FAKE_AGY_DENY": "1"})):
            p.start(); self.addCleanup(p.stop)

    def argv(self):
        return json.loads(open(self.log).read().splitlines()[-1])

    def ask(self, **kw):
        seen = []
        out = P.cli_stream("agy-cli", "default", [{"role": "user", "content": "how do you think of the project in /Users/x/blotscribe"}],
                           cwd=self.tmp, emit=lambda k, p: seen.append((k, p)), **kw)
        return out, seen

    def test_ask_mode_reports_the_refusal_in_the_chat(self):
        out, seen = self.ask(autonomy="ask")
        notes = [p for k, p in seen if k == "notice"]
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["kind"], "permission")
        self.assertIn("ls -la /Users/x/blotscribe", notes[0]["msg"])
        self.assertIn("autonomy", notes[0]["msg"])
        self.assertIn("guess", notes[0]["msg"])
        self.assertEqual(out["denied"], ["ls -la /Users/x/blotscribe"])
        self.assertNotIn("--dangerously-skip-permissions", self.argv())

    def test_auto_mode_lets_it_read_the_folder(self):
        out, seen = self.ask(autonomy="auto")
        self.assertEqual(out["content"], "Read the folder: it is a blot tool.")
        self.assertFalse([1 for k, p in seen if k == "notice"])
        argv = self.argv()
        self.assertEqual(argv[argv.index("--mode") + 1], "auto")
        self.assertIn("--dangerously-skip-permissions", argv)
        self.assertEqual(argv[-2], "-p")                                   # every flag still comes before the prompt

    def test_plan_mode_is_read_only_and_says_so_when_refused(self):
        with mock.patch.dict(os.environ, {"FAKE_AGY_DENY": "1"}):
            out, seen = self.ask(autonomy="full", read_only=True)
        argv = self.argv()
        self.assertEqual(argv[argv.index("--mode") + 1], "plan")
        self.assertNotIn("--dangerously-skip-permissions", argv)
        self.assertIn("Plan mode", [p for k, p in seen if k == "notice"][0]["msg"])


if __name__ == "__main__":
    unittest.main()
