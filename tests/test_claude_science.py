"""Reading Claude Science chats into Orbit: read-only, words only, nothing the app wrote for itself."""
import json, os, shutil, sqlite3, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
import claude_science as C         # noqa: E402


def build(path, chats):
    db = sqlite3.connect(path)
    db.executescript("create table frames (id text, parent_frame_id text, root_frame_id text, name text, created_at integer, last_user_message_at integer, is_hidden integer);"
                     "create table frame_messages (frame_id text, idx integer, msg_json text, msg_uuid text);")
    for cid, name, created, hidden, kids, msgs in chats:
        db.execute("insert into frames values (?,?,?,?,?,?,?)", (cid, None, cid, name, created, created, hidden))
        for k in kids: db.execute("insert into frames values (?,?,?,?,?,?,?)", (k, cid, cid, "sub", created, created, 0)); db.execute("insert into frame_messages values (?,?,?,?)", (k, 0, json.dumps({"role": "user", "content": "sub-agent task"}), "u"))
        for i, m in enumerate(msgs): db.execute("insert into frame_messages values (?,?,?,?)", (cid, i, json.dumps(m), "u%d" % i))
    db.commit(); db.close()


U = lambda t, **k: dict({"role": "user", "content": [{"type": "text", "text": t}], "_ts": 1_790_000_000_000}, **k)
A = lambda t, **k: dict({"role": "assistant", "content": [{"type": "text", "text": t}], "_ts": 1_790_000_001_000}, **k)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.db = os.path.join(self.tmp, "operon-cli.db")
        build(self.db, [
            ("c1", "Pollen methylation", 1_790_000_000_000, 0, ["k1"], [
                U("[System] <skill_discovery>stuff</skill_discovery>"), U("What does psd13 do?"),
                {"role": "assistant", "content": [{"type": "thinking", "thinking": "hmm"}, {"type": "tool_use", "id": "t", "name": "run", "input": {}}, {"type": "text", "text": "Let me look."}], "_ts": 1},
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "OUTPUT"}]},
                A("It affects pollen CHH methylation."), U("[Memory] <memory_recall>x</memory_recall>"), U("harness", _harness_notice=True),
                {"role": "user", "content": "A plain string question"}, A("Plain answer."), A("A second part.")]),
            ("c2", "Hidden one", 1_780_000_000_000, 1, [], [U("secret")]),
            ("c3", "Empty", 1_770_000_000_000, 0, [], []),
        ])


class TestList(Base):
    def test_lists_top_level_visible_chats_newest_first(self):
        got = C.list_chats(self.db); self.assertEqual([(c["id"], c["title"]) for c in got], [("c1", "Pollen methylation")])
        self.assertEqual(got[0]["messages"], 10); self.assertEqual(got[0]["created"], 1_790_000_000.0)

    def test_not_a_chat_database_is_refused_plainly(self):
        other = os.path.join(self.tmp, "x.db"); sqlite3.connect(other).execute("create table t (a)").connection.commit()
        with self.assertRaises(C.ScienceError): C.list_chats(other)
        with self.assertRaises(C.ScienceError): C.list_chats(os.path.join(self.tmp, "missing.db"))

    def test_the_database_is_never_written(self):
        before = (os.path.getsize(self.db), os.path.getmtime(self.db)); C.list_chats(self.db); C.chat_messages(self.db, "c1")
        self.assertEqual((os.path.getsize(self.db), os.path.getmtime(self.db)), before)
        db = C._open(self.db)
        with self.assertRaises(sqlite3.OperationalError): db.execute("delete from frames")


class TestMessages(Base):
    def test_only_the_conversation_comes_across(self):
        title, msgs = C.chat_messages(self.db, "c1")
        self.assertEqual(title, "Pollen methylation (Claude Science)")
        self.assertIn("copied from the Claude Science app", msgs[0]["content"])
        body = [(m["role"], m["content"]) for m in msgs[1:]]
        self.assertEqual(body, [("user", "What does psd13 do?"), ("assistant", "Let me look.\n\nIt affects pollen CHH methylation."), ("user", "A plain string question"),
                                ("assistant", "Plain answer.\n\nA second part.")])
        blob = json.dumps(msgs); [self.assertNotIn(x, blob) for x in ("OUTPUT", "hmm", "skill_discovery", "memory_recall", "sub-agent")]
        self.assertEqual(msgs[2]["model_label"], "Claude Science"); self.assertEqual(msgs[1]["t"], 1_790_000_000.0)

    def test_unknown_and_sub_agent_chats_are_not_importable(self):
        for bad in ("nope", "k1"):
            with self.assertRaises(C.ScienceError): C.chat_messages(self.db, bad)

    def test_a_very_long_chat_keeps_its_most_recent_part_and_says_so(self):
        db2 = os.path.join(self.tmp, "long.db"); msgs = []
        for i in range(C.MAX_MESSAGES + 50): msgs += [U(f"q{i}"), A(f"a{i}")]
        build(db2, [("L", "Long", 1, 0, [], msgs)]); title, out = C.chat_messages(db2, "L")
        self.assertLessEqual(len(out), C.MAX_MESSAGES + 2); self.assertIn("most recent part", out[0]["content"]); self.assertIn(f"a{C.MAX_MESSAGES + 49}", out[-1]["content"])

    def test_huge_text_is_cut_and_junk_lines_are_skipped(self):
        db2 = os.path.join(self.tmp, "j.db"); build(db2, [("J", "J", 1, 0, [], [U("x" * (C.MAX_TEXT + 500)), A("ok")])])
        db = sqlite3.connect(db2); db.execute("insert into frame_messages values ('J', 9, 'not json', 'z')"); db.execute("insert into frame_messages values ('J', 10, '[1,2]', 'z')"); db.commit(); db.close()
        _, out = C.chat_messages(db2, "J"); self.assertEqual(len(out[1]["content"]), C.MAX_TEXT); self.assertEqual(out[2]["content"], "ok")


