"""One chat handing work to another: starting it, sending it a message, waiting for the
answer. The model is stubbed; chats live in the run's own folder."""
import importlib.machinery, importlib.util, json, os, shutil, sys, tempfile, threading, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "bin"))

import qqcore as q


def load_ui():
    loader = importlib.machinery.SourceFileLoader("orbit_ui_chats", os.path.join(ROOT, "bin", "orbit-ui"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = load_ui()

    def setUp(self):
        ui = self.ui
        self.tmp = tempfile.mkdtemp(prefix="orbit-chats-"); self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = (q.SESSIONS, ui.QUEUE_INDEX, q.turn, q.slot_enter, q.slot_exit, ui._learn_later, q.CHATS)
        def restore():
            q.SESSIONS, ui.QUEUE_INDEX, q.turn, q.slot_enter, q.slot_exit, ui._learn_later, q.CHATS = saved
        self.addCleanup(restore)
        q.SESSIONS = os.path.join(self.tmp, "s"); os.makedirs(q.SESSIONS)
        ui.QUEUE_INDEX = os.path.join(self.tmp, "queues.json")
        q._SESS_CACHE["key"] = None
        self.seen = []
        def fake_turn(msgs, content, tools, **kw):
            msgs.append({"role": "user", "content": content, "t": time.time(), **q.take_user_meta()})
            self.seen.append((kw.get("sid"), content, list(getattr(q.TURN_CTX, "chat_chain", []) or [])))
            msgs.append({"role": "assistant", "content": "the answer to: " + content.split("\n\n")[0]})
            q.LAST_TURN[kw.get("sid")] = {"usage": {}}
            return "ok"
        q.turn = fake_turn
        q.slot_enter = lambda *a, **k: True
        q.slot_exit = lambda *a, **k: None
        ui._learn_later = lambda *a, **k: None
        q.CHATS = ui.CHATS
        self.made = []

    def tearDown(self):
        for sid in self.made: self.ui.STATES.pop(sid, None)

    HOSTED = "harness:opencode-go/deepseek-v4.1-flash"

    def chat(self, model=None, title="parent"):
        st = self.ui.State(); st.temp = False; st.title = title; st.title_auto = False
        st.model = model or self.HOSTED
        self.ui.STATES[st.sid] = st; self.made.append(st.sid)
        self.ui.save_session(st)
        return st

    def sid_of(self, out):
        return out.split("(id ")[1].split(")")[0]


class TestTalking(Base):
    def test_create_send_and_wait_for_the_answer(self):
        par = self.chat()
        out = self.ui.CHATS.create(parent=par.sid, title="Helper", instructions="Answer in one line.",
                                   model=self.HOSTED)
        self.assertIn("Started the chat “Helper”", out)
        kid = self.sid_of(out); self.made.append(kid)
        got = self.ui.CHATS.send(parent=par.sid, chain=[], target=kid, message="count the files", timeout=0.5)
        self.assertIn("Answer from “Helper”", got)
        self.assertIn("the answer to: count the files", got)
        child = self.ui.STATES[kid]
        um = next(m for m in child.msgs if m.get("role") == "user")
        self.assertEqual(um["from_chat"]["sid"], par.sid, "the message does not say which chat sent it")
        self.assertEqual(self.seen[-1][2], [par.sid], "the child does not know who is waiting on it")
        saved = json.load(open(q.session_path(kid)))
        self.assertEqual(saved["parent"]["sid"], par.sid)
        self.assertIn("## This chat\nAnswer in one line.", child.msgs[0]["content"])

    def test_by_title_and_without_waiting(self):
        par = self.chat(); kid = self.chat(title="Formatter")
        out = self.ui.CHATS.send(parent=par.sid, chain=[], target="Formatter", message="tidy", wait=False)
        self.assertIn("Sent to “Formatter”", out)
        got = self.ui.CHATS.wait(parent=par.sid, target=kid.sid, timeout=0.5)
        self.assertIn("the answer to: tidy", got)

    def test_no_loops_and_no_talking_to_yourself(self):
        a = self.chat(title="A"); b = self.chat(title="B")
        self.assertIn("this chat", self.ui.CHATS.send(parent=a.sid, chain=[], target=a.sid, message="x"))
        out = self.ui.CHATS.send(parent=b.sid, chain=[a.sid], target=a.sid, message="x")
        self.assertIn("already waiting on this one", out)
        deep = self.ui.CHATS.send(parent=b.sid, chain=["1", "2", "3", "4"], target=a.sid, message="x")
        self.assertIn("handed on 4 times", deep)

    def test_two_local_chats_cannot_wait_on_each_other(self):
        saved = q.model_is_local; q.model_is_local = lambda m: True
        self.addCleanup(setattr, q, "model_is_local", saved)
        a = self.chat(); b = self.chat(title="B")
        self.assertIn("local model", self.ui.CHATS.send(parent=a.sid, chain=[], target=b.sid, message="x"))

    def test_a_waiting_chat_does_not_hold_a_slot(self):
        """With one answer at a time, a chat waiting on another would block it for ever."""
        ui = self.ui
        a = self.chat(); a.lock.acquire(); self.addCleanup(a.lock.release)
        ui.WAITING_ON[a.sid] = "x"; self.addCleanup(ui.WAITING_ON.pop, a.sid, None)
        self.assertNotIn(a.sid, [s for s in ui.running_sids() if s not in ui.WAITING_ON])
        self.assertEqual(ui._busy_count(), len([s for s in ui.running_sids() if s not in ui.WAITING_ON]))

    def test_the_models_and_chats_are_listed(self):
        par = self.chat(); self.chat(title="Summariser")
        out = self.ui.CHATS.list(parent=par.sid)
        self.assertIn("Summariser", out); self.assertIn("Models a new chat can use", out)

    def test_an_unknown_model_or_chat_is_refused_plainly(self):
        par = self.chat()
        self.assertTrue(self.ui.CHATS.create(parent=par.sid, title="x", model="no-such-model-zz").startswith("Error"))
        self.assertTrue(self.ui.CHATS.send(parent=par.sid, chain=[], target="nothing like this", message="x").startswith("Error"))


class TestLongerWork(Base):
    def test_a_chat_can_set_its_own_goal(self):
        a = self.chat()
        q.TURN_CTX.sid = q.TURN_CTX.settings_sid = a.sid
        out = q.t_goal_set("every test passes")
        self.assertIn("Goal set", out)
        self.assertEqual((a.goal["status"], a.goal["objective"]), ("active", "every test passes"))
        self.assertIn("Status: active", q.t_goal_status())
        self.assertEqual(json.load(open(q.session_path(a.sid)))["goal"]["status"], "active")

    def test_a_goal_send_waits_until_the_other_chat_is_done(self):
        """Two chats working a long time: the other chat keeps going answer after answer,
        and this one hears back only when its goal is met."""
        verdicts = iter([{"status": "continue", "reason": "half done", "next": "the rest", "failed": False},
                         {"status": "complete", "reason": "all checked", "next": "", "failed": False}])
        saved = q.goal_audit; q.goal_audit = lambda *a, **k: next(verdicts)
        self.addCleanup(setattr, q, "goal_audit", saved)
        par = self.chat(); kid = self.chat(title="Worker")
        got = self.ui.CHATS.send(parent=par.sid, chain=[], target=kid.sid, message="write the report",
                                 as_goal=True, timeout=0.5)
        self.assertIn("finished working on its goal — complete: all checked", got)
        self.assertEqual(kid.goal["turns_used"], 1, "it did not carry on by itself")
        self.assertEqual([l["role"] for l in par.links], ["messaged"])
        self.assertEqual(kid.links[0]["sid"], par.sid)
        # its continuations keep the chain: it cannot send work back up to the chat waiting on it
        self.assertIn([par.sid], [c for _, _, c in self.seen])

    def test_whom_a_chat_is_waiting_on_is_reported(self):
        par = self.chat(); kid = self.chat(title="Slow one")
        kid.lock.acquire(); self.addCleanup(kid.lock.release)       # busy: the message waits
        t = threading.Thread(target=self.ui.CHATS.wait, kwargs=dict(parent=par.sid, target=kid.sid, timeout=0.05))
        t.start(); time.sleep(0.3)
        self.assertEqual(self.ui.CHATS.talking_to(par.sid)["title"], "Slow one")
        t.join(15)                                                 # its shortest wait is six seconds
        self.assertIsNone(self.ui.CHATS.talking_to(par.sid))


class TestTheTools(unittest.TestCase):
    def test_offered_to_claude_code_chats_on_their_own(self):
        src = open(os.path.join(ROOT, "bin", "claude_engine.py")).read()
        self.assertIn('if c.get("chat_tools", True):', src)
        for t in ("chat_create", "chat_send", "chat_wait", "chat_list"):
            self.assertIn(t, q.BUILTIN)

    def test_outside_the_app_they_say_so(self):
        saved = q.CHATS; q.CHATS = None; self.addCleanup(setattr, q, "CHATS", saved)
        self.assertIn("inside the Orbit app", q.t_chat_send("x", "y"))

    def test_one_answer_cannot_start_chats_without_end(self):
        class Fake:
            def create(self, **kw): return "Started"
        saved = q.CHATS; q.CHATS = Fake(); self.addCleanup(setattr, q, "CHATS", saved)
        q.TURN_CTX.chats_created = 0; self.addCleanup(setattr, q.TURN_CTX, "chats_created", 0)
        outs = [q.t_chat_create(f"c{i}") for i in range(q.CHAT_CREATE_LIMIT + 1)]
        self.assertTrue(outs[-1].startswith("Error"))


class TestLeanKeepsTheBridge(unittest.TestCase):
    """--safe-mode switches off every MCP server: a lean chat told it could hand work to
    other chats had no tool to do it with."""
    def test_lean_with_the_bridge_is_lean_without_safe_mode(self):
        CE = q.CE
        c = dict(CE.cfg()); c["profile"] = "lean"
        argv = CE.build_argv(c, session_id="s", mcp_path="/tmp/mcp.json", bridge=True, kind="provider")
        self.assertNotIn("--safe-mode", argv)
        for flag in ("--setting-sources", "--disable-slash-commands", "--strict-mcp-config"):
            self.assertIn(flag, argv)
        plain = CE.build_argv(c, session_id="s", kind="provider")
        self.assertIn("--safe-mode", plain)

    def test_a_bridge_call_is_this_chats_whatever_the_thread_did_before(self):
        CE = q.CE
        seen = {}
        saved = q._run_one_tool
        def fake(tc, name, args, scratch, emit, approve, cache):
            seen["chat"] = q._this_chat(); seen["chain"] = list(q.TURN_CTX.chat_chain)
            scratch.append({"role": "tool", "content": "ok"})
        q._run_one_tool = fake; self.addCleanup(setattr, q, "_run_one_tool", saved)
        q.TURN_CTX.settings_sid = "someone-else"
        CE.BRIDGE["tok"] = {"sid": "mine", "project": None, "read_only": False, "emit": lambda *a: None,
                            "approve": None, "cancel": None, "specs": [{"function": {"name": "chat_list"}}],
                            "chain": ["up"]}
        self.addCleanup(CE.BRIDGE.pop, "tok", None)
        CE.bridge_call("tok", "chat_list", {})
        self.assertEqual(seen, {"chat": "mine", "chain": ["up"]})


if __name__ == "__main__":
    unittest.main()
