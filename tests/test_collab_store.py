"""Shared projects: members, tokens, invites, grants and the event log -- including everything a hostile member would try against them."""
import json, os, shutil, sys, tempfile, threading, time, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
import collab_policy as P      # noqa: E402
import collab_store as S       # noqa: E402


class Clock:
    def __init__(self, t=1_800_000_000.0): self.t = t
    def __call__(self): return self.t


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.work = os.path.join(self.tmp, "work"); os.makedirs(self.work)
        self.clock = Clock()
        self.pol = P.Policy(never=[], home=os.path.join(self.tmp, "home"), sensitive=lambda p: None)
        self.st = S.Store(os.path.join(self.tmp, "collab"), policy=self.pol, now=self.clock)
        self.p = self.st.create_project("Lab notebook", owner_name="Owner", working_dir=self.work)
        self.pid, self.owner, self.otok = self.p["project"]["id"], self.p["member"]["id"], self.p["token"]

    def invite(self, role="editor", by=None, **kw):
        by = by or self.owner
        g = P.template(role, project=self.work)
        inv = self.st.create_invite(self.pid, by, grant=g, **kw)
        return inv

    def join(self, name="Guest", role="editor", **kw):
        inv = self.invite(role)
        j = self.st.join(self.pid, inv["id"], inv["secret"], name=name, **kw)
        return j["member"]["id"], j["token"]

    def refuse(self, code, fn, *a, **kw):
        with self.assertRaises(S.CollabError) as cm: fn(*a, **kw)
        self.assertEqual(cm.exception.code, code, str(cm.exception))
        return cm.exception


class TestProjects(Base):
    def test_a_project_starts_with_one_owner_and_a_first_event(self):
        ev = self.st.read(self.pid, self.owner)
        self.assertEqual([e["type"] for e in ev], ["project"]); self.assertEqual(ev[0]["seq"], 1)
        pj = self.st.project_view(self.pid, self.owner)
        self.assertEqual(pj["name"], "Lab notebook"); self.assertEqual(pj["working_dir"], self.work)
        self.assertEqual([m["name"] for m in pj["members"]], ["Owner"]); self.assertEqual(pj["my_grant"]["role"], "owner")
        self.assertEqual(pj["proto"], S.PROTO)

    def test_the_working_directory_must_be_a_real_absolute_folder(self):
        for bad in ("relative", "/does/not/exist/at/all", "", None, "/"):
            self.refuse("bad_input", self.st.create_project, "x", owner_name="o", working_dir=bad)

    def test_names_are_cleaned_and_limited(self):
        p = self.st.create_project("  <b>x</b>\n" + "n" * 500, owner_name="Me\x00\x07", working_dir=self.work)
        self.assertLessEqual(len(p["project"]["name"]), 80); self.assertNotIn("\n", p["project"]["name"]); self.assertNotIn("\x00", p["member"]["name"])
        self.refuse("bad_input", self.st.create_project, "", owner_name="o", working_dir=self.work)

    def test_tokens_are_stored_hashed_only(self):
        blob = "".join(open(os.path.join(r, f)).read() for r, _, fs in os.walk(os.path.join(self.tmp, "collab")) for f in fs)
        self.assertNotIn(self.otok, blob)

    def test_files_are_private_to_the_user(self):
        for r, _, fs in os.walk(os.path.join(self.tmp, "collab")):
            for f in fs: self.assertEqual(os.stat(os.path.join(r, f)).st_mode & 0o077, 0, f)

    def test_projects_survive_a_restart_with_the_chain_intact(self):
        self.st.submit(self.pid, self.otok, {"id": "i1", "type": "msg", "chat": "main", "payload": {"text": "hello"}})
        st2 = S.Store(os.path.join(self.tmp, "collab"), policy=self.pol, now=self.clock)
        self.assertEqual([e["type"] for e in st2.read(self.pid, self.owner)], ["project", "msg"])
        self.assertTrue(st2.verify(self.pid)["ok"])
        st2.submit(self.pid, self.otok, {"id": "i2", "type": "msg", "chat": "main", "payload": {"text": "again"}})
        self.assertTrue(st2.verify(self.pid)["ok"]); self.assertEqual(st2.verify(self.pid)["events"], 3)


