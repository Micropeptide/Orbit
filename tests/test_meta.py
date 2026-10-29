"""Meta Model API (Muse Wonder, Muse Spark, Muse Image, SAM 3.1), Muse Code and Muse Glimmer.

Everything runs against fake servers and fake programs: no key is spent, nothing is installed.
"""
import base64, http.server, json, os, shutil, stat, sys, tempfile, threading, unittest, urllib.error, urllib.request
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "bin"))

import qqcore as q                       # noqa: E402
import claude_engine as CE               # noqa: E402
import harness as H                      # noqa: E402
import harness_gateway as G              # noqa: E402
import meta_api as M                     # noqa: E402
import providers as P                    # noqa: E402
import glimmer                           # noqa: E402

KEY = "LLM_1234_secretvalue"


class Fake(http.server.BaseHTTPRequestHandler):
    """A scripted Meta Model API: every request is kept in `seen`."""
    seen, script = [], []

    def log_message(self, *a): pass

    def _reply(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code); self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        Fake.seen.append({"method": "GET", "path": self.path, "headers": dict(self.headers)})
        self._reply(*(Fake.script.pop(0) if Fake.script else (200, {"data": []})))

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        Fake.seen.append({"method": "POST", "path": self.path, "body": body, "headers": dict(self.headers)})
        self._reply(*(Fake.script.pop(0) if Fake.script else (200, {})))


class WithServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        Fake.seen.clear(); Fake.script.clear()
        p = mock.patch.dict(os.environ, {"META_API_BASE": self.base, "MODEL_API_KEY": KEY})
        p.start(); self.addCleanup(p.stop)
        self.tmp = tempfile.mkdtemp(prefix="orbit-meta-")
        self.addCleanup(shutil.rmtree, self.tmp, True)


# ------------------------------------------------------------------ the chat models

class TestHarnessPreset(unittest.TestCase):
    def test_meta_is_a_provider_with_wonder_and_spark(self):
        ps = H.providers(ROOT)
        ids = [m["id"] for m in ps["meta"]["models"]]
        self.assertEqual(ids[:2], ["muse-wonder-1.0", "muse-spark-1.3"])
        self.assertIn("muse-spark-1.3-contributor", ids)
        self.assertEqual(ps["meta"]["key"], "MODEL_API_KEY")
        self.assertEqual(ps["meta"]["base"], "https://api.meta.ai/v1")

    def test_a_key_makes_the_models_appear_in_the_picker(self):
        none = [m["id"] for m in H.catalogue(ROOT, {})]
        self.assertFalse([i for i in none if i.startswith("harness:meta/")])
        got = [m["id"] for m in H.catalogue(ROOT, {"MODEL_API_KEY": KEY})]
        self.assertIn("harness:meta/muse-wonder-1.0", got)

    def test_claude_code_runs_through_the_gateway_with_metas_settings(self):
        spec = H.resolve(ROOT, "harness:meta/muse-wonder-1.0", {"MODEL_API_KEY": KEY})
        with mock.patch.object(CE, "gateway_port", lambda: 8897):
            t = CE.harness_target(spec)
        self.assertIn("/h/meta", t["url"])                                    # the key never enters the Claude process
        self.assertEqual(t["env"]["ENABLE_TOOL_SEARCH"], "true")
        self.assertEqual(t["env"]["CLAUDE_CODE_SUBAGENT_MODEL"], "muse-spark-1.3")
        self.assertEqual(t["small"], "muse-spark-1.3")
        self.assertEqual(t["model"], "muse-wonder-1.0")
        self.assertEqual(t["ctx"], 1048576)

    def test_codex_gets_the_models_too_and_speaks_responses(self):
        import codex_engine as CX
        cat = CX.catalogue(H.catalogue(ROOT, {"MODEL_API_KEY": KEY}))
        self.assertIn("codex:meta/muse-spark-1.3", [m["id"] for m in cat])
        spec = H.resolve(ROOT, "harness:meta/muse-spark-1.3", {"MODEL_API_KEY": KEY})
        self.assertEqual(spec["provider_cfg"]["responses_format"], "responses")
        self.assertEqual(spec["provider_cfg"]["profile"], "meta")

    def test_native_agent_has_metas_chat_models_and_no_image_models(self):
        self.assertEqual(P.BUILTIN_PROVIDERS["meta"]["base_url"], "https://api.meta.ai/v1")
        rows = {"data": [{"id": "muse-wonder-1.0"}, {"id": "muse-image-1.0"}, {"id": "sam-3.1"}, {"id": "muse-spark-1.3"},
                         {"id": "muse-voice-transcribe-1.0"}]}

        class R:
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def read(s): return json.dumps(rows).encode()
        with mock.patch("urllib.request.urlopen", lambda *a, **k: R()):
            got = P.fetch_models({"kind": "openai", "base_url": "https://api.meta.ai/v1"}, KEY)
        self.assertEqual([m["model"] for m in got["models"]], ["muse-wonder-1.0", "muse-spark-1.3"])


