"""Joining a shared project with an Orbit account: the host checks the account token itself, never believes a bare account field, and a member can
come back on a new device by proving the account again."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey     # noqa: E402
import collab_accounts as A       # noqa: E402
import collab_store as S          # noqa: E402
from test_collab_server import Base                                                 # noqa: E402
from test_collab_accounts import jwk, token, claims, ISS                            # noqa: E402

NOW = 1_800_000_000


class TestAccountJoin(Base):
    def setUp(self):
        super().setUp()
        self.key = Ed25519PrivateKey.generate()
        self.srv.accounts = A.AccountChecker(ISS, fetch=lambda: {"keys": [jwk(self.key, "k1")]}, now=lambda: NOW)

    def aud(self): return f"orbit-join:http://127.0.0.1:{self.port}"

    def tok(self, sub="acc_1", **kw):
        self._n = getattr(self, "_n", 0) + 1                      # every proof the service makes has its own jti
        kw.setdefault("aud", self.aud()); kw.setdefault("jti", f"jti-{self._n}"); return token(self.key, c=claims(sub=sub, **kw))

    def invite(self, **body):
        st, inv, _ = self.call("POST", f"/api/collab/p/{self.pid}/invite", dict({"role": "editor", "uses": 5}, **body), token=self.otok); self.assertEqual(st, 200, inv); return inv

    def join(self, inv, **body):
        return self.call("POST", "/api/collab/join", dict({"p": self.pid, "i": inv["id"], "s": inv["secret"], "name": "Ada"}, **body))

    def test_a_valid_account_token_links_the_account_to_the_new_member(self):
        st, j, _ = self.join(self.invite(), account_token=self.tok()); self.assertEqual(st, 200, j)
        m = self.st._proj(self.pid).members[j["member"]["id"]]; self.assertEqual(m["account"], {"provider": "orbit", "sub": "acc_1"})

    def test_a_bare_account_field_is_never_believed(self):
        st, j, _ = self.join(self.invite(), account={"provider": "orbit", "sub": "acc_owner"}); self.assertEqual(st, 200)
        self.assertIsNone(self.st._proj(self.pid).members[j["member"]["id"]]["account"])

    def test_bad_tokens_are_refused(self):
        other = Ed25519PrivateKey.generate()
        for bad in ("junk", token(other, c=claims(aud=self.aud())), self.tok(exp=NOW - 1000), self.tok(iss="https://evil.example"), self.tok(aud="other"),
                    self.tok(aud="orbit"), self.tok(aud="orbit-join:https://another-host.example")):             # an ordinary token, or a proof made for a different host, is no proof for this one
            st, j, _ = self.join(self.invite(), account_token=bad); self.assertEqual(st, 401, bad)

    def test_a_host_that_cannot_check_accounts_says_so(self):
        self.srv.accounts = None; st, j, _ = self.join(self.invite(), account_token=self.tok()); self.assertEqual(st, 400)

    def test_an_invite_can_require_an_account(self):
        inv = self.invite(account_required=True)
        st, j, _ = self.join(inv); self.assertEqual(st, 403); self.assertIn("Orbit account", j["error"]["message"] if isinstance(j.get("error"), dict) else str(j))
        self.assertEqual(self.join(inv, account_token=self.tok())[0], 200)
        listed = self.call("GET", f"/api/collab/p/{self.pid}/invites", token=self.otok)[1]["invites"]; self.assertTrue(listed[0]["account_required"])

    def test_the_same_account_joining_again_is_the_same_member_and_uses_no_invite(self):
        inv = self.invite(uses=2); _, a, _ = self.join(inv, account_token=self.tok()); _, b, _ = self.join(inv, account_token=self.tok())
        self.assertEqual(a["member"]["id"], b["member"]["id"]); self.assertNotEqual(a["token"], b["token"])
        self.assertEqual(self.st._proj(self.pid).invites[inv["id"]]["uses_left"], 1)
        self.assertEqual(self.call("GET", f"/api/collab/p/{self.pid}", token=a["token"])[0], 200); self.assertEqual(self.call("GET", f"/api/collab/p/{self.pid}", token=b["token"])[0], 200)

    def test_signing_in_again_gives_a_new_device_without_an_invite(self):
        _, a, _ = self.join(self.invite(), account_token=self.tok())
        st, j, _ = self.call("POST", f"/api/collab/p/{self.pid}/signin", {"account_token": self.tok()}); self.assertEqual(st, 200, j)
        self.assertEqual(j["member"]["id"], a["member"]["id"]); self.assertEqual(self.call("GET", f"/api/collab/p/{self.pid}", token=j["token"])[0], 200)

    def test_signin_refuses_strangers_removed_members_and_no_token(self):
        _, a, _ = self.join(self.invite(), account_token=self.tok())
        self.assertEqual(self.call("POST", f"/api/collab/p/{self.pid}/signin", {"account_token": self.tok(sub="acc_stranger")})[0], 403)
        self.assertEqual(self.call("POST", f"/api/collab/p/{self.pid}/signin", {})[0], 401)
        st, _, _ = self.call("POST", f"/api/collab/p/{self.pid}/members/{a['member']['id']}", {"action": "remove"}, token=self.otok)
        if st == 200: self.assertEqual(self.call("POST", f"/api/collab/p/{self.pid}/signin", {"account_token": self.tok()})[0], 403)

    def test_a_flood_of_bad_tokens_is_throttled(self):
        inv = self.invite(); codes = [self.join(inv, account_token="junk")[0] for _ in range(40)]
        self.assertIn(429, codes)


if __name__ == "__main__":
    unittest.main()