class TestHostileInput(Base):
    def test_invisible_and_direction_changing_characters_are_dropped_from_names(self):
        p = self.st.create_project("\u202eevil\u200b", owner_name="A\u202eB\u2066C", working_dir=self.work)
        self.assertEqual(p["project"]["name"], "evil"); self.assertEqual(p["member"]["name"], "ABC")
        self.refuse("bad_input", self.st.create_project, "x", owner_name="\u200b\u200b", working_dir=self.work)

    def test_odd_arguments_never_crash(self):
        self.assertTrue(self.st.read(self.pid, self.owner, limit="abc")); self.assertTrue(self.st.read(self.pid, self.owner, after="zzz"))
        deep = cur = {}
        for _ in range(3000): cur["a"] = {}; cur = cur["a"]
        for bad in ({"id": "a", "type": "msg", "payload": {"text": "x", "o": object()}}, {"id": "b", "type": "msg", "payload": {"text": "x", "d": deep}}):
            try: self.st.submit(self.pid, self.otok, bad)
            except S.CollabError as e: self.assertIn(e.code, ("bad_input", "too_large"))

    def test_the_account_link_is_checked(self):
        inv = self.invite()
        self.refuse("bad_input", self.st.join, self.pid, inv["id"], inv["secret"], name="A", account="javascript:alert(1)")
        self.refuse("bad_input", self.st.join, self.pid, inv["id"], inv["secret"], name="A", account={"provider": "x"})
        j = self.st.join(self.pid, inv["id"], inv["secret"], name="A", account={"provider": "github", "sub": "123", "evil": "<script>"})
        self.assertTrue(j["token"])

    def test_a_removed_member_takes_their_unused_invites_with_them(self):
        m, tok = self.join("Admin", role="admin")
        inv = self.st.create_invite(self.pid, m, grant=P.template("viewer", project=self.work))
        self.st.remove_member(self.pid, self.owner, m)
        self.refuse("unauthorized", self.st.join, self.pid, inv["id"], inv["secret"], name="X")


class TestAuth(Base):
    def test_a_token_belongs_to_one_member_in_one_project(self):
        self.assertEqual(self.st.authenticate(self.pid, self.otok)["id"], self.owner)
        other = self.st.create_project("Other", owner_name="x", working_dir=self.work)
        self.assertIsNone(self.st.authenticate(other["project"]["id"], self.otok))
        for bad in ("", None, "x", self.otok + "x", self.otok[:-1], 5, "A" * 10000):
            self.assertIsNone(self.st.authenticate(self.pid, bad), repr(bad)[:20])
        self.assertIsNone(self.st.authenticate("p_nope", self.otok)); self.assertIsNone(self.st.authenticate(None, self.otok))

    def test_removing_a_member_kills_every_token_at_once(self):
        m, tok = self.join("Guest")
        d2 = self.st.add_device(self.pid, tok, "second laptop")
        self.assertIsNotNone(self.st.authenticate(self.pid, d2["token"]))
        self.st.remove_member(self.pid, self.owner, m)
        self.assertIsNone(self.st.authenticate(self.pid, tok)); self.assertIsNone(self.st.authenticate(self.pid, d2["token"]))
        self.refuse("unauthorized", self.st.submit, self.pid, tok, {"id": "z", "type": "msg", "chat": "main", "payload": {"text": "hi"}})

    def test_a_device_can_be_revoked_on_its_own(self):
        m, tok = self.join("Guest")
        d2 = self.st.add_device(self.pid, tok, "phone")
        self.st.revoke_device(self.pid, tok, d2["device"])
        self.assertIsNone(self.st.authenticate(self.pid, d2["token"])); self.assertIsNotNone(self.st.authenticate(self.pid, tok))

    def test_muted_members_can_read_but_not_write(self):
        m, tok = self.join("Guest")
        self.st.set_member_state(self.pid, self.owner, m, "muted")
        self.refuse("forbidden", self.st.submit, self.pid, tok, {"id": "q", "type": "msg", "chat": "main", "payload": {"text": "hi"}})
        self.assertTrue(self.st.read(self.pid, m))


class TestInvites(Base):
    def test_an_invite_works_once_per_use_and_not_after_it_expires_or_is_revoked(self):
        inv = self.invite(uses=1)
        j = self.st.join(self.pid, inv["id"], inv["secret"], name="A")
        self.assertIn("token", j)
        self.refuse("unauthorized", self.st.join, self.pid, inv["id"], inv["secret"], name="B")             # used up
        inv = self.invite(expires_in=60); self.clock.t += 61
        self.refuse("unauthorized", self.st.join, self.pid, inv["id"], inv["secret"], name="C")
        inv = self.invite(); self.st.revoke_invite(self.pid, self.owner, inv["id"])
        self.refuse("unauthorized", self.st.join, self.pid, inv["id"], inv["secret"], name="D")

    def test_wrong_secret_wrong_project_and_junk_are_all_the_same_refusal(self):
        inv = self.invite()
        other = self.st.create_project("Other", owner_name="x", working_dir=self.work)["project"]["id"]
        for args in ((self.pid, inv["id"], "wrong"), (other, inv["id"], inv["secret"]), (self.pid, "i_nope", inv["secret"]), (self.pid, None, None), (self.pid, inv["id"], "")):
            e = self.refuse("unauthorized", self.st.join, *args, name="X")
        self.assertNotIn("secret", str(e).lower())

    def test_the_secret_is_stored_hashed(self):
        inv = self.invite()
        blob = open(os.path.join(self.tmp, "collab", self.pid, "invites.json")).read()
        self.assertNotIn(inv["secret"], blob)

    def test_nobody_can_invite_with_more_power_than_they_have(self):
        m, tok = self.join("Admin", role="admin")
        # an admin may add members but cannot make someone an owner-strength member where the admin holds less
        g = P.template("owner", project=self.work)
        self.refuse("forbidden", self.st.create_invite, self.pid, m, grant=g)
        e = P.template("editor", project=self.work)
        inv = self.st.create_invite(self.pid, m, grant=e)
        self.assertTrue(inv["id"])

    def test_an_editor_cannot_invite_at_all(self):
        m, tok = self.join("Ed", role="editor")
        self.refuse("forbidden", self.st.create_invite, self.pid, m, grant=P.template("viewer", project=self.work))

    def test_joining_is_an_event_and_the_new_member_gets_the_invited_grant(self):
        m, tok = self.join("Ed", role="commenter")
        self.assertEqual(self.st.grant_of(self.pid, m)["tools"], ["read"])
        self.assertIn("join", [e["type"] for e in self.st.read(self.pid, self.owner)])

    def test_an_invite_cannot_be_created_with_a_grant_that_reaches_the_never_list_or_the_home(self):
        g = P.template("owner", project=self.work); g["write_paths"] = [self.pol.home]
        self.refuse("bad_input", self.st.create_invite, self.pid, self.owner, grant=g)

    def test_the_list_of_invites_never_shows_secrets(self):
        self.invite(); inv = self.st.list_invites(self.pid, self.owner)
        self.assertTrue(inv); self.assertNotIn("secret", json.dumps(inv)); self.assertNotIn("hash", json.dumps(inv))
        m, tok = self.join("Ed")
        self.refuse("forbidden", self.st.list_invites, self.pid, m)


