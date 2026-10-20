"""What Gemini's OpenAI-compatible endpoint needs from the gateway.

Gemini 3 and later hand back a "thought signature" with each tool call and refuse the
conversation if it does not come back with it. Claude Code speaks Messages, which has no
such field, so the signature rides in the tool call's id. Also: Gemini gives parallel tool
calls no id and numbers them all 0, and refuses a JSON-schema "$schema" marker.
"""
import json, os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))

import harness_gateway as G

SIG = "CiQBjz1rX+/abc=="            # base64 with the characters ids cannot hold


def sse(events):
    """The data lines of a stream, as the gateway reads them."""
    return [("data: " + json.dumps(e)).encode() for e in events] + [b"data: [DONE]"]


def events_of(chunks):
    out = []
    for blob in chunks:
        for line in blob.decode().splitlines():
            if line.startswith("data: "): out.append(json.loads(line[6:]))
    return out


def tool_blocks(chunks):
    return [e["content_block"] for e in events_of(chunks) if e["type"] == "content_block_start"
            and e["content_block"]["type"] == "tool_use"]


class TestTheSignatureComesBack(unittest.TestCase):
    def test_id_round_trip(self):
        tagged = G.with_signature("call_1", SIG)
        self.assertRegex(tagged, r"^[A-Za-z0-9_-]+$")               # an id any client accepts
        self.assertEqual(G.split_signature(tagged), ("call_1", SIG))
        self.assertEqual(G.split_signature("call_1"), ("call_1", None))
        self.assertEqual(G.with_signature("call_1", None), "call_1")

    def test_a_streamed_tool_call_carries_it_out(self):
        stream = G.stream_to_anthropic(sse([
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_9", "type": "function",
                          "function": {"name": "Read", "arguments": '{"file_path": "a.py"}'},
                          "extra_content": {"google": {"thought_signature": SIG}}}]}}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}]), "gemini-3.8-flash")
        (call,) = tool_blocks(stream)
        self.assertEqual(G.split_signature(call["id"]), ("call_9", SIG))

    def test_a_whole_answer_carries_it_out_too(self):
        r = G.complete_to_anthropic({"choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [
            {"id": "c1", "function": {"name": "Bash", "arguments": "{}"},
             "extra_content": {"google": {"thought_signature": SIG}}}]}}]}, "m")
        self.assertEqual(G.split_signature(r["content"][0]["id"]), ("c1", SIG))

    def test_and_goes_back_with_the_call_and_its_result(self):
        tagged = G.with_signature("call_9", SIG)
        out = G.to_openai({"model": "m", "messages": [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": [{"type": "tool_use", "id": tagged, "name": "Read", "input": {"a": 1}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tagged, "content": "ok"}]}]})
        call = out["messages"][1]["tool_calls"][0]
        self.assertEqual(call["id"], "call_9")                                         # its own id, not the tag
        self.assertEqual(call["extra_content"], {"google": {"thought_signature": SIG}})
        self.assertEqual(out["messages"][2]["tool_call_id"], "call_9")

    def test_a_call_without_one_is_sent_as_it_always_was(self):
        out = G.to_openai({"model": "m", "messages": [
            {"role": "assistant", "content": [{"type": "tool_use", "id": "c", "name": "R", "input": {}}]}]})
        self.assertNotIn("extra_content", out["messages"][0]["tool_calls"][0])


class TestGeminiQuirks(unittest.TestCase):
    def test_parallel_calls_with_no_id_all_numbered_zero_stay_separate(self):
        stream = G.stream_to_anthropic(sse([
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "Read", "arguments": '{"a": 1}'}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "Grep", "arguments": '{"b": 2}'}}]}}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}]), "m")
        self.assertEqual([c["name"] for c in tool_blocks(stream)], ["Read", "Grep"])

    def test_a_name_repeated_on_every_chunk_of_one_call_is_still_one_call(self):
        stream = G.stream_to_anthropic(sse([
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "Read", "arguments": '{"file_'}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "Read", "arguments": 'path": "a"}'}}]}}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}]), "m")
        (call,) = tool_blocks(stream)
        self.assertEqual(call["name"], "Read")

    def test_the_schema_marker_is_left_off_a_tools_parameters(self):
        out = G.to_openai({"model": "m", "messages": [{"role": "user", "content": "x"}], "tools": [
            {"name": "T", "description": "d",
             "input_schema": {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
                              "properties": {"a": {"type": "string"}}}}]})
        params = out["tools"][0]["function"]["parameters"]
        self.assertNotIn("$schema", params)
        self.assertEqual(params["properties"]["a"]["type"], "string")


if __name__ == "__main__":
    unittest.main()


class TestForCodex(unittest.TestCase):
    """Codex speaks Responses; its tool calls carry the signature in their call_id the same way."""
    def test_out_and_back(self):
        import responses_bridge as RB
        stream = RB.chat_stream_to_responses(sse([
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "shell", "arguments": '{"c": 1}'},
                          "extra_content": {"google": {"thought_signature": SIG}}}]}}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}]), "gemini-3.8-flash")
        calls = [e["item"] for e in events_of(stream) if e.get("type") == "response.output_item.done"
                 and e["item"].get("type") == "function_call"]
        self.assertEqual(len(calls), 1)
        cid, sig = G.split_signature(calls[0]["call_id"])
        self.assertEqual(sig, SIG)
        back, _names = RB.responses_to_chat({"model": "m", "input": [
            {"type": "function_call", "call_id": calls[0]["call_id"], "name": "shell", "arguments": "{}"},
            {"type": "function_call_output", "call_id": calls[0]["call_id"], "output": "ok"}]})
        call = back["messages"][0]["tool_calls"][0]
        self.assertEqual((call["id"], call["extra_content"]["google"]["thought_signature"]), (cid, SIG))
        self.assertEqual(back["messages"][1]["tool_call_id"], cid)
