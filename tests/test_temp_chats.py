"""A temporary chat leaves nothing: not in the CLIs it ran through, not in Orbit's logs. Everything here
runs on temporary folders; no CLI is started."""
import json, os, shutil, sqlite3, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin"))

import qqcore as q                        # noqa: E402
import claude_engine as CE                # noqa: E402
import codex_engine as CX                 # noqa: E402
import providers as P                     # noqa: E402

CID = "9cbaa8db-e89b-48aa-b597-497b17935964"


class TestWhatTheClisKeep(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="orbit-temp-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.saved = os.environ.get("HOME")
        os.environ["HOME"] = self.home
        self.addCleanup(lambda: os.environ.__setitem__("HOME", self.saved))

    def agy_tree(self):
        base = os.path.join(self.home, ".gemini", "antigravity-cli")
        for rel in ("conversations", "annotations", "cache", f"brain/{CID}", f"brain/{CID}/.system_generated/logs"):
            os.makedirs(os.path.join(base, rel), exist_ok=True)
        for rel in (f"conversations/{CID}.db", f"conversations/{CID}.db-wal", f"annotations/{CID}.pbtxt",
                    f"brain/{CID}/x.md", f"brain/{CID}/.system_generated/logs/transcript.jsonl"):
            open(os.path.join(base, rel), "w").write("secret")
        json.dump({"/some/folder": CID, "/other": "keep-me-0000-0000-0000-000000000000"}, open(os.path.join(base, "cache", "last_conversations.json"), "w"))
        json.dump({"conversations": {CID: {"summary": {"Title": "private"}}, "keep-me-0000-0000-0000-000000000000": {}}},
                  open(os.path.join(base, "cache", "conversation_metadata.json"), "w"))
        con = sqlite3.connect(os.path.join(base, "conversation_summaries.db"))
        con.execute("CREATE TABLE conversation_summaries (conversation_id text, title text, preview text)")
        con.execute("CREATE VIRTUAL TABLE conversations_fts USING fts5(conversation_id UNINDEXED, body)")
        con.execute("INSERT INTO conversation_summaries VALUES (?,?,?)", (CID, "a private title", "a private preview"))
        con.execute("INSERT INTO conversation_summaries VALUES (?,?,?)", ("keep-me-0000-0000-0000-000000000000", "kept", "kept"))
        con.execute("INSERT INTO conversations_fts VALUES (?,?)", (CID, "private words"))
        con.commit(); con.close()
        return base

    def test_antigravity_conversation_files_and_index_rows_are_removed(self):
        base = self.agy_tree()
        before = set()                                       # none existed before the run
        removed = P.forget_cli_session("agy-cli", None, before)
        self.assertTrue(removed)
        for rel in (f"conversations/{CID}.db", f"conversations/{CID}.db-wal", f"annotations/{CID}.pbtxt", f"brain/{CID}"):
            self.assertFalse(os.path.exists(os.path.join(base, rel)), rel)             # and the transcript logs inside brain/
        con = sqlite3.connect(os.path.join(base, "conversation_summaries.db"))
        self.assertEqual(con.execute("SELECT count(*) FROM conversation_summaries WHERE conversation_id=?", (CID,)).fetchone()[0], 0)
        self.assertEqual(con.execute("SELECT count(*) FROM conversations_fts WHERE conversation_id=?", (CID,)).fetchone()[0], 0)
        self.assertEqual(con.execute("SELECT count(*) FROM conversation_summaries").fetchone()[0], 1)   # others untouched
        con.close()
        self.assertEqual(json.load(open(os.path.join(base, "cache", "last_conversations.json"))), {"/other": "keep-me-0000-0000-0000-000000000000"})
        self.assertEqual(list(json.load(open(os.path.join(base, "cache", "conversation_metadata.json")))["conversations"]), ["keep-me-0000-0000-0000-000000000000"])

    def test_only_conversations_made_during_the_run_are_touched(self):
        base = self.agy_tree()
        P.forget_cli_session("agy-cli", None, {CID})         # it existed before the run: not this chat's
        self.assertTrue(os.path.exists(os.path.join(base, f"conversations/{CID}.db")))

    def test_codex_thread_files_are_removed(self):
        d = os.path.join(self.home, ".codex", "sessions", "2026", "10", "25"); os.makedirs(d)
        mine = os.path.join(d, f"rollout-2026-10-25T01-00-00-{CID}.jsonl")
        other = os.path.join(d, "rollout-2026-10-25T01-00-00-aaaaaaaa-0000-0000-0000-000000000000.jsonl")
        open(mine, "w").write("x"); open(other, "w").write("y")
        self.assertEqual(CX.forget_thread_files(CID, home=self.home), [mine])
        self.assertFalse(os.path.exists(mine)); self.assertTrue(os.path.exists(other))


class TestClaudeCodeKeepsNothing(unittest.TestCase):
    def test_the_run_is_told_not_to_save_its_session(self):
        self.assertIn("--no-session-persistence", CE.build_argv(dict(CE.DEFAULTS), temp=True, kind="subscription"))
        self.assertNotIn("--no-session-persistence", CE.build_argv(dict(CE.DEFAULTS), kind="subscription"))
        self.assertNotIn("--prompt-suggestions", CE.build_argv({**CE.DEFAULTS, "prompt_suggestions": True}, temp=True, kind="subscription"))

    def test_plugin_hooks_that_record_prompts_are_off(self):
        settings_path, _ = CE.launcher_files(dict(CE.DEFAULTS), "temp-test", temp=True)
        self.addCleanup(lambda: os.path.exists(settings_path) and os.remove(settings_path))
        self.assertTrue(json.load(open(settings_path))["disableAllHooks"])

    def test_every_session_a_temporary_chat_used_is_erased(self):
        home = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, home, True)
        saved = CE.claude_dir; CE.claude_dir = lambda: home
        self.addCleanup(setattr, CE, "claude_dir", saved)
        os.makedirs(os.path.join(home, "projects", "-w"))
        a, b = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
        for sid in (a, b):
            open(os.path.join(home, "projects", "-w", sid + ".jsonl"), "w").write("x")
            os.makedirs(os.path.join(home, "file-history", sid))
        msgs = [{"role": "user", "content": "1", "claude": {"session": a, "cwd": "/w"}},
                {"role": "user", "content": "2", "claude": {"session": b, "cwd": "/w"}}]
        CE.erase_session_traces(msgs)
        self.assertEqual(os.listdir(os.path.join(home, "projects", "-w")), [])
        self.assertEqual(os.listdir(os.path.join(home, "file-history")), [])


