"""Joining from this Orbit: reading invitation links safely, and showing the account to the host with a proof made for that host alone."""
import os, sys, threading, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
import collab_join as J            # noqa: E402
from test_collab_join_accounts import TestAccountJoin as _T      # noqa: E402,F401  (reused fixtures)
from test_collab_server import Base                               # noqa: E402
from test_collab_join_accounts import A, Ed25519PrivateKey, jwk, token, claims, ISS, NOW    # noqa: E402

PID, IID, SEC = "p_0123456789ab", "i_0123456789", "s" * 24


class TestLinks(unittest.TestCase):
    def test_both_forms_parse(self):
        want = {"base": "https://host.example:8443", "p": PID, "i": IID, "s": SEC}
        self.assertEqual(J.parse_link(f"https://host.example:8443/join?p={PID}&i={IID}&s={SEC}"), want)
        self.assertEqual(J.parse_link(f"orbit://join?host=https%3A%2F%2Fhost.example%3A8443&p={PID}&i={IID}&s={SEC}"), want)

    def test_a_link_through_the_service_keeps_the_project_path(self):
        want = {"base": "https://svc.example/r/p_0123456789ab", "p": PID, "i": IID, "s": SEC}
        self.assertEqual(J.parse_link(f"https://svc.example/r/p_0123456789ab/join?p={PID}&i={IID}&s={SEC}"), want)
        self.assertEqual(J.parse_link(f"orbit://join?host=https%3A%2F%2Fsvc.example%2Fr%2Fp_0123456789ab&p={PID}&i={IID}&s={SEC}"), want)
        for bad in (f"https://svc.example/other/join?p={PID}&i={IID}&s={SEC}", f"http://svc.example/r/p_0123456789ab/join?p={PID}&i={IID}&s={SEC}", f"https://svc.example/r/p_bad/join?p={PID}&i={IID}&s={SEC}",
                    f"https://svc.example/r/p_0123456789ab/x/join?p={PID}&i={IID}&s={SEC}", f"orbit://join?host=https%3A%2F%2Fsvc.example%2Fr%2Fp_0123456789ab%3Fx%3D1&p={PID}&i={IID}&s={SEC}"):
            with self.assertRaises(J.JoinError, msg=bad): J.parse_link(bad)

    def test_everything_else_is_refused(self):
        for bad in ("", "hello", "ftp://h.example/join?p=%s&i=%s&s=%s" % (PID, IID, SEC), "javascript:alert(1)", f"https://h.example/other?p={PID}&i={IID}&s={SEC}",
                    f"https://h.example/join?p=bad&i={IID}&s={SEC}", f"https://h.example/join?p={PID}&i={IID}", f"orbit://join?host=file%3A%2F%2F%2Fetc&p={PID}&i={IID}&s={SEC}",
                    "https://u:p" + chr(64) + f"h.example/join?p={PID}&i={IID}&s={SEC}", f"orbit://join?p={PID}&i={IID}&s={SEC}"):
            with self.assertRaises(J.JoinError, msg=bad): J.parse_link(bad)


class FakeAccounts:
    def __init__(self, key, aud_for=lambda a: "orbit-join:" + a): self.key, self.asked, self.aud_for = key, [], aud_for
    def join_proof(self, audience):
        self.asked.append(audience); return token(self.key, c=claims(aud=self.aud_for(audience)))


class TestJoin(Base):
    def setUp(self):
        super().setUp()
        self.key = Ed25519PrivateKey.generate()
        self.srv.accounts = A.AccountChecker(ISS, fetch=lambda: {"keys": [jwk(self.key, "k1")]}, now=lambda: NOW)

    def link(self, **body):
        st, inv, _ = self.call("POST", f"/api/collab/p/{self.pid}/invite", dict({"role": "editor", "uses": 5}, **body), token=self.otok)
        return inv["link"]

    def test_join_with_the_account_returns_an_address_that_opens_the_project(self):
        acc = FakeAccounts(self.key); r = J.join(self.link(account_required=True), "Ada", accounts=acc)
        self.assertEqual(acc.asked, [f"http://127.0.0.1:{self.port}"]); self.assertTrue(r["signed_in"])
        frag = r["url"].split("#", 1)[1]; self.assertIn("t=", frag); self.assertIn("p=" + self.pid, frag)
        tok = dict(x.split("=", 1) for x in frag.split("&"))["t"]
        self.assertEqual(self.call("GET", f"/api/collab/p/{self.pid}", token=tok)[0], 200)

    def test_without_an_account_it_joins_as_a_guest_unless_the_invite_needs_one(self):
        self.assertFalse(J.join(self.link(), "Ada", accounts=None)["signed_in"])
        with self.assertRaises(J.JoinError) as cm: J.join(self.link(account_required=True), "Ada", accounts=None)
        self.assertIn("Orbit account", str(cm.exception))

    def test_a_proof_for_another_host_does_not_work_here(self):
        acc = FakeAccounts(self.key, aud_for=lambda a: "orbit-join:https://elsewhere.example")
        with self.assertRaises(J.JoinError): J.join(self.link(account_required=True), "Ada", accounts=acc)

    def test_an_unreachable_host_is_said_plainly(self):
        with self.assertRaises(J.JoinError) as cm: J.join(f"http://127.0.0.1:1/join?p={PID}&i={IID}&s={SEC}", "Ada")
        self.assertIn("reach", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