class TestGrants(Base):
    def test_grants_can_be_lowered_but_not_raised_past_the_granter(self):
        m, tok = self.join("Ed", role="editor")
        a, atok = self.join("Admin", role="admin")
        g = P.template("commenter", project=self.work)
        self.st.set_grant(self.pid, a, m, g)
        self.assertEqual(self.st.grant_of(self.pid, m)["tools"], ["read"])
        self.refuse("forbidden", self.st.set_grant, self.pid, a, m, P.template("owner", project=self.work))
        self.refuse("forbidden", self.st.set_grant, self.pid, m, m, P.template("owner", project=self.work))      # nobody promotes themselves
        self.refuse("forbidden", self.st.set_grant, self.pid, a, self.owner, P.template("viewer", project=self.work))   # nobody touches the owner

    def test_a_member_cannot_change_grants_without_the_right(self):
        m, tok = self.join("Ed"); o, otok2 = self.join("Other")
        self.refuse("forbidden", self.st.set_grant, self.pid, m, o, P.template("viewer", project=self.work))

    def test_a_grant_change_is_logged_with_who_did_it(self):
        m, tok = self.join("Ed"); self.st.set_grant(self.pid, self.owner, m, P.template("viewer", project=self.work))
        ev = [e for e in self.st.read(self.pid, self.owner) if e["type"] == "grant"][-1]
        self.assertEqual(ev["payload"]["member"], m); self.assertEqual(ev["payload"]["set_by"], self.owner); self.assertEqual(ev["author"], self.owner)

    def test_a_revoked_grant_stops_what_it_allowed_at_once(self):
        m, tok = self.join("Ed")
        eff = self.st.effective_grant(self.pid, [m])
        self.assertEqual(self.pol.decide(eff, {"tool": "read_file", "args": {"path": "x"}, "cwd": self.work})["verdict"], "allow")
        self.st.set_grant(self.pid, self.owner, m, P.template("guest", project=self.work))
        eff = self.st.effective_grant(self.pid, [m])
        self.assertEqual(self.pol.decide(eff, {"tool": "read_file", "args": {"path": "x"}, "cwd": self.work})["verdict"], "deny")

    def test_effective_grant_of_several_authors_is_the_stricter(self):
        m, tok = self.join("Ed"); eff = self.st.effective_grant(self.pid, [self.owner, m])
        self.assertEqual(eff["shell"], "build"); self.assertFalse(eff["delete"])
        self.assertEqual(self.st.effective_grant(self.pid, [self.owner, "m_unknown"])["tools"], [])


