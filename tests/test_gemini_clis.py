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
        # as agy 1.4.3 prints it: a heading, then one "slug<TAB>Label" line per model; no JSON flag
        print("Fetching available models...")
        print("gemini-3.8-flash\tGemini 3.8 Flash")
        print("gemini-4-argon\tGemini 4 Argon")
        sys.exit(0)
    # the prompt is whatever follows -p; flags must all come before it
    i = a.index("-p")
    flags, prompt = " ".join(a[:i]), " ".join(a[i + 1:])
    if "--output-format" in a and a[a.index("--output-format") + 1] == "stream-json":     # agy, as 1.4.3 writes it
        conv = a[a.index("--conversation") + 1] if "--conversation" in a else "conv-1"
        def ev(o): print(json.dumps(o), flush=True)
        ev({"event": "init", "conversation_id": conv, "init": {"model": "m", "cwd": "/x", "tools": [], "permission_mode": "request-review"}})
        step = {"conversation_id": conv, "step_index": 1, "step_type": "tool", "tool_name": "read_file"}
        ev({"event": "step_update", "step_update": {**step, "state": "ACTIVE", "tool_info": {"name": "read_file", "parameters": {"Path": "notes.txt"}}}})
        ev({"event": "step_update", "step_update": {**step, "state": "DONE", "tool_info": {"name": "read_file", "parameters": {"Path": "notes.txt"}, "output": "1 lines, 17 bytes"}}})
        text = "flags=" + flags + " | prompt=" + prompt.splitlines()[0]
        if "FAIL" in prompt:
            ev({"event": "result", "result": {"conversation_id": conv, "status": "ERROR", "response": "the model refused"}})
            sys.exit(3)
        for chunk in (text[:12], text[12:]):
            ev({"event": "step_update", "step_update": {"conversation_id": conv, "step_index": 2, "state": "ACTIVE",
                                                        "step_type": "agent_response", "text_delta": chunk}})
        ev({"event": "result", "result": {"conversation_id": conv, "status": "SUCCESS", "response": text + "\\n", "num_turns": 1,
                                          "usage": {"input_tokens": 100, "output_tokens": 7}}})
        sys.exit(0)
    print("flags=" + flags + " | prompt=" + prompt.splitlines()[0])
    print("second line")