class TestMetaBody(unittest.TestCase):
    """What Claude Code sends, cut to what Meta's Messages endpoint accepts."""
    def body(self, **kw):
        return {"model": "muse-wonder-1.0", "max_tokens": 4096, "stream": True,
                "system": [{"type": "text", "text": "x", "cache_control": {"type": "ephemeral"}}],
                "messages": [{"role": "user", "content": [{"type": "text", "text": "hi", "cache_control": {"type": "ephemeral"}}]}],
                **kw}

    def test_fields_meta_refuses_are_removed(self):
        out = G.meta_body(self.body(stop_sequences=["x"], top_k=5, container="c", inference_geo="us",
                                    context_management={"edits": []}, betas=["b"]))
        for k in ("stop_sequences", "top_k", "container", "inference_geo", "context_management", "betas"):
            self.assertNotIn(k, out)
        self.assertEqual(out["model"], "muse-wonder-1.0")
        self.assertNotIn("cache_control", json.dumps(out))

    def test_it_always_reasons(self):
        self.assertNotIn("thinking", G.meta_body(self.body(thinking={"type": "disabled"})))
        self.assertEqual(G.meta_body(self.body(thinking={"type": "adaptive"}))["thinking"], {"type": "adaptive"})
        self.assertEqual(G.meta_body(self.body(thinking={"type": "enabled", "budget_tokens": 2000}))["thinking"],
                         {"type": "enabled", "budget_tokens": 2000})
        # a budget Meta would reject becomes adaptive
        self.assertEqual(G.meta_body(self.body(thinking={"type": "enabled", "budget_tokens": 100}))["thinking"], {"type": "adaptive"})
        self.assertEqual(G.meta_body(self.body(thinking={"type": "enabled", "budget_tokens": 9000}, max_tokens=4096))["thinking"],
                         {"type": "adaptive"})

    def test_effort_is_mapped_and_max_becomes_xhigh(self):
        self.assertEqual(G.meta_body(self.body(output_config={"effort": "max"}))["output_config"], {"effort": "xhigh"})
        self.assertEqual(G.meta_body(self.body(output_config={"effort": "low"}))["output_config"], {"effort": "low"})
        self.assertNotIn("output_config", G.meta_body(self.body(output_config={"effort": "weird"})))

    def test_sampling_is_one_or_the_other(self):
        out = G.meta_body(self.body(temperature=1.7, top_p=0.9))
        self.assertEqual(out["temperature"], 1.0)
        self.assertNotIn("top_p", out)
        self.assertIn("top_p", G.meta_body(self.body(top_p=0.9)))

    def test_tools_and_tool_choice(self):
        tools = [{"name": "Read", "description": "read", "input_schema": {"type": "object"}, "cache_control": {"type": "ephemeral"},
                  "eager_input_streaming": True},
                 {"type": "web_search_20250305", "name": "web_search", "max_uses": 3, "allowed_domains": ["a.com"]},
                 {"type": "bash_20250124", "name": "bash"}]
        out = G.meta_body(self.body(tools=tools, tool_choice={"type": "tool", "name": "Read", "disable_parallel_tool_use": True}))
        self.assertEqual(out["tools"][0], {"name": "Read", "description": "read", "input_schema": {"type": "object"}})
        self.assertEqual(out["tools"][1], {"type": "web_search"})
        self.assertEqual(len(out["tools"]), 2)                          # Anthropic's own bash tool has no meaning here
        self.assertEqual(out["tool_choice"], {"type": "any", "disable_parallel_tool_use": True})
        self.assertNotIn("tools", G.meta_body(self.body(tools=[{"type": "bash_20250124", "name": "bash"}], tool_choice={"type": "auto"})))

    def test_metadata_keeps_strings_only(self):
        self.assertEqual(G.meta_body(self.body(metadata={"user_id": "u", "n": 3}))["metadata"], {"user_id": "u"})