class TestEvents(Base):
    def msg(self, tok, text="hi", chat="main", **kw):
        d = {"id": kw.pop("id", "i_%d" % time.time_ns()), "type": "msg", "chat": chat, "payload": {"text": text}}; d.update(kw)
        return self.st.submit(self.pid, tok, d)

    def test_the_host_sets_the_author_and_the_order(self):
        m, tok = self.join("Ed")
        r = self.st.submit(self.pid, tok, {"id": "a1", "type": "msg", "chat": "main", "author": self.owner, "seq": 99, "ts": 5, "payload": {"text": "x", "author": self.owner}})
        ev = self.st.read(self.pid, m)[-1]
        self.assertEqual(ev["author"], m); self.assertEqual(ev["seq"], r["seq"]); self.assertNotEqual(ev["ts"], 5)
        seqs = [e["seq"] for e in self.st.read(self.pid, m)]
        self.assertEqual(seqs, list(range(1, len(seqs) + 1)))

    def test_the_chain_verifies_and_any_edit_to_the_file_is_caught(self):
        for i in range(5): self.msg(self.otok, "m%d" % i)
        self.assertTrue(self.st.verify(self.pid)["ok"])
        path = os.path.join(self.tmp, "collab", self.pid, "events.jsonl")
        lines = open(path).read().splitlines(); orig = list(lines)
        d = json.loads(lines[3]); d["payload"]["text"] = "forged"; lines[3] = json.dumps(d, sort_keys=True)
        open(path, "w").write("\n".join(lines) + "\n")
        v = S.Store(os.path.join(self.tmp, "collab"), policy=self.pol).verify(self.pid)
        self.assertFalse(v["ok"]); self.assertEqual(v["at"], 4)
        lines = list(orig); del lines[2]; open(path, "w").write("\n".join(lines) + "\n")
        self.assertFalse(S.Store(os.path.join(self.tmp, "collab"), policy=self.pol).verify(self.pid)["ok"])
        lines = list(orig); lines[2], lines[3] = lines[3], lines[2]; open(path, "w").write("\n".join(lines) + "\n")
        self.assertFalse(S.Store(os.path.join(self.tmp, "collab"), policy=self.pol).verify(self.pid)["ok"])

    def test_resending_the_same_intent_does_not_duplicate_it(self):
        a = self.msg(self.otok, "once", id="same"); b = self.msg(self.otok, "once", id="same")
        self.assertEqual(a["seq"], b["seq"]); self.assertEqual(len([e for e in self.st.read(self.pid, self.owner) if e["type"] == "msg"]), 1)

    def test_reusing_an_id_for_different_content_is_refused(self):
        self.msg(self.otok, "one", id="same")
        self.refuse("conflict", self.msg, self.otok, "two", id="same")
        m, tok = self.join("Ed")                                     # another member's id space is separate
        self.assertTrue(self.msg(tok, "mine", id="same")["seq"])

    def test_cursors_resume_where_they_left_off(self):
        for i in range(6): self.msg(self.otok, "m%d" % i)
        first = self.st.read(self.pid, self.owner, after=0, limit=3)
        rest = self.st.read(self.pid, self.owner, after=first[-1]["seq"])
        self.assertEqual(len(first), 3); self.assertEqual(first[-1]["seq"] + 1, rest[0]["seq"]); self.assertEqual(len(first) + len(rest), 7)
        self.assertEqual(self.st.read(self.pid, self.owner, after=10_000), [])
        self.assertEqual(len(self.st.read(self.pid, self.owner, after=-5)), 7)

    def test_unknown_and_system_only_types_cannot_be_posted(self):
        for t in ("grant", "revoke", "join", "leave", "model_turn_start", "tool_result", "guard_decision", "panic", "config", "project", "bogus", "", None):
            self.refuse("bad_input" if t in ("bogus", "", None) else "forbidden", self.st.submit, self.pid, self.otok, {"id": "x" + str(t), "type": t, "chat": "main", "payload": {}})

    def test_size_rate_and_shape_limits(self):
        self.refuse("too_large", self.msg, self.otok, "x" * (S.MAX_TEXT + 1))
        for bad in ({"id": "a", "type": "msg", "chat": "main", "payload": {"text": 5}}, {"id": "a", "type": "msg", "chat": "main", "payload": []},
                    {"id": "a", "type": "msg", "chat": "main", "payload": {"text": ""}}, {"id": "", "type": "msg", "chat": "main", "payload": {"text": "x"}},
                    {"type": "msg", "chat": "main", "payload": {"text": "x"}}, {"id": "a", "type": "msg", "chat": "bad chat!", "payload": {"text": "x"}}, "not a dict", None):
            self.refuse("bad_input", self.st.submit, self.pid, self.otok, bad)
        m, tok = self.join("Spam")
        n = 0
        with self.assertRaises(S.CollabError) as cm:
            for i in range(S.RATE_PER_MIN + 5): self.msg(tok, "s%d" % i); n += 1
        self.assertEqual(cm.exception.code, "rate_limited"); self.assertEqual(n, S.RATE_PER_MIN)
        self.clock.t += 61; self.assertTrue(self.msg(tok, "later")["seq"])

    def test_text_is_stored_raw_and_never_interpreted(self):
        evil = "<script>alert(1)</script> [x](javascript:alert(1)) \x00\x07 ```"
        self.msg(self.otok, evil)
        self.assertEqual([e for e in self.st.read(self.pid, self.owner) if e["type"] == "msg"][-1]["payload"]["text"], evil.replace("\x00", ""))

    def test_edit_delete_and_react_belong_to_their_author(self):
        m, tok = self.join("Ed"); a = self.msg(tok, "mine"); b = self.msg(self.otok, "owners")
        eid = [e for e in self.st.read(self.pid, m) if e["seq"] == a["seq"]][0]["id"]; oid = [e for e in self.st.read(self.pid, m) if e["seq"] == b["seq"]][0]["id"]
        self.st.submit(self.pid, tok, {"id": "ed1", "type": "edit", "chat": "main", "payload": {"target": eid, "text": "mine, fixed"}})
        self.refuse("forbidden", self.st.submit, self.pid, tok, {"id": "ed2", "type": "edit", "chat": "main", "payload": {"target": oid, "text": "forged"}})
        self.refuse("forbidden", self.st.submit, self.pid, tok, {"id": "d2", "type": "delete", "chat": "main", "payload": {"target": oid}})
        self.st.submit(self.pid, tok, {"id": "r1", "type": "react", "chat": "main", "payload": {"target": oid, "emoji": "+1"}})
        self.refuse("not_found", self.st.submit, self.pid, tok, {"id": "d3", "type": "delete", "chat": "main", "payload": {"target": "e_nope"}})

    def test_delete_leaves_a_tombstone_and_the_original_stays_in_the_log(self):
        m, tok = self.join("Ed"); a = self.msg(tok, "regret")
        eid = [e for e in self.st.read(self.pid, m) if e["seq"] == a["seq"]][0]["id"]
        self.st.submit(self.pid, tok, {"id": "del1", "type": "delete", "chat": "main", "payload": {"target": eid}})
        view = [e for e in self.st.read(self.pid, self.owner) if e["id"] == eid][0]
        self.assertEqual(view["payload"], {"deleted": True}); self.assertEqual(view["author"], m)
        self.assertIn("regret", open(os.path.join(self.tmp, "collab", self.pid, "events.jsonl")).read())
        self.assertTrue(self.st.verify(self.pid)["ok"])

    def test_a_message_the_model_has_read_cannot_be_deleted(self):
        m, tok = self.join("Ed"); a = self.msg(tok, "seen")
        eid = [e for e in self.st.read(self.pid, m) if e["seq"] == a["seq"]][0]["id"]
        self.st.mark_model_seen(self.pid, "main", a["seq"])
        self.refuse("conflict", self.st.submit, self.pid, tok, {"id": "del2", "type": "delete", "chat": "main", "payload": {"target": eid}})
        b = self.msg(tok, "not yet seen"); bid = [e for e in self.st.read(self.pid, m) if e["seq"] == b["seq"]][0]["id"]
        self.st.submit(self.pid, tok, {"id": "del3", "type": "delete", "chat": "main", "payload": {"target": bid}})

    def test_private_chats_are_invisible_to_everyone_else(self):
        m, tok = self.join("Ed"); n, ntok = self.join("Nosy")
        self.st.create_chat(self.pid, m, "secret", visibility={"mode": "members", "members": [m]})
        self.msg(tok, "just for me", chat="secret"); self.msg(self.otok, "public", chat="main")
        for who in (self.owner, n):
            texts = json.dumps(self.st.read(self.pid, who))
            self.assertNotIn("just for me", texts); self.assertNotIn("secret", texts)
            self.refuse("forbidden" if who == n else "forbidden", self.msg, ntok if who == n else self.otok, "peek", chat="secret")
        self.assertIn("just for me", json.dumps(self.st.read(self.pid, m)))
        self.assertNotIn("secret", [c["id"] for c in self.st.project_view(self.pid, n)["chats"]])
        self.assertIn("secret", [c["id"] for c in self.st.project_view(self.pid, m)["chats"]])

    def test_a_chat_cannot_be_made_private_to_nobody_or_to_strangers(self):
        self.refuse("bad_input", self.st.create_chat, self.pid, self.owner, "x", visibility={"mode": "members", "members": []})
        self.refuse("bad_input", self.st.create_chat, self.pid, self.owner, "x", visibility={"mode": "members", "members": ["m_stranger"]})

    def test_many_writers_at_once_keep_the_log_gapless_and_the_chain_valid(self):
        toks = [self.join("U%d" % i)[1] for i in range(4)]
        errs = []
        def go(tok, k):
            for i in range(20):
                try: self.st.submit(self.pid, tok, {"id": "t%d_%d" % (k, i), "type": "msg", "chat": "main", "payload": {"text": "x"}})
                except S.CollabError as e:
                    if e.code != "rate_limited": errs.append(e)
        ts = [threading.Thread(target=go, args=(t, k)) for k, t in enumerate(toks)]
        [t.start() for t in ts]; [t.join(20) for t in ts]
        self.assertEqual(errs, [])
        seqs = [e["seq"] for e in self.st.read(self.pid, self.owner, limit=10_000)]
        self.assertEqual(seqs, list(range(1, len(seqs) + 1))); self.assertTrue(self.st.verify(self.pid)["ok"])

    def test_events_are_only_returned_to_members(self):
        self.refuse("unauthorized", self.st.read, self.pid, "m_nobody")
        m, tok = self.join("Ed"); self.st.remove_member(self.pid, self.owner, m)
        self.refuse("unauthorized", self.st.read, self.pid, m)

    def test_panic_freezes_writing_and_grants(self):
        m, tok = self.join("Ed")
        self.st.panic(self.pid, self.owner)
        self.refuse("forbidden", self.msg, tok, "after")
        self.refuse("forbidden", self.st.set_grant, self.pid, self.owner, m, P.template("viewer", project=self.work))
        self.assertEqual([e["type"] for e in self.st.read(self.pid, self.owner)][-1], "panic")
        self.refuse("forbidden", self.st.panic, self.pid, m)
        self.st.resume(self.pid, self.owner); self.assertTrue(self.msg(tok, "back")["seq"])


