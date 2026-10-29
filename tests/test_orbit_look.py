"""bin/orbit-look: the MCP server that gives an agent eyes (browser, iOS Simulator, Mac windows).

Unit tests need no browser and no simulator: the WebSocket client runs against an in-test
echo server, simctl/AXe calls are captured with subprocess.run patched. The integration
tests drive a real headless Chrome against a local page and are skipped without Chrome.
The simulator smoke runs only with ORBIT_TEST_SIMULATOR=1."""
import base64, importlib.machinery, importlib.util, json, os, shutil, signal, socket, struct
import subprocess, sys, tempfile, threading, time, unittest, zlib
import hashlib
import http.server
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOOK_PATH = os.path.join(ROOT, "bin", "orbit-look")


def load():
    loader = importlib.machinery.SourceFileLoader("orbit_look", LOOK_PATH)
    spec = importlib.util.spec_from_loader("orbit_look", loader)
    mod = importlib.util.module_from_spec(spec)
    keep, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try: loader.exec_module(mod)
    finally: sys.dont_write_bytecode = keep
    return mod


look = load()

EXPECTED_TOOLS = {
    "browser_open", "browser_snapshot", "browser_screenshot", "browser_click", "browser_type", "browser_press",
    "browser_scroll", "browser_back", "browser_reload", "browser_eval", "browser_console", "browser_resize", "browser_close",
    "simulator_devices", "simulator_boot", "simulator_install", "simulator_launch", "simulator_terminate",
    "simulator_open_url", "simulator_screenshot", "simulator_shutdown", "simulator_logs", "simulator_tap",
    "simulator_swipe", "simulator_type", "simulator_button", "simulator_ui",
    "simulator_tap_element", "simulator_long_press", "simulator_drag", "simulator_key", "simulator_gesture",
    "mac_windows", "mac_launch", "mac_screenshot", "mac_quit",
    "screen_look", "screen_click", "screen_move", "screen_drag", "screen_type", "screen_key", "screen_scroll",
}
try: CHROME = look.find_chrome()
except look.ToolError: CHROME = None


def png_bytes(w, h):
    raw = b"".join(b"\x00" + b"\x80\x80\x80" * w for _ in range(h))
    def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def text_of(res):
    return "\n".join(p["text"] for p in res["content"] if p["type"] == "text")


def images_of(res):
    return [p for p in res["content"] if p["type"] == "image"]


class TmpDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="olt-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        p = mock.patch.dict(os.environ, {"ORBIT_LOOK_DIR": os.path.join(self.tmp, "shots")})
        p.start(); self.addCleanup(p.stop)


# ------------------------------------------------------------------------ JSON-RPC

class TestProtocol(unittest.TestCase):
    def test_initialize_ping_list_unknown(self):
        r = look.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
        self.assertEqual(r["id"], 1)
        self.assertEqual(r["result"]["protocolVersion"], "2024-11-05")
        self.assertIn("tools", r["result"]["capabilities"])
        self.assertEqual(r["result"]["serverInfo"]["name"], "orbit-look")
        self.assertEqual(look.handle({"jsonrpc": "2.0", "id": 2, "method": "ping"})["result"], {})
        tools = look.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})["result"]["tools"]
        self.assertEqual({t["name"] for t in tools}, {n for n in EXPECTED_TOOLS if not n.startswith("screen_")})
        bad = look.handle({"jsonrpc": "2.0", "id": 4, "method": "resources/list"})
        self.assertEqual(bad["error"]["code"], -32601)
        self.assertEqual(look.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "nope"}})["error"]["code"], -32602)

    def test_notifications_get_no_reply(self):
        self.assertIsNone(look.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_tool_errors_are_results_not_crashes(self):
        r = look.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "browser_click", "arguments": {}}})
        self.assertNotIn("error", r)
        self.assertTrue(r["result"]["isError"])
        r = look.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "browser_open", "arguments": {}}})
        self.assertTrue(r["result"]["isError"])
        self.assertIn("url", r["result"]["content"][0]["text"])

    def test_stdio_framing_and_exit_on_eof(self):
        p = subprocess.Popen([sys.executable, LOOK_PATH], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True)
        self.addCleanup(lambda: p.poll() is None and p.kill())
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "ping"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 4, "method": "no/such"}]
        p.stdin.write("\n".join(json.dumps(m) for m in msgs) + "\nnot json\n")
        p.stdin.flush()
        got = {}
        for _ in range(5):                                   # 4 replies + the parse error
            r = json.loads(p.stdout.readline())
            got[r["id"]] = r
        self.assertEqual(got[2]["result"], {})
        self.assertEqual(len(got[3]["result"]["tools"]), len([n for n in EXPECTED_TOOLS if not n.startswith("screen_")]))
        self.assertEqual(got[4]["error"]["code"], -32601)
        self.assertEqual(got[None]["error"]["code"], -32700)
        p.stdin.close()
        self.assertEqual(p.wait(timeout=10), 0)

    def test_selftest(self):
        out = subprocess.run([sys.executable, LOOK_PATH, "--selftest"], capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0)
        self.assertEqual(set(out.stdout.split()[4:]), EXPECTED_TOOLS)


class TestToolDefinitions(unittest.TestCase):
    TYPES = {"string", "integer", "number", "boolean", "array", "object"}

    def test_every_tool_is_described_and_schema_valid(self):
        self.assertEqual(set(look.TOOLS), EXPECTED_TOOLS)
        for name, t in look.TOOLS.items():
            self.assertRegex(name, r"^[a-z]+(_[a-z]+)+$")
            self.assertGreater(len(t["description"]), 30, name)
            s = t["inputSchema"]
            self.assertEqual(s["type"], "object", name)
            for prop, spec in s["properties"].items():
                types = spec["type"] if isinstance(spec["type"], list) else [spec["type"]]
                self.assertTrue(set(types) <= self.TYPES, (name, prop))
                self.assertTrue(spec.get("description"), (name, prop))
                if "array" in types: self.assertIn("items", spec, (name, prop))
            self.assertTrue(set(s["required"]) <= set(s["properties"]), name)
            json.dumps(s)

    def test_arguments_are_coerced_and_required_enforced(self):
        schema = look.TOOLS["browser_open"]["inputSchema"]
        self.assertEqual(look.coerce({"url": "http://x", "width": "800", "mobile": "true"}, schema),
                         {"url": "http://x", "width": 800, "mobile": True})
        with self.assertRaises(look.ToolError): look.coerce({}, schema)
        with self.assertRaises(look.ToolError): look.coerce({"url": "u", "width": "wide"}, schema)


