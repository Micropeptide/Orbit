"""Joining a shared project through the Orbit service (the relay page): a join proof made for ONE project's page is accepted for that project and nothing else, each proof
works once, and an invitation can be addressed to an Orbit account id so that only that account can use it."""
import base64, json, os, sys, threading, time, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey     # noqa: E402
import collab_accounts as A       # noqa: E402
import collab_host as H           # noqa: E402
import collab_join as J           # noqa: E402
import collab_policy as P         # noqa: E402
import collab_store as S          # noqa: E402
from test_collab_server import Base                                                 # noqa: E402
from test_collab_accounts import jwk, token, claims, ISS                            # noqa: E402
import test_collab_relay as TR    # noqa: E402

NOW = 1_800_000_000
SERVICE = "https://svc.example.test"
ADA, BOB = "acc_AdaAdaAdaAdaAda1", "acc_BobBobBobBobBob2"


class RelayBase(Base):
    def setUp(self):
        super().setUp()
        self.key = Ed25519PrivateKey.generate(); self._n = 0
        self.srv.accounts = A.AccountChecker(ISS, fetch=lambda: {"keys": [jwk(self.key, "k1")]}, now=lambda: NOW)
        self.srv.relay_audience = lambda pid: f"orbit-join:{SERVICE}/r/{pid}" if pid == self.pid else None      # this project is published on the service

    def aud(self, pid=None): return f"orbit-join:{SERVICE}/r/{pid or self.pid}"

    def proof(self, sub=ADA, aud=None, **kw):
        self._n += 1
        kw.setdefault("jti", f"jti-{self._n}"); return token(self.key, c=claims(sub=sub, aud=aud or self.aud(), **kw))

    def invite(self, **body):
        st, inv, _ = self.call("POST", f"/api/collab/p/{self.pid}/invite", dict({"role": "editor", "uses": 5}, **body), token=self.otok); self.assertEqual(st, 200, inv); return inv

    def join(self, inv, **body):
        self.srv.fails.clear()                                    # the per-address throttle on wrong proofs has its own tests; these are about what a proof is worth
        return self.call("POST", "/api/collab/join", dict({"p": self.pid, "i": inv["id"], "s": inv["secret"], "name": "Ada"}, **body))

    def signin(self, pid=None, **body):
        self.srv.fails.clear()
        return self.call("POST", f"/api/collab/p/{pid or self.pid}/signin", body)

    def address(self, sub=ADA, **kw):
        """An invitation addressed to an account, made the way the host does it (the store call; the door's invite route is for ordinary invitations)."""
        return self.st.create_invite(self.pid, self.owner, grant=P.template("editor", project=self.work), for_account=sub, **kw)