if __name__ == "__main__":
    unittest.main()


class TestSharedChats(Base):
    """An existing local chat shared into a project (a copy, marked imported), and taken out again by the owner."""

    MSGS = [{"role": "user", "text": "What is in the pollen data?", "ts": 1700000000.0}, {"role": "assistant", "text": "Three libraries.", "ts": 1700000005.0, "label": "Qwen3 27B"},
            {"role": "user", "text": "Summarise them."}]

    def share(self, chat="old1", name="Pollen analysis", msgs=None, actor=None):
        return self.st.import_chat(self.pid, actor or self.owner, chat, name, msgs if msgs is not None else self.MSGS, source={"title": "Pollen"})

    def test_the_chat_arrives_as_a_new_chat_everyone_can_read_with_its_history_marked_imported(self):
        m, _ = self.join("Mei"); r = self.share()
        self.assertEqual(r, {"chat": "old1", "messages": 3})
        ev = [e for e in self.st.read(self.pid, m, limit=100) if e["chat"] == "old1" and e["type"] == "msg"]
        self.assertEqual([e["payload"]["text"] for e in ev], ["What is in the pollen data?", "Three libraries.", "Summarise them."])
        self.assertTrue(all(e["payload"]["imported"] for e in ev))
        self.assertEqual([e["author"] for e in ev], [self.owner, "model:imported", self.owner])
        self.assertEqual(ev[1]["payload"]["model_label"], "Qwen3 27B"); self.assertEqual(ev[0]["payload"]["orig_ts"], 1700000000.0)
        self.assertIn("old1", [c["id"] for c in self.st.project_view(self.pid, m)["chats"]])
        self.assertTrue(self.st.verify(self.pid)["ok"])

    def test_only_the_owner_shares_a_local_chat(self):
        m, _ = self.join("Admin", role="admin")
        self.refuse("forbidden", self.share, actor=m)
        e, _ = self.join("Ed"); self.refuse("forbidden", self.share, actor=e)

    def test_what_is_refused_or_cleaned(self):
        for bad in ("x y", "", "a" * 50, "main", None):
            self.refuse("bad_input" if bad != "main" else "conflict", self.share, chat=bad)
        self.share(); self.refuse("conflict", self.share)
        self.refuse("bad_input", self.share, chat="c2", msgs="nope"); self.refuse("bad_input", self.share, chat="c3", msgs=[{"role": "tool", "text": "x"}])
        self.refuse("bad_input", self.share, chat="c4", msgs=[{"role": "user", "text": 5}]); self.refuse("bad_input", self.share, chat="c5", msgs=[{"role": "user", "text": "x"}] * (S.MAX_IMPORT + 1))
        self.refuse("too_large", self.share, chat="c6", msgs=[{"role": "user", "text": "x" * S.MAX_TEXT}] * 30)

    def test_text_is_cleaned_and_empty_messages_are_skipped(self):
        r = self.share(msgs=[{"role": "user", "text": "a\x00b"}, {"role": "assistant", "text": "   "}, {"role": "user", "text": "<script>alert(1)</script>"}])
        self.assertEqual(r["messages"], 2)
        texts = [e["payload"]["text"] for e in self.st.read(self.pid, self.owner, limit=100) if e["type"] == "msg" and e["chat"] == "old1"]
        self.assertEqual(texts, ["ab", "<script>alert(1)</script>"])

    def test_a_member_cannot_make_a_message_look_imported(self):
        m, tok = self.join("Mei"); self.share(msgs=[{"role": "user", "text": "first"}])
        self.st.submit(self.pid, tok, {"id": "i2", "type": "msg", "chat": "old1", "payload": {"text": "mine", "imported": True}})
        mine = [e for e in self.st.read(self.pid, m, limit=100) if e["type"] == "msg" and e["payload"].get("text") == "mine"][0]
        self.assertNotIn("imported", mine["payload"], "a member cannot make a message look imported")

    def test_removing_the_chat_hides_it_from_everyone_and_keeps_the_record_valid(self):
        m, tok = self.join("Mei"); self.share()
        self.st.remove_chat(self.pid, self.owner, "old1")
        for who in (self.owner, m):
            self.assertEqual([e for e in self.st.read(self.pid, who, limit=100) if e["chat"] == "old1"], [])
            self.assertNotIn("old1", [c["id"] for c in self.st.project_view(self.pid, who)["chats"]])
        self.refuse("forbidden", self.st.submit, self.pid, tok, {"id": "z", "type": "msg", "chat": "old1", "payload": {"text": "hello?"}})
        self.assertIn("chat_removed", [e["type"] for e in self.st.read(self.pid, m, limit=100)])
        self.assertTrue(self.st.verify(self.pid)["ok"])
        self.assertEqual(self.st.read(self.pid, self.owner, after=0, limit=1)[0]["type"], "project")

    def test_only_the_owner_or_a_moderator_removes_and_main_stays(self):
        m, _ = self.join("Mei"); self.share()
        self.refuse("forbidden", self.st.remove_chat, self.pid, m, "old1")
        self.refuse("forbidden", self.st.remove_chat, self.pid, self.owner, "main")
        self.refuse("not_found", self.st.remove_chat, self.pid, self.owner, "nope")
        self.st.remove_chat(self.pid, self.owner, "old1"); self.refuse("not_found", self.st.remove_chat, self.pid, self.owner, "old1")

    def test_removed_chats_do_not_come_back_in_exports_or_searches_and_survive_a_restart(self):
        self.share(); self.st.remove_chat(self.pid, self.owner, "old1")
        st2 = S.Store(os.path.join(self.tmp, "collab"), policy=self.pol)
        self.assertEqual([e for e in st2.read(self.pid, self.owner, limit=1000) if e["chat"] == "old1"], [])
        self.assertNotIn("old1", [c["id"] for c in st2.project_view(self.pid, self.owner)["chats"]]); self.assertTrue(st2.verify(self.pid)["ok"])

    def test_the_project_view_says_a_chat_was_imported(self):
        self.share(); c = [c for c in self.st.project_view(self.pid, self.owner)["chats"] if c["id"] == "old1"][0]
        self.assertEqual(c["imported"], 3)