# ------------------------------------------------------------------------ WebSocket

class EchoServer:
    """A tiny RFC 6455 server: echoes messages, and on command misbehaves in the ways a client must survive."""

    def __init__(self):
        self.srv = socket.socket(); self.srv.bind(("127.0.0.1", 0)); self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.masked_ok, self.pongs, self.frames_in = [], [], []
        threading.Thread(target=self.run, daemon=True).start()

    @staticmethod
    def frame(op, payload, fin=True):
        n = len(payload)
        h = bytes([(0x80 if fin else 0) | op])
        if n < 126: h += bytes([n])
        elif n < 65536: h += bytes([126]) + struct.pack(">H", n)
        else: h += bytes([127]) + struct.pack(">Q", n)
        return h + payload

    def read(self, c, n):
        b = b""
        while len(b) < n:
            d = c.recv(n - len(b))
            if not d: raise EOFError
            b += d
        return b

    def run(self):
        c, _ = self.srv.accept()
        req = b""
        while b"\r\n\r\n" not in req: req += c.recv(1024)
        key = [l.split(b":", 1)[1].strip() for l in req.split(b"\r\n") if l.lower().startswith(b"sec-websocket-key")][0]
        acc = base64.b64encode(hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest())
        c.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: " + acc + b"\r\n\r\n")
        try:
            while True:
                b0, b1 = self.read(c, 2)
                op, n = b0 & 0x0F, b1 & 0x7F
                self.masked_ok.append(bool(b1 & 0x80))
                if n == 126: n = struct.unpack(">H", self.read(c, 2))[0]
                elif n == 127: n = struct.unpack(">Q", self.read(c, 8))[0]
                mask = self.read(c, 4)
                data = bytearray(self.read(c, n))
                for i in range(n): data[i] ^= mask[i % 4]
                data = bytes(data)
                if op == 0xA: self.pongs.append(data); continue
                if op == 0x8: c.sendall(self.frame(0x8, data)); return
                text = data.decode() if op == 1 else None
                if text == "FRAG":                         # "abc" "def" "ghi", with a ping in the middle
                    c.sendall(self.frame(1, b"abc", fin=False) + self.frame(0x9, b"hi") + self.frame(0, b"def", fin=False) + self.frame(0, b"ghi"))
                elif text == "PING": c.sendall(self.frame(0x9, b"are-you-there")); c.sendall(self.frame(1, b"after-ping"))
                elif text == "CLOSE": c.sendall(self.frame(0x8, struct.pack(">H", 1000)))
                else: c.sendall(self.frame(op, data))
        except (EOFError, OSError):
            pass


class TestWebSocket(unittest.TestCase):
    def setUp(self):
        self.srv = EchoServer()
        self.ws = look.WS("ws://127.0.0.1:%d/x" % self.srv.port)
        self.addCleanup(self.ws.close)

    def test_text_roundtrip_is_masked(self):
        self.ws.send("héllo")
        self.assertEqual(self.ws.recv(5), "héllo")
        self.assertTrue(all(self.srv.masked_ok))

    def test_large_payload_200kb(self):
        blob = ("x" * 1000 + "é") * 200
        self.ws.send(blob)
        self.assertEqual(self.ws.recv(10), blob)
        raw = os.urandom(300000)
        self.ws.send(raw)
        self.assertEqual(self.ws.recv(10), raw)

    def test_fragmented_message_with_ping_between(self):
        self.ws.send("FRAG")
        self.assertEqual(self.ws.recv(5), "abcdefghi")
        time.sleep(0.2)
        self.assertEqual(self.srv.pongs, [b"hi"])

    def test_ping_is_answered_and_following_message_arrives(self):
        self.ws.send("PING")
        self.assertEqual(self.ws.recv(5), "after-ping")
        time.sleep(0.2)
        self.assertEqual(self.srv.pongs, [b"are-you-there"])

    def test_timeout_keeps_the_connection_usable(self):
        with self.assertRaises(socket.timeout): self.ws.recv(0.2)
        self.ws.send("again")
        self.assertEqual(self.ws.recv(5), "again")

    def test_close_frame_raises(self):
        self.ws.send("CLOSE")
        with self.assertRaises(ConnectionError): self.ws.recv(5)

    def test_mask_helper(self):
        self.assertEqual(look.ws_mask(b"", b"abcd"), b"")
        data, key = os.urandom(1001), os.urandom(4)
        self.assertEqual(look.ws_mask(look.ws_mask(data, key), key), data)
        self.assertEqual(look.ws_mask(b"\x01\x02\x03\x04\x05", b"\xff\x00\xff\x00"), bytes([0xFE, 2, 0xFC, 4, 0xFA]))


# ------------------------------------------------------------------------ browser helpers (no browser)

