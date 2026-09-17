"""Codex mode (bin/codex_engine.py): Orbit chats answered through `codex app-server`,
with a stand-in app-server script speaking the same JSON-RPC -- no Codex, no network."""
import json, os, shutil, stat, sys, tempfile, threading, time, unittest
from collections import deque

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin"))
import qqcore as q                     # noqa: E402
CX = q.CX

FAKE = r'''#!/usr/bin/env python3
import json, os, sys, threading, time
log = open(os.environ["FAKE_CODEX_LOG"], "a")
lock = threading.Lock()
def out(obj):
    with lock:
        sys.stdout.write(json.dumps(obj) + "\n"); sys.stdout.flush()
threads = {}
pending = {}
def run_turn(tid, turn, text):
    def note(method, params): out({"method": method, "params": {"threadId": tid, "turnId": turn, **params}})
    if "slow" in text:
        note("item/started", {"item": {"type": "agentMessage", "id": "m0", "text": ""}})
        note("item/agentMessage/delta", {"itemId": "m0", "delta": "working"})
        for _ in range(100):
            if threads[tid].get("interrupted"): break
            time.sleep(0.05)
        out({"method": "turn/completed", "params": {"threadId": tid, "turn": {"id": turn, "status": "interrupted"}}})
        return
    note("item/started", {"item": {"type": "reasoning", "id": "r1"}})
    note("item/reasoning/summaryTextDelta", {"itemId": "r1", "delta": "thinking about it"})
    note("item/started", {"item": {"type": "agentMessage", "id": "m1", "text": ""}})
    note("item/agentMessage/delta", {"itemId": "m1", "delta": "Let me check."})
    note("item/completed", {"item": {"type": "agentMessage", "id": "m1", "text": "Let me check."}})
    note("item/started", {"item": {"type": "commandExecution", "id": "c1", "command": "ls", "cwd": "/tmp"}})
    ev = threading.Event(); pending[900] = ev
    out({"id": 900, "method": "item/commandExecution/requestApproval", "params": {"threadId": tid, "turnId": turn, "itemId": "c1", "command": "ls", "cwd": "/tmp"}})
    ev.wait(10)
    note("item/commandExecution/outputDelta", {"itemId": "c1", "delta": "a.txt\n"})
    note("item/completed", {"item": {"type": "commandExecution", "id": "c1", "status": "completed", "exitCode": 0, "aggregatedOutput": None}})
    note("item/started", {"item": {"type": "fileChange", "id": "f1", "changes": [{"path": "new.txt", "kind": {"type": "add"}, "diff": "+hello"}]}})
    note("item/completed", {"item": {"type": "fileChange", "id": "f1", "status": "completed", "changes": [{"path": "new.txt", "kind": {"type": "add"}, "diff": "+hello"}]}})
    note("item/started", {"item": {"type": "agentMessage", "id": "m2", "text": ""}})
    note("item/agentMessage/delta", {"itemId": "m2", "delta": "Done: a.txt"})
    note("item/completed", {"item": {"type": "agentMessage", "id": "m2", "text": "Done: a.txt"}})
    note("thread/tokenUsage/updated", {"tokenUsage": {"total": {"inputTokens": 500, "outputTokens": 20}, "last": {"inputTokens": 300}, "modelContextWindow": 272000}})
    out({"method": "turn/completed", "params": {"threadId": tid, "turn": {"id": turn, "status": "completed"}}})
for line in sys.stdin:
    m = json.loads(line)
    log.write(json.dumps(m) + "\n"); log.flush()
    meth, p = m.get("method"), m.get("params") or {}
    if meth is None:
        if m.get("id") in pending: pending.pop(m["id"]).set()
        continue
    if meth == "initialize": out({"id": m["id"], "result": {"userAgent": "fake"}})
    elif meth == "thread/start":
        tid = "thr-%d" % (len(threads) + 1); threads[tid] = {}
        out({"id": m["id"], "result": {"thread": {"id": tid}}})
    elif meth == "thread/resume":
        if p["threadId"] not in threads and not p["threadId"].startswith("imported"):
            out({"id": m["id"], "error": {"code": 1, "message": "no such thread"}})
        else:
            threads.setdefault(p["threadId"], {})
            out({"id": m["id"], "result": {"thread": {"id": p["threadId"]}}})
    elif meth == "turn/start":
        turn = "turn-%d" % time.time_ns()
        out({"id": m["id"], "result": {"turn": {"id": turn}}})
        threading.Thread(target=run_turn, args=(p["threadId"], turn, p["input"][0]["text"]), daemon=True).start()
    elif meth == "turn/interrupt":
        threads[p["threadId"]]["interrupted"] = True
        out({"id": m["id"], "result": {}})
    elif meth == "turn/steer":
        out({"id": m["id"], "result": {}})
    elif "id" in m:
        out({"id": m["id"], "result": {}})
'''