class TestGatewayToMeta(unittest.TestCase):
    """Claude Code and Codex requests, through Orbit's gateway, arriving at a fake Meta."""
    @classmethod
    def setUpClass(cls):
        cls.up = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.up.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{cls.up.server_address[1]}/v1"

        def resolver(provider, model):
            if provider != "meta": return None
            return {"base": base, "format": "messages", "responses_format": "responses", "profile": "meta",
                    "api_key": KEY, "max_output": 131072}
        cls.gw = G.serve(0, resolver)
        cls.url = f"http://127.0.0.1:{cls.gw.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.gw.shutdown(); cls.up.shutdown()

    def setUp(self):
        Fake.seen.clear(); Fake.script.clear()

    def post(self, path, body):
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode(), headers={"content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r: return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_claude_code_request_is_trimmed_and_carries_the_bearer_key(self):
        Fake.script = [(200, b"event: message_stop\ndata: {\"type\":\"message_stop\"}\n\n", "text/event-stream")]
        code, raw = self.post("/h/meta/v1/messages", {
            "model": "muse-wonder-1.0", "max_tokens": 64, "stream": True, "top_k": 3, "stop_sequences": ["x"],
            "thinking": {"type": "disabled"}, "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(code, 200)
        s = Fake.seen[-1]
        self.assertEqual(s["path"], "/v1/messages")
        self.assertEqual(s["headers"].get("Authorization"), "Bearer " + KEY)
        for k in ("top_k", "stop_sequences", "thinking"): self.assertNotIn(k, s["body"])

    def test_codex_talks_responses_and_keeps_the_sealed_reasoning(self):
        done = {"type": "response.completed", "response": {"id": "r", "output": [], "usage": {"input_tokens": 1, "output_tokens": 1}}}
        Fake.script = [(200, ("event: response.completed\ndata: " + json.dumps(done) + "\n\n").encode(), "text/event-stream")]
        code, raw = self.post("/h/meta/v1/responses", {
            "model": "muse-spark-1.3", "stream": True, "include": ["reasoning.encrypted_content"],
            "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hi"}]},
                      {"type": "reasoning", "id": "rs_1", "encrypted_content": "SEALED", "summary": []}]})
        self.assertEqual(code, 200, raw)
        s = Fake.seen[-1]
        self.assertEqual(s["path"], "/v1/responses")                      # not translated to Messages
        self.assertEqual(s["body"]["include"], ["reasoning.encrypted_content"])
        self.assertTrue(any(i.get("encrypted_content") == "SEALED" for i in s["body"]["input"] if isinstance(i, dict)))


# ------------------------------------------------------------------ Muse Image and SAM

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


class TestMuseImage(WithServer):
    def test_generate_saves_files_and_sends_the_right_request(self):
        Fake.script = [(200, {"data": [{"b64_json": base64.b64encode(PNG).decode()}]})]
        paths = M.generate_image("a red fox", self.tmp, size="1024x1024")
        self.assertEqual(len(paths), 1)
        self.assertEqual(open(paths[0], "rb").read(), PNG)
        s = Fake.seen[-1]
        self.assertEqual(s["path"], "/v1/images/generations")
        self.assertEqual(s["headers"].get("Authorization"), "Bearer " + KEY)
        self.assertEqual(s["body"]["model"], "muse-image-1.0")
        self.assertEqual(s["body"]["size"], "1024x1024")
        self.assertEqual(s["body"]["output_format"], "png")

    def test_edit_sends_the_image_as_a_data_url(self):
        src = os.path.join(self.tmp, "in.png")
        open(src, "wb").write(PNG)
        Fake.script = [(200, {"data": [{"b64_json": base64.b64encode(PNG).decode()}]})]
        M.edit_image("add a hat", [src], self.tmp)
        s = Fake.seen[-1]
        self.assertEqual(s["path"], "/v1/images/edits")
        self.assertTrue(s["body"]["images"][0]["image_url"].startswith("data:image/png;base64,"))

    def test_errors_say_what_meta_said(self):
        Fake.script = [(402, {"error": {"message": "add a payment method"}})]
        with self.assertRaises(M.MetaError) as cm: M.generate_image("x", self.tmp)
        self.assertIn("402", str(cm.exception)); self.assertIn("payment method", str(cm.exception))

    def test_no_key_says_where_to_get_one(self):
        with mock.patch.dict(os.environ, {"MODEL_API_KEY": "", "META_API_KEY": ""}):
            with self.assertRaises(M.MetaError) as cm: M.generate_image("x", self.tmp)
        self.assertIn("dev.meta.ai", str(cm.exception))

    def test_missing_file_and_empty_prompt(self):
        with self.assertRaises(M.MetaError): M.edit_image("x", ["/no/such/file.png"], self.tmp)
        with self.assertRaises(M.MetaError): M.generate_image("  ", self.tmp)