class TestOrbitsOwnLogsSkipTemporaryChats(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.saved = (q.LOGS, q.LEDGER, q.TOOL_LOG)
        q.LOGS = self.tmp; q.LEDGER = os.path.join(self.tmp, "ledger.jsonl"); q.TOOL_LOG = os.path.join(self.tmp, "tools.jsonl")
        self.addCleanup(lambda: (setattr(q, "LOGS", self.saved[0]), setattr(q, "LEDGER", self.saved[1]), setattr(q, "TOOL_LOG", self.saved[2])))
        q.TEMP_SIDS.add("tmp-chat"); self.addCleanup(q.TEMP_SIDS.discard, "tmp-chat")

    def test_no_usage_tool_or_safety_record_for_a_temporary_chat(self):
        q.ledger_add("tmp-chat", seconds=1)
        q._tool_log("run_shell", 0.1, True, sid="tmp-chat")
        q.TURN_CTX.sid = "tmp-chat"
        try: q.LOG_SAFETY("run_shell", {"command": "rm -rf /tmp/x"}, "denied", "x")
        finally: q.TURN_CTX.sid = None
        self.assertEqual(os.listdir(self.tmp), [])
        q.ledger_add("normal-chat", seconds=1)               # an ordinary chat is still recorded
        self.assertEqual(os.listdir(self.tmp), ["ledger.jsonl"])


if __name__ == "__main__":
    unittest.main()


class TestMirrorOfOtherProgramsChats(unittest.TestCase):
    """chat_mirror copies what changed, never a temporary chat's, and puts back only what is missing."""
    def setUp(self):
        import chat_mirror as M
        self.M = M
        self.home = tempfile.mkdtemp(prefix="orbit-home-"); self.dest = tempfile.mkdtemp(prefix="orbit-dest-")
        self.addCleanup(shutil.rmtree, self.home, True); self.addCleanup(shutil.rmtree, self.dest, True)
        self.cfg = {"dest": self.dest, "include_external": True, "external": {}}
        old = __import__("time").time() - 3600
        def put(rel, text="x"):
            p = os.path.join(self.home, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").write(text); os.utime(p, (old, old)); return p
        self.put = put
        put(".claude/projects/-Users-me-proj/aaaaaaaa-0000-0000-0000-000000000001.jsonl", "chat one")
        put(".claude/projects/-Users-me-proj/bbbbbbbb-0000-0000-0000-000000000002.jsonl", "a temporary chat's")
        put(".claude/projects/-Users-me-claude-mem-observer-sessions/cccccccc-0000-0000-0000-000000000003.jsonl", "observer")
        put(".claude/projects/-private-tmp-scratch/dddddddd-0000-0000-0000-000000000004.jsonl", "scratch")
        put(".claude/projects/-Users-me-proj/aaaaaaaa-0000-0000-0000-000000000001/subagents/agent-1.jsonl", "agent")
        put(".codex/sessions/2026/10/25/rollout-2026-10-25T01-00-00-eeeeeeee-0000-0000-0000-000000000005.jsonl", "codex chat")

    def mirrored(self):
        out = []
        for r, _, fs in os.walk(os.path.join(self.dest, "external")):
            out += [os.path.relpath(os.path.join(r, f), os.path.join(self.dest, "external")) for f in fs if not f.startswith(".")]
        return sorted(out)

    def test_it_copies_chats_and_leaves_out_what_it_should(self):
        r = self.M.mirror(self.cfg, skip_ids={"bbbbbbbb-0000-0000-0000-000000000002"}, home=self.home)
        got = self.mirrored()
        self.assertEqual(r["errors"], 0)
        self.assertIn("claude/-Users-me-proj/aaaaaaaa-0000-0000-0000-000000000001.jsonl", got)
        self.assertTrue(any(g.startswith("codex/sessions/") for g in got))
        self.assertFalse(any("bbbbbbbb" in g for g in got), "a temporary chat's session")
        self.assertFalse(any("observer" in g for g in got)); self.assertFalse(any("scratch" in g for g in got))
        self.assertFalse(any("subagents" in g for g in got), "helper-agent transcripts are off by default")

    def test_only_what_changed_is_copied_again_and_a_file_still_being_written_waits(self):
        self.M.mirror(self.cfg, home=self.home)
        self.assertEqual(self.M.mirror(self.cfg, home=self.home)["copied"], 0)
        p = self.put(".claude/projects/-Users-me-proj/aaaaaaaa-0000-0000-0000-000000000001.jsonl", "chat one, longer now")
        os.utime(p, None)                                    # written just now: still being written
        self.assertEqual(self.M.mirror(self.cfg, home=self.home)["copied"], 0)
        old = __import__("time").time() - 600; os.utime(p, (old, old))
        self.assertEqual(self.M.mirror(self.cfg, home=self.home)["copied"], 1)

    def test_a_switched_off_source_is_not_copied(self):
        self.M.mirror({**self.cfg, "external": {"codex": False}}, home=self.home)
        self.assertFalse(any(g.startswith("codex/") for g in self.mirrored()))
        self.assertEqual(self.M.mirror({**self.cfg, "include_external": False}, home=self.home)["seen"], 0)

    def test_putting_back_adds_what_is_missing_and_never_overwrites(self):
        self.M.mirror(self.cfg, home=self.home)
        gone = os.path.join(self.home, ".claude/projects/-Users-me-proj/aaaaaaaa-0000-0000-0000-000000000001.jsonl")
        os.remove(gone)
        kept = os.path.join(self.home, ".codex/sessions/2026/10/25/rollout-2026-10-25T01-00-00-eeeeeeee-0000-0000-0000-000000000005.jsonl")
        open(kept, "w").write("newer than the mirror")
        self.assertEqual(self.M.restore_missing(self.cfg, home=self.home)["n"], 1)
        self.assertEqual(open(gone).read(), "chat one"); self.assertEqual(open(kept).read(), "newer than the mirror")

    def test_antigravity_databases_are_copied_consistently(self):
        base = os.path.join(self.home, ".gemini", "antigravity", "conversations"); os.makedirs(base)
        db = os.path.join(base, "ffffffff-0000-0000-0000-000000000006.db")
        con = sqlite3.connect(db); con.execute("CREATE TABLE t (x)"); con.execute("INSERT INTO t VALUES (7)"); con.commit(); con.close()
        self.M.mirror(self.cfg, home=self.home)
        copy = os.path.join(self.dest, "external", "antigravity", "conversations", "ffffffff-0000-0000-0000-000000000006.db")
        self.assertEqual(sqlite3.connect(copy).execute("SELECT x FROM t").fetchone()[0], 7)