class TestRelayAudience(RelayBase):
    def test_a_proof_for_this_projects_page_joins_and_signs_in(self):
        inv = self.invite(account_required=True)
        st, j, _ = self.join(inv, account_token=self.proof()); self.assertEqual(st, 200, j)
        self.assertEqual(self.st._proj(self.pid).members[j["member"]["id"]]["account"], {"provider": "orbit", "sub": ADA})
        st, k, _ = self.signin(account_token=self.proof()); self.assertEqual(st, 200, k); self.assertEqual(k["member"]["id"], j["member"]["id"])
        self.assertEqual(self.call("GET", f"/api/collab/p/{self.pid}", token=k["token"])[0], 200)

    def test_it_is_good_for_that_project_only(self):
        other = "p_" + "0" * 12
        inv = self.invite(account_required=True)
        for bad in (self.aud(other), f"orbit-join:{SERVICE}", f"orbit-join:{SERVICE}/r/", f"orbit-join:{SERVICE}/r/{self.pid}/", f"orbit-join:{SERVICE}/r/{self.pid}/x", f"orbit-join:https://other.example/r/{self.pid}",
                    f"orbit-join:{SERVICE.replace('https', 'http')}/r/{self.pid}", f"orbit-join:{SERVICE}/r/{self.pid.upper()}", f"orbit-join:{SERVICE}:443/r/{self.pid}", "orbit", f"{SERVICE}/r/{self.pid}"):
            self.assertEqual(self.join(inv, account_token=self.proof(aud=bad))[0], 401, bad)
            self.assertEqual(self.signin(account_token=self.proof(aud=bad))[0], 401, bad)

    def test_a_proof_for_one_project_does_not_sign_in_to_another_on_the_same_host(self):
        p2 = self.st.create_project("Other", owner_name="O2", working_dir=self.work)["project"]["id"]
        self.srv.relay_audience = lambda pid: self.aud(pid) if pid in (self.pid, p2) else None
        self.assertEqual(self.join(self.invite(account_required=True), account_token=self.proof())[0], 200)
        self.assertEqual(self.signin(pid=p2, account_token=self.proof())[0], 401)                                   # a proof made for the first project is no proof for the second
        self.assertEqual(self.signin(pid=p2, account_token=self.proof(aud=self.aud(p2)))[0], 403)                   # a proof made for the second is accepted as a proof, but this account is not a member there
        self.assertEqual(self.signin(pid=self.pid, account_token=self.proof(aud=self.aud(p2)))[0], 401)             # ...and a proof for the second does not sign in to the first

    def test_a_project_that_is_not_published_accepts_no_relay_proof(self):
        self.srv.relay_audience = lambda pid: None
        self.assertEqual(self.join(self.invite(account_required=True), account_token=self.proof())[0], 401)
        self.srv.relay_audience = None
        self.assertEqual(self.join(self.invite(account_required=True), account_token=self.proof())[0], 401)
        self.srv.relay_audience = lambda pid: (_ for _ in ()).throw(RuntimeError("boom"))
        self.assertEqual(self.join(self.invite(account_required=True), account_token=self.proof())[0], 401)         # a failing hook is "no", not a crash

    def test_the_direct_address_still_works_and_an_ordinary_access_token_never_does(self):
        self.assertEqual(self.join(self.invite(account_required=True), account_token=self.proof(aud=f"orbit-join:http://127.0.0.1:{self.port}"))[0], 200)
        inv = self.invite(account_required=True)
        self.assertEqual(self.join(inv, account_token=self.proof(aud="orbit"))[0], 401)
        self.srv.public_url, self.srv.allowed_hosts, self.srv.relay_audience = None, None, None                     # a door that answers to no address accepts no proof (and does not fall back to ordinary tokens)
        self.assertEqual(self.join(inv, account_token=self.proof(aud="orbit"))[0], 401)
        self.assertEqual(self.signin(account_token=self.proof(aud="orbit"))[0], 401)

    def test_the_project_id_in_the_request_is_not_trusted_as_text(self):
        inv = self.invite(account_required=True)
        for pid in (None, 5, [], {}, "", "p_", self.pid + "x", self.pid.upper(), "../" + self.pid, self.pid + "\x00", "p_" + "g" * 12, "x" * 5000):
            self.srv.fails.clear(); st, j, _ = self.call("POST", "/api/collab/join", {"p": pid, "i": inv["id"], "s": inv["secret"], "account_token": self.proof()})
            self.assertIn(st, (400, 401, 404), (pid, st, j))