SAM_LINE = ("<0f>0<|box;x1=1;y1=0;x2=1;y2=1;w=1;h=1;c=0.9|><|mask;x=0;y=0;c=0.9;data=1,1,!!|>,"
            "2<|box;x1=0;y1=0;x2=1;y2=1;w=1;h=1|><|mask;x=0;y=0;data=1,1,~!|>")


def sse(*events):
    return "".join("event: %s\ndata: %s\n\n" % (e["type"], json.dumps(e)) for e in events).encode()


class TestSam(WithServer):
    def test_the_text_grammar_is_read_into_boxes(self):
        rows = M.parse_segmentation(SAM_LINE + "\n")
        self.assertEqual([r["object"] for r in rows], [0, 2])
        self.assertEqual(rows[0]["box"], [1, 0, 1, 1])
        self.assertEqual(rows[0]["confidence"], 0.9)
        self.assertEqual(rows[1]["mask"], [1, 1])
        self.assertEqual(M.parse_segmentation(""), [])                      # zero matches is a valid answer

    def test_segment_streams_and_collects_the_lines(self):
        src = os.path.join(self.tmp, "in.png")
        open(src, "wb").write(PNG)
        Fake.script = [(200, sse({"type": "response.output_text.delta", "delta": SAM_LINE},
                                 {"type": "response.completed", "response": {}}), "text/event-stream")]
        res = M.segment("duck", src)
        self.assertEqual(len(res["objects"]), 2)
        self.assertEqual(res["size"], [1, 1])
        s = Fake.seen[-1]
        self.assertEqual(s["path"], "/v1/responses")
        self.assertEqual(s["body"]["model"], "sam-3.1")
        self.assertTrue(s["body"]["stream"])
        content = s["body"]["input"][0]["content"]
        self.assertEqual(content[0], {"type": "input_text", "text": "duck"})
        self.assertTrue(content[1]["image_url"].startswith("data:image/png;base64,"))
        self.assertEqual(s["body"]["metadata"]["include_confidence"], "true")

    def test_overlay_draws_the_boxes(self):
        from PIL import Image
        src = os.path.join(self.tmp, "big.png")
        Image.new("RGB", (40, 30), (255, 255, 255)).save(src)
        res = {"text": "", "objects": [{"frame": 0, "object": 0, "box": [5, 5, 30, 25], "size": [40, 30]}]}
        out = M.overlay(src, res, os.path.join(self.tmp, "o.png"))
        self.assertTrue(os.path.isfile(out))
        px = Image.open(out).convert("RGB").getpixel((5, 15))
        self.assertNotEqual(px, (255, 255, 255))                           # the box edge is drawn

    def test_segment_failure_is_reported(self):
        Fake.script = [(200, sse({"type": "response.failed", "response": {"error": {"message": "bad image"}}}), "text/event-stream")]
        with self.assertRaises(M.MetaError) as cm: M.segment("duck", "https://example.com/a.png")
        self.assertIn("bad image", str(cm.exception))


