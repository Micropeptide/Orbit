"""Opening a long chat sends its newest part and brings older parts in as you scroll up.

A chat of 20,000 messages is tens of megabytes, nearly all of it tool output nobody sees when it opens; sending all of it took
5-40 seconds. Every test runs against a temporary sessions folder.
"""
import importlib.machinery, importlib.util, json, os, shutil, sys, tempfile, types, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "bin"))


def load_ui():
    loader = importlib.machinery.SourceFileLoader("orbit_ui_session_window", os.path.join(ROOT, "bin", "orbit-ui"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def chat(n_pairs):
    """n questions, each answered by a step that ran a tool: three saved messages, two drawn entries, per pair."""
    out = []
    for i in range(n_pairs):
        out.append({"role": "user", "content": f"question {i}"})
        out.append({"role": "assistant", "content": f"answer {i}", "tool_calls": [
            {"id": f"t{i}", "type": "function", "function": {"name": "bash", "arguments": "{}"}}]})
        out.append({"role": "tool", "tool_call_id": f"t{i}", "name": "bash", "content": f"output {i}"})
    return out


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = load_ui()
        cls.q = cls.ui.q

    def setUp(self):
        q = self.q
        self.tmp = tempfile.mkdtemp(prefix="orbit-window-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = {k: getattr(q, k) for k in ("SESSIONS", "WORKSPACE", "UPLOADS", "TRASH", "TRASH_SESS", "TRASH_FILE")}
        self.addCleanup(lambda: [setattr(q, k, v) for k, v in saved.items()])
        q.SESSIONS = os.path.join(self.tmp, "sessions"); os.makedirs(q.SESSIONS)
        q.WORKSPACE = os.path.join(self.tmp, "workspace"); os.makedirs(q.WORKSPACE)
        q.UPLOADS = os.path.join(q.WORKSPACE, "uploads"); os.makedirs(q.UPLOADS)
        q.TRASH = os.path.join(self.tmp, "trash")
        q.TRASH_SESS = os.path.join(q.TRASH, "sessions"); os.makedirs(q.TRASH_SESS)
        q.TRASH_FILE = os.path.join(q.TRASH, "files"); os.makedirs(q.TRASH_FILE)
        q._SESS_CACHE["key"] = None
        self.ui._RENDER_CACHE.clear()
        self.addCleanup(self.ui._RENDER_CACHE.clear)
        self.ui.STATES.pop("cq-long", None)
        self.addCleanup(lambda: self.ui.STATES.pop("cq-long", None))
        json.dump({"schema": 2, "title": "long", "messages": chat(100)}, open(q.session_path("cq-long"), "w"))

    def get(self, path):
        out = types.SimpleNamespace(code=None, body=None)
        ui = self.ui

        class Fake(ui.H):
            def __init__(self): self.path = path; self.headers = {}
            def _send(self, code, b, ctype="application/json", headers=None):
                out.code = code
                try: out.body = json.loads(b)
                except Exception: out.body = b
        Fake()._get(path)
        return out


class Window(Base):
    def test_without_tail_the_whole_chat_is_sent_as_before(self):
        r = self.get("/api/session/cq-long").body
        self.assertEqual(len(r["messages"]), 200)          # 100 questions + 100 answers (tool rows are folded into them)
        self.assertEqual((r["base"], r["total"], r["users_before"], r["users"]), (0, 200, 0, 100))

    def test_tail_sends_only_the_newest_entries_and_says_where_they_start(self):
        r = self.get("/api/session/cq-long?tail=60").body
        self.assertEqual(len(r["messages"]), 60)
        self.assertEqual((r["base"], r["total"]), (140, 200))
        self.assertEqual(r["messages"][-1]["text"], "answer 99")
        self.assertEqual(r["messages"][0]["text"], "question 70")
        self.assertEqual(r["users_before"], 70)            # for numbering the user messages in the window (fork)
        self.assertEqual(r["users"], 100)
        self.assertEqual(r["last_user"], "question 99")
        self.assertEqual(r["n"], 300)                      # the saved count the chat watcher compares is unchanged

    def test_since_pulls_the_start_back_to_where_you_were(self):
        r = self.get("/api/session/cq-long?tail=60&since=100").body
        self.assertEqual((r["base"], len(r["messages"])), (100, 100))
        self.assertEqual(r["messages"][0]["text"], "question 50")

    def test_since_never_pulls_in_more_than_the_window_cap(self):
        json.dump({"schema": 2, "title": "huge", "messages": chat(600)}, open(self.q.session_path("cq-huge"), "w"))
        r = self.get("/api/session/cq-huge?tail=60&since=0").body
        self.assertEqual(r["total"], 1200)
        self.assertEqual(len(r["messages"]), self.ui._WINDOW_MAX)
        self.assertEqual(r["base"], 1200 - self.ui._WINDOW_MAX)

    def test_a_short_chat_is_sent_whole_even_with_tail(self):
        r = self.get("/api/session/cq-long?tail=500").body
        self.assertEqual((r["base"], len(r["messages"])), (0, 200))

    def test_range_joins_the_window_with_nothing_missing_or_repeated(self):
        win = self.get("/api/session/cq-long?tail=60").body
        old = self.get("/api/session_range/cq-long?from=100&to=%d" % win["base"]).body
        self.assertEqual(len(old["messages"]), win["base"] - 100)
        everything = self.get("/api/session/cq-long").body["messages"]
        self.assertEqual(everything[100:], old["messages"] + win["messages"])

    def test_range_asks_for_a_sensible_part_only(self):
        for q in ("from=5&to=5", "from=9&to=2", "from=-1&to=4", "from=x&to=4", "to=4"):
            self.assertEqual(self.get("/api/session_range/cq-long?" + q).code, 400, q)
        self.assertEqual(self.get("/api/session_range/cq-nothing?from=0&to=10").code, 404)
        big = self.get("/api/session_range/cq-long?from=0&to=100000").body
        self.assertEqual(len(big["messages"]), 200)        # clipped to what exists

    def test_rendering_is_remembered_until_the_chat_changes(self):
        calls = []
        real = self.ui.render
        self.ui.render = lambda m: (calls.append(1), real(m))[1]
        self.addCleanup(setattr, self.ui, "render", real)
        self.get("/api/session/cq-long?tail=60")
        self.get("/api/session_range/cq-long?from=0&to=50")
        self.assertEqual(len(calls), 1)                    # scrolling up did not render the chat again
        d = json.load(open(self.q.session_path("cq-long")))
        d["messages"].append({"role": "user", "content": "one more"})
        json.dump(d, open(self.q.session_path("cq-long"), "w"))
        r = self.get("/api/session/cq-long?tail=60").body
        self.assertEqual(len(calls), 2)
        self.assertEqual(r["messages"][-1]["text"], "one more")

    def test_a_chat_that_is_answering_is_never_served_from_memory(self):
        sid = "cq-long"
        a = self.ui._render_cached(sid, chat(3), False)
        b = self.ui._render_cached(sid, chat(3), True)
        self.assertIsNot(a, b)
        self.assertNotIn(sid, self.ui._RENDER_CACHE)

    def test_only_a_couple_of_chats_are_kept(self):
        for i in range(5):
            sid = f"cq-k{i}"
            json.dump({"schema": 2, "title": "t", "messages": chat(2)}, open(self.q.session_path(sid), "w"))
            self.ui._render_cached(sid, chat(2), False)
        self.assertLessEqual(len(self.ui._RENDER_CACHE), 2)


class EstimateOnlyWhenNeeded(unittest.TestCase):
    def test_a_measured_chat_does_not_walk_every_message(self):
        import qqcore as q
        msgs = [{"role": "user", "content": "hi", "claude": {"ctx": 4321}}]
        called = []
        real = q.estimate_tokens
        q.estimate_tokens = lambda m: (called.append(1), real(m))[1]
        try:
            r = q.context_state(msgs, "cq-none")
            self.assertEqual((r["used"], r["basis"]), (4321, "measured"))
            self.assertEqual(called, [])
            r2 = q.context_state([{"role": "user", "content": "x" * 3600}], "cq-none")
            self.assertEqual(r2["basis"], "estimated")
            self.assertEqual(len(called), 1)
        finally:
            q.estimate_tokens = real


class OpeningDoesNotReconvertAnUnchangedTranscript(unittest.TestCase):
    """A chat whose Claude Code transcript is newer than the chat but holds nothing new was converted in full on every open:
    over a second in a long chat, several when the Mac was busy."""

    def setUp(self):
        import claude_engine as ce
        self.ce = ce
        self.tmp = tempfile.mkdtemp(prefix="orbit-sync-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.chat = os.path.join(self.tmp, "chat.json")
        self.jsonl = os.path.join(self.tmp, "s.jsonl")
        msgs = [{"role": "user", "content": "hi", "claude": {"session": "S", "cwd": self.tmp}},
                {"role": "assistant", "content": "hello"}]
        json.dump({"schema": 2, "messages": msgs, "saved": 1000.0}, open(self.chat, "w"))
        open(self.jsonl, "w").write("{}")
        os.utime(self.jsonl, (5000, 5000))
        self.converted = []
        self.patched = {}
        def patch(name, value):
            self.patched[name] = getattr(ce, name); setattr(ce, name, value)
        patch("marker_of", lambda m: {"session": "S", "cwd": self.tmp})
        patch("jsonl_path", lambda s, c: self.jsonl)
        patch("convert", lambda p: (self.converted.append(p) or list(msgs), "t", self.tmp))
        self.q_path = ce.Q.session_path; ce.Q.session_path = lambda sid: self.chat
        ce._SYNC_SEEN.clear()
        self.addCleanup(self.restore)

    def restore(self):
        for k, v in self.patched.items(): setattr(self.ce, k, v)
        self.ce.Q.session_path = self.q_path
        self.ce._SYNC_SEEN.clear()

    def test_it_is_compared_once_until_something_changes(self):
        self.assertFalse(self.ce.sync_session("cq-x"))
        self.assertFalse(self.ce.sync_session("cq-x"))
        self.assertFalse(self.ce.sync_session("cq-x"))
        self.assertEqual(len(self.converted), 1)
        os.utime(self.jsonl, (6000, 6000))                  # continued in a terminal: look again
        self.assertFalse(self.ce.sync_session("cq-x"))
        self.assertEqual(len(self.converted), 2)


class OpeningParsesTheFileOnce(Base):
    """Opening a 41 MB chat parsed its file four times (sync, load, settings, parent link)."""

    def spy_parses(self):
        real = json.load
        seen = []
        def spy(fp, *a, **k):
            if str(getattr(fp, "name", "")).endswith("cq-long.json"): seen.append(1)
            return real(fp, *a, **k)
        json.load = spy
        self.addCleanup(setattr, json, "load", real)
        return seen

    def test_a_repeat_open_reads_the_file_one_time(self):
        self.get("/api/session/cq-long?tail=60")            # the first open learns there is no transcript to follow
        seen = self.spy_parses()
        r = self.get("/api/session/cq-long?tail=60")
        self.assertEqual(r.code, 200)
        self.assertEqual(len(seen), 1)

    def test_small_fields_come_from_what_was_already_read(self):
        q = self.q
        d = json.load(open(q.session_path("cq-long"))); d["model"] = "m1"; d["goal"] = {"text": "g"}
        json.dump(d, open(q.session_path("cq-long"), "w"))
        seen = self.spy_parses()
        q.session_load("cq-long")
        self.assertEqual(q.chat_fields("cq-long").get("model"), "m1")
        self.assertEqual(self.ui._disk_key("cq-long", "goal"), {"text": "g"})
        self.assertEqual(len(seen), 1)                      # session_load's own read served both

    def test_fields_follow_the_file_and_leaves_out_the_messages(self):
        q = self.q
        self.assertNotIn("messages", q.chat_fields("cq-long"))
        d = json.load(open(q.session_path("cq-long"))); d["model"] = "m2"
        json.dump(d, open(q.session_path("cq-long"), "w"))
        self.assertEqual(q.chat_fields("cq-long").get("model"), "m2")
        self.assertEqual(q.chat_fields("cq-nothing"), {})

    def test_a_copy_is_what_callers_may_change(self):
        g = self.ui._disk_key("cq-long", "tags")
        d = json.load(open(self.q.session_path("cq-long"))); d["goal"] = {"text": "a"}
        json.dump(d, open(self.q.session_path("cq-long"), "w"))
        got = self.ui._disk_key("cq-long", "goal"); got["text"] = "changed"
        self.assertEqual(self.ui._disk_key("cq-long", "goal"), {"text": "a"})


if __name__ == "__main__":
    unittest.main()