class TestProofsWorkOnce(RelayBase):
    def test_a_proof_cannot_be_replayed_to_join_or_to_sign_in(self):
        inv = self.invite(account_required=True, uses=5); t = self.proof()
        self.assertEqual(self.join(inv, account_token=t)[0], 200)
        self.assertEqual(self.join(inv, account_token=t)[0], 401); self.assertEqual(self.signin(account_token=t)[0], 401)
        self.assertEqual(self.signin(account_token=self.proof())[0], 200)                       # a new proof is fine
        t2 = self.proof(); self.assertEqual(self.signin(account_token=t2)[0], 200); self.assertEqual(self.signin(account_token=t2)[0], 401)
        self.assertEqual(len([m for m in self.st._proj(self.pid).members.values() if m.get("account")]), 1)

    def test_a_refused_join_gives_the_proof_back_so_an_honest_retry_works(self):
        inv = self.invite(account_required=True); t = self.proof()
        self.assertEqual(self.join(inv, account_token=t, s="wrong-secret-xxxxxxxxxxxx")[0], 401)
        self.assertEqual(self.signin(account_token=t)[0], 403)                                  # not a member yet, and that did not spend it either
        self.assertEqual(self.join(inv, account_token=t)[0], 200)
        self.assertEqual(self.join(inv, account_token=t)[0], 401)

    def test_two_requests_with_one_proof_at_once_let_one_through(self):
        inv = self.invite(account_required=True, uses=5); self.join(inv, account_token=self.proof())
        t = self.proof(); out = []
        def go(): out.append(self.signin(account_token=t)[0])
        ts = [threading.Thread(target=go) for _ in range(8)]
        [x.start() for x in ts]; [x.join() for x in ts]
        self.assertEqual(sorted(out), [200] + [401] * 7)

    def test_a_proof_without_an_id_is_refused(self):
        self.assertEqual(self.signin(account_token=self.proof(jti=None))[0], 401)
        for bad in (5, "", "x" * 300, ["a"], {"a": 1}, True):
            self.assertEqual(self.signin(account_token=self.proof(jti=bad))[0], 401, bad)

    def test_the_ledger(self):
        t = [1000.0]; L = A.ProofLedger(now=lambda: t[0], cap=3, skew=30)
        self.assertTrue(L.reserve("a", 1100)); self.assertFalse(L.reserve("a", 1100)); L.release("a"); self.assertTrue(L.reserve("a", 1100))
        for bad in (None, 5, "", "x" * 201, ["a"]): self.assertFalse(L.reserve(bad, 1100))
        for bad in (None, "1", float("nan"), float("inf"), True): self.assertFalse(L.reserve("z", bad), bad)
        self.assertTrue(L.reserve("b", 1100)); self.assertTrue(L.reserve("c", 1100))
        self.assertFalse(L.reserve("d", 1100), "full of live proofs: refuse rather than forget one")
        t[0] = 1200.0; self.assertTrue(L.reserve("d", 1300), "expired entries make room"); self.assertTrue(L.reserve("a", 1300))
        L.release("never-reserved")