class TestBrowserHelpers(TmpDirTest):
    def test_snapshot_number_parsing(self):
        P = look.parse_ref
        self.assertEqual(P(3), ("n", 3))
        self.assertEqual(P("3"), ("n", 3))
        self.assertEqual(P("[12]"), ("n", 12))
        self.assertEqual(P(4.0), ("n", 4))
        self.assertEqual(P("#go"), ("css", "#go"))
        self.assertEqual(P("button.primary"), ("css", "button.primary"))
        for bad in (None, "", True):
            with self.assertRaises(look.ToolError): P(bad)

    def test_number_vs_selector_in_the_script(self):
        self.assertIn('{"n": 7}', look.resolve_js(("n", 7)))
        js = look.resolve_js(("css", 'a[href="x"]'))
        self.assertIn('"css": "a[href=\\"x\\"]"', js)
        self.assertNotIn("__SPEC__", js)

    def test_resolution_against_a_fake_page(self):
        b = look.Browser()
        seen = []
        def fake(expr, timeout=30):
            seen.append(expr)
            return {"value": b.fake_reply}
        b.evaluate = fake
        b.fake_reply = {"ok": True, "x": 10, "y": 20}
        self.assertEqual(b.resolve("[2]")["x"], 10)
        b.fake_reply = {"ok": False, "why": "stale"}
        with self.assertRaisesRegex(look.ToolError, r"Element \[2\].*browser_snapshot"): b.resolve(2)
        b.fake_reply = {"ok": False, "why": "nomatch"}
        with self.assertRaisesRegex(look.ToolError, "No element matches"): b.resolve("#nope")
        b.fake_reply = {"ok": False, "why": "hidden"}
        with self.assertRaisesRegex(look.ToolError, "hidden"): b.resolve("#h")

    def test_snapshot_text_lists_numbered_elements(self):
        txt = look.fmt_snapshot({
            "title": "T", "url": "http://x/", "text": "Hello", "total": 3,
            "scroll": {"x": 0, "y": 0, "w": 1280, "h": 2000, "vw": 1280, "vh": 800},
            "elements": [{"role": "button", "label": "Go", "x": 1, "y": 2, "w": 30, "h": 10},
                         {"role": "input:text", "label": "Name", "value": "bob", "x": 5, "y": 6, "w": 7, "h": 8},
                         {"role": "link", "label": "More", "href": "/m", "x": 0, "y": 900, "w": 5, "h": 5, "off": "below"}]})
        self.assertIn('[0] button "Go" @ 1,2 30x10', txt)
        self.assertIn("[1] input:text \"Name\" value='bob'", txt)
        self.assertIn("[2] link \"More\" -> /m", txt)
        self.assertIn("below the viewport", txt)
        self.assertIn("Title: T", txt)

    def test_keys(self):
        self.assertEqual(look.parse_key("Enter")["text"], "\r")
        self.assertEqual(look.parse_key("Tab")["windowsVirtualKeyCode"], 9)
        ev = look.parse_key("Control+a")
        self.assertEqual((ev["modifiers"], ev["commands"]), (2, ["selectAll"]))
        self.assertNotIn("text", ev)
        self.assertEqual(look.parse_key("x")["text"], "x")
        with self.assertRaises(look.ToolError): look.parse_key("Hyper+z")
        with self.assertRaises(look.ToolError): look.parse_key("NotAKey")

    def test_only_web_and_file_schemes(self):
        for bad in ("javascript:alert(1)", "chrome://settings", "data:text/html,hi", "about:blank", "ftp://x/y", "view-source:http://x"):
            with self.assertRaises(look.ToolError, msg=bad): look.check_url(bad)
        with self.assertRaisesRegex(look.ToolError, "http://localhost:3000"): look.check_url("localhost:3000")
        for ok in ("http://127.0.0.1:8000/a?b=1", "https://example.com", "file:///tmp/x.html"):
            self.assertEqual(look.check_url(ok), ok)

    def test_refused_scheme_never_starts_a_browser(self):
        with mock.patch.object(look.B, "start", side_effect=AssertionError("started a browser")):
            for url in ("javascript:alert(1)", "chrome://version"):
                res = look.call_tool("browser_open", {"url": url})
                self.assertTrue(res["isError"])
                self.assertIn("http, https and file", text_of(res))

    def test_find_chrome_honours_env_and_explains_when_missing(self):
        with mock.patch.dict(os.environ, {"ORBIT_LOOK_CHROME": "/no/such/browser"}):
            with self.assertRaisesRegex(look.ToolError, "ORBIT_LOOK_CHROME"): look.find_chrome()
        fake = os.path.join(self.tmp, "chromeish")
        open(fake, "w").write("#!/bin/sh\n"); os.chmod(fake, 0o755)
        with mock.patch.dict(os.environ, {"ORBIT_LOOK_CHROME": fake}):
            self.assertEqual(look.find_chrome(), fake)
        with mock.patch.dict(os.environ, {"ORBIT_LOOK_CHROME": ""}), mock.patch.object(look, "app_executable", return_value=None), \
                mock.patch.object(look.shutil, "which", return_value=None):
            with self.assertRaisesRegex(look.ToolError, "brew install --cask google-chrome"): look.find_chrome()

    def test_browser_flags_are_isolated_and_headless_by_default(self):
        f = look.chrome_flags("/p/orbit-look-x")
        self.assertIn("--headless=new", f)
        self.assertIn("--user-data-dir=/p/orbit-look-x", f)
        self.assertIn("--remote-debugging-port=0", f)
        self.assertIn("--disable-extensions", f)
        self.assertNotIn("--headless=new", look.chrome_flags("/p", headed=True))

    def test_console_and_snapshot_without_a_browser(self):
        self.assertIn("No browser", text_of(look.call_tool("browser_console", {})))
        res = look.call_tool("browser_snapshot", {})
        self.assertTrue(res["isError"])
        self.assertIn("browser_open", text_of(res))


# ------------------------------------------------------------------------ screenshots on disk

class TestShots(TmpDirTest):
    def test_prune_keeps_newest_and_leaves_other_files(self):
        d = os.path.join(self.tmp, "p"); os.makedirs(d)
        for i in range(70):
            p = os.path.join(d, "orbit-look-%03d.png" % i)
            open(p, "wb").write(b"x"); os.utime(p, (1000 + i, 1000 + i))
        keepme = os.path.join(d, "notes.txt"); open(keepme, "w").write("mine")
        look.prune_shots(d, keep=60)
        names = sorted(os.listdir(d))
        self.assertEqual(len([n for n in names if n.endswith(".png")]), 60)
        self.assertIn("notes.txt", names)
        self.assertNotIn("orbit-look-000.png", names)
        self.assertIn("orbit-look-069.png", names)

    def test_saved_screenshot_is_capped_to_1568(self):
        data = png_bytes(2400, 60)
        path, w, h = look.save_png_bytes(data, "t")
        self.assertTrue(path.startswith(os.environ["ORBIT_LOOK_DIR"]))
        if shutil.which("sips"):
            self.assertLessEqual(max(w, h), 1568)
            self.assertEqual(look.png_size(path), (w, h))
        small, sw, sh = look.save_png_bytes(png_bytes(100, 50), "t")
        self.assertEqual((sw, sh), (100, 50))

    def test_not_a_png_is_an_error(self):
        p = os.path.join(self.tmp, "x.png"); open(p, "wb").write(b"nope" * 10)
        with self.assertRaises(look.ToolError): look.png_size(p)

    def test_image_part_shape(self):
        p, _, _ = look.save_png_bytes(png_bytes(8, 8), "t")
        part = look.image_part(p)
        self.assertEqual((part["type"], part["mimeType"]), ("image", "image/png"))
        self.assertEqual(base64.b64decode(part["data"])[:8], b"\x89PNG\r\n\x1a\n")


# ------------------------------------------------------------------------ simulator (subprocess.run patched)

UDID_A, UDID_B = "AAAAAAAA-0000-0000-0000-000000000001", "BBBBBBBB-0000-0000-0000-000000000002"