class TestCodexEngine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orbit-codex-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.exe = os.path.join(self.tmp, "codex")
        open(self.exe, "w").write(FAKE.replace("#!/usr/bin/env python3", "#!" + sys.executable))
        os.chmod(self.exe, os.stat(self.exe).st_mode | stat.S_IEXEC)
        self.log = os.path.join(self.tmp, "rpc.jsonl")
        os.environ["FAKE_CODEX_LOG"] = self.log
        self.work = os.path.join(self.tmp, "work"); os.makedirs(self.work)
        saved = {"which_codex": CX.which_codex, "login_state": CX.login_state, "chatgpt_models": CX.chatgpt_models,
                 "_remember_thread": CX._remember_thread}
        self.addCleanup(lambda: [setattr(CX, k, v) for k, v in saved.items()])
        CX.which_codex = lambda: self.exe
        CX.login_state = lambda max_age=300: "chatgpt"
        CX.chatgpt_models = lambda: [{"slug": "gpt-test", "display_name": "GPT Test"}]
        CX._remember_thread = lambda t, s: None
        saved_ce = {"gateway_token": q.CE.gateway_token, "gateway_port": q.CE.gateway_port,
                    "chat_prefs": q.CE.chat_prefs, "_system_parts": q.CE._system_parts}
        self.addCleanup(lambda: [setattr(q.CE, k, v) for k, v in saved_ce.items()])
        q.CE.gateway_token = lambda: "gw-token"
        q.CE.gateway_port = lambda: 18897
        q.CE.chat_prefs = lambda sid=None: {"cwd": self.work} if sid else {}
        q.CE._system_parts = lambda project: []
        CX.shutdown()
        self.addCleanup(CX.shutdown)
        q.TURN_CTX.model = q.TURN_CTX.pin_model = "codex:chatgpt/gpt-test"
        self.events, self.asked = [], []

    def emit(self, k, p): self.events.append((k, p))
    def kinds(self): return [k for k, _ in self.events]

    def rpc(self):
        return [json.loads(l) for l in open(self.log)] if os.path.exists(self.log) else []

    def approve(self, fn, args, reason):
        self.asked.append((fn, args, reason)); return True

    def test_an_answer_with_a_command_and_a_file_change(self):
        msgs = [{"role": "system", "content": "sys"}]
        out = CX.run_turn(msgs, "list the files", [], emit=self.emit, approve=self.approve, sid="chat1")
        self.assertEqual(out, "Done: a.txt")
        start = next(m for m in self.rpc() if m.get("method") == "thread/start")["params"]
        self.assertEqual((start["model"], start["modelProvider"], start["cwd"], start["approvalPolicy"], start["sandbox"]),
                         ("gpt-test", None, self.work, "on-request", "workspace-write"))
        self.assertEqual(self.asked[0][0], "run_command")
        self.assertEqual(self.asked[0][1]["command"], "ls")
        reply = next(m for m in self.rpc() if m.get("id") == 900 and "method" not in m)
        self.assertEqual(reply["result"], {"decision": "accept"})
        roles = [m["role"] for m in msgs]
        self.assertEqual(roles, ["system", "user", "assistant", "tool", "tool", "assistant"])
        self.assertEqual(msgs[1]["codex"]["thread"], "thr-1")
        self.assertEqual(msgs[2]["content"], "Let me check.")
        self.assertEqual(msgs[2]["reasoning_content"], "thinking about it")
        self.assertEqual([c["function"]["name"] for c in msgs[2]["tool_calls"]], ["shell", "apply_patch"])
        self.assertEqual(msgs[3]["content"], "a.txt\n")
        self.assertEqual(msgs[-1]["content"], "Done: a.txt")
        self.assertEqual(msgs[-1]["usage"], {"prompt_tokens": 500, "completion_tokens": 20})
        self.assertEqual(q.TURN_CTX.changes[0]["path"], os.path.join(self.work, "new.txt"))
        for k in ("model", "thinking_delta", "content_delta", "tool", "tool_result", "done"):
            self.assertIn(k, self.kinds())
        self.assertNotIn("error", self.kinds())

        # the next message continues the same thread, with nothing repeated
        self.asked.clear()
        CX.run_turn(msgs, "and again", [], emit=self.emit, approve=self.approve, sid="chat1")
        rpc = self.rpc()
        self.assertEqual(next(m for m in rpc if m.get("method") == "thread/resume")["params"]["threadId"], "thr-1")
        last_turn = [m for m in rpc if m.get("method") == "turn/start"][-1]["params"]
        self.assertEqual(last_turn["input"][0]["text"], "and again")

    def test_a_chat_that_was_elsewhere_brings_what_was_said(self):
        msgs = [{"role": "system", "content": "sys"},
                {"role": "user", "content": "my favourite fruit is quince"},
                {"role": "assistant", "content": "Noted, quince.", "model": "Claude Code · DeepSeek"}]
        CX.run_turn(msgs, "what fruit?", [], emit=self.emit, approve=self.approve, sid="chat2")
        text = [m for m in self.rpc() if m.get("method") == "turn/start"][-1]["params"]["input"][0]["text"]
        self.assertIn("quince", text); self.assertIn("what fruit?", text)
        # back from another model: only what came after Codex's last turn
        msgs += [{"role": "user", "content": "(on Orbit) also I like figs"}, {"role": "assistant", "content": "figs too"}]
        CX.run_turn(msgs, "list both", [], emit=self.emit, approve=self.approve, sid="chat2")
        text = [m for m in self.rpc() if m.get("method") == "turn/start"][-1]["params"]["input"][0]["text"]
        self.assertIn("figs", text); self.assertNotIn("quince", text)

    def test_plan_mode_declines_without_asking_and_stop_interrupts(self):
        msgs = [{"role": "system", "content": "sys"}]
        CX.run_turn(msgs, "look around", [], emit=self.emit, approve=self.approve, sid="chat3", read_only=True)
        start = next(m for m in self.rpc() if m.get("method") == "thread/start")["params"]
        self.assertEqual(start["sandbox"], "read-only")
        self.assertEqual(self.asked, [])
        self.assertEqual(next(m for m in self.rpc() if m.get("id") == 900 and "method" not in m)["result"], {"decision": "decline"})
        cancel = threading.Event()
        threading.Timer(0.8, cancel.set).start()
        out = CX.run_turn(msgs, "slow task", [], emit=self.emit, approve=self.approve, sid="chat3", cancel=cancel)
        self.assertIn("stopped", out)
        self.assertTrue(any(m.get("method") == "turn/interrupt" for m in self.rpc()))

    def test_other_providers_go_through_orbits_gateway(self):
        spec = {"id": "codex:opencode-go/deepseek-v4-flash", "provider_label": "Codex · OpenCode Go", "context": 1000000,
                "codex": {"provider": "opencode-go", "model": "deepseek-v4-flash"}}
        key, cfg, model = CX.provider_config(spec)
        p = cfg["model_providers"][key]
        self.assertEqual((key, model, p["wire_api"], p["env_key"]), ("orbit-opencode-go", "deepseek-v4-flash", "responses", "ORBIT_GATEWAY_TOKEN"))
        self.assertEqual(p["base_url"], "http://127.0.0.1:18897/h/opencode-go/v1")
        self.assertEqual(cfg["model_context_window"], 1000000)
        self.assertEqual(CX.provider_config({"codex": {"provider": "chatgpt", "model": "gpt-x"}}), (None, {}, "gpt-x"))
        self.assertEqual(CX.parse_id("codex:opencode-go/kimi-k2.6"), ("opencode-go", "kimi-k2.6"))
        # a chat opened from a Codex session continues that session's thread
        mk = CX.marker_of([{"role": "user", "content": "x", "agent": {"source": "codex", "id": "imported-1", "cwd": "/w"}}])
        self.assertEqual((mk["thread"], mk["imported"]), ("imported-1", True))

    def test_a_branched_chat_gets_its_own_thread_and_stopped_tools_get_a_result(self):
        msgs = [{"role": "system", "content": "sys"}]
        CX.run_turn(msgs, "list the files", [], emit=self.emit, approve=self.approve, sid="parent")
        child = [dict(m) for m in msgs]                   # what session_branch copies
        CX.run_turn(child, "and in the branch?", [], emit=self.emit, approve=self.approve, sid="child")
        starts = [m for m in self.rpc() if m.get("method") == "thread/start"]
        self.assertEqual(len(starts), 2)                  # not the parent's thread
        self.assertFalse(any(m.get("method") == "thread/resume" for m in self.rpc()))
        self.assertEqual(child[-1]["usage"]["completion_tokens"], 20)
        # the same chat's next answer counts only its own tokens (the stand-in reports the same totals)
        CX.run_turn(msgs, "again", [], emit=self.emit, approve=self.approve, sid="parent")
        self.assertEqual(msgs[-1]["usage"], {"prompt_tokens": 0, "completion_tokens": 0})
        # a tool call that never finished still has a result
        items_msgs = [{"role": "system", "content": "sys"}]
        cancel = threading.Event()
        def stuck_approve(fn, args, reason):
            cancel.set(); time.sleep(0.2); return False
        CX.run_turn(items_msgs, "list the files", [], emit=self.emit, approve=stuck_approve, sid="c3", cancel=cancel)
        calls = [c["id"] for m in items_msgs if m.get("tool_calls") for c in m["tool_calls"]]
        results = {m.get("tool_call_id") for m in items_msgs if m.get("role") == "tool"}
        self.assertTrue(set(calls) <= results)


if __name__ == "__main__":
    unittest.main()