class TestAddressedInvitations(RelayBase):
    def test_only_the_named_account_can_use_it_with_the_link(self):
        inv = self.address()
        self.assertEqual(self.join(inv)[0], 403)                                                                    # no account
        st, j, _ = self.join(inv, account_token=self.proof(sub=BOB)); self.assertEqual(st, 403); self.assertIn("different Orbit account", j["error"])
        self.assertEqual(self.join(inv, account_token=self.proof(sub=ADA), s="wrong-secret-xxxxxxxxxxxx")[0], 401)   # the secret still has to be right
        self.assertEqual(self.join(inv, account_token=self.proof(sub=ADA))[0], 200)
        self.assertEqual(self.join(inv, account_token=self.proof(sub=ADA))[0], 200, "the same account again is the same member, a new device")
        self.assertEqual(len([m for m in self.st._proj(self.pid).members.values() if m.get("account")]), 1)
        self.assertEqual(self.join(inv, account_token=self.proof(sub="acc_Third_Third_Thi"))[0], 401)          # used up: nobody else gets in with it

    def test_the_named_account_needs_no_link_at_all(self):
        self.address(); before = len(self.st._proj(self.pid).members)
        self.assertEqual(self.signin(account_token=self.proof(sub=BOB))[0], 403)                                    # someone else
        st, j, _ = self.signin(account_token=self.proof(sub=ADA, name="Ada L")); self.assertEqual(st, 200, j)
        self.assertEqual(j["member"]["name"], "Ada L"); self.assertEqual(len(self.st._proj(self.pid).members), before + 1)
        m = self.st._proj(self.pid).members[j["member"]["id"]]; self.assertEqual((m["account"], m["role"]), ({"provider": "orbit", "sub": ADA}, "editor"))
        self.assertEqual(self.call("GET", f"/api/collab/p/{self.pid}", token=j["token"])[0], 200)
        join_events = [e for e in self.st.read(self.pid, self.owner, limit=100) if e["type"] == "join"]; self.assertEqual(join_events[-1]["payload"]["name"], "Ada L")
        # used once: the same account signing in again is the member it became, and the invitation does not make another
        st, k, _ = self.signin(account_token=self.proof(sub=ADA)); self.assertEqual((st, k["member"]["id"]), (200, j["member"]["id"]))
        self.assertEqual(len(self.st._proj(self.pid).members), before + 1)
        self.assertEqual(self.st._proj(self.pid).invites[next(iter(self.st._proj(self.pid).invites))]["uses_left"], 0)

    def test_the_name_comes_from_the_request_then_the_proof_then_a_default(self):
        self.address(ADA); self.address(BOB)
        a = self.signin(account_token=self.proof(sub=ADA, name="From Proof"))[1]; self.assertEqual(a["member"]["name"], "From Proof")
        b = self.signin(account_token=self.proof(sub=BOB, name=None), name=5)[1]; self.assertEqual(b["member"]["name"], "Guest")
        self.address("acc_Cara_Cara_Cara1"); c = self.signin(account_token=self.proof(sub="acc_Cara_Cara_Cara1", name="x"), name="  ‮Evil‬  ")[1]; self.assertNotIn("‮", c["member"]["name"])

    def test_it_lapses_and_can_be_cancelled_and_does_not_open_a_frozen_project(self):
        inv = self.address(expires_in=100)
        clock = [time.time()]; self.st.now = lambda: clock[0]
        clock[0] += 500
        self.assertEqual(self.signin(account_token=self.proof())[0], 403); self.assertEqual(self.join(inv, account_token=self.proof())[0], 401)
        inv2 = self.address(); self.st.revoke_invite(self.pid, self.owner, inv2["id"])
        self.assertEqual(self.signin(account_token=self.proof())[0], 403)
        self.address(BOB); self.st.panic(self.pid, self.owner)
        self.assertEqual(self.signin(account_token=self.proof(sub=BOB))[0], 403)
        self.st.resume(self.pid, self.owner); self.assertEqual(self.signin(account_token=self.proof(sub=BOB))[0], 200)

    def test_it_is_one_use_whatever_the_caller_asked_for_and_a_removed_member_does_not_come_back(self):
        inv = self.address(uses=50); self.assertEqual(self.st._proj(self.pid).invites[inv["id"]]["uses_left"], 1)
        mid = self.signin(account_token=self.proof())[1]["member"]["id"]
        self.st.remove_member(self.pid, self.owner, mid)
        self.assertEqual(self.signin(account_token=self.proof())[0], 403)
        self.assertEqual(self.join(inv, account_token=self.proof())[0], 401)

    def test_a_muted_member_signs_in_but_is_never_made_a_second_member(self):
        inv = self.invite(account_required=True, uses=5); mid = self.join(inv, account_token=self.proof())[1]["member"]["id"]
        self.st.set_member_state(self.pid, self.owner, mid, "muted")
        st, j, _ = self.signin(account_token=self.proof()); self.assertEqual((st, j["member"]["id"]), (200, mid))
        st, k, _ = self.join(inv, account_token=self.proof()); self.assertEqual((st, k["member"]["id"]), (200, mid), "no second member: a mute cannot be shed by joining again")
        self.assertEqual(self.st.member_state(self.pid, mid), "muted")
        self.assertEqual(self.call("POST", f"/api/collab/p/{self.pid}/intent", {"id": "i1", "type": "msg", "chat": "main", "payload": {"text": "x"}}, token=k["token"])[0], 403)

    def test_the_owner_sees_who_it_is_for_and_nobody_else_does(self):
        self.address(); listed = self.call("GET", f"/api/collab/p/{self.pid}/invites", token=self.otok)[1]["invites"]
        self.assertEqual((listed[0]["for_account"], listed[0]["account_required"], listed[0]["uses_left"]), (ADA, True, 1))
        plain = self.invite(); self.assertIsNone([i for i in self.call("GET", f"/api/collab/p/{self.pid}/invites", token=self.otok)[1]["invites"] if i["id"] == plain["id"]][0]["for_account"])
        _, g, _ = self.join(self.invite(), name="Guest1")
        self.assertEqual(self.call("GET", f"/api/collab/p/{self.pid}/invites", token=g["token"])[0], 403)

    def test_store_refuses_a_malformed_address_and_more_power_than_the_inviter_has(self):
        for bad in ("", 5, ["a"], {"a": 1}, "x" * 101, True):
            with self.assertRaises(S.CollabError, msg=repr(bad)) as cm: self.st.create_invite(self.pid, self.owner, grant=P.template("editor", project=self.work), for_account=bad)
            self.assertEqual(cm.exception.code, "bad_input")
        _, g, _ = self.join(self.invite(role="editor"), name="Eddie")
        with self.assertRaises(S.CollabError): self.st.create_invite(self.pid, g["member"]["id"], grant=P.template("owner", project=self.work), for_account=ADA)

    def test_an_address_survives_a_restart(self):
        inv = self.address(); st2 = S.Store(self.st.root, policy=self.st.policy)
        self.assertEqual(st2._proj(self.pid).invites[inv["id"]]["for_account"], {"provider": "orbit", "sub": ADA})
        self.assertEqual(st2.sign_in(self.pid, {"provider": "orbit", "sub": ADA})["member"]["name"], "Guest")

    def test_junk_proofs_and_bodies_never_crash_it(self):
        self.address()
        junk = [None, 5, [], {}, "", "x" * 20000, "a.b.c", "\u0000", ["tok"], {"$gt": ""}, True, 1.5, "ey" + "J" * 500]
        for j in junk:
            for body in ({"account_token": j}, {"account_token": j, "name": j}, {"name": j}, {"account": j}):
                st, r, _ = self.signin(**body); self.assertLess(st, 500, (body, r))
                self.srv.fails.clear(); st, r, _ = self.call("POST", "/api/collab/join", dict(body, p=self.pid, i=j, s=j)); self.assertLess(st, 500, (body, r))
        self.assertEqual(self.signin(account_token=self.proof())[0], 200, "after all that the real account still gets in")