class TestApprovalRequests(Base):
    """The record side of human approval: a request names an action; an approver answers it once, in time, not for their own request."""

    def request(self, by=None, rid="r_1", chat="main"):
        self.st.append_system(self.pid, "approval_request", {"request": rid, "turn": "t1", "tool": "run_shell", "args_summary": "rm src/a.py", "touches": ["src/a.py"],
                                                             "requested_by": by or self.owner, "reason": "deletes a file"}, chat=chat)

    def answer(self, token, rid="r_1", decision="allow", chat="main", **kw):
        return self.st.submit(self.pid, token, {"id": "a%d" % time.time_ns(), "type": "approval", "chat": chat, "payload": dict({"request": rid, "decision": decision}, **kw)})

    def test_an_approver_answers_an_open_request_once(self):
        a, atok = self.join("Admin", role="admin"); e, etok = self.join("Ed"); self.request(by=e)
        self.assertTrue(self.answer(atok, mode="chat", note="fine")["seq"])
        ev = [x for x in self.st.read(self.pid, self.owner) if x["type"] == "approval"][0]["payload"]
        self.assertEqual((ev["request"], ev["decision"], ev["mode"], ev["note"], ev["approver"]), ("r_1", "allow", "chat", "fine", a))
        self.refuse("conflict", self.answer, atok)                     # single use: the request is closed

    def test_the_wrong_people_and_the_wrong_requests_are_refused(self):
        e, etok = self.join("Ed"); f, ftok = self.join("Fay"); a, atok = self.join("Admin", role="admin"); self.request(by=e)
        self.refuse("forbidden", self.answer, etok)                     # an editor is not an approver (and it is their own request)
        self.refuse("forbidden", self.answer, ftok)
        self.refuse("not_found", self.answer, atok, rid="r_nope")
        self.refuse("bad_input", self.answer, atok, decision="maybe")
        self.refuse("not_found", self.answer, atok, chat="other")        # a request is answered in the chat it was made in

    def test_nobody_but_the_owner_approves_their_own_request(self):
        a, atok = self.join("Admin", role="admin"); self.request(by=a)
        self.refuse("forbidden", self.answer, atok)
        self.request(by=self.owner, rid="r_2"); self.assertTrue(self.answer(self.otok, rid="r_2")["seq"])

    def test_old_requests_expire(self):
        a, atok = self.join("Admin", role="admin"); self.request(by=self.owner); self.clock.t += S.APPROVAL_TTL_S + 1
        self.refuse("conflict", self.answer, atok)

    def test_an_approval_cannot_be_posted_into_a_chat_the_approver_cannot_see(self):
        m, mtok = self.join("Admin", role="admin"); n, ntok = self.join("Ed")
        self.st.create_chat(self.pid, n, "mine", visibility={"mode": "members", "members": [n]})
        self.request(by=n, rid="r_p", chat="mine")
        self.refuse("forbidden", self.answer, mtok, rid="r_p", chat="mine")

    def test_requests_are_system_only_and_survive_a_restart_still_open(self):
        e, etok = self.join("Ed")
        self.refuse("forbidden", self.st.submit, self.pid, etok, {"id": "x", "type": "approval_request", "chat": "main", "payload": {"request": "r_fake"}})
        self.request(by=e)
        st2 = S.Store(os.path.join(self.tmp, "collab"), policy=self.pol, now=self.clock)
        self.assertTrue(st2.submit(self.pid, self.otok, {"id": "z", "type": "approval", "chat": "main", "payload": {"request": "r_1", "decision": "deny", "note": "no"}})["seq"])


