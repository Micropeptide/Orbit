"""Pairing a browser, an Android phone or Orbit for Windows: a one-time link (and its QR)
that leaves the device a token of its own in a cookie. And the two things a browser fetches
without that cookie when it installs Orbit as an app -- the manifest and the icons -- which
are public, while nothing else is."""
import importlib.machinery, importlib.util, json, os, shutil, sys, tempfile, types, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "bin"))

import remote as R


def load_ui():
    loader = importlib.machinery.SourceFileLoader("orbit_ui_webpair", os.path.join(ROOT, "bin", "orbit-ui"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class TestDeviceNames(unittest.TestCase):
    def test_what_a_device_calls_itself(self):
        cases = {
            "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 Chrome/141.0 Mobile Safari/537.36": "Chrome on Android",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Orbit/0.3.0 Chrome/140 Electron/44.7.1 Safari/537.36": "Orbit for Windows",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/141 Safari/537.36 Edg/141": "Edge on Windows",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Gecko/20100101 Firefox/140.0": "Firefox on Mac",
            "": "Browser",
        }
        for ua, want in cases.items():
            self.assertEqual(R.device_name_from_agent(ua), want, ua)


class TestTheLink(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="orbit-webpair-")
        self.addCleanup(shutil.rmtree, self.root, True)
        os.makedirs(os.path.join(self.root, "config"))

    def test_one_code_for_the_link_and_its_qr_good_once(self):
        with mock.patch.object(R, "best_url", lambda mode, port: "https://mac.example.ts.net"), \
             mock.patch.object(R, "alt_urls", lambda mode, port: []), \
             mock.patch.object(R, "mac_name", lambda: "Test Mac"):
            link, png = R.web_pair(self.root, "tailscale", 8899)
        self.assertTrue(link.startswith("https://mac.example.ts.net/?c="))
        self.assertTrue(png.startswith(b"\x89PNG"))
        code = link.split("?c=")[1]
        tok, did = R.claim_code(self.root, code, name="Chrome on Android", via="web")
        self.assertTrue(tok and did)
        self.assertEqual(R.claim_code(self.root, code)[0], None)      # used up


class TestWhatIsPublic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = load_ui()
        cls.ui.start_turn = lambda *a, **k: None

    def get(self, path):
        ui, out = self.ui, types.SimpleNamespace(code=None)
        class Fake(ui.H):
            def __init__(self):
                self.path = path; self.command = "GET"; self.headers = {"Host": "mac.example.ts.net"}
                self.client_address = ("100.64.0.9", 5555)
            def _origin_ok(self): return True
            def _authorised(self): return False          # a device with no cookie
            def _refuse_unauthorised(self): out.code = 401
            def _send(self, code, b, ctype="application/json", headers=None): out.code = code
            def send_response(self, code, *a): out.code = code
            def send_header(self, *a): pass
            def end_headers(self): pass
            wfile = types.SimpleNamespace(write=lambda *a: None)
        Fake().do_GET()
        return out.code

    def test_the_manifest_and_icons_are(self):
        self.assertEqual(self.get("/manifest.json"), 200)
        self.assertEqual(self.get("/icons/orbit-192.png?v=2"), 200)

    def test_nothing_else_is(self):
        for p in ("/", "/api/sessions", "/guide.md", "/icons/../manifest.json", "/icons/x.txt"):
            self.assertEqual(self.get(p), 401, p)

    def test_a_chats_only_device_cannot_mint_links(self):
        self.assertTrue(any("/api/remote/weblink".startswith(x) for x in self.ui.H.ADMIN_PREFIXES))


if __name__ == "__main__":
    unittest.main()