class TestHostInvitations(unittest.TestCase):
    def setUp(self):
        import tempfile, shutil
        self.tmp = os.path.realpath(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.work = os.path.join(self.tmp, "work"); os.makedirs(self.work)
        pol = P.Policy(never=[], home=os.path.join(self.tmp, "home"), sensitive=lambda p: None)
        self.h = H.Host(self.tmp, remote=None, policy=pol, accounts=None); self.addCleanup(self.h.stop); self.addCleanup(self.h._stop_engine)
        self.h.configure(port=0, enabled=True)
        self.pid = self.h.create_project("Lab", "Owner", self.work)["project"]["id"]

    def test_inviting_an_account_by_its_id(self):
        inv = self.h.invite(self.pid, role="editor", for_account=f"  orbit:{ADA}  ")
        self.assertEqual((inv["for_account"], inv["account_required"]), (ADA, True)); self.assertTrue(inv["link"].endswith(f"s={inv['secret']}"))
        self.assertTrue(inv["page_link"].endswith("/")); self.assertNotIn("s=", inv["page_link"])
        rec = self.h.store._proj(self.pid).invites[inv["id"]]
        self.assertEqual((rec["uses_left"], rec["account_required"]), (1, True)); self.assertAlmostEqual(rec["expires_at"] - rec["created"], 14 * 86400, delta=5)
        again = self.h.invite(self.pid, role="editor", for_account=BOB, uses=9, account_required=False, expires_in=3600)
        rec = self.h.store._proj(self.pid).invites[again["id"]]; self.assertEqual((rec["uses_left"], rec["account_required"]), (1, True)); self.assertAlmostEqual(rec["expires_at"] - rec["created"], 3600, delta=5)

    def test_a_mistyped_id_is_caught_before_an_invitation_nobody_can_use_is_made(self):
        for bad in ("", "acc_", "acc_short", "acc_" + "a" * 17, "acc_" + "a" * 15 + "!", "ACC_" + "a" * 16, ADA + "\n" + ADA, "x" * 500, 5, ["a"], {"a": 1}, True, "acc_" + "é" * 16):
            with self.assertRaises(S.CollabError, msg=repr(bad)) as cm: self.h.invite(self.pid, role="editor", for_account=bad)
            self.assertEqual(cm.exception.code, "bad_input")
        self.assertEqual(len(self.h.store._proj(self.pid).invites), 0)

    def test_an_ordinary_invitation_is_as_before(self):
        inv = self.h.invite(self.pid, role="viewer"); self.assertNotIn("for_account", inv); self.assertNotIn("page_link", inv)
        self.assertIsNone(self.h.store._proj(self.pid).invites[inv["id"]]["for_account"])

    def test_the_door_gets_the_relay_hook_and_it_follows_publishing(self):
        srv = self.h.servers[0]; self.assertEqual(srv.relay_audience, self.h.relay_audience)
        self.assertIsNone(self.h.relay_audience(self.pid))
        self.h.cfg["relay"]["projects"][self.pid] = "S" * 43; self.h.cfg["relay"]["service"] = SERVICE
        self.assertEqual(self.h.relay_audience(self.pid), f"orbit-join:{SERVICE}/r/{self.pid}"); self.assertIsNone(self.h.relay_audience("p_" + "1" * 12))
        self.assertIsNone(self.h.relay_audience("junk"))
        del self.h.cfg["relay"]["projects"][self.pid]; self.assertIsNone(self.h.relay_audience(self.pid))


class TestOverTheRelayClient(TR.Base):
    """The whole path on the host's side: a frame from the service carrying the page's request, the host's door, a member token back in frames."""
    def setUp(self):
        super().setUp()
        self.key = Ed25519PrivateKey.generate()
        self.srv.accounts = A.AccountChecker(ISS, fetch=lambda: {"keys": [jwk(self.key, "k1")]}, now=lambda: NOW)
        self.srv.relay_audience = lambda pid: f"orbit-join:{SERVICE}/r/{pid}" if pid == self.pid else None
        self.n = 0

    def proof(self, sub=ADA, **kw):
        self.n += 1; return token(self.key, c=claims(sub=sub, aud=f"orbit-join:{SERVICE}/r/{self.pid}", jti=f"t{self.n}", **kw))

    def test_an_addressed_account_gets_in_through_the_relay_page_and_only_once_per_proof(self):
        self.st.create_invite(self.pid, self.owner, grant=P.template("editor", project=self.work), for_account=ADA)
        path = f"/api/collab/p/{self.pid}/signin"; t = self.proof()
        fr = self.ask("s1", method="POST", path=path, body={"account_token": t, "name": "Ada"}); self.assertEqual(fr[0]["status"], 200, self.text(fr))
        member_token = json.loads(self.text(fr))["token"]
        self.assertEqual(self.ask("s2", path=f"/api/collab/p/{self.pid}", token=member_token)[0]["status"], 200)
        self.assertEqual(self.ask("s3", method="POST", path=path, body={"account_token": t})[0]["status"], 401, "the same proof twice")
        self.assertEqual(self.ask("s4", method="POST", path=path, body={"account_token": self.proof(sub=BOB)})[0]["status"], 403)
        self.assertEqual(self.ask("s5", method="POST", path="/api/collab/join", body={"p": self.pid, "i": "i_0000000000", "s": "x" * 20, "account_token": self.proof()})[0]["status"], 401)


class TestPlainProjectAddressInTheApp(RelayBase):
    """The Orbit app's "Join someone else's project": a plain project address (no invitation) signs in an account the host already added."""
    class Acc:
        def __init__(self, outer, sub=ADA): self.outer, self.sub, self.asked = outer, sub, []
        def join_proof(self, audience): self.asked.append(audience); return self.outer.proof(sub=self.sub)

    def setUp(self):
        super().setUp()
        self.calls = []
        def post(url, body):
            self.calls.append((url, body)); path = url[len(SERVICE):] if url.startswith(SERVICE) else url
            return self.call("POST", path.split("/r/" + self.pid, 1)[-1], body)[:2]
        self.post = post
        self.link = f"{SERVICE}/r/{self.pid}"

    def test_parse_project_accepts_only_a_published_projects_page(self):
        want = {"base": self.link, "p": self.pid}
        self.assertEqual(J.parse_project(self.link), want); self.assertEqual(J.parse_project(self.link + "/"), want)
        self.assertEqual(J.parse_project(f"orbit://join?host={SERVICE.replace(':', '%3A').replace('/', '%2F')}%2Fr%2F{self.pid}&p={self.pid}"), want)
        for bad in ("", None, "hello", SERVICE, SERVICE + "/", self.link + "?x=1", self.link + "#x", f"http://svc.example.test/r/{self.pid}", self.link + "/join", f"{SERVICE}/r/p_bad", f"{SERVICE}/x/{self.pid}",
                    f"{SERVICE}/r/{self.pid}/../{self.pid}", f"orbit://join?host={SERVICE}&p={self.pid}", f"orbit://join?host=https%3A%2F%2Fsvc.example.test%2Fr%2F{self.pid}&p=p_000000000000", f"javascript:{self.link}", "https://u:p" + chr(64) + f"svc.example.test/r/{self.pid}"):
            with self.assertRaises(J.JoinError, msg=repr(bad)): J.parse_project(bad)

    def test_an_added_account_joins_by_pasting_the_address_alone(self):
        self.address(); acc = self.Acc(self)
        # the frame goes to the project's door as a signin; the service address in front of it is not here, so the fake post maps the path
        r = J.join(self.link, "Ada", accounts=acc, post=self.post)
        self.assertEqual(acc.asked, [self.link]); self.assertTrue(r["signed_in"]); self.assertEqual(self.calls[0][0], f"{self.link}/api/collab/p/{self.pid}/signin")
        self.assertEqual(self.calls[0][1]["name"], "Ada"); self.assertEqual(set(self.calls[0][1]), {"account_token", "name"})
        tok = dict(x.split("=", 1) for x in r["url"].split("#", 1)[1].split("&"))["t"]; self.assertEqual(self.call("GET", f"/api/collab/p/{self.pid}", token=tok)[0], 200)

    def test_without_an_account_signed_in_it_says_what_to_do_and_asks_the_host_for_nothing(self):
        with self.assertRaises(J.JoinError) as cm: J.join(self.link, "Ada", accounts=None, post=self.post)
        self.assertIn("Orbit account", str(cm.exception)); self.assertEqual(self.calls, [])

        class Out:
            def join_proof(self, a): return None
        with self.assertRaises(J.JoinError): J.join(self.link, "Ada", accounts=Out(), post=self.post)
        self.assertEqual(self.calls, [])

    def test_an_account_the_host_did_not_add_is_told_so(self):
        with self.assertRaises(J.JoinError) as cm: J.join(self.link, "Bob", accounts=self.Acc(self, BOB), post=self.post)
        self.assertIn("not a member", str(cm.exception))

    def test_a_damaged_invitation_link_still_gives_the_old_message(self):
        with self.assertRaises(J.JoinError) as cm: J.join("hello", "Ada", accounts=None, post=self.post)
        self.assertIn("not an Orbit invitation link", str(cm.exception))


class TestAccountIds(unittest.TestCase):
    def test_clean_account_id(self):
        self.assertEqual(A.clean_account_id(ADA), ADA); self.assertEqual(A.clean_account_id("\t" + ADA + " \n"), ADA); self.assertEqual(A.clean_account_id("Orbit:" + ADA), ADA)
        for bad in ("", " ", "acc_", ADA[:-1], ADA + "x", ADA.replace("acc_", "acc-"), ADA.upper(), "acc_" + "é" * 16, ADA + "\u0000", None, 5, b"acc", ["acc"]):
            with self.assertRaises(ValueError, msg=repr(bad)): A.clean_account_id(bad)

    def test_relay_audience(self):
        self.assertEqual(A.relay_audience("https://s.example/", "p_0123456789ab"), "orbit-join:https://s.example/r/p_0123456789ab")
        for bad in (None, "", "p_x", "p_0123456789AB", "p_0123456789ab/", 5): self.assertRaises(ValueError, A.relay_audience, "https://s.example", bad)


if __name__ == "__main__":
    unittest.main()
