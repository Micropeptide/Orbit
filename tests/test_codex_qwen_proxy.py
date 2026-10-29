#!/usr/bin/env python3
"""Protocol-level tests for the Codex Responses/MTPLX chat bridge."""
import importlib.util
import os
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = importlib.util.spec_from_file_location(
    "codex_qwen_proxy", os.path.join(ROOT, "bin", "codex-qwen-proxy.py"))
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)


class CodexQwenProxyTests(unittest.TestCase):
    def test_responses_history_and_tools_become_chat_messages(self):
        body = {
            "model": P.LOCAL_MODEL,
            "instructions": "Be precise",
            "input": [
                {"type": "message", "role": "user",
                 "content": [{"type": "input_text", "text": "inspect it"}]},
                {"type": "function_call", "call_id": "call_1", "name": "shell_command",
                 "arguments": '{"command":"pwd"}'},
                {"type": "function_call_output", "call_id": "call_1",
                 "output": "/tmp/project"},
            ],
            "tools": [{"type": "function", "name": "shell_command",
                       "description": "run a command",
                       "parameters": {"type": "object", "properties": {}}}],
        }
        chat = P.responses_to_chat(body)
        self.assertEqual([m["role"] for m in chat["messages"]],
                         ["system", "user", "assistant", "tool"])
        self.assertEqual(chat["messages"][2]["tool_calls"][0]["id"], "call_1")
        self.assertEqual(chat["messages"][3]["tool_call_id"], "call_1")
        self.assertEqual(chat["tools"][0]["function"]["name"], "shell_command")

    def test_bridge_disables_local_thinking(self):
        chat = P.responses_to_chat({
            "model": P.LOCAL_MODEL,
            "input": "create the file",
        })
        self.assertIs(chat["enable_thinking"], False)

    def test_chat_tool_call_becomes_responses_events(self):
        request = {"model": P.LOCAL_MODEL, "stream": True, "tools": []}
        completion = {
            "model": P.LOCAL_MODEL,
            "choices": [{"message": {"role": "assistant", "content": None,
                                       "tool_calls": [{"id": "call_7", "type": "function",
                                                       "function": {"name": "shell_command",
                                                                    "arguments": '{"command":"pwd"}'}}]}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        response = P.make_response(request, completion)
        self.assertEqual(response["output"][0]["type"], "function_call")
        self.assertEqual(response["output"][0]["call_id"], "call_7")
        events = list(P.response_events(response))
        names = [name for name, _ in events]
        self.assertIn("response.function_call_arguments.delta", names)
        self.assertEqual(names[-1], "response.completed")

    def test_catalog_describes_local_context_and_tools(self):
        model = P.codex_model_catalog()["models"][0]
        self.assertEqual(model["slug"], P.LOCAL_MODEL)
        self.assertEqual(model["context_window"], 131072)
        self.assertTrue(model["supports_parallel_tool_calls"])


if __name__ == "__main__":
    unittest.main()