def sim_json(booted=(UDID_A,)):
    st = lambda u: "Booted" if u in booted else "Shutdown"
    return json.dumps({"devices": {
        "com.apple.CoreSimulator.SimRuntime.iOS-26-5": [
            {"udid": UDID_A, "name": "iPhone 17 Pro", "state": st(UDID_A), "isAvailable": True},
            {"udid": UDID_B, "name": "iPad Air", "state": st(UDID_B), "isAvailable": True}],
        "com.apple.CoreSimulator.SimRuntime.iOS-18-0": [
            {"udid": "CCCCCCCC-0000-0000-0000-000000000003", "name": "iPhone 17 Pro", "state": "Shutdown", "isAvailable": True},
            {"udid": "DDDDDDDD-0000-0000-0000-000000000004", "name": "Gone", "state": "Shutdown", "isAvailable": False}]}})


class FakeRun:
    """Stands in for subprocess.run: records every call, answers simctl list, writes a PNG for screenshots."""

    def __init__(self, booted=(UDID_A,), fail=None, png=(1206, 2622)):
        self.calls, self.booted, self.fail, self.png = [], booted, fail or {}, png

    def __call__(self, cmd, **kw):
        self.calls.append((list(cmd), kw))
        out, rc, err = "", 0, ""
        if cmd[:4] == ["xcrun", "simctl", "list", "devices"]: out = sim_json(self.booted)
        elif cmd[:3] == ["xcrun", "simctl", "io"]:
            open(cmd[-1], "wb").write(png_bytes(*self.png))
        elif cmd[:3] == ["xcrun", "simctl", "launch"] or "--terminate-running-process" in cmd: out = "com.example.App: 4242\n"
        for key, (frc, fout, ferr) in self.fail.items():
            if key in cmd: rc, out, err = frc, fout, ferr
        return subprocess.CompletedProcess(cmd, rc, out, err)

    def simctl(self):
        return [c for c, _ in self.calls if c[:2] == ["xcrun", "simctl"] and c[2] != "list"]


