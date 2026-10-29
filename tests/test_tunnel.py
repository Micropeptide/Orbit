"""The internet door: a Cloudflare Tunnel fronted by Cloudflare Access.

What must hold: Orbit accepts a request that names the tunnel's hostname only with a live Access token for this
application (signature, audience, issuer, expiry); that a request which came through the tunnel is never mistaken for
"you at the Mac" just because it arrives over loopback; and that turning phone access off turns the door off."""
import http.client, importlib.machinery, importlib.util, json, os, sys, tempfile, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "bin"))

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import remote as R

TEAM = "example-team.cloudflareaccess.com"
AUD = "a" * 64
HOST = "phone.example.com"


def keypair():
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(k.public_key())); jwk.update(kid="k1", alg="RS256", use="sig")
    return pem, jwk


PEM, JWK = keypair()
OTHER_PEM, _ = keypair()


def token(pem=PEM, **over):
    now = int(time.time())
    claims = {"aud": [AUD], "iss": "https://" + TEAM, "iat": now, "exp": now + 600, "email": "someone@example.com"}
    claims.update(over)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, pem, algorithm="RS256", headers={"kid": "k1"})


class TunnelCase(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.file = os.path.join(d, "tunnel.json")
        self.env = mock.patch.dict(os.environ, {"ORBIT_TUNNEL_FILE": self.file}); self.env.start()
        self.addCleanup(self.env.stop)
        R._ACCESS_KEYS.update(at=0.0, tried=0.0, keys={})

    def write(self, **kw):
        json.dump({"host": HOST, "team": TEAM, "aud": AUD, **kw}, open(self.file, "w"))


class TestConfig(TunnelCase):
    def test_not_set_up(self):
        self.assertEqual(R.tunnel_config(), {})
        self.assertEqual(R.tunnel_host(), "")
        self.assertEqual(R.best_url("off", 8899), "")

    def test_set_up(self):
        self.write()
        self.assertEqual(R.tunnel_host(), HOST)
        self.assertEqual(R.best_url("tailscale", 8899), "https://" + HOST)

    def test_malformed_means_not_set_up(self):
        for bad in ({"host": "not a host"}, {"host": "a.b/evil"}, {"aud": "short"}, {"team": ""}, {"host": "localhost"}):
            self.write(**bad); self.assertEqual(R.tunnel_config(), {}, bad)
        open(self.file, "w").write("{nope")
        self.assertEqual(R.tunnel_config(), {})

    def test_off_means_the_door_is_shut(self):
        self.write()
        self.assertNotIn(HOST, R.reachable_hosts("off", 8899))
        self.assertEqual(R.best_url("off", 8899), "")
        for mode in ("tailscale", "lan"):
            with mock.patch.object(R, "tailscale_ip", return_value=""), mock.patch.object(R, "tailscale_name", return_value=""), \
                 mock.patch.object(R, "serve_map", return_value=[]):
                self.assertIn(HOST, R.reachable_hosts(mode, 8899))


class TestInternetMode(TunnelCase):
    def test_listens_on_loopback_only(self):
        self.write()
        self.assertEqual(R.bind_addresses("internet"), ["127.0.0.1"])

    def test_the_address_is_the_tunnels_and_nothing_else(self):
        self.write()
        self.assertEqual(R.best_url("internet", 8899), "https://" + HOST)
        self.assertEqual(R.alt_urls("internet", 8899), [])
        self.assertIn(HOST, R.reachable_hosts("internet", 8899))

    def test_without_the_door_there_is_no_address(self):
        self.assertEqual(R.best_url("internet", 8899), "")
        self.assertIn("not set up", R.status("/nonexistent", "internet", 8899)["hint"])


class TestAccessToken(TunnelCase):
    def check(self, tok, **kw):
        self.write()
        return R.access_jwt_ok(tok, R.tunnel_config(), fetch=lambda team: {"k1": JWK})

    def test_a_good_token(self):
        self.assertTrue(self.check(token()))

    def test_refuses(self):
        cases = {
            "no token": "",
            "garbage": "not.a.jwt",
            "signed with another key": token(OTHER_PEM),
            "another application": token(aud=["b" * 64]),
            "another team": token(iss="https://evil.cloudflareaccess.com"),
            "expired": token(exp=int(time.time()) - 5, iat=int(time.time()) - 900),
            "no expiry": token(exp=None),
            "no audience": token(aud=None),
        }
        for why, tok in cases.items():
            R._ACCESS_KEYS.update(at=0.0, tried=0.0, keys={})
            self.assertFalse(self.check(tok), why)

    def test_algorithm_confusion(self):
        """A token signed HS256 with the public key as the secret, or "none", must not pass."""
        for alg in ("HS256", "none"):
            self.write()
            now = int(time.time())
            claims = {"aud": [AUD], "iss": "https://" + TEAM, "iat": now, "exp": now + 600}
            try: tok = jwt.encode(claims, "x" * 40, algorithm=alg, headers={"kid": "k1"})
            except Exception: continue
            self.assertFalse(R.access_jwt_ok(tok, R.tunnel_config(), fetch=lambda t: {"k1": JWK}), alg)

    def test_fails_closed_when_the_key_cannot_be_fetched(self):
        self.write()
        def boom(team): raise OSError("no network")
        self.assertFalse(R.access_jwt_ok(token(), R.tunnel_config(), fetch=boom))

    def test_not_set_up_never_passes(self):
        self.assertFalse(R.access_jwt_ok(token(), {}, fetch=lambda t: {"k1": JWK}))


def load_ui():
    loader = importlib.machinery.SourceFileLoader("orbit_ui_tunnel", os.path.join(ROOT, "bin", "orbit-ui"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec); loader.exec_module(mod)
    return mod


class TestGate(TunnelCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = load_ui()

    def handler(self, headers, peer="127.0.0.1"):
        h = object.__new__(self.ui.H)
        h.client_address = (peer, 5555)
        msg = http.client.HTTPMessage()
        for k, v in headers.items(): msg[k] = v
        h.headers = msg
        return h

    def test_a_local_request_is_still_local(self):
        port = self.ui.PORT
        for host in (f"127.0.0.1:{port}", f"localhost:{port}", None):
            self.assertTrue(self.handler({"Host": host} if host else {})._from_loopback(), host)

    def test_a_tunnelled_request_is_never_local(self):
        port = self.ui.PORT
        for hdrs in ({"Host": HOST}, {"Host": f"127.0.0.1:{port}", "Cf-Ray": "abc"}, {"Host": f"127.0.0.1:{port}", "X-Forwarded-For": "1.2.3.4"},
                     {"Host": f"localhost:{port}", "Cf-Connecting-Ip": "1.2.3.4"}, {"Host": f"127.0.0.1:{port}", "Cf-Access-Jwt-Assertion": "x"},
                     {"Host": f"127.0.0.1:{port}", "Forwarded": "for=1.2.3.4"}, {"Host": "evil.example"}):
            self.assertFalse(self.handler(hdrs)._from_loopback(), hdrs)
        self.assertFalse(self.handler({}, peer="203.0.113.9")._from_loopback())

    def test_the_tunnel_hostname_needs_an_access_token(self):
        self.write()
        with mock.patch.object(R, "_fetch_access_keys", lambda team: {"k1": JWK}):
            self.assertFalse(self.handler({"Host": HOST})._tunnel_ok())
            self.assertFalse(self.handler({"Host": HOST, "Cf-Access-Jwt-Assertion": token(OTHER_PEM)})._tunnel_ok())
            self.assertTrue(self.handler({"Host": HOST, "Cf-Access-Jwt-Assertion": token()})._tunnel_ok())

    def test_other_hostnames_are_not_asked_for_one(self):
        self.write()
        self.assertTrue(self.handler({"Host": f"127.0.0.1:{self.ui.PORT}"})._tunnel_ok())

    def test_origin_check_includes_the_gate(self):
        self.write()
        h = self.handler({"Host": HOST})
        with mock.patch.object(self.ui, "allowed_hosts", return_value={HOST}), mock.patch.object(self.ui, "allowed_origins", return_value={"https://" + HOST}):
            self.assertFalse(h._origin_ok())


if __name__ == "__main__":
    unittest.main()