class TestTwoPersonApproval(Base):
    def setUp(self):
        super().setUp()
        self.a, self.atok = self.join("Admin", role="admin"); self.e, self.etok = self.join("Ed")
        self.st.set_two_person(self.pid, self.owner, ["delete"])

    def ask(self, need=2, rid="r_2p"):
        self.st.append_system(self.pid, "approval_request", {"request": rid, "turn": "t", "tool": "run_shell", "args_summary": "rm x", "touches": [], "requested_by": self.e, "reason": "deletes", "need": need, "flags": ["delete"]}, chat="main")

    def say(self, who_tok, decision="allow", rid="r_2p"):
        return self.st.submit(self.pid, who_tok, {"id": "a%d" % time.time_ns(), "type": "approval", "chat": "main", "payload": {"request": rid, "decision": decision}})

    def approvals(self): return [e["payload"] for e in self.st.read(self.pid, self.owner) if e["type"] == "approval"]

    def test_two_different_approvers_are_needed_and_the_second_makes_it_final(self):
        self.ask(); self.say(self.atok)
        self.assertEqual([(p["final"], p["have"], p["need"]) for p in self.approvals()], [(False, 1, 2)])
        self.refuse("conflict", self.say, self.atok)                                  # the same person cannot count twice
        self.say(self.otok)
        self.assertEqual([(p["final"], p["have"]) for p in self.approvals()], [(False, 1), (True, 2)])
        self.refuse("conflict", self.say, self.otok)                                  # and now it is closed

    def test_one_deny_ends_it_at_once(self):
        self.ask(); self.say(self.atok); self.say(self.otok, "deny")
        self.assertEqual([(p["decision"], p["final"]) for p in self.approvals()], [("allow", False), ("deny", True)])
        self.refuse("conflict", self.say, self.atok)

    def test_a_single_person_request_is_unchanged(self):
        self.ask(need=1, rid="r_1"); self.say(self.atok, rid="r_1")
        self.assertEqual([(p["final"], p["need"]) for p in self.approvals()], [(True, 1)])

    def test_the_requester_still_cannot_count_and_it_survives_a_restart(self):
        self.ask(); self.say(self.atok)
        st2 = S.Store(os.path.join(self.tmp, "collab"), policy=self.pol, now=self.clock)
        with self.assertRaises(S.CollabError) as cm: st2.submit(self.pid, self.atok, {"id": "again", "type": "approval", "chat": "main", "payload": {"request": "r_2p", "decision": "allow"}})
        self.assertEqual(cm.exception.code, "conflict")                               # the first approval was remembered
        self.assertTrue(st2.submit(self.pid, self.otok, {"id": "second", "type": "approval", "chat": "main", "payload": {"request": "r_2p", "decision": "allow"}})["seq"])

    def test_the_setting_is_the_owners_checked_and_public(self):
        self.refuse("forbidden", self.st.set_two_person, self.pid, self.a, ["delete"])
        self.refuse("bad_input", self.st.set_two_person, self.pid, self.owner, ["delete", "bogus"]); self.refuse("bad_input", self.st.set_two_person, self.pid, self.owner, "delete")
        self.assertEqual(self.st.set_two_person(self.pid, self.owner, ["git_push", "delete", "delete"]), ["delete", "git_push"])
        self.assertEqual(self.st.project_view(self.pid, self.e)["two_person"], ["delete", "git_push"])
        self.assertEqual([e["payload"]["two_person"] for e in self.st.read(self.pid, self.owner) if e["type"] == "config" and "two_person" in e["payload"]][-1], ["delete", "git_push"])