class TestSimulator(TmpDirTest):
    def run_tool(self, name, args=None, fake=None, which=None):
        fake = fake or FakeRun()
        with mock.patch.object(look.subprocess, "run", fake), \
                mock.patch.object(look.shutil, "which", side_effect=lambda x: (which or {}).get(x)), \
                mock.patch.object(look.os, "access", return_value=False):
            return look.call_tool(name, args or {}), fake

    def test_devices_grouped_by_runtime_and_booted_marked(self):
        res, _ = self.run_tool("simulator_devices")
        t = text_of(res)
        self.assertLess(t.index("iOS 26.5"), t.index("iOS 18.0"))
        self.assertIn("* iPhone 17 Pro  " + UDID_A + "  BOOTED", t)
        self.assertIn("iPad Air", t)
        self.assertNotIn("Gone", t)
        self.assertIn("1 booted", t)

    def test_launch_builds_the_simctl_command(self):
        res, fake = self.run_tool("simulator_launch", {"bundle_id": "com.example.App", "args": ["-a", "b"], "env": {"MODE": "x"}})
        self.assertFalse(res.get("isError"), text_of(res))
        self.assertEqual(fake.simctl(), [["xcrun", "simctl", "launch", "--terminate-running-process", UDID_A, "com.example.App", "-a", "b"]])
        launch_kw = [kw for c, kw in fake.calls if "launch" in c][0]
        self.assertEqual(launch_kw["env"]["SIMCTL_CHILD_MODE"], "x")
        self.assertEqual(launch_kw["stdin"], subprocess.DEVNULL)
        self.assertIn("4242", text_of(res))
        res, fake = self.run_tool("simulator_launch", {"bundle_id": "com.example.App", "terminate_running": False})
        self.assertEqual(fake.simctl(), [["xcrun", "simctl", "launch", UDID_A, "com.example.App"]])

    def test_install_terminate_open_url_commands(self):
        app = os.path.join(self.tmp, "My.app"); os.makedirs(app)
        res, fake = self.run_tool("simulator_install", {"app_path": app})
        self.assertEqual(fake.simctl(), [["xcrun", "simctl", "install", UDID_A, app]])
        res, fake = self.run_tool("simulator_install", {"app_path": os.path.join(self.tmp, "nope.app")})
        self.assertTrue(res["isError"]); self.assertEqual(fake.simctl(), [])
        res, fake = self.run_tool("simulator_terminate", {"bundle_id": "com.example.App"})
        self.assertEqual(fake.simctl(), [["xcrun", "simctl", "terminate", UDID_A, "com.example.App"]])
        res, fake = self.run_tool("simulator_open_url", {"url": "myapp://x?y=1"})
        self.assertEqual(fake.simctl(), [["xcrun", "simctl", "openurl", UDID_A, "myapp://x?y=1"]])

    def test_which_device_when_ambiguous_or_none(self):
        res, _ = self.run_tool("simulator_screenshot", fake=FakeRun(booted=(UDID_A, UDID_B)))
        self.assertTrue(res["isError"])
        self.assertIn("Several simulators are booted", text_of(res))
        self.assertIn("device=", text_of(res))
        res, _ = self.run_tool("simulator_screenshot", fake=FakeRun(booted=()))
        self.assertIn("simulator_boot", text_of(res))
        res, _ = self.run_tool("simulator_launch", {"bundle_id": "a.b", "device": "iPad Air"}, fake=FakeRun())
        self.assertIn("simulator_boot", text_of(res))

    def test_name_matching_prefers_booted_then_newest_runtime(self):
        with mock.patch.object(look.subprocess, "run", FakeRun(booted=())):
            devs = look.sim_list()
        self.assertEqual(look.pick_device("iphone 17 pro", devs)["udid"], UDID_A)           # newest runtime
        self.assertEqual(look.pick_device(UDID_B.lower(), devs)["name"], "iPad Air")
        self.assertEqual(look.pick_device("ipad", devs)["udid"], UDID_B)
        with self.assertRaises(look.ToolError): look.pick_device("iPhone", devs + [dict(devs[1], name="iPhone SE")])
        with self.assertRaises(look.ToolError): look.pick_device("Pixel", devs)

    def test_boot_then_waits_for_bootstatus_and_shutdown_all(self):
        res, fake = self.run_tool("simulator_boot", {"device": "iPad Air"})
        self.assertEqual(fake.simctl(), [["xcrun", "simctl", "boot", UDID_B], ["xcrun", "simctl", "bootstatus", UDID_B]])
        self.assertIn("simulator_shutdown", text_of(res))
        res, fake = self.run_tool("simulator_boot", {"device": "iPhone 17 Pro"})
        self.assertIn("already booted", text_of(res)); self.assertEqual(fake.simctl(), [])
        res, fake = self.run_tool("simulator_shutdown", {"device": "all"})
        self.assertEqual(fake.simctl(), [["xcrun", "simctl", "shutdown", "all"]])
        res, fake = self.run_tool("simulator_shutdown", {})
        self.assertEqual(fake.simctl(), [["xcrun", "simctl", "shutdown", UDID_A]])

    def test_slow_boot_says_so(self):
        fake = FakeRun(fail={"bootstatus": (124, "", "timed out after 240s")})
        res, _ = self.run_tool("simulator_boot", {"device": "iPad Air"}, fake=fake)
        self.assertTrue(res["isError"])
        self.assertIn("slow or busy", text_of(res))

    def test_screenshot_works_without_axe_and_explains_points(self):
        res, fake = self.run_tool("simulator_screenshot")
        self.assertFalse(res.get("isError"), text_of(res))
        self.assertEqual(fake.simctl()[0][:5], ["xcrun", "simctl", "io", UDID_A, "screenshot"])
        t = text_of(res)
        self.assertIn("402 x 874 points", t)               # 1206x2622 px at 3x
        self.assertIn("without AXe", t)
        self.assertEqual(len(images_of(res)), 1)
        self.assertEqual(base64.b64decode(images_of(res)[0]["data"])[:8], b"\x89PNG\r\n\x1a\n")
        self.assertRegex(t, r"orbit-look-\d+-\d+-sim\.png")

    def test_logs_command(self):
        fake = FakeRun()
        res, _ = self.run_tool("simulator_logs", {"bundle_id_or_process": "MyApp", "seconds": 7}, fake=fake)
        cmd = fake.simctl()[0]
        self.assertEqual(cmd[:7], ["xcrun", "simctl", "spawn", UDID_A, "log", "show", "--last"])
        self.assertEqual(cmd[7], "7s")
        self.assertIn('process == "MyApp"', cmd[-1])
        self.assertIn("messageType == error", cmd[-1])
        res, fake = self.run_tool("simulator_logs", {"bundle_id_or_process": "MyApp", "errors_only": False})
        self.assertNotIn("messageType", fake.simctl()[0][-1])
        res, _ = self.run_tool("simulator_logs", {"bundle_id_or_process": 'x" OR 1==1'})
        self.assertTrue(res["isError"])

    def test_tap_needs_axe_exact_message(self):
        for name, args in (("simulator_tap", {"x": 1, "y": 2}), ("simulator_swipe", {"x1": 1, "y1": 2, "x2": 3, "y2": 4}),
                           ("simulator_type", {"text": "hi"}), ("simulator_button", {"name": "home"}), ("simulator_ui", {})):
            res, fake = self.run_tool(name, args)
            self.assertTrue(res["isError"], name)
            self.assertEqual(text_of(res), "Tapping needs AXe: brew install cameroncooke/axe/axe")
            self.assertEqual(fake.simctl(), [])

    def test_the_other_actions_need_axe_too(self):
        for name, args in (("simulator_tap_element", {"label": "Send"}), ("simulator_long_press", {"x": 1, "y": 2}),
                           ("simulator_drag", {"x1": 1, "y1": 2, "x2": 3, "y2": 4}), ("simulator_key", {"key": "return"}),
                           ("simulator_gesture", {"preset": "scroll-down"})):
            res, fake = self.run_tool(name, args)
            self.assertTrue(res["isError"], name)
            self.assertEqual(text_of(res), "Tapping needs AXe: brew install cameroncooke/axe/axe", name)

    def test_the_other_actions_through_axe(self):
        axe = ("axe", "/x/axe")
        self.assertEqual(look.input_cmd(axe, "tap_element", "U", label="Send", id=None, value=None, element_type="Button"),
                         ["/x/axe", "tap", "--label", "Send", "--element-type", "Button", "--udid", "U"])
        self.assertEqual(look.input_cmd(axe, "long_press", "U", x=10, y=20, seconds=1.5),
                         ["/x/axe", "touch", "-x", "10", "-y", "20", "--down", "--up", "--delay", "1.5", "--udid", "U"])
        self.assertEqual(look.input_cmd(axe, "drag", "U", x1=1, y1=2, x2=3, y2=4, duration=0.6),
                         ["/x/axe", "drag", "--start-x", "1", "--start-y", "2", "--end-x", "3", "--end-y", "4", "--duration", "0.6", "--udid", "U"])
        self.assertEqual(look.input_cmd(axe, "key", "U", code=40), ["/x/axe", "key", "40", "--udid", "U"])
        self.assertEqual(look.input_cmd(axe, "key_combo", "U", modifiers=[227], code=4),
                         ["/x/axe", "key-combo", "--modifiers", "227", "--key", "4", "--udid", "U"])
        self.assertEqual(look.input_cmd(axe, "gesture", "U", preset="scroll-up", screen=(393, 852)),
                         ["/x/axe", "gesture", "scroll-up", "--screen-width", "393", "--screen-height", "852", "--udid", "U"])
        with self.assertRaises(look.ToolError): look.input_cmd(("idb", "/x/idb"), "long_press", "U", x=1, y=2, seconds=1)

    def test_key_names_become_hid_codes(self):
        self.assertEqual([look.KEYCODES[k] for k in ("return", "delete", "a", "z", "1", "0", "up")], [40, 42, 4, 29, 30, 39, 82])
        res, _ = self.run_tool("simulator_key", {"key": "banana"}, which={"axe": "/opt/axe"})
        self.assertTrue(res["isError"]); self.assertIn("Unknown key", text_of(res))
        res, _ = self.run_tool("simulator_key", {"key": "a", "modifiers": ["hyper"]}, which={"axe": "/opt/axe"})
        self.assertIn("Unknown modifier", text_of(res))
        res, _ = self.run_tool("simulator_gesture", {"preset": "teleport"}, which={"axe": "/opt/axe"})
        self.assertIn("Unknown gesture", text_of(res))
        res, _ = self.run_tool("simulator_tap_element", {}, which={"axe": "/opt/axe"})
        self.assertIn("label, an id or a value", text_of(res))

    def test_input_commands_through_axe_and_idb(self):
        axe = ("axe", "/x/axe")
        self.assertEqual(look.input_cmd(axe, "tap", "U", x=10, y=20.5), ["/x/axe", "tap", "-x", "10", "-y", "20.5", "--udid", "U"])
        self.assertEqual(look.input_cmd(axe, "swipe", "U", x1=1, y1=2, x2=3, y2=4, duration=0.3),
                         ["/x/axe", "swipe", "--start-x", "1", "--start-y", "2", "--end-x", "3", "--end-y", "4", "--duration", "0.3", "--udid", "U"])
        self.assertEqual(look.input_cmd(axe, "type", "U", text="-hi"), ["/x/axe", "type", "--udid", "U", "--", "-hi"])
        self.assertEqual(look.input_cmd(axe, "button", "U", name="home"), ["/x/axe", "button", "home", "--udid", "U"])
        self.assertEqual(look.describe_cmd(axe, "U"), ["/x/axe", "describe-ui", "--udid", "U"])
        idb = ("idb", "/x/idb")
        self.assertEqual(look.input_cmd(idb, "tap", "U", x=1, y=2), ["/x/idb", "ui", "tap", "1", "2", "--udid", "U"])
        self.assertEqual(look.input_cmd(idb, "button", "U", name="side-button"), ["/x/idb", "ui", "button", "SIDE_BUTTON", "--udid", "U"])

    def test_tap_runs_axe_then_returns_the_screen(self):
        fake = FakeRun()
        with mock.patch.object(look.time, "sleep"):
            res, _ = self.run_tool("simulator_tap", {"x": 100, "y": 200}, fake=fake, which={"axe": "/opt/axe"})
        axe_calls = [c for c, _ in fake.calls if c[0] == "/opt/axe"]
        self.assertEqual(axe_calls[0], ["/opt/axe", "tap", "-x", "100", "-y", "200", "--udid", UDID_A])
        self.assertEqual(axe_calls[1][:2], ["/opt/axe", "describe-ui"])
        self.assertEqual(len(images_of(res)), 1)
        res, _ = self.run_tool("simulator_button", {"name": "volcano"}, which={"axe": "/opt/axe"})
        self.assertIn("Unknown button", text_of(res))

    def test_ui_tree_is_flattened_to_numbered_text(self):
        tree = json.dumps([{"type": "Application", "frame": {"x": 0, "y": 0, "width": 402, "height": 874}, "AXLabel": "App", "children": [
            {"type": "Button", "AXLabel": "Sign in", "AXUniqueId": "signin", "frame": {"x": 10, "y": 20, "width": 100, "height": 44}, "enabled": True},
            {"type": "TextField", "AXLabel": "Email", "AXValue": "a@b.c", "frame": {"x": 10, "y": 80, "width": 300, "height": 44}},
            {"type": "Other", "frame": {"x": 0, "y": 0, "width": 5, "height": 5}}]}])
        lines, screen = look.flatten_ui(tree)
        self.assertEqual(screen, (402, 874))
        self.assertEqual(lines[0], '[0] Button "Sign in" id=signin @ 10,20 100x44')
        self.assertEqual(lines[1], "[1] TextField \"Email\" value='a@b.c' @ 10,80 300x44")
        self.assertEqual(len(lines), 2)
        self.assertEqual(look.flatten_ui("not json at all")[0], ["not json at all"])

    def test_elements_off_the_screen_do_not_crowd_out_the_ones_on_it(self):
        rows = [{"type": "StaticText", "AXLabel": "old %d" % i, "frame": {"x": 0, "y": -3000 + i * 10, "width": 100, "height": 8}} for i in range(300)]
        tree = json.dumps([{"type": "Application", "frame": {"x": 0, "y": 0, "width": 402, "height": 874}, "children": rows + [
            {"type": "TextField", "AXLabel": "Message", "frame": {"x": 10, "y": 800, "width": 300, "height": 44}}]}])
        lines, screen = look.flatten_ui(tree)
        self.assertEqual(lines[0], '[0] TextField "Message" @ 10,800 300x44')
        self.assertEqual(lines[-1], "(300 more elements are off-screen: scroll to reach them)")
        self.assertEqual(len(lines), 2)

    def test_point_sizes(self):
        self.assertEqual(look.guess_points(1206, 2622)[:2], (402, 874))
        self.assertEqual(look.guess_points(2048, 2732)[:2], (1024, 1366))
        self.assertEqual(look.guess_points(2622, 1206)[:2], (874, 402))
        self.assertEqual(look.guess_points(750, 1334)[:2], (375, 667))


