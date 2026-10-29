"""Verifying account tokens offline (bin/collab_accounts.py): every rule, every way to forge one, the key cache, and a cross-check
against the account service's own JavaScript (tokens signed there are verified here, and the other way round)."""
import base64
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
from cryptography.hazmat.primitives import serialization          # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

import collab_accounts as A                                          # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOW = 1_800_000_000
ISS = "https://orbit.example.test"


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def raw_pub(key):
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def jwk(key, kid):
    return {"kty": "OKP", "crv": "Ed25519", "x": b64u(raw_pub(key)), "kid": kid, "alg": "EdDSA", "use": "sig"}


def claims(**over):
    c = {"sub": "acc_1", "name": "Ada", "iat": NOW, "exp": NOW + 900, "iss": ISS, "aud": "orbit", "jti": "j1"}
    c.update(over)
    return {k: v for k, v in c.items() if v is not None}


def token(key, kid="k1", c=None, header=None, sign=True, sig=None):
    h = {"alg": "EdDSA", "typ": "JWT", "kid": kid}
    h.update(header or {})
    h = {k: v for k, v in h.items() if v is not None}
    seg = lambda o: b64u(json.dumps(o, separators=(",", ":")).encode())  # noqa: E731
    signing_input = seg(h) + "." + seg(claims() if c is None else c)
    if sig is None:
        sig = key.sign(signing_input.encode()) if sign else b""
    return signing_input + "." + b64u(sig)