class TestRename(unittest.TestCase):
    def test_only_the_owner_renames_and_the_record_says_so(self):
        import tempfile, shutil
        tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, tmp, True); work = os.path.join(tmp, "w"); os.makedirs(work)
        st = S.Store(os.path.join(tmp, "c"), policy=P.Policy(never=[], home=os.path.join(tmp, "h"), sensitive=lambda p: None))
        r = st.create_project("Old", owner_name="Me", working_dir=work); pid, owner = r["project"]["id"], r["member"]["id"]
        inv = st.create_invite(pid, owner, grant=P.template("admin", project=work)); other = st.join(pid, inv["id"], inv["secret"], name="Ann")["member"]["id"]
        with self.assertRaises(S.CollabError): st.rename_project(pid, other, "Mine now")
        for bad in ("", "   ", 5): 
            with self.assertRaises(S.CollabError): st.rename_project(pid, owner, bad)
        self.assertEqual(len(st.rename_project(pid, owner, "x" * 200)), 80); self.assertEqual(st.rename_project(pid, owner, "  New name "), "New name"); self.assertEqual(st.project_view_admin(pid)["name"], "New name")
        ev = [e for e in st.read(pid, owner, limit=1000) if e["type"] == "config" and e["payload"].get("name")]; self.assertEqual((ev[-1]["payload"]["name"], ev[-1]["payload"]["was"]), ("New name", "x" * 80))