class TestTheTools(WithServer):
    def setUp(self):
        super().setUp()
        self.saved_ws = q.WORKSPACE
        q.WORKSPACE = self.tmp
        self.addCleanup(setattr, q, "WORKSPACE", self.saved_ws)
        p = mock.patch.object(q, "secrets_load", lambda: {"MODEL_API_KEY": KEY})
        p.start(); self.addCleanup(p.stop)

    def test_meta_image_saves_into_the_workspace_and_returns_the_path(self):
        Fake.script = [(200, {"data": [{"b64_json": base64.b64encode(PNG).decode()}]})]
        out = q.t_meta_image("a fox")
        self.assertIn("Muse Image saved 1 image", out)
        path = out.split("- ", 1)[1].splitlines()[0]
        self.assertTrue(path.startswith(self.tmp) and os.path.isfile(path))

    def test_meta_image_errors_come_back_as_text(self):
        Fake.script = [(401, {"error": {"message": "invalid_api_key"}})]
        self.assertTrue(q.t_meta_image("a fox").startswith("Error: "))

    def test_meta_segment_reports_boxes_and_an_overlay(self):
        from PIL import Image
        src = os.path.join(self.tmp, "in.png")
        Image.new("RGB", (40, 30), (255, 255, 255)).save(src)
        line = "<0f>0<|box;x1=5;y1=5;x2=30;y2=25;w=40;h=30|><|mask;x=0;y=0;data=1,1,!!|>"
        Fake.script = [(200, sse({"type": "response.output_text.delta", "delta": line}, {"type": "response.completed", "response": {}}),
                        "text/event-stream")]
        out = q.t_meta_segment("duck", src)
        self.assertIn('found 1 "duck"', out)
        self.assertIn("#0 box 5,5,30,25", out)
        self.assertIn("Overlay", out)

    def test_nothing_found_is_not_an_error(self):
        Fake.script = [(200, sse({"type": "response.completed", "response": {}}), "text/event-stream")]
        self.assertIn("found no", q.t_meta_segment("unicorn", "https://example.com/a.png"))

    def test_the_tools_are_offered_only_with_a_key(self):
        names = lambda: {t["function"]["name"] for t in q.active_tools()[0]}
        self.assertTrue({"meta_image", "meta_segment"} <= names())
        with mock.patch.object(q, "secrets_load", lambda: {}), mock.patch.dict(os.environ, {"MODEL_API_KEY": "", "META_API_KEY": ""}):
            self.assertFalse({"meta_image", "meta_segment"} & names())

    def test_the_prompt_of_a_claude_chat_mentions_them(self):
        note = str(CE._orbit_append(None, dict(CE.DEFAULTS), [], None, "local", look=False)) if False else None
        # _orbit_append reads the bridge flag, so give it one
        note = str(CE._orbit_append(None, dict(CE.DEFAULTS), True, None, "local", look=False))
        self.assertIn("mcp__orbit__meta_image", note)
        self.assertIn("SAM 3.1", note)


# ------------------------------------------------------------------ Muse Code

FAKE_MUSE = r"""#!%(py)s
import json, os, sys
log = open(os.environ["FAKE_MUSE_LOG"], "a")
log.write(json.dumps({"argv": sys.argv[1:], "key": os.environ.get("META_API_KEY"), "cwd": os.getcwd()}) + "\n")
def out(o):
    sys.stdout.write(json.dumps(o) + "\n"); sys.stdout.flush()
def note(method, **p):
    out({"jsonrpc": "2.0", "method": method, "params": {"sessionId": "sess-1", **p}})
if sys.argv[1:2] == ["--version"]:
    print("Muse Code 9.9.9"); sys.exit(0)
for line in sys.stdin:
    m = json.loads(line)
    meth, i, p = m.get("method"), m.get("id"), m.get("params") or {}
    log.write(json.dumps({"rpc": meth, "params": p}) + "\n"); log.flush()
    if meth == "initialize": out({"jsonrpc": "2.0", "id": i, "result": {"serverInfo": {"name": "muse", "version": "9"}}})
    elif meth == "session/start": out({"jsonrpc": "2.0", "id": i, "result": {"session": {"sessionId": "sess-1"}}})
    elif meth == "session/resume":
        if p.get("sessionId") != "sess-1": out({"jsonrpc": "2.0", "id": i, "error": {"code": -32004, "message": "unknown session"}})
        else: out({"jsonrpc": "2.0", "id": i, "result": {"session": {"sessionId": "sess-1"}}})
    elif meth == "session/setApprovalMode": out({"jsonrpc": "2.0", "id": i, "result": {}})
    elif meth == "turn/interrupt": out({"jsonrpc": "2.0", "id": i, "result": {}})
    elif meth == "turn/start":
        out({"jsonrpc": "2.0", "id": i, "result": {"turnId": "t1", "status": "accepted"}})
        if os.environ.get("FAKE_MUSE_FAIL"):
            note("turn/completed", turnId="t1", terminal="failed", error={"message": os.environ["FAKE_MUSE_FAIL"]})
            continue
        note("item/started", item={"itemId": "r1", "kind": "reasoning", "status": "inProgress"})
        note("item/delta", itemId="r1", field="summary.0", delta="Looking at the test.")
        note("item/started", item={"itemId": "a1", "kind": "agentMessage", "status": "inProgress", "text": ""})
        note("item/delta", itemId="a1", field="text", delta="Done: ")
        note("item/delta", itemId="a1", field="text", delta="fixed the test.")
        note("item/completed", item={"itemId": "c1", "kind": "toolCall", "tool": "Bash", "args": json.dumps({"command": "pytest -q"}),
                                     "visibleOutput": "1 passed\nmore", "status": "completed"})
        note("session/tokenUsage", turnId="t1", usage={"inputTokens": 100, "outputTokens": 20})
        note("turn/completed", turnId="t1", terminal="completed")
"""


