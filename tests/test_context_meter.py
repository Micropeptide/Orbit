"""The context meter: how full this chat's window is, out of the window its model really has.

It read "100% · 632,053/200,000" on a Claude Opus chat: the window came from a model list
that put Opus at 200k while the Opus actually answering has 1M -- the measured prompt was
right, the limit was not. And at the end of an answer the measurement was replaced by the
answer's prompt tokens summed over every step, which grows with each tool call.
"""
import importlib.machinery, importlib.util, os, shutil, sys, tempfile, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "bin"))

import qqcore as q
import claude_engine as CE


def load_ui():
    loader = importlib.machinery.SourceFileLoader("orbit_ui_ctx", os.path.join(ROOT, "bin", "orbit-ui"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class Patch(unittest.TestCase):
    def patch(self, obj, name, value):
        old = getattr(obj, name); setattr(obj, name, value); self.addCleanup(setattr, obj, name, old)

    def chat_window(self, mx):
        self.patch(q, "current_model", lambda mid=None: {"context": mx, "model": "m", "provider": "x"})


class TestTheWindow(Patch):
    def setUp(self):
        self.addCleanup(q.SESSION_TOKENS.pop, "s1", None)
        self.addCleanup(q.SESSION_WINDOW.pop, "s1", None)

    def test_the_window_the_engine_reported_wins(self):
        self.chat_window(200000)
        q.SESSION_WINDOW["s1"] = 1000000
        q.SESSION_TOKENS["s1"] = 632053
        st = q.context_state([{"role": "user", "content": "x" * 2000000}], "s1")
        self.assertEqual((st["used"], st["max"]), (632053, 1000000))
        self.assertLess(st["pct"], 100)

    def test_a_prompt_bigger_than_the_listed_window_proves_the_list_wrong(self):
        """Without a reported window: a request of 632k tokens went through, so the window
        is not 200k. It shows the next real size rather than 316%."""
        self.chat_window(200000)
        q.SESSION_TOKENS["s1"] = 632053
        st = q.context_state([{"role": "user", "content": "x" * 2000000}], "s1")
        self.assertEqual(st["max"], 1000000)
        self.assertAlmostEqual(st["pct"], 63.2, places=1)

    def test_the_chats_own_model_not_the_one_picked_elsewhere(self):
        seen = []
        def cm(mid=None):
            seen.append(mid)
            return {"context": 128000 if mid == "chat-model" else 32000, "model": "m", "provider": "x"}
        self.patch(q, "current_model", cm)
        st = q.context_state([{"role": "user", "content": "hello"}], "s1", model="chat-model")
        self.assertEqual(st["max"], 128000)


class TestAfterARestart(Patch):
    """Nothing measured in memory yet: the figures saved with the chat, not an estimate
    over Orbit's copy of a transcript that Claude Code has long since compacted."""
    def setUp(self):
        self.chat_window(200000)
        for k in ("r1", "r2", "r3"):
            self.addCleanup(q.SESSION_TOKENS.pop, k, None); self.addCleanup(q.SESSION_WINDOW.pop, k, None)
        self.big = [{"role": "user", "content": "x" * 4000000}]          # ~1M estimated

    def test_what_claude_code_measured_last(self):
        msgs = self.big + [{"role": "user", "content": "go", "claude": {"session": "s", "ctx": 91000}},
                           {"role": "assistant", "content": "ok", "usage": {"prompt_tokens": 450000}}]
        st = q.context_state(msgs, "r1")
        self.assertEqual((st["used"], st["max"]), (91000, 200000))

    def test_a_claude_turns_window_is_only_the_list_s_guess(self):
        msgs = self.big + [{"role": "user", "content": "go",
                            "claude": {"session": "s", "ctx": 327739, "ctx_max": 200000}},
                           {"role": "assistant", "content": "ok", "secs": 4}]
        st = q.context_state(msgs, "r1")
        self.assertEqual((st["used"], st["max"]), (327739, 400000))

    def test_what_codex_measured_and_its_window(self):
        msgs = self.big + [{"role": "user", "content": "go", "codex": {"ctx": 70000, "ctx_max": 272000}},
                           {"role": "assistant", "content": "ok"}]
        st = q.context_state(msgs, "r2")
        self.assertEqual((st["used"], st["max"]), (70000, 272000))

    def test_an_answer_orbit_ran_is_a_total_not_a_measurement(self):
        msgs = self.big + [{"role": "user", "content": "go", "claude": {"session": "s", "ctx": 277142}},
                           {"role": "assistant", "content": "a", "model": "Claude Code · DeepSeek V4.1 Flash",
                            "secs": 300, "tool_runs": 40, "usage": {"prompt_tokens": 9363084}}]
        st = q.context_state(msgs, "r1")
        self.assertEqual(st["used"], 277142)

    def test_an_imported_claude_code_session(self):
        msgs = self.big + [{"role": "user", "content": "go"},
                           {"role": "assistant", "content": "a", "model": "Claude Code · claude-opus-5-5",
                            "usage": {"prompt_tokens": 734521, "completion_tokens": 514}}]
        st = q.context_state(msgs, "r3")
        self.assertEqual((st["used"], st["max"]), (734521, 1000000))


class TestClaudeCodeSaysHowBig(Patch):
    def setUp(self):
        self.addCleanup(q.SESSION_WINDOW.pop, "s2", None)

    def test_its_result_carries_the_window(self):
        ev = {"type": "result", "subtype": "success",
              "modelUsage": {"claude-opus-5-5": {"inputTokens": 10, "contextWindow": 1000000},
                             "claude-haiku-4-5": {"inputTokens": 3, "contextWindow": 200000}}}
        CE.note_context_window("s2", ev, model_hint="claude-opus-5-5")
        self.assertEqual(q.SESSION_WINDOW["s2"], 1000000)

    def test_nothing_reported_changes_nothing(self):
        CE.note_context_window("s2", {"type": "result"})
        self.assertNotIn("s2", q.SESSION_WINDOW)


class TestTheEndOfAnAnswerKeepsTheMeasurement(Patch):
    """The engines measure each request; the answer's end used to overwrite that with the
    prompt tokens summed over every step of the answer."""
    @classmethod
    def setUpClass(cls):
        cls.ui = load_ui()

    def test_the_last_request_is_kept_not_the_sum(self):
        ui = self.ui
        tmp = tempfile.mkdtemp(prefix="orbit-ctx-"); self.addCleanup(shutil.rmtree, tmp, True)
        self.patch(q, "SESSIONS", os.path.join(tmp, "s")); os.makedirs(q.SESSIONS)
        self.patch(ui, "QUEUE_INDEX", os.path.join(tmp, "queues.json"))
        q._SESS_CACHE["key"] = None
        st = ui.State(); st.temp = True; st.msgs = [{"role": "system", "content": "s"}]
        ui.STATES[st.sid] = st; self.addCleanup(ui.STATES.pop, st.sid, None)
        self.addCleanup(q.SESSION_TOKENS.pop, st.sid, None)

        def fake_turn(msgs, content, tools, **kw):
            msgs.append({"role": "user", "content": content})
            for step in range(5):                       # five requests, ~60k each
                q.SESSION_TOKENS[kw.get("sid")] = 60000 + step * 100
            msgs.append({"role": "assistant", "content": "done"})
            q.LAST_TURN[kw.get("sid")] = {"secs": 1, "usage": {"prompt_tokens": 301000, "completion_tokens": 900}}
            return "done"
        self.patch(q, "turn", fake_turn)
        self.patch(q, "slot_enter", lambda *a, **k: True)
        self.patch(q, "slot_exit", lambda *a, **k: None)
        self.patch(ui, "_learn_later", lambda *a, **k: None)
        self.patch(ui, "_drain", lambda *a, **k: None)
        self.assertTrue(st.lock.acquire(blocking=False))
        ui.start_turn(st, "go", [], None)
        end = time.time() + 10
        while st.lock.locked() and time.time() < end: time.sleep(0.02)
        self.assertEqual(q.SESSION_TOKENS.get(st.sid), 60400)


if __name__ == "__main__":
    unittest.main()