class VerifyTokenTests(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        self.jwks = {"keys": [jwk(self.key, "k1")]}

    def reason(self, tok, **kw):
        kw.setdefault("now", NOW)
        with self.assertRaises(A.AccountTokenError) as cm:
            A.verify_token(tok, self.jwks, **kw)
        return cm.exception.reason

    def test_valid_token_returns_claims(self):
        c = A.verify_token(token(self.key), self.jwks, now=NOW, iss=ISS)
        self.assertEqual((c["sub"], c["name"], c["aud"], c["iss"]), ("acc_1", "Ada", "orbit", ISS))

    def test_optional_avatar_and_extra_claims_pass_through(self):
        c = A.verify_token(token(self.key, c=claims(avatar="https://img.example.com/a.png", did="dev_1")), self.jwks, now=NOW)
        self.assertEqual(c["avatar"], "https://img.example.com/a.png")

    def test_default_clock_is_the_real_one(self):
        import time
        t = time.time()
        tok = token(self.key, c=claims(iat=int(t), exp=int(t) + 900))
        self.assertEqual(A.verify_token(tok, self.jwks)["sub"], "acc_1")

    # -- algorithms -----------------------------------------------------------------------------------------------------------
    def test_alg_none_is_refused(self):
        self.assertEqual(self.reason(token(self.key, header={"alg": "none"}, sign=False)), "malformed")  # empty signature segment
        self.assertEqual(self.reason(token(self.key, header={"alg": "none"}, sig=b"\x01\x02")), "bad_alg")
        self.assertEqual(self.reason(token(self.key, header={"alg": "None"}, sig=b"\x01\x02")), "bad_alg")

    def test_hmac_with_the_public_key_as_secret_is_refused(self):
        pub = raw_pub(self.key)
        for alg, h in (("HS256", hashlib.sha256), ("HS384", hashlib.sha384), ("HS512", hashlib.sha512)):
            seg = lambda o: b64u(json.dumps(o).encode())  # noqa: E731
            inp = seg({"alg": alg, "kid": "k1"}) + "." + seg(claims())
            tok = inp + "." + b64u(hmac.new(pub, inp.encode(), h).digest())
            self.assertEqual(self.reason(tok), "bad_alg", alg)

    def test_other_algorithms_and_spellings_are_refused(self):
        for alg in ("RS256", "ES256", "PS256", "EdDSA2", "eddsa", "ed25519", "", None, 5, ["EdDSA"]):
            self.assertEqual(self.reason(token(self.key, header={"alg": alg})), "bad_alg", repr(alg))

    def test_critical_header_is_refused(self):
        self.assertEqual(self.reason(token(self.key, header={"crit": ["exp"]})), "unsupported_header")

    def test_a_key_embedded_in_the_token_is_never_used(self):
        attacker = Ed25519PrivateKey.generate()
        for extra in ({"jwk": jwk(attacker, "evil")}, {"jku": "https://evil.example.net/jwks"}, {"x5u": "https://evil.example.net/c"}):
            self.assertEqual(self.reason(token(attacker, kid="evil", header=extra)), "unknown_kid")
            self.assertEqual(self.reason(token(attacker, kid="k1", header=extra)), "bad_signature")

    # -- keys and signatures ----------------------------------------------------------------------------------------------------------
    def test_unknown_missing_and_mistyped_kid(self):
        self.assertEqual(self.reason(token(self.key, kid="other")), "unknown_kid")
        self.assertEqual(self.reason(token(self.key, kid=None)), "unknown_kid")
        self.assertEqual(self.reason(token(self.key, kid=7)), "unknown_kid")

    def test_signature_by_another_key_or_with_a_flipped_bit(self):
        self.assertEqual(self.reason(token(Ed25519PrivateKey.generate())), "bad_signature")
        good = token(self.key)
        sig = bytearray(base64.urlsafe_b64decode(good.split(".")[2] + "=="))
        sig[0] ^= 1
        self.assertEqual(self.reason(good.rsplit(".", 1)[0] + "." + b64u(bytes(sig))), "bad_signature")

    def test_changing_the_payload_after_signing_breaks_it(self):
        h, p, s = token(self.key).split(".")
        forged = json.loads(base64.urlsafe_b64decode(p + "=="))
        forged["sub"] = "acc_victim"
        self.assertEqual(self.reason(h + "." + b64u(json.dumps(forged).encode()) + "." + s), "bad_signature")

    def test_the_right_key_is_picked_by_kid_among_several(self):
        other = Ed25519PrivateKey.generate()
        jwks = {"keys": [jwk(other, "k0"), jwk(self.key, "k1")]}
        self.assertEqual(A.verify_token(token(self.key), jwks, now=NOW)["sub"], "acc_1")
        self.assertEqual(A.verify_token(token(other, kid="k0"), jwks, now=NOW)["sub"], "acc_1")

    def test_malformed_key_sets(self):
        for bad in (None, {}, {"keys": "x"}, {"keys": [{"kty": "OKP", "crv": "Ed25519", "kid": "k1", "x": "AAAA"}]},
                    {"keys": [jwk(self.key, "k1"), jwk(self.key, "k1")]}, "not json"):
            with self.assertRaises(A.AccountTokenError) as cm:
                A.verify_token(token(self.key), bad, now=NOW)
            self.assertIn(cm.exception.reason, ("bad_jwks",))
        # keys of other types are skipped, not fatal
        mixed = {"keys": [{"kty": "RSA", "kid": "r", "n": "AQAB", "e": "AQAB"}, jwk(self.key, "k1")]}
        self.assertEqual(A.verify_token(token(self.key), mixed, now=NOW)["sub"], "acc_1")
        # a key that says it is for encryption is not used to verify
        enc = jwk(self.key, "k1"); enc["use"] = "enc"
        with self.assertRaises(A.AccountTokenError) as cm:
            A.verify_token(token(self.key), {"keys": [enc]}, now=NOW)
        self.assertEqual(cm.exception.reason, "unknown_kid")

    # -- claims ---------------------------------------------------------------------------------------------------------------------
    def test_expiry_with_skew(self):
        self.assertEqual(self.reason(token(self.key), now=NOW + 900 + 31), "expired")
        self.assertEqual(A.verify_token(token(self.key), self.jwks, now=NOW + 900 + 30)["sub"], "acc_1")
        self.assertEqual(self.reason(token(self.key), now=NOW + 900 + 5, skew=0), "expired")
        self.assertEqual(self.reason(token(self.key, c=claims(exp=NOW - 1)), now=NOW + 60), "expired")

    def test_not_yet_valid(self):
        self.assertEqual(self.reason(token(self.key, c=claims(iat=NOW + 3600, exp=NOW + 4500))), "not_yet_valid")
        self.assertEqual(self.reason(token(self.key, c=claims(nbf=NOW + 3600))), "not_yet_valid")
        self.assertEqual(self.reason(token(self.key, c=claims(nbf="soon"))), "not_yet_valid")
        self.assertEqual(A.verify_token(token(self.key, c=claims(iat=NOW + 20)), self.jwks, now=NOW)["sub"], "acc_1")

    def test_audience(self):
        self.assertEqual(self.reason(token(self.key, c=claims(aud="other"))), "bad_aud")
        self.assertEqual(self.reason(token(self.key, c=claims(aud=None))), "bad_aud")
        self.assertEqual(self.reason(token(self.key, c=claims(aud=["a", "b"]))), "bad_aud")
        self.assertEqual(A.verify_token(token(self.key, c=claims(aud=["a", "orbit"])), self.jwks, now=NOW)["sub"], "acc_1")
        self.assertEqual(A.verify_token(token(self.key, c=claims(aud="mine")), self.jwks, now=NOW, aud="mine")["sub"], "acc_1")
        self.assertEqual(A.verify_token(token(self.key, c=claims(aud="whatever")), self.jwks, now=NOW, aud=None)["sub"], "acc_1")

    def test_issuer(self):
        self.assertEqual(self.reason(token(self.key), iss="https://other.example.net"), "bad_iss")
        self.assertEqual(self.reason(token(self.key, c=claims(iss=None)), iss=ISS), "bad_iss")
        self.assertEqual(A.verify_token(token(self.key), self.jwks, now=NOW)["iss"], ISS, "not checked unless asked")

    def test_required_claims_and_their_types(self):
        for name in ("exp", "iat", "sub"):
            self.assertEqual(self.reason(token(self.key, c=claims(**{name: None}))), "missing_claim", name)
        for bad in ("9999999999", True, None, [1], {"a": 1}):
            self.assertEqual(self.reason(token(self.key, c=claims(exp=bad))), "missing_claim", repr(bad))
        for bad in ("", 5, ["a"], None):
            self.assertEqual(self.reason(token(self.key, c=claims(sub=bad))), "missing_claim", repr(bad))

    def test_non_json_numbers_are_malformed(self):
        h = b64u(json.dumps({"alg": "EdDSA", "kid": "k1"}).encode())
        p = b64u(b'{"sub":"a","iat":1800000000,"aud":"orbit","exp":NaN}')
        inp = h + "." + p
        self.assertEqual(self.reason(inp + "." + b64u(self.key.sign(inp.encode()))), "malformed")

    # -- shape ----------------------------------------------------------------------------------------------------------------------
    def test_size_limit(self):
        self.assertEqual(self.reason("A" * (A.MAX_TOKEN_BYTES + 1)), "oversize")
        self.assertEqual(self.reason(token(self.key, c=claims(name="x" * 9000))), "oversize")
        ok = token(self.key, c=claims(name="x" * 3000))
        self.assertLess(len(ok), A.MAX_TOKEN_BYTES)
        self.assertEqual(A.verify_token(ok, self.jwks, now=NOW)["sub"], "acc_1")

    def test_malformed_tokens(self):
        good = token(self.key)
        h, p, s = good.split(".")
        for bad in ("", "a.b", "a.b.c.d", "..", h + "." + p + ".", "." + p + "." + s, h + ".!!!." + s, h + "." + p + "." + s + "=",
                    h + "=." + p + "." + s, h + "\n." + p + "." + s, h + "." + p + "\n." + s, h + "." + p + "." + s + "\n", " " + good, good + "\n", good.replace(".", ". ", 1), "é." + p + "." + s,
                    b64u(b"[]") + "." + p + "." + s, b64u(b"{") + "." + p + "." + s, h + "." + b64u(b"[]") + "." + s,
                    h + "." + b64u(b"\xff\xfe") + "." + s):
            self.assertEqual(self.reason(bad), "malformed", repr(bad)[:50])
        for not_str in (None, 5, b"abc", ["a"]):
            self.assertEqual(self.reason(not_str), "malformed")

    def test_signature_segment_of_the_wrong_length(self):
        self.assertEqual(self.reason(token(self.key, sig=b"short")), "bad_signature")
        self.assertEqual(self.reason(token(self.key, sig=b"x" * 200)), "bad_signature")


class FakeService:
    """Stands in for GET /.well-known/jwks.json: the test decides what it publishes, and when it is down."""

    def __init__(self, *entries):
        self.entries, self.calls, self.down, self.garbage = list(entries), 0, False, None

    def fetch(self):
        self.calls += 1
        if self.down:
            raise OSError("service unreachable")
        if self.garbage is not None:
            return self.garbage
        return {"keys": [jwk(k, kid) for kid, k in self.entries]}


class Clock:
    def __init__(self, t=NOW):
        self.t = t

    def __call__(self):
        return self.t


class JwksCacheTests(unittest.TestCase):
    def setUp(self):
        self.k1, self.k2 = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
        self.svc = FakeService(("k1", self.k1))
        self.clock = Clock()
        self.cache = A.JwksCache(self.svc.fetch, ttl=3600, now=self.clock)

    def tok(self, key, kid, **c):
        return token(key, kid=kid, c=claims(iat=int(self.clock.t), exp=int(self.clock.t) + 900, **c))

    def test_fetches_lazily_once_and_caches_for_the_ttl(self):
        self.assertEqual(self.svc.calls, 0)
        self.assertEqual(self.cache.verify(self.tok(self.k1, "k1"))["sub"], "acc_1")
        self.cache.verify(self.tok(self.k1, "k1"))
        self.assertEqual(self.svc.calls, 1)
        self.clock.t += 3599
        self.cache.verify(self.tok(self.k1, "k1"))
        self.assertEqual(self.svc.calls, 1)
        self.clock.t += 2
        self.cache.verify(self.tok(self.k1, "k1"))
        self.assertEqual(self.svc.calls, 2, "refetched after the TTL")

    def test_a_new_key_published_by_rotation_is_picked_up_on_first_use(self):
        self.cache.verify(self.tok(self.k1, "k1"))
        self.svc.entries = [("k2", self.k2), ("k1", self.k1)]
        self.clock.t += 120
        self.assertEqual(self.cache.verify(self.tok(self.k2, "k2"))["sub"], "acc_1")
        self.assertEqual(self.svc.calls, 2)
        self.assertEqual(self.cache.verify(self.tok(self.k1, "k1"))["sub"], "acc_1", "the previous key is still published")

    def test_unknown_kid_refetches_at_most_once_per_min_refresh(self):
        self.cache.verify(self.tok(self.k1, "k1"))
        calls = self.svc.calls
        junk = self.tok(self.k2, "ghost")
        for _ in range(5):
            with self.assertRaises(A.AccountTokenError) as cm:
                self.cache.verify(junk)
            self.assertEqual(cm.exception.reason, "unknown_kid")
        self.assertEqual(self.svc.calls, calls, "within min_refresh of the last fetch: no new fetch")
        self.clock.t += 61
        for _ in range(5):
            with self.assertRaises(A.AccountTokenError):
                self.cache.verify(self.tok(self.k2, "ghost"))
        self.assertEqual(self.svc.calls, calls + 1, "one refetch for a whole stream of junk")

    def test_previous_keys_are_kept_for_a_while_after_the_service_drops_them(self):
        self.svc.entries = [("k1", self.k1)]
        self.cache.verify(self.tok(self.k1, "k1"))
        old_token = self.tok(self.k1, "k1")
        self.svc.entries = [("k2", self.k2)]  # the service rotated and stopped publishing k1
        self.clock.t += 3601
        self.assertEqual(self.cache.verify(self.tok(self.k2, "k2"))["sub"], "acc_1")
        self.assertEqual(self.cache.verify(old_token, now=self.clock.t - 3000)["sub"], "acc_1", "a token signed just before rotation is still accepted")
        self.clock.t += A.ACCESS_TTL + 400  # past keep_previous
        with self.assertRaises(A.AccountTokenError) as cm:
            self.cache.verify(self.tok(self.k1, "k1"))
        self.assertEqual(cm.exception.reason, "unknown_kid")

    def test_drop_previous_ends_trust_in_a_retired_key_at_once(self):
        self.cache.verify(self.tok(self.k1, "k1"))
        self.svc.entries = [("k2", self.k2)]
        self.clock.t += 3601
        self.cache.verify(self.tok(self.k2, "k2"))
        self.cache.verify(self.tok(self.k1, "k1"))
        self.cache.drop_previous()
        with self.assertRaises(A.AccountTokenError):
            self.cache.verify(self.tok(self.k1, "k1"))

    def test_a_key_that_comes_back_is_current_again(self):
        self.cache.verify(self.tok(self.k1, "k1"))
        self.svc.entries = [("k2", self.k2)]
        self.clock.t += 3601
        self.cache.jwks()
        self.svc.entries = [("k1", self.k1), ("k2", self.k2)]
        self.clock.t += 3601
        kids = [k["kid"] for k in self.cache.jwks()["keys"]]
        self.assertEqual(sorted(kids), ["k1", "k2"], "no duplicate for a key that is both current and previous")

    def test_service_down_uses_the_last_good_keys_for_a_limited_time(self):
        self.cache.verify(self.tok(self.k1, "k1"))
        self.svc.down = True
        self.clock.t += 7200
        self.assertEqual(self.cache.verify(self.tok(self.k1, "k1"))["sub"], "acc_1", "stale keys beat no keys")
        calls = self.svc.calls
        for _ in range(5):
            self.cache.verify(self.tok(self.k1, "k1"))
        self.assertLessEqual(self.svc.calls, calls, "a dead service is not asked on every token")
        self.clock.t += 86400
        with self.assertRaises(A.AccountTokenError) as cm:
            self.cache.verify(self.tok(self.k1, "k1"))
        self.assertEqual(cm.exception.reason, "jwks_unavailable")

    def test_service_down_from_the_start(self):
        self.svc.down = True
        with self.assertRaises(A.AccountTokenError) as cm:
            self.cache.verify(self.tok(self.k1, "k1"))
        self.assertEqual(cm.exception.reason, "jwks_unavailable")

    def test_a_garbage_answer_changes_nothing(self):
        self.cache.verify(self.tok(self.k1, "k1"))
        for garbage in ({"keys": "x"}, {"keys": [jwk(self.k1, "k1"), jwk(self.k2, "k1")]}, "<html>", None, {}):
            self.svc.garbage = garbage
            self.clock.t += 3601
            self.assertEqual(self.cache.verify(self.tok(self.k1, "k1"))["sub"], "acc_1", repr(garbage))

    def test_verify_passes_options_through(self):
        with self.assertRaises(A.AccountTokenError) as cm:
            self.cache.verify(self.tok(self.k1, "k1"), iss="https://other.example.net")
        self.assertEqual(cm.exception.reason, "bad_iss")
        with self.assertRaises(A.AccountTokenError) as cm:
            self.cache.verify(self.tok(self.k1, "k1"), aud="someone-else")
        self.assertEqual(cm.exception.reason, "bad_aud")

    def test_https_fetcher_refuses_plain_http_to_other_hosts(self):
        for url in ("http://orbit.example.test/jwks", "ftp://127.0.0.1/x", "file:///etc/passwd", "javascript:1"):
            with self.assertRaises(ValueError):
                A.https_fetcher(url)
        A.https_fetcher("https://orbit.example.test/.well-known/jwks.json")  # builds, does not connect
        A.https_fetcher("http://127.0.0.1:8787/.well-known/jwks.json")


NODE = shutil.which("node")


@unittest.skipUnless(NODE, "node is not installed")
class CrossCheckWithTheWorkerTests(unittest.TestCase):
    """The Worker's own JavaScript and this module must agree, in both directions."""

    SCRIPT_SIGN = """
import { pathToFileURL } from 'node:url';
const { generateKeyEntry, KeySet, signAccessToken } = await import(pathToFileURL(process.argv[2]).href);
const entry = await generateKeyEntry('node-key-1');
const ks = await KeySet.parse(JSON.stringify({ active: entry.kid, keys: [entry] }));
const now = Number(process.argv[3]);
const token = await signAccessToken(ks, { sub: 'acc_cross', name: 'Node Signed', avatar: 'https://img.example.com/n.png', did: 'dev_1', now, iss: process.argv[4] });
process.stdout.write(JSON.stringify({ token, jwks: ks.publicJwks() }));
"""
    SCRIPT_VERIFY = """
import { pathToFileURL } from 'node:url';
const { verifyAccessToken } = await import(pathToFileURL(process.argv[2]).href);
const { token, jwks, now, iss } = JSON.parse(process.argv[3]);
try { const c = await verifyAccessToken(token, jwks, { now, iss }); process.stdout.write(JSON.stringify({ ok: true, sub: c.sub })); }
catch (e) { process.stdout.write(JSON.stringify({ ok: false, reason: e.reason || String(e) })); }
"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.jwt_js = os.path.join(ROOT, "accounts", "worker", "src", "jwt.js")
        if not os.path.exists(self.jwt_js): self.skipTest("the account Worker's source is not in this checkout")

    def run_node(self, source, *args):
        path = os.path.join(self.tmp, "run.mjs")  # the script lives in the temp dir, away from the code under test
        with open(path, "w") as f:
            f.write(source)
        out = subprocess.run([NODE, path, *args], cwd=self.tmp, capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_token_signed_by_the_worker_verifies_in_python(self):
        r = self.run_node(self.SCRIPT_SIGN, self.jwt_js, str(NOW), ISS)
        c = A.verify_token(r["token"], r["jwks"], now=NOW + 10, iss=ISS)
        self.assertEqual((c["sub"], c["name"], c["aud"], c["iss"], c["avatar"]), ("acc_cross", "Node Signed", "orbit", ISS, "https://img.example.com/n.png"))
        self.assertEqual(c["exp"] - c["iat"], 900)
        self.assertTrue(c["jti"])
        # the same rules hold on the Python side for a token that really came from the Worker
        with self.assertRaises(A.AccountTokenError) as cm:
            A.verify_token(r["token"], r["jwks"], now=NOW + 900 + 31, iss=ISS)
        self.assertEqual(cm.exception.reason, "expired")
        with self.assertRaises(A.AccountTokenError) as cm:
            A.verify_token(r["token"], r["jwks"], now=NOW, iss="https://other.example.net")
        self.assertEqual(cm.exception.reason, "bad_iss")
        # and a JwksCache fed from the Worker's JWKS output works end to end
        cache = A.JwksCache(lambda: r["jwks"], now=Clock(NOW))
        self.assertEqual(cache.verify(r["token"], now=NOW)["sub"], "acc_cross")

    def test_token_signed_in_python_verifies_in_the_worker(self):
        key = Ed25519PrivateKey.generate()
        jwks = {"keys": [jwk(key, "py-key")]}
        good = token(key, kid="py-key")
        ok = self.run_node(self.SCRIPT_VERIFY, self.jwt_js, json.dumps({"token": good, "jwks": jwks, "now": NOW, "iss": ISS}))
        self.assertEqual(ok, {"ok": True, "sub": "acc_1"})
        # refusals agree with this module's own verdicts
        h, p, s = good.split(".")
        cases = {
            "bad_signature": token(Ed25519PrivateKey.generate(), kid="py-key"),
            "bad_alg": token(key, kid="py-key", header={"alg": "HS256"}),
            "expired": token(key, kid="py-key", c=claims(exp=NOW - 100)),
            "bad_aud": token(key, kid="py-key", c=claims(aud="other")),
            "bad_iss": token(key, kid="py-key", c=claims(iss="https://evil.example.net")),
            "unknown_kid": token(key, kid="nope"),
        }
        for reason, tok in cases.items():
            theirs = self.run_node(self.SCRIPT_VERIFY, self.jwt_js, json.dumps({"token": tok, "jwks": jwks, "now": NOW, "iss": ISS}))
            self.assertEqual(theirs, {"ok": False, "reason": reason}, reason)
            with self.assertRaises(A.AccountTokenError) as cm:
                A.verify_token(tok, jwks, now=NOW, iss=ISS)
            self.assertEqual(cm.exception.reason, reason, "python and the Worker agree on: " + reason)


if __name__ == "__main__":
    unittest.main()