class TestMuseCode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orbit-muse-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.log = os.path.join(self.tmp, "calls.jsonl")
        exe = os.path.join(self.tmp, "muse")
        with open(exe, "w") as f: f.write(FAKE_MUSE % {"py": sys.executable})
        os.chmod(exe, os.stat(exe).st_mode | stat.S_IXUSR)
        self.exe = exe
        p = mock.patch.object(P, "which", lambda name: exe if name == "muse" else None)
        p.start(); self.addCleanup(p.stop)
        p = mock.patch.dict(os.environ, {"FAKE_MUSE_LOG": self.log})
        p.start(); self.addCleanup(p.stop)

    def calls(self):
        return [json.loads(l) for l in open(self.log)] if os.path.exists(self.log) else []

    def rpc(self, name):
        return [c["params"] for c in self.calls() if c.get("rpc") == name]

    def test_it_is_an_agent_in_the_picker_once_installed(self):
        got = [m for m in P.cli_models() if m["provider"] == "muse-cli"]
        self.assertTrue(got)
        self.assertIn("muse-spark-1.3", [m["model"] for m in got])

    def test_a_turn_streams_the_reply_reasoning_and_tools(self):
        seen = []
        out = P.cli_stream("muse-cli", "muse-spark-1.3", [{"role": "user", "content": "fix the failing test"}], cwd=self.tmp,
                           emit=lambda k, p: seen.append((k, p)), effort="high",
                           account_for=lambda *a: ({"META_API_KEY": KEY}, None))
        self.assertEqual(out["content"], "Done: fixed the test.")
        self.assertIn("Looking at the test.", out["reasoning_content"])
        self.assertIn("⚙ Bash pytest -q — 1 passed", out["reasoning_content"])
        self.assertEqual(out["usage"], {"prompt_tokens": 100, "completion_tokens": 20})
        self.assertEqual([p for k, p in seen if k == "content_delta"], ["Done: ", "fixed the test."])
        self.assertEqual(out["agent"]["id"], "sess-1")                      # the chat continues this session
        self.assertEqual(out["agent"]["source"], "muse")
        first = self.calls()[0]
        self.assertEqual(first["argv"], ["serve", "--model", "muse-spark-1.3"])
        self.assertEqual(first["key"], KEY)
        self.assertNotIn("--disable-sandbox", first["argv"])                  # the sandbox stays on
        start = self.rpc("session/start")[0]
        self.assertEqual(start["approvalMode"], "allowAll")                   # ...which is what makes this safe
        self.assertEqual(start["modelId"], "muse-spark-1.3")
        turn = self.rpc("turn/start")[0]
        self.assertEqual(turn["reasoningEffort"], "high")
        self.assertTrue(turn["input"][0]["text"].endswith("fix the failing test"))
        self.assertRegex(turn["commandId"], r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab]")   # UUIDv7, as the host demands

    def test_the_next_message_resumes_the_session_and_sends_only_what_is_new(self):
        msgs = [{"role": "user", "content": "fix it"},
                {"role": "assistant", "content": "done", "agent": {"source": "muse", "id": "sess-1", "cwd": self.tmp}},
                {"role": "user", "content": "now add a test"}]
        out = P.cli_stream("muse-cli", "default", msgs, cwd=self.tmp)
        self.assertEqual(out["content"], "Done: fixed the test.")
        self.assertEqual(self.rpc("session/resume")[0]["sessionId"], "sess-1")
        self.assertFalse(self.rpc("session/start"))
        self.assertEqual(self.rpc("turn/start")[0]["input"][0]["text"], "now add a test")
        self.assertNotIn("--model", self.calls()[0]["argv"])                  # "default" is the agent's own choice

    def test_a_vanished_session_falls_back_to_the_whole_conversation(self):
        msgs = [{"role": "user", "content": "fix it"},
                {"role": "assistant", "content": "done", "agent": {"source": "muse", "id": "gone", "cwd": self.tmp}},
                {"role": "user", "content": "now add a test"}]
        out = P.cli_stream("muse-cli", "default", msgs, cwd=self.tmp)
        self.assertEqual(out["content"], "Done: fixed the test.")
        self.assertTrue(self.rpc("session/start"))
        text = self.rpc("turn/start")[0]["input"][0]["text"]
        self.assertIn("fix it", text); self.assertIn("now add a test", text)

    def test_a_temporary_chat_leaves_nothing(self):
        out = P.cli_stream("muse-cli", "default", [{"role": "user", "content": "secret"}], cwd=self.tmp, temp=True)
        self.assertIn("--no-session-log", self.calls()[0]["argv"])           # memory-only session
        self.assertNotIn("agent", out)                                         # and no marker to come back to

    def test_plan_mode_turns_writes_and_shell_off(self):
        P.cli_stream("muse-cli", "default", [{"role": "user", "content": "just look"}], cwd=self.tmp, read_only=True)
        argv = self.calls()[0]["argv"]
        self.assertIn("--disable-write", argv); self.assertIn("--disable-shell", argv)
        self.assertEqual(self.rpc("session/start")[0]["approvalMode"], "denyUnmatched")

    def test_a_failed_turn_says_why_and_a_sign_in_problem_says_how_to_fix_it(self):
        with mock.patch.dict(os.environ, {"FAKE_MUSE_FAIL": "model overloaded"}):
            with self.assertRaises(RuntimeError) as cm:
                P.cli_stream("muse-cli", "default", [{"role": "user", "content": "x"}], cwd=self.tmp)
        self.assertIn("model overloaded", str(cm.exception))
        with mock.patch.dict(os.environ, {"FAKE_MUSE_FAIL": "Unauthorized: invalid API key"}):
            with self.assertRaises(RuntimeError) as cm:
                P.cli_stream("muse-cli", "default", [{"role": "user", "content": "x"}], cwd=self.tmp)
        self.assertIn("/login", str(cm.exception)); self.assertIn("Settings", str(cm.exception))

    def test_stop_interrupts_the_turn(self):
        cancel = threading.Event(); cancel.set()
        slow = os.path.join(self.tmp, "muse")
        with open(slow, "w") as f:
            f.write(FAKE_MUSE.replace('note("turn/completed", turnId="t1", terminal="completed")',
                                      'import time; time.sleep(0.6); note("turn/completed", turnId="t1", terminal="cancelled")')
                    % {"py": sys.executable})
        P.cli_stream("muse-cli", "default", [{"role": "user", "content": "go"}], cwd=self.tmp, cancel=cancel)
        self.assertTrue(self.rpc("turn/interrupt"))

    def test_the_saved_key_is_passed_to_muse_code(self):
        with mock.patch.object(q, "secrets_load", lambda: {"MODEL_API_KEY": KEY}):
            env, who = q._cli_account_for("muse-cli", "muse-spark-1.3", [])
        self.assertEqual(env, {"META_API_KEY": KEY})
        with mock.patch.object(q, "secrets_load", lambda: {}), mock.patch.dict(os.environ, {"MODEL_API_KEY": "", "META_API_KEY": ""}):
            self.assertIsNone(q._cli_account_for("muse-cli", "x", []))     # its own browser sign-in then

    def test_status_for_settings(self):
        st = P.muse_status(fresh=True)
        self.assertTrue(st["installed"]); self.assertEqual(st["version"], "Muse Code 9.9.9")
        self.assertIn("dev.meta.ai/install.sh", st["install"])

    def test_opencode_gets_metas_built_in_provider_with_the_saved_key(self):
        with mock.patch.object(q, "secrets_load", lambda: {"MODEL_API_KEY": KEY}), mock.patch.object(q, "look_enabled", lambda e: False):
            env, who = q._cli_account_for("opencode-cli", "meta/muse-spark-1.3", [])
        cfg = json.loads(env["OPENCODE_CONFIG_CONTENT"])
        self.assertEqual(cfg["provider"]["meta"]["options"]["apiKey"], KEY)


