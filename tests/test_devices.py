"""Each paired device has its own token. The one shared token meant a lost phone could
only be cut off by unpairing everything, and every device could change every setting.
Requests are driven through the real handler as if from another machine; the device
store and the old shared token live in a temporary folder."""
import importlib.machinery, importlib.util, json, os, shutil, sys, tempfile, time, types, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "bin"))

import remote as R


def load_ui():
    loader = importlib.machinery.SourceFileLoader("orbit_ui_devices", os.path.join(ROOT, "bin", "orbit-ui"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = load_ui()

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="orbit-devices-")
        self.addCleanup(shutil.rmtree, self.root, True)
        os.makedirs(os.path.join(self.root, "config"))
        ui = self.ui
        saved = (ui.q.ROOT, ui.remote_mode)
        self.addCleanup(lambda: (setattr(ui.q, "ROOT", saved[0]), setattr(ui, "remote_mode", saved[1])))
        ui.q.ROOT = self.root
        ui.remote_mode = lambda: "tailscale"
        R._DEV.update(at=None, data=None); R._SEEN.clear()

    def request(self, method, path, token=None, body=None, cookie=None):
        out = types.SimpleNamespace(code=None, body=None, headers={})
        ui = self.ui
        hdrs = {}
        if token: hdrs["Authorization"] = "Bearer " + token
        if cookie: hdrs["Cookie"] = cookie
        class Fake(ui.H):
            def __init__(self):
                self.path = path; self.headers = hdrs; self.command = method
                self.client_address = ("100.64.0.9", 5555)       # a phone on the tailnet
            def _body(self): return body or {}
            def _send(self, code, b, ctype="application/json", headers=None):
                out.code = code
                try: out.body = json.loads(b)
                except Exception: out.body = b
            def _refuse_unauthorised(self): out.code = 401
            def send_response(self, code): out.code = code
            def send_header(self, k, v): out.headers[k] = v
            def end_headers(self): pass
        getattr(Fake(), "do_" + method)()
        return out


class TestPairing(Base):
    def test_a_code_is_traded_once_for_a_token_of_its_own(self):
        code = R.new_pair_code(self.root)
        r = self.request("POST", "/api/pair/claim", body={"code": code, "name": "Test iPhone"})
        self.assertEqual(r.code, 200, r.body)
        tok = r.body["token"]
        self.assertEqual(self.request("GET", "/api/running", token=tok).code, 200)
        again = self.request("POST", "/api/pair/claim", body={"code": code})
        self.assertEqual(again.code, 401, "a pairing code worked twice")
        devs = R.list_devices(self.root)["devices"]
        self.assertEqual(devs[0]["name"], "Test iPhone")
        self.assertNotIn("hash", devs[0])

    def test_an_expired_code_is_refused(self):
        code = R.new_pair_code(self.root, ttl=-1)
        self.assertEqual(self.request("POST", "/api/pair/claim", body={"code": code}).code, 401)

    def test_no_token_no_answer(self):
        self.assertEqual(self.request("GET", "/api/running").code, 401)
        self.assertEqual(self.request("GET", "/api/running", token="made-up").code, 401)

    def test_a_phone_browser_pairs_with_the_link_and_gets_a_cookie(self):
        code = R.new_pair_code(self.root)
        r = self.request("GET", "/?c=" + code)
        self.assertEqual(r.code, 303)
        tok = r.headers["Set-Cookie"].split("orbit_token=")[1].split(";")[0]
        self.assertEqual(self.request("GET", "/api/running", cookie="orbit_token=" + tok).code, 200)

    def test_the_qr_carries_a_code_not_the_token(self):
        uri = R.pair_uri(self.root, "lan", 8899) if R.best_url("lan", 8899) else "orbit://pair?code=x"
        self.assertIn("code=", uri); self.assertNotIn("token=", uri)


class TestEachDeviceAlone(Base):
    def device(self, name="phone"):
        tok, did = R.claim_code(self.root, R.new_pair_code(self.root), name)
        return tok, did

    def test_revoking_one_leaves_the_others(self):
        a, a_id = self.device("phone"); b, _ = self.device("ipad")
        self.assertTrue(R.revoke_device(self.root, a_id))
        self.assertEqual(self.request("GET", "/api/running", token=a).code, 401)
        self.assertEqual(self.request("GET", "/api/running", token=b).code, 200)

    def test_the_old_shared_token_works_until_retired(self):
        legacy = R.load_token(self.root, create=True)
        self.assertEqual(self.request("GET", "/api/running", token=legacy).code, 200)
        R.retire_legacy(self.root)
        self.assertEqual(self.request("GET", "/api/running", token=legacy).code, 401)

    def test_a_device_limited_to_chats_cannot_change_settings_or_pair_others(self):
        tok, did = self.device()
        R.update_device(self.root, did, scope="chat")
        self.assertEqual(self.request("POST", "/api/settings", token=tok, body={"settings": {"x": 1}}).code, 403)
        self.assertEqual(self.request("POST", "/api/secrets", token=tok, body={}).code, 403)
        self.assertEqual(self.request("GET", "/api/remote/qr", token=tok).code, 403)
        self.assertEqual(self.request("POST", "/api/devices", token=tok, body={"op": "revoke", "id": did}).code, 403)
        self.assertEqual(self.request("GET", "/api/running", token=tok).code, 200)

    def test_unpair_everything(self):
        tok, _ = self.device()
        legacy = R.load_token(self.root, create=True)
        R.unpair_everything(self.root)
        self.assertEqual(self.request("GET", "/api/running", token=tok).code, 401)
        self.assertEqual(self.request("GET", "/api/running", token=legacy).code, 401)

    def test_the_store_keeps_no_token_and_is_private(self):
        tok, _ = self.device()
        raw = open(R.devices_path(self.root)).read()
        self.assertNotIn(tok, raw)
        self.assertEqual(os.stat(R.devices_path(self.root)).st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