# ------------------------------------------------------------------------ Mac windows

class TestMac(TmpDirTest):
    WINS = [{"id": 11, "app": "My App", "title": "Main", "pid": 5, "x": 0, "y": 30, "w": 800, "h": 600},
            {"id": 12, "app": "My App", "title": "Prefs", "pid": 5, "x": 10, "y": 40, "w": 400, "h": 300},
            {"id": 13, "app": "Other", "title": "", "pid": 6, "x": 0, "y": 0, "w": 5, "h": 5}]

    def test_selection(self):
        S = look.select_windows
        self.assertEqual([w["id"] for w in S(self.WINS, app="my")], [11, 12])
        self.assertEqual([w["id"] for w in S(self.WINS, app="my", title_contains="pref")], [12])
        self.assertEqual([w["id"] for w in S(self.WINS, window_id=13)], [13])
        self.assertEqual(S(self.WINS, app="other"), [])           # a 5x5 sliver is not a window
        self.assertIn('id=11 app="My App" title="Main" pid=5 bounds=0,30 800x600', look.fmt_windows(self.WINS))

    def test_screenshot_uses_window_capture_and_no_shadow(self):
        calls = []
        def fake(cmd, timeout=30, env=None):
            calls.append(cmd)
            if cmd[0] == "screencapture": open(cmd[-1], "wb").write(png_bytes(40, 30))
            return (0, "", "")
        with mock.patch.object(look, "mac_window_list", return_value=self.WINS), mock.patch.object(look, "run_cmd", fake), \
                mock.patch.object(look, "ax_text", return_value=["[0] Button \"OK\""]):
            res = look.call_tool("mac_screenshot", {"app": "my app", "title_contains": "main"})
        self.assertFalse(res.get("isError"), text_of(res))
        self.assertEqual(calls[0][:5], ["screencapture", "-x", "-o", "-l", "11"])
        self.assertIn('Button "OK"', text_of(res))
        self.assertEqual(len(images_of(res)), 1)

    def test_no_match_lists_what_exists(self):
        with mock.patch.object(look, "mac_window_list", return_value=self.WINS):
            res = look.call_tool("mac_screenshot", {"app": "nothing"})
            self.assertTrue(res["isError"])
            self.assertIn("id=11", text_of(res))
            self.assertTrue(look.call_tool("mac_screenshot", {})["isError"])

    def test_screen_recording_permission_message(self):
        with mock.patch.object(look, "mac_window_list", return_value=self.WINS), \
                mock.patch.object(look, "run_cmd", return_value=(1, "", "could not create image from window")):
            res = look.call_tool("mac_screenshot", {"window_id": 11})
        self.assertTrue(res["isError"])
        self.assertIn("Screen Recording", text_of(res))
        self.assertIn("Privacy & Security", text_of(res))

    def test_quit_does_not_launch_a_stopped_app(self):
        calls = []
        def fake(cmd, timeout=30, env=None):
            calls.append(cmd)
            return (0, "no\n", "")
        with mock.patch.object(look, "run_cmd", fake):
            res = look.call_tool("mac_quit", {"app": "/x/My App.app"})
        self.assertIn("not running", text_of(res))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][-1], "My App")

    def test_quit_passes_the_name_as_an_argument_not_script_text(self):
        calls = []
        def fake(cmd, timeout=30, env=None):
            calls.append(cmd)
            return (0, "yes\n", "")
        with mock.patch.object(look, "run_cmd", fake):
            look.call_tool("mac_quit", {"app": 'Evil" & (do shell script "x") & "'})
        quit_cmd = calls[1]
        self.assertEqual(quit_cmd[-1], 'Evil" & (do shell script "x") & "')
        self.assertNotIn("Evil", " ".join(quit_cmd[:-1]))

    @unittest.skipUnless(sys.platform == "darwin", "macOS only")
    def test_window_list_reads_real_windows_shape(self):
        try: wins = look.mac_window_list()
        except look.ToolError: self.skipTest("window server not reachable here")
        for w in wins[:5]:
            self.assertEqual(set(w), {"id", "app", "pid", "title", "x", "y", "w", "h"})