@unittest.skipUnless(os.path.exists(os.path.expanduser("~/.local/bin/muse")), "Muse Code is not installed here")
class TestRealMuseCode(unittest.TestCase):
    """The real binary with its keyless echo provider: the protocol as it really is."""
    def setUp(self):
        import muse_msp
        self.M = muse_msp
        self.exe = os.path.expanduser("~/.local/bin/muse")
        self.tmp = tempfile.mkdtemp(prefix="orbit-muse-real-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.env = dict(os.environ, XDG_DATA_HOME=os.path.join(self.tmp, "xdg"))      # its sessions go in a folder of ours

    def test_a_turn_and_a_resume_against_the_real_host(self):
        got = self.M.run_turn(self.exe, "hello there", self.tmp, provider="echo", env=self.env)
        self.assertEqual(got["text"], "echo: hello there")
        again = self.M.run_turn(self.exe, "and again", self.tmp, provider="echo", env=self.env, resume=got["session"])
        self.assertEqual(again["text"], "echo: and again")
        self.assertEqual(again["session"], got["session"])

    def test_an_unknown_session_is_reported_as_gone(self):
        with self.assertRaises(self.M.MuseResumeError):
            self.M.run_turn(self.exe, "x", self.tmp, provider="echo", env=self.env, resume=self.M.uuid7())

    def test_a_memory_only_session_cannot_be_resumed(self):
        got = self.M.run_turn(self.exe, "private", self.tmp, provider="echo", env=self.env, temp=True)
        self.assertEqual(got["text"], "echo: private")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "xdg", "muse", "sessions", "2026")) and
                         any(files for _, _, files in os.walk(os.path.join(self.tmp, "xdg", "muse", "sessions"))
                             if any(f.endswith(".jsonl") for f in files)))


