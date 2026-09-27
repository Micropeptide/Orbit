"""The server side of the web page's fixes: which chat an answer, an agent or an alert
belongs to, streams that say they are alive, MCP servers that fail cleanly, and a task
list that two writers cannot tear. Nothing here touches real chats or real settings.
"""
import importlib.machinery, importlib.util, json, os, shutil, sys, tempfile, time, types, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "bin"))

import qqcore as q


def load_ui():
    loader = importlib.machinery.SourceFileLoader("orbit_ui_webfix", os.path.join(ROOT, "bin", "orbit-ui"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = load_ui()

    def patch(self, obj, name, value):
        old = getattr(obj, name)
        setattr(obj, name, value)
        self.addCleanup(setattr, obj, name, old)

    def call(self, method, path, body=None):
        out = types.SimpleNamespace(code=None, body=None)
        ui = self.ui
        class Fake(ui.H):
            def __init__(self): self.path = path; self.headers = {}
            def _body(self): return body or {}
            def _send(self, code, b, ctype="application/json", headers=None):
                out.code = code
                try: out.body = json.loads(b)
                except Exception: out.body = b
        getattr(Fake(), "_" + method)(path.split("?")[0] if method == "post" else path)
        return out


class TestTheAgentFollowsTheChat(Base):
    def test_the_chat_asked_about_not_the_macs_open_one(self):
        ui = self.ui
        st = ui.State(); st.temp = True; st.agent = "paper-reviewer"
        ui.STATES[st.sid] = st; self.addCleanup(ui.STATES.pop, st.sid, None)
        self.patch(ui.S, "agent", None)
        r = self.call("get", "/api/agents?sid=" + st.sid)
        self.assertEqual(r.body["active"], "paper-reviewer")
        self.assertIsNone(self.call("get", "/api/agents").body["active"])


class TestTaskDeletionIsOneStep(Base):
    def test_it_goes_through_the_schedule_lock(self):
        jobs = {"jobs": [{"id": "a"}, {"id": "b"}]}
        seen = []
        def upd(fn):
            seen.append(fn); fn(jobs); return jobs
        self.patch(q, "sched_update", upd)
        self.patch(q, "sched_save", lambda d: self.fail("saved outside the lock"))
        r = self.call("post", "/api/schedule/delete", {"id": "a"})
        self.assertEqual([j["id"] for j in r.body["jobs"]], ["b"])
        self.assertEqual(len(seen), 1)


class TestStreamsSayTheyAreAlive(unittest.TestCase):
    def test_a_quiet_answer_still_writes(self):
        src = open(os.path.join(ROOT, "bin", "orbit-ui")).read()
        self.assertIn("Q.get(timeout=15)", src)
        self.assertIn('b": ping\\n\\n"', src)
        page = open(os.path.join(ROOT, "web", "index.html")).read()
        self.assertIn("Date.now()-lastByte>60000", page, "the page never notices a dead stream")


class TestOneAlertPerPrompt(unittest.TestCase):
    def test_the_mac_alert_only_when_no_page_is_following(self):
        src = open(os.path.join(ROOT, "bin", "orbit-ui")).read()
        blk = src[src.index('Q.put(("approval_request", req))') - 200:][:900]
        self.assertIn('if getattr(Q, "deaf", False) or isinstance(Q, _Sink):', blk)


class TestMCPServersFailCleanly(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orbit-mcp-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = (q.LOGS, q.MCPCFG, dict(q._MCP_STATE), q.MCP.START_TIMEOUT)
        def restore():
            q.LOGS, q.MCPCFG = saved[0], saved[1]
            q._MCP_STATE.clear(); q._MCP_STATE.update(saved[2]); q.MCP.START_TIMEOUT = saved[3]
        self.addCleanup(restore)
        q.LOGS = self.tmp
        q.MCPCFG = os.path.join(self.tmp, "mcp.json")

    def test_a_server_that_dies_says_why(self):
        m = q.MCP("dies", {"command": sys.executable,
                           "args": ["-c", "import sys; sys.stderr.write('missing API key'); sys.exit(3)"]})
        with self.assertRaises(RuntimeError) as cm: m.start()
        self.assertIn("missing API key", str(cm.exception))

    def test_a_server_that_hangs_is_not_left_running(self):
        q.MCP.START_TIMEOUT = 1
        m = q.MCP("hangs", {"command": sys.executable, "args": ["-c", "import time; time.sleep(60)"]})
        with self.assertRaises(RuntimeError): m.start()
        self.assertIsNotNone(m.p.poll(), "the process was orphaned")

    def test_a_remote_entry_says_so(self):
        with self.assertRaises(RuntimeError) as cm: q.MCP("r", {"url": "https://x.example/mcp"}).start()
        self.assertIn("remote", str(cm.exception))

    def test_failures_are_cached_rather_than_retried_on_every_call(self):
        json.dump({"mcpServers": {"bad": {"command": "x"}}}, open(q.MCPCFG, "w"))
        starts = []
        def fail(self_): starts.append(1); raise RuntimeError("nope")
        orig = q.MCP.start
        q.MCP.start = fail; self.addCleanup(setattr, q.MCP, "start", orig)
        q._MCP_STATE.update(hash=None, at=0.0)
        q.load_mcp(); q.load_mcp(); q.load_mcp()
        self.assertEqual(len(starts), 1)
        self.assertIn("bad", q.load_mcp()[1])
        q.load_mcp(force=True)
        self.assertEqual(len(starts), 2)


class TestUndoOfACreatedFile(unittest.TestCase):
    def test_your_edits_to_it_are_not_removed_unasked(self):
        tmp = tempfile.mkdtemp(prefix="orbit-created-"); self.addCleanup(shutil.rmtree, tmp, True)
        p = os.path.join(tmp, "new.txt"); open(p, "w").write("from the answer\n")
        ch = [{"path": p, "snap": None, "created": True, "after_sha": q._file_sha(p)}]
        self.assertEqual(q.preview_undo(ch)["unsafe"], [])
        open(p, "w").write("from the answer\nand mine\n")
        self.assertEqual([x["path"] for x in q.preview_undo(ch)["unsafe"]], [p])
        self.assertFalse(q.undo_result(ch)["undone"])
        self.assertTrue(os.path.exists(p))


class TestARemovedModelCanComeBack(Base):
    def test_fetching_the_providers_models_again_unhides_it(self):
        cfg = {"providers": {"p": {"key": ""}}, "models": [], "hidden": ["p:m1", "p:other"]}
        saved = []
        self.patch(q.MODELS, "load", lambda root: cfg)
        self.patch(q.MODELS, "save", lambda root, c: saved.append(json.loads(json.dumps(c))))
        self.patch(q.MODELS, "fetch_models", lambda prov, key: {"models": [{"model": "m1"}]})
        self.patch(q.MODELS, "model_id", lambda pid, m: f"{pid}:{m}")
        self.patch(q, "model_catalogue", lambda *a, **k: [])
        self.patch(q, "secrets_load", lambda: {})
        r = self.call("post", "/api/model/fetch", {"provider": "p"})
        self.assertEqual(r.code, 200, r.body)
        self.assertEqual(saved[-1]["hidden"], ["p:other"])


class TestTheSessionSaysItsAgent(unittest.TestCase):
    def test_the_payload_has_it(self):
        src = open(os.path.join(ROOT, "bin", "orbit-ui")).read()
        self.assertIn('"agent": getattr(stt, "agent", None) or ""', src)


if __name__ == "__main__":
    unittest.main()