# ------------------------------------------------------------------------ real browser

PAGE = """<!doctype html><html><head><title>Look Test</title></head><body>
<h1>Hello look</h1>
<button id="b" onclick="this.textContent='Clicked!'">Press me</button>
<input id="i" placeholder="Your name"><select id="s"><option>Red</option><option>Green</option></select>
<a id="l" href="/second">next page</a>
<div style="height:2500px">tall</div>
<script>console.error('boom-from-page'); fetch('/nope').catch(function(){});</script></body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/second": body, code = b"<title>Second</title><p>second page body</p>", 200
        elif self.path == "/": body, code = PAGE.encode(), 200
        else: body, code = b"missing", 404
        self.send_response(code); self.send_header("Content-Type", "text/html"); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def log_message(self, *a): pass


def chrome_procs(profile):
    out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
    return [l for l in out.splitlines() if profile and profile in l]


def wait_gone(profile, secs=12):
    end = time.time() + secs
    while time.time() < end:
        if not chrome_procs(profile): return True
        time.sleep(0.3)
    return False


@unittest.skipUnless(CHROME, "Google Chrome (or another Chromium browser) is not installed")
class TestBrowserIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="olt-")
        cls.env = mock.patch.dict(os.environ, {"ORBIT_LOOK_DIR": os.path.join(cls.tmp, "shots"), "ORBIT_LOOK_HEADED": ""})
        cls.env.start()
        cls.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        cls.profile = None

    @classmethod
    def tearDownClass(cls):
        look.call_tool("browser_close", {})
        cls.httpd.shutdown()
        cls.env.stop()
        shutil.rmtree(cls.tmp, True)

    def call(self, name, **args):
        res = look.call_tool(name, args)
        self.assertFalse(res.get("isError"), text_of(res))
        return res

    def test_01_whole_flow(self):
        res = self.call("browser_open", url=self.base + "/")
        TestBrowserIntegration.profile = look.B.tmp
        t = text_of(res)
        for s in ("Look Test", "Final URL: " + self.base + "/", "HTTP status: 200", "Hello look", 'button "Press me"', "next page"):
            self.assertIn(s, t)
        img = images_of(res)[0]
        raw = base64.b64decode(img["data"])
        self.assertEqual(raw[:8], b"\x89PNG\r\n\x1a\n")
        path = [l.split("saved: ")[1].split(" (")[0] for l in t.splitlines() if l.startswith("Screenshot saved: ")][0]
        self.assertTrue(os.path.isfile(path))
        self.assertLessEqual(max(look.png_size(path)), 1568)

        snap = text_of(self.call("browser_snapshot"))
        num = [l for l in snap.splitlines() if 'button "Press me"' in l][0].split("]")[0].lstrip("[")
        res = self.call("browser_click", element=int(num))
        self.assertIn("Clicked!", text_of(res))
        self.assertIn("Clicked <button> Press me", text_of(res))

        snap = text_of(self.call("browser_snapshot"))
        n_in = [l for l in snap.splitlines() if "Your name" in l][0].split("]")[0].lstrip("[")
        self.assertIn("hello world", text_of(self.call("browser_type", element=n_in, text="hello world")))
        self.assertIn("value='hello world'", text_of(self.call("browser_snapshot")))
        self.call("browser_type", element="#i", text="replaced")
        self.assertEqual(text_of(self.call("browser_eval", js="document.querySelector('#i').value")), '"replaced"')
        self.assertIn("Selected 'Green'", text_of(self.call("browser_type", element="#s", text="green")))
        self.assertEqual(text_of(self.call("browser_eval", js="document.querySelector('#s').value")), '"Green"')

        self.assertEqual(text_of(self.call("browser_eval", js="document.querySelector('#b').textContent")), '"Clicked!"')
        self.assertEqual(text_of(self.call("browser_eval", js="[1,2,3].map(x => x * 2)")), "[2, 4, 6]")
        self.assertEqual(text_of(self.call("browser_eval", js="Promise.resolve({a: 1})")), '{"a": 1}')
        err = look.call_tool("browser_eval", {"js": "nope.nope"})
        self.assertTrue(err["isError"]); self.assertIn("ReferenceError", text_of(err))

        con = text_of(self.call("browser_console"))
        self.assertIn("boom-from-page", con)
        self.assertIn("HTTP 404", con)
        self.assertIn("/nope", con)
        self.assertIn("No new console", text_of(self.call("browser_console")))

        res = self.call("browser_screenshot", full_page=True)
        self.assertEqual(base64.b64decode(images_of(res)[0]["data"])[:8], b"\x89PNG\r\n\x1a\n")
        res = self.call("browser_screenshot", element="#b")
        self.assertEqual(len(images_of(res)), 1)

    def test_02_navigation_and_stale_numbers(self):
        self.call("browser_open", url=self.base + "/")
        snap = text_of(self.call("browser_snapshot"))
        link = [l for l in snap.splitlines() if "next page" in l and l.startswith("[")][0].split("]")[0].lstrip("[")
        res = self.call("browser_click", element=link)
        self.assertIn("second page body", text_of(res))
        self.assertIn("Title: Second", text_of(res))
        stale = look.call_tool("browser_click", {"element": 99})
        self.assertTrue(stale["isError"])
        self.assertIn("browser_snapshot", text_of(stale))
        self.assertIn("Look Test", text_of(self.call("browser_back")))
        self.assertIn("Hello look", text_of(self.call("browser_reload")))
        bad = look.call_tool("browser_click", {"element": "#does-not-exist"})
        self.assertIn("No element matches", text_of(bad))
        self.assertTrue(look.call_tool("browser_click", {})["isError"])

    def test_03_coordinates_keys_scroll_and_resize(self):
        self.call("browser_open", url=self.base + "/", width=900, height=600)
        r = look.B.evaluate("(() => { const r = document.querySelector('#b').getBoundingClientRect(); return [r.x + 5, r.y + 5]; })()")["value"]
        self.assertIn("Clicked!", text_of(self.call("browser_click", x=r[0], y=r[1])))
        self.call("browser_type", element="#i", text="abc")
        self.call("browser_press", key="Control+a")
        self.call("browser_press", key="Backspace")
        self.assertEqual(text_of(self.call("browser_eval", js="document.querySelector('#i').value")), '""')
        self.call("browser_scroll", dy=700)
        self.assertGreater(float(text_of(self.call("browser_eval", js="window.scrollY"))), 100)
        self.assertEqual(text_of(self.call("browser_eval", js="innerWidth")), "900")
        res = self.call("browser_resize", width=390, height=700, mobile=True)
        self.assertIn("390x700", text_of(res))
        self.assertIn("iPhone", text_of(self.call("browser_eval", js="navigator.userAgent")))
        self.call("browser_resize", width=1280, height=800)
        self.assertEqual(text_of(self.call("browser_eval", js="innerWidth")), "1280")
        self.assertNotIn("iPhone", text_of(self.call("browser_eval", js="navigator.userAgent")))

    def test_04_failed_load_is_an_error_with_advice(self):
        res = look.call_tool("browser_open", {"url": "http://127.0.0.1:1/"})
        self.assertTrue(res["isError"])
        self.assertIn("Is the server running", text_of(res))

    def test_05_close_leaves_no_chrome_behind(self):
        self.call("browser_open", url=self.base + "/")
        profile = look.B.tmp
        self.assertTrue(chrome_procs(profile))
        self.assertIn("closed", text_of(self.call("browser_close")))
        self.assertTrue(wait_gone(profile), chrome_procs(profile))
        self.assertFalse(os.path.exists(profile))
        self.call("browser_open", url=self.base + "/")          # and it can start again
        self.assertNotEqual(look.B.tmp, profile)


@unittest.skipUnless(CHROME, "Google Chrome (or another Chromium browser) is not installed")
class TestNoOrphans(unittest.TestCase):
    """The server process is the thing that must never leave Chrome running."""

    def start(self):
        self.tmp = tempfile.mkdtemp(prefix="olt-", dir="/tmp")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.shutdown)
        env = dict(os.environ, TMPDIR=self.tmp, ORBIT_LOOK_DIR=os.path.join(self.tmp, "shots"))
        self.p = subprocess.Popen([sys.executable, LOOK_PATH], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, env=env)
        self.addCleanup(lambda: self.p.poll() is None and self.p.kill())
        req = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": "browser_open", "arguments": {"url": "http://127.0.0.1:%d/" % httpd.server_address[1]}}}
        self.p.stdin.write(json.dumps(req) + "\n"); self.p.stdin.flush()
        resp = json.loads(self.p.stdout.readline())
        self.assertFalse(resp["result"].get("isError"), resp)
        self.assertTrue(chrome_procs(self.tmp), "no browser process found under the test profile dir")

    def test_stdin_eof(self):
        self.start()
        self.p.stdin.close()
        self.assertEqual(self.p.wait(timeout=15), 0)
        self.assertTrue(wait_gone(self.tmp), chrome_procs(self.tmp))

    def test_sigterm(self):
        self.start()
        self.p.send_signal(signal.SIGTERM)
        self.p.wait(timeout=15)
        self.assertTrue(wait_gone(self.tmp), chrome_procs(self.tmp))

    def test_sigkill_of_the_server_is_cleaned_up_by_the_guard(self):
        self.start()
        self.p.kill(); self.p.wait(timeout=5)
        self.assertTrue(wait_gone(self.tmp, secs=20), chrome_procs(self.tmp))


# ------------------------------------------------------------------------ simulator smoke (opt-in)

@unittest.skipUnless(os.environ.get("ORBIT_TEST_SIMULATOR") == "1", "set ORBIT_TEST_SIMULATOR=1 to run against a real simulator")
class TestSimulatorSmoke(TmpDirTest):
    def test_devices_and_screenshot(self):
        before = look.sim_list()
        was_booted = [d for d in before if d["state"] == "Booted"]
        booted_here = False
        try:
            if not was_booted:
                iphone = [d for d in before if d["name"].startswith("iPhone")][0]
                booted_here = True
                res = look.call_tool("simulator_boot", {"device": iphone["udid"]})
                self.assertFalse(res.get("isError"), text_of(res))
            self.assertIn("BOOTED", text_of(look.call_tool("simulator_devices", {})))
            dev = (was_booted or [d for d in look.sim_list() if d["state"] == "Booted"])[0]["udid"]
            res = look.call_tool("simulator_screenshot", {"device": dev})
            self.assertFalse(res.get("isError"), text_of(res))
            self.assertEqual(base64.b64decode(images_of(res)[0]["data"])[:8], b"\x89PNG\r\n\x1a\n")
            self.assertIn("points", text_of(res))
        finally:
            if booted_here: subprocess.run(["xcrun", "simctl", "shutdown", "all"], timeout=120)


class TestGroups(unittest.TestCase):
    """Only the kinds of tool you switched on are offered, listed and callable."""
    def test_every_group_by_default(self):
        # the screen group is the exception: Orbit lists it only when Screen control is on
        old = os.environ.pop("ORBIT_LOOK_GROUPS", None)
        try:
            self.assertEqual(len(look.listed_tools()), len([n for n in look.TOOLS if not n.startswith("screen_")]))
        finally:
            if old is not None: os.environ["ORBIT_LOOK_GROUPS"] = old

    def test_a_group_can_be_left_out(self):
        os.environ["ORBIT_LOOK_GROUPS"] = "browser"
        try:
            names = [t["name"] for t in look.listed_tools()]
            self.assertTrue(names and all(n.startswith("browser_") for n in names))
            r = look.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                             "params": {"name": "simulator_devices", "arguments": {}}})
            self.assertEqual(r["error"]["code"], -32602)
        finally:
            del os.environ["ORBIT_LOOK_GROUPS"]


if __name__ == "__main__":
    unittest.main()