# ------------------------------------------------------------------ Muse Glimmer

class Ollama(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        data = json.dumps({"models": [{"name": "muse-glimmer:latest"}, {"name": "llama3:8b"}]} if self.path == "/api/tags"
                          else {"data": [{"id": "muse-glimmer"}]}).encode()
        self.send_response(200); self.send_header("content-length", str(len(data))); self.end_headers(); self.wfile.write(data)


class TestGlimmer(unittest.TestCase):
    def setUp(self):
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Ollama)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown)
        root = f"http://127.0.0.1:{self.srv.server_address[1]}"
        p = mock.patch.object(glimmer, "RUNTIMES", (("ollama", root, "ollama"), ("llama.cpp", "http://127.0.0.1:9", "llama")))
        p.start(); self.addCleanup(p.stop)
        glimmer._CACHE.update(at=0.0, rows=[])
        self.addCleanup(lambda: glimmer._CACHE.update(at=0.0, rows=[]))

    def test_it_finds_glimmer_among_what_is_served(self):
        rows = glimmer.served(force=True)
        self.assertEqual([r["id"] for r in rows], ["muse-glimmer:latest"])
        self.assertEqual(rows[0]["runtime"], "ollama")
        self.assertTrue(rows[0]["base"].endswith("/v1"))

    def test_it_is_in_the_pickers_while_served(self):
        glimmer.served(force=True)
        self.assertEqual([m["provider"] for m in P.glimmer_models()], ["glimmer"])
        ps = H.providers(ROOT)
        self.assertIn("glimmer", ps)
        self.assertEqual(ps["glimmer"]["models"][0]["id"], "muse-glimmer:latest")
        self.assertEqual(ps["glimmer"]["models"][0]["format"], "chat")

    def test_it_is_absent_when_nothing_serves_it(self):
        with mock.patch.object(glimmer, "RUNTIMES", (("ollama", "http://127.0.0.1:9", "ollama"),)):
            glimmer._CACHE.update(at=0.0, rows=[])
            self.assertEqual(glimmer.served(force=True), [])
            self.assertEqual(P.glimmer_models(), [])
            self.assertNotIn("glimmer", H.providers(ROOT))

    def test_status_gives_the_commands_and_a_memory_verdict(self):
        st = glimmer.status(fresh=True)
        self.assertIn("ollama run muse-glimmer", st["commands"]["ollama"])
        self.assertIn("Muse-Glimmer-30B-KQuant-17GB-Q4_K_M.gguf", st["commands"]["llama.cpp"])
        self.assertEqual(st["license"], "Apache 2.0")
        self.assertEqual(st["serving"][0]["runtime"], "ollama")


if __name__ == "__main__":
    unittest.main()