''')


class Fake(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orbit-gcli-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.exe = os.path.join(self.tmp, "fake")
        open(self.exe, "w").write(FAKE)
        os.chmod(self.exe, os.stat(self.exe).st_mode | stat.S_IXUSR)
        saved = (P.which, dict(P._AGY), dict(P._SIGNED))
        P.which = lambda name: self.exe if name in ("agy", "gemini") else None
        P._AGY.update(at=0.0, rows=[]); P._SIGNED.clear()
        def restore():
            P.which = saved[0]; P._AGY.clear(); P._AGY.update(saved[1]); P._SIGNED.clear(); P._SIGNED.update(saved[2])
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
        self.assertIn("flags=--output-format stream-json --model gemini-3.8-flash | prompt=User: what is 2+2", out["content"])

    def test_the_default_model_passes_no_flag(self):
        self.assertIn("flags=--output-format stream-json | prompt=User: hello", self.ask("agy-cli", "default")["content"])

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


class TestAntigravityChat(Fake):
    """An Antigravity chat: its text streams, its tool steps show, its own conversation goes on,
    and what it spent is counted."""
    def run_chat(self, messages, model="gemini-3.8-flash-low"):
        seen = []
        out = P.cli_stream("agy-cli", model, messages, emit=lambda k, p: seen.append((k, p)), cwd=self.tmp)
        return out, seen

    def test_the_answer_streams_in_pieces(self):
        out, seen = self.run_chat([{"role": "user", "content": "hello"}])
        deltas = [p for k, p in seen if k == "content_delta"]
        self.assertGreater(len(deltas), 1)
        self.assertTrue("".join(deltas).startswith("flags="))
        self.assertEqual(out["content"], "".join(deltas).strip())

    def test_a_tool_it_used_shows_as_a_line_of_its_thinking(self):
        out, seen = self.run_chat([{"role": "user", "content": "hello"}])
        self.assertIn("⚙ read_file notes.txt — 1 lines, 17 bytes", out["reasoning_content"])
        self.assertTrue(any(k == "thinking_delta" and "read_file" in p for k, p in seen))

    def test_it_says_which_conversation_to_continue_and_what_it_cost(self):
        out, _ = self.run_chat([{"role": "user", "content": "hello"}])
        self.assertEqual(out["agent"]["source"], "agy")
        self.assertEqual(out["agent"]["id"], "conv-1")
        self.assertEqual(out["usage"], {"prompt_tokens": 100, "completion_tokens": 7})

    def test_the_next_message_goes_into_the_same_conversation_alone(self):
        first, _ = self.run_chat([{"role": "user", "content": "hello"}])
        history = [{"role": "user", "content": "hello"}, {**first},
                   {"role": "user", "content": "and now this"}]
        out, _ = self.run_chat(history)
        self.assertIn("--conversation conv-1", out["content"])
        self.assertIn("prompt=and now this", out["content"])               # just the new message, not a replay
        self.assertNotIn("User: hello", out["content"])

    def test_what_was_said_on_another_model_meanwhile_goes_along(self):
        first, _ = self.run_chat([{"role": "user", "content": "hello"}])
        history = [{"role": "user", "content": "hello"}, {**first},
                   {"role": "user", "content": "q2"}, {"role": "assistant", "content": "a2 from elsewhere"},
                   {"role": "user", "content": "q3"}]
        out, _ = self.run_chat(history)
        self.assertIn("--conversation conv-1", out["content"])
        self.assertIn("Meanwhile", out["content"])

    def test_a_turn_it_stops_with_an_error_is_an_error(self):
        with self.assertRaises(RuntimeError) as cm:
            self.run_chat([{"role": "user", "content": "please FAIL"}])
        self.assertIn("the model refused", str(cm.exception))


class TestGeminiCliIsRetired(Fake):
    """Google stopped letting the Gemini CLI sign in ("migrate to the Antigravity suite"): it is not offered."""
    def test_it_is_not_offered_even_when_installed(self):
        self.assertEqual([m for m in P.cli_models() if m["provider"] == "gemini-cli"], [])
        self.assertNotIn("gemini-cli", [r["id"] for r in P.google_cli_status(fresh=True)])


if __name__ == "__main__":
    unittest.main()


class TestSigningIn(Fake):
    """Settings offers each Google agent's install and sign-in command, for Orbit's terminal."""
    def row(self, cid):
        return next(r for r in P.google_cli_status(fresh=True) if r["id"] == cid)

    def test_the_model_list_alone_proves_nothing_about_the_sign_in(self):
        r = self.row("agy-cli")
        self.assertEqual((r["installed"], r["models"], r["signed_in"]), (True, 2, None))   # asked nothing yet
        self.assertEqual(r["login"], "agy")

    def test_a_question_that_gets_an_answer_is_a_working_sign_in(self):
        self.assertTrue(P.google_cli_test("agy-cli")["ok"])
        self.assertTrue(self.row("agy-cli")["signed_in"])

    def test_a_question_that_does_not_is_not_and_says_why(self):
        bad = os.path.join(self.tmp, "bad")
        open(bad, "w").write("#!/bin/sh\necho 'please sign in with Google' >&2\nexit 1\n")
        os.chmod(bad, 0o755)
        P.which = lambda name: bad if name == "agy" else None
        res = P.google_cli_test("agy-cli")
        self.assertFalse(res["ok"])
        self.assertIn("sign in with Google", res["detail"])
        self.assertIs(self.row("agy-cli")["signed_in"], False)

    def test_not_installed_says_how(self):
        P.which = lambda name: None
        r = self.row("agy-cli")
        self.assertEqual((r["installed"], r["signed_in"]), (False, None))
        self.assertIn("antigravity.google/cli/install.sh", r["install"])