class TestWhereItLives(unittest.TestCase):
    def test_the_data_dir_comes_from_the_config_and_the_busiest_database_first(self):
        tmp = os.path.realpath(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, tmp, True)
        home, data = os.path.join(tmp, "home"), os.path.join(tmp, "data"); os.makedirs(home)
        open(os.path.join(home, "config.toml"), "w").write(f'data_dir = "{data}"\n')
        for o in ("a", "b"): os.makedirs(os.path.join(data, "orgs", o))
        for o, t in (("a", 100), ("b", 200)):
            p = os.path.join(data, "orgs", o, "operon-cli.db"); open(p, "w").write("x"); os.utime(p, (t, t))
        self.assertEqual(C.data_dir(home), data); self.assertEqual([os.path.basename(os.path.dirname(p)) for p in C.find_dbs(home)], ["b", "a"])
        self.assertEqual(C.find_dbs(os.path.join(tmp, "nowhere")), [])



class TestRoute(Base):
    """/api/claudescience through the real server module, with a fake Claude Science folder and a temp sessions folder."""

    @classmethod
    def setUpClass(cls):
        import importlib.machinery, importlib.util
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_loader("qqui_sci", importlib.machinery.SourceFileLoader("qqui_sci", os.path.join(root, "bin", "orbit-ui")))
        cls.ui = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.ui)

    def setUp(self):
        super().setUp()
        import qqcore as q
        self.q = q; self.old = (q.SESSIONS, self.ui._SCI_MAP, C.DEFAULT_HOME)
        home = os.path.join(self.tmp, "home"); data = os.path.join(self.tmp, "data"); os.makedirs(os.path.join(data, "orgs", "o1")); os.makedirs(home)
        open(os.path.join(home, "config.toml"), "w").write(f'data_dir = "{data}"\n'); shutil.copy(self.db, os.path.join(data, "orgs", "o1", "operon-cli.db"))
        q.SESSIONS = os.path.join(self.tmp, "sessions"); os.makedirs(q.SESSIONS); self.ui._SCI_MAP = os.path.join(self.tmp, "map.json")
        orig = C.find_dbs; self.addCleanup(setattr, C, "find_dbs", orig); C.find_dbs = lambda home=home: orig(home)
        self.addCleanup(lambda: (setattr(q, "SESSIONS", self.old[0]), setattr(self.ui, "_SCI_MAP", self.old[1])))

    def call(self, d):
        status, raw = self.ui._science_route(d); return status, json.loads(raw)

    def test_nothing_installed_is_just_not_found(self):
        C.find_dbs = lambda home=None: []; self.assertEqual(self.call({"op": "list"}), (200, {"found": False, "chats": []}))

    def test_list_then_copy_makes_a_new_tagged_chat_and_remembers_it(self):
        st, j = self.call({"op": "list"}); self.assertEqual((st, [c["id"] for c in j["chats"]], j["chats"][0]["imported"]), (200, ["c1"], None))
        st, r = self.call({"op": "import", "ids": ["c1"]}); self.assertEqual(st, 200); sid = r["imported"][0]["sid"]
        msgs, title = self.q.session_load(sid); self.assertEqual(title, "Pollen methylation (Claude Science)"); self.assertEqual([m["role"] for m in msgs], ["user", "user", "assistant", "user", "assistant"])
        self.assertEqual(json.load(open(os.path.join(self.q.SESSIONS, sid + ".json")))["tags"], ["imported", "claude-science"])
        self.assertEqual(self.call({"op": "list"})[1]["chats"][0]["imported"], sid)

    def test_an_unknown_chat_is_refused_and_creates_nothing(self):
        st, r = self.call({"op": "import", "ids": ["nope"]}); self.assertEqual(st, 400); self.assertEqual(os.listdir(self.q.SESSIONS), [])
        self.assertEqual(self.call({"op": "import", "ids": [5, None]})[1], {"imported": []}); self.assertEqual(self.call({"op": "wat"})[0], 400)


if __name__ == "__main__":
    unittest.main()
