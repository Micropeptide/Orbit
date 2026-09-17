"""Codex and OpenCode conversations in Orbit (bin/agent_sessions.py), and continuing
them through the agents' own CLIs (providers.cli_stream) -- with made-up histories
and a stand-in CLI, never the real ones."""
import json, os, shutil, sqlite3, stat, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin"))
import agent_sessions as A            # noqa: E402
import providers as P                 # noqa: E402


class TestAgentSessions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orbit-agents-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.saved = (A.CODEX_DIR, A.OPENCODE_DB, A._SCRATCH)
        A._SCRATCH = ()                        # this test's own folders are temporary ones
        A.CODEX_DIR = os.path.join(self.tmp, "codex", "sessions")
        A.OPENCODE_DB = os.path.join(self.tmp, "opencode.db")
        A._CACHE["codex"].clear(); A._CACHE["opencode"].update(key=None, rows=[])
        self.addCleanup(self.restore)
        self.work = os.path.join(self.tmp, "project"); os.makedirs(self.work)

    def restore(self):
        A.CODEX_DIR, A.OPENCODE_DB, A._SCRATCH = self.saved
        A._CACHE["codex"].clear(); A._CACHE["opencode"].update(key=None, rows=[])

    def codex_session(self, sid="019-abc", cwd=None):
        d = os.path.join(A.CODEX_DIR, "2026", "09", "16"); os.makedirs(d, exist_ok=True)
        rows = [
            {"type": "session_meta", "payload": {"id": sid, "cwd": cwd or self.work, "originator": "codex_cli"}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": "<environment_context>cwd</environment_context>"}]}},
            {"type": "turn_context", "payload": {"model": "gpt-5.6-sol"}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": "List the files"}]}},
            {"type": "response_item", "payload": {"type": "function_call", "name": "shell", "call_id": "c1",
                                                  "arguments": "{\"command\": [\"ls\"]}"}},
            {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1",
                                                  "output": [{"type": "input_text", "text": "a.txt"}]}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [
                {"type": "output_text", "text": "There is a.txt."}]}},
        ]
        with open(os.path.join(d, f"rollout-2026-09-16-{sid}.jsonl"), "w") as fh:
            for r in rows: fh.write(json.dumps(r) + "\n")

    def opencode_db(self):
        con = sqlite3.connect(A.OPENCODE_DB)
        con.executescript("""
          create table session (id text primary key, parent_id text, directory text, title text, model text,
                                time_updated integer, time_archived integer);
          create table message (id text primary key, session_id text, time_created integer, data text);
          create table part (id text primary key, message_id text, session_id text, time_created integer, data text);""")
        con.execute("insert into session values ('ses_1', null, ?, 'New session - 2026', ?, 1789000000000, null)",
                    (self.work, json.dumps({"providerID": "opencode-go", "id": "deepseek-v4-flash"})))
        con.execute("insert into session values ('ses_bot', null, '/', 'daemon', null, 1789000000000, null)")
        con.execute("insert into message values ('m1', 'ses_1', 1, ?)", (json.dumps({"role": "user"}),))
        con.execute("insert into message values ('m2', 'ses_1', 2, ?)",
                    (json.dumps({"role": "assistant", "modelID": "deepseek-v4-flash", "providerID": "opencode-go"}),))
        con.execute("insert into message values ('mb', 'ses_bot', 1, ?)", (json.dumps({"role": "user"}),))
        for pid, mid, t, d in (("p1", "m1", 1, {"type": "text", "text": "Build the site"}),
                               ("p2", "m2", 2, {"type": "reasoning", "text": "thinking"}),
                               ("p3", "m2", 3, {"type": "tool", "tool": "bash", "callID": "t1",
                                                "state": {"status": "completed", "input": {"command": "ls"}, "output": "x"}}),
                               ("p4", "m2", 4, {"type": "text", "text": "Done."}),
                               ("pb", "mb", 1, {"type": "text", "text": "You are running as a daemon"})):
            sid = "ses_bot" if mid == "mb" else "ses_1"
            con.execute("insert into part values (?, ?, ?, ?, ?)", (pid, mid, sid, t, json.dumps(d)))
        con.commit(); con.close()

    def test_codex_and_opencode_sessions_are_listed_and_converted(self):
        self.codex_session(); self.opencode_db()
        rows = {r["id"]: r for r in A.sessions()}
        self.assertEqual(set(rows), {"cx-019-abc", "oc-ses_1"})          # the one-shot daemon run is left out
        self.assertEqual((rows["cx-019-abc"]["title"], rows["cx-019-abc"]["n"]), ("List the files", 1))
        self.assertEqual(rows["oc-ses_1"]["title"], "Build the site")     # not "New session - …"
        msgs, title, cwd, marker, model = A.convert("cx-019-abc")
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "tool", "assistant"])
        self.assertEqual(msgs[2]["content"], "a.txt")
        self.assertEqual((cwd, marker["id"], model), (self.work, "019-abc", "codex-cli:gpt-5.6-sol"))
        self.assertTrue(all(m["agent"]["id"] == "019-abc" for m in msgs))
        msgs, title, cwd, marker, model = A.convert("oc-ses_1")
        self.assertEqual(model, "opencode-cli:opencode-go/deepseek-v4-flash")
        a = [m for m in msgs if m["role"] == "assistant"]
        self.assertEqual(a[0]["tool_calls"][0]["function"]["name"], "bash")
        self.assertEqual(a[-1]["content"], "Done.")

    def fake_cli(self, name, events):
        """A stand-in CLI that records its arguments and prints the given events."""
        exe = os.path.join(self.tmp, name)
        rec = os.path.join(self.tmp, name + ".args")
        with open(exe, "w") as fh:
            fh.write("#!/bin/sh\n" f"printf '%s\\n' \"$@\" > {rec}\n")
            for ev in events: fh.write(f"echo '{json.dumps(ev)}'\n")
        os.chmod(exe, os.stat(exe).st_mode | stat.S_IEXEC)
        return exe, rec

    def test_a_chat_continues_the_agents_own_session(self):
        exe, rec = self.fake_cli("codex", [{"type": "thread.started", "thread_id": "019-abc"},
                                           {"type": "item.completed", "item": {"type": "agent_message", "text": "hi again"}}])
        old = P.which
        P.which = lambda name: exe
        try:
            mk = {"source": "codex", "id": "019-abc", "cwd": self.work}
            msgs = [{"role": "system", "content": "sys"},
                    {"role": "user", "content": "List the files", "agent": mk},
                    {"role": "assistant", "content": "There is a.txt.", "agent": mk},
                    {"role": "user", "content": "(asked the local model) what is a.txt?"},
                    {"role": "assistant", "content": "a text file"},
                    {"role": "user", "content": "Open it"}]
            out = P.cli_stream("codex-cli", "default", msgs, cwd="/")
            args = open(rec).read().splitlines()
            self.assertEqual(args[:4], ["exec", "--json", "--skip-git-repo-check", "resume"])
            self.assertEqual(args[4], "019-abc")
            prompt = "\n".join(args[5:])
            self.assertIn("Open it", prompt)
            self.assertIn("what is a.txt?", prompt)                      # said meanwhile on another model
            self.assertNotIn("There is a.txt.", prompt)                  # already in Codex's session
            self.assertNotIn("sys", prompt)
            self.assertEqual(out["agent"], {"source": "codex", "id": "019-abc", "cwd": self.work})
            # a new chat on the Codex CLI: its session is remembered from the first answer
            out = P.cli_stream("codex-cli", "default", [{"role": "user", "content": "hello"}])
            self.assertEqual(open(rec).read().splitlines()[0], "exec")
            self.assertNotIn("resume", open(rec).read().splitlines())
            self.assertEqual(out["agent"]["id"], "019-abc")
        finally:
            P.which = old

    def test_the_cli_finds_its_interpreter_on_a_bare_path(self):
        env = P.cli_env("/opt/homebrew/bin/codex")
        self.assertIn("/opt/homebrew/bin", env["PATH"].split(":") if os.path.isdir("/opt/homebrew/bin") else ["/opt/homebrew/bin"])


if __name__ == "__main__":
    unittest.main()
