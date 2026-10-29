"""The host: shared projects are off until the person turns them on, and then the member door opens where they said and nowhere else."""
import http.client, json, os, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
import collab_host as H        # noqa: E402
import collab_policy as P      # noqa: E402
import collab_store as S       # noqa: E402


class FakeRemote:
    def bind_addresses(self, mode): return ["127.0.0.1"] + (["127.0.0.1"] if False else [])
    def reachable_hosts(self, mode, port): return {f"127.0.0.1:{port}", f"fake.example:{port}"}
    def best_url(self, mode, port): return f"https://fake.example:{port}"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.work = os.path.join(self.tmp, "work"); os.makedirs(self.work)
        pol = P.Policy(never=[], home=os.path.join(self.tmp, "home"), sensitive=lambda p: None)
        self.h = H.Host(self.tmp, remote=FakeRemote(), policy=pol)
        self.addCleanup(self.h.stop)

    def get(self, port, path, token=None, host=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        hd = {"Authorization": "Bearer " + token} if token else {}
        if host: hd["Host"] = host
        c.request("GET", path, headers=hd); r = c.getresponse(); return r.status, r.read()


class TestHost(Base):
    def test_everything_is_off_by_default_and_nothing_is_created(self):
        st = self.h.status()
        self.assertEqual((st["enabled"], st["running"], st["projects"]), (False, False, []))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "collab")))
        for fn in (lambda: self.h.create_project("x", "o", self.work), lambda: self.h.invite("p_000000000000"), self.h.start):
            with self.assertRaises(S.CollabError) as cm: fn()
            self.assertEqual(cm.exception.code, "forbidden")

    def test_settings_are_checked(self):
        for bad in ({"enabled": "yes"}, {"mode": "everywhere"}, {"port": 80}, {"port": "x"}, {"port": True}, {"public_url": "javascript:x"}, {"public_url": "x" * 400}):
            with self.assertRaises(ValueError): self.h.configure(**bad)
        self.assertEqual(self.h.configure(public_url="https://a.example/")["public_url"], "https://a.example")

    def test_turning_it_on_opens_the_door_and_off_closes_it(self):
        self.h.configure(port=0)
        st = self.h.configure(enabled=True)
        self.assertTrue(st["running"]); port = st["port"]
        code, body = self.get(port, "/api/collab/proto"); self.assertEqual(code, 200)
        st = self.h.configure(enabled=False)
        self.assertFalse(st["running"])
        with self.assertRaises(OSError): self.get(port, "/api/collab/proto")

    def test_the_door_serves_only_the_collab_routes(self):
        self.h.configure(port=0); port = self.h.configure(enabled=True)["port"]
        for path in ("/api/chat", "/api/settings", "/api/secrets", "/config/secrets.json", "/index.html", "/app.js", "/sessions"):
            self.assertEqual(self.get(port, path)[0], 404, path)

    def test_a_request_with_a_foreign_host_header_is_refused(self):
        self.h.configure(port=0); port = self.h.configure(enabled=True)["port"]            # local mode: only this Mac's own names
        self.assertEqual(self.get(port, "/api/collab/proto", host=f"127.0.0.1:{port}")[0], 200)
        self.assertEqual(self.get(port, "/api/collab/proto", host=f"fake.example:{port}")[0], 403)
        self.h.configure(mode="tailscale"); port = self.h.status()["port"]                 # the tailnet name is ours in that mode
        self.assertEqual(self.get(port, "/api/collab/proto", host=f"fake.example:{port}")[0], 200)
        self.assertEqual(self.get(port, "/api/collab/proto", host="attacker.example")[0], 403)      # DNS rebinding guard (the origin check)

    def test_project_creation_and_invitation_by_the_owner_of_the_mac(self):
        self.h.configure(port=0, mode="tailscale"); self.h.configure(enabled=True)
        p = self.h.create_project("Lab", "Me", self.work)
        inv = self.h.invite(p["project"]["id"], role="editor", uses=2)
        self.assertTrue(inv["link"].startswith("https://fake.example:")); self.assertIn(inv["secret"], inv["link"]); self.assertTrue(inv["app_link"].startswith("orbit://join?"))
        port = self.h.status()["port"]
        import urllib.parse
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("POST", "/api/collab/join", body=json.dumps({"p": p["project"]["id"], "i": inv["id"], "s": inv["secret"], "name": "Ed"}), headers={"Content-Type": "application/json"})
        r = c.getresponse(); j = json.loads(r.read()); self.assertEqual(r.status, 200)
        self.assertEqual(self.get(port, f"/api/collab/p/{p['project']['id']}", token=j["token"])[0], 200)
        self.assertEqual([x["name"] for x in self.h.status()["projects"]], ["Lab"])

    def test_settings_survive_a_restart_but_a_running_door_does_not_start_by_itself(self):
        self.h.configure(port=0, enabled=True)
        h2 = H.Host(self.tmp, remote=FakeRemote())
        self.assertTrue(h2.cfg["enabled"]); self.assertFalse(h2.running())
        h2.start(); self.assertTrue(h2.running()); h2.stop()

    def test_the_settings_file_is_private_and_a_damaged_one_means_off(self):
        self.h.configure(port=0)
        self.assertEqual(os.stat(self.h.cfg_path).st_mode & 0o077, 0)
        open(self.h.cfg_path, "w").write("{broken")
        self.assertFalse(H.Host(self.tmp, remote=FakeRemote()).cfg["enabled"])

    def test_a_busy_port_is_reported_not_crashed_on(self):
        import socket
        s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(); busy = s.getsockname()[1]; self.addCleanup(s.close)
        self.h.cfg["port"], self.h.cfg["enabled"] = busy, True
        with self.assertRaises(S.CollabError) as cm: self.h.start()
        self.assertEqual(cm.exception.code, "conflict"); self.assertFalse(self.h.running())


class TestDashboard(Base):
    def test_the_project_cards_count_what_happened_and_who_is_here_without_any_text(self):
        self.assertEqual(self.h.dashboard()["projects"], [])                              # off: nothing to show
        self.h.configure(enabled=True, mode="local", port=8497)
        r = self.h.create_project("Lab", "Owner", self.work); pid, owner = r["project"]["id"], r["member"]["id"]
        inv = self.h.invite(pid, role="editor"); self.assertTrue(inv["link"])
        d = self.h.dashboard()["projects"][0]
        self.assertEqual((d["id"], d["members"], d["open_invites"], d["here"], d["web"]), (pid, 1, 1, 0, None))
        self.assertEqual((d["activity"]["messages_24h"], d["activity"]["turns_24h"], d["activity"]["approvals_waiting"]), (0, 0, 0))
        self.h._store().submit_as(pid, owner, {"id": "d1", "type": "msg", "chat": "main", "payload": {"text": "private words"}})
        d = self.h.dashboard()["projects"][0]
        self.assertEqual(d["activity"]["messages_24h"], 1); self.assertNotIn("private words", json.dumps(d))


if __name__ == "__main__":
    unittest.main()


class TestRoute(Base):
    """/api/collabhost, through the real server module: the host's own window."""

    @classmethod
    def setUpClass(cls):
        import importlib.machinery, importlib.util
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_loader("qqui_collab", importlib.machinery.SourceFileLoader("qqui_collab", os.path.join(root, "bin", "orbit-ui")))
        cls.ui = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.ui)

    def setUp(self):
        super().setUp()
        self.orig = self.ui.COLLAB_HOST; self.ui.COLLAB_HOST = self.h
        self.addCleanup(setattr, self.ui, "COLLAB_HOST", self.orig)

    def call(self, **d):
        code, body = self.ui._collab_route(d); return code, json.loads(body)

    def test_off_means_forbidden_and_on_means_it_works(self):
        self.assertEqual(self.call(op="create", name="x", working_dir=self.work)[0], 403)
        code, st = self.call(op="configure", enabled=True, port=0); self.assertEqual((code, st["running"]), (200, True))
        code, r = self.call(op="create", name="Lab", owner_name="Me", working_dir=self.work)
        self.assertEqual(code, 200); self.assertNotIn("token", r)                  # the owner's token stays on this Mac
        code, inv = self.call(op="invite", project=r["project"]["id"], role="viewer")
        self.assertEqual(code, 200); self.assertIn("link", inv)
        self.assertEqual(self.call(op="panic", project=r["project"]["id"])[0], 200)

    def test_bad_input_is_a_400_not_a_crash(self):
        self.assertEqual(self.call(op="configure", port=80)[0], 400)
        self.assertEqual(self.call(op="configure", mode="x")[0], 400)
        self.call(op="configure", enabled=True, port=0)
        self.assertEqual(self.call(op="create", name="", working_dir=self.work)[0], 400)
        self.assertEqual(self.call(op="invite", project="../../x")[0], 404)
        self.assertEqual(self.call(op="nope")[0], 400)

    def test_it_is_an_admin_route(self):
        import re
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "orbit-ui")).read()
        self.assertIn('"/api/collabhost"', re.search(r"ADMIN_PREFIXES = \((.*?)\)\n", src, re.S).group(1))


class TestModels(Base):
    def fake_run(self, messages, user_content, tools, emit=None, **kw):
        emit("content_delta", "pong"); emit("done", None); return "pong"

    def make(self):
        pol = P.Policy(never=[], home=os.path.join(self.tmp, "home"), sensitive=lambda p: None)
        h = H.Host(self.tmp, remote=FakeRemote(), policy=pol, tools=lambda: [], run=self.fake_run); self.addCleanup(h.stop); self.addCleanup(h._stop_engine)
        return h

    def test_models_are_checked_when_they_are_set(self):
        h = self.make()
        for bad in ([{"handle": "x y", "id": "m"}], [{"handle": "a", "id": ""}], [{"handle": "a", "id": "m"}, {"handle": "A", "id": "n"}], "nope", [{"handle": "a"}] * 11, [5]):
            with self.assertRaises(ValueError): h.configure(models=bad)
        st = h.configure(models=[{"handle": "qwen", "id": "hpc:qwen", "label": "Qwen"}])
        self.assertEqual(st["models"][0]["payer"], "the host")

    def test_a_message_to_a_model_runs_a_turn_once_models_are_set(self):
        h = self.make(); h.configure(port=0, enabled=True, models=[{"handle": "qwen", "id": "hpc:qwen", "label": "Qwen"}])
        p = h.create_project("Lab", "Me", self.work); pid = p["project"]["id"]; owner = p["member"]["id"]
        h.store.submit_as(pid, owner, {"id": "m1", "type": "msg", "chat": "main", "payload": {"text": "@qwen ping"}})
        self.assertTrue(h.engine.wait_idle(pid, 5))
        texts = [e["payload"].get("text") for e in h.store.read(pid, owner, limit=100) if e["type"] == "msg"]
        self.assertEqual(texts, ["@qwen ping", "pong"])

    def test_turning_it_off_stops_the_engine_and_nothing_answers_any_more(self):
        h = self.make(); h.configure(port=0, enabled=True, models=[{"handle": "qwen", "id": "x", "label": "Q"}])
        self.assertIsNotNone(h.engine); h.configure(enabled=False); self.assertIsNone(h.engine)


class TestFreezeAndOpen(Base):
    def test_freeze_and_lift_it_from_the_hosts_window(self):
        self.h.configure(port=0, enabled=True)
        p = self.h.create_project("Lab", "Me", self.work); pid, owner = p["project"]["id"], p["member"]["id"]
        inv = self.h.invite(pid, role="editor"); j = self.h.store.join(pid, inv["id"], inv["secret"], name="Ed")
        say = lambda who, i: self.h.store.submit_as(pid, who, {"id": i, "type": "msg", "chat": "main", "payload": {"text": "hi"}})
        self.h.panic(pid)
        with self.assertRaises(S.CollabError) as cm: say(j["member"]["id"], "a")
        self.assertEqual(cm.exception.code, "forbidden")
        self.assertTrue(say(owner, "b")["seq"], "the owner can still write while the project is frozen")
        self.h.resume(pid)
        self.assertTrue(say(j["member"]["id"], "c")["seq"])

    def test_open_gives_the_owner_a_new_device_whose_token_stays_in_the_fragment(self):
        self.h.configure(port=0, enabled=True)
        p = self.h.create_project("Lab", "Me", self.work); pid = p["project"]["id"]
        r = self.h.open_url(pid)
        self.assertIn("#p=" + pid, r["url"]); self.assertNotIn("?", r["url"].split("#")[0])
        tok = r["url"].split("&t=")[1].split("&")[0]
        self.assertEqual(self.h.store.authenticate(pid, tok)["id"], p["member"]["id"])


class FakeLocal:
    marker = "[Orbit says:"
    def __init__(self, folder): self.folder = folder
    def list(self): return [{"id": f[:-5], "title": f[:-5], "mtime": 1, "n": 3} for f in sorted(os.listdir(self.folder)) if f.endswith(".json")]


class TestSharingLocalChats(Base):
    def setUp(self):
        super().setUp()
        self.sessions = os.path.join(self.tmp, "sessions"); os.makedirs(self.sessions)
        pol = P.Policy(never=[], home=os.path.join(self.tmp, "home"), sensitive=lambda p: None)
        self.h = H.Host(self.tmp, remote=FakeRemote(), policy=pol, local=FakeLocal(self.sessions)); self.addCleanup(self.h.stop); self.addCleanup(self.h._stop_engine)
        self.h.configure(port=0, enabled=True)
        p = self.h.create_project("Lab", "Me", self.work); self.pid, self.owner = p["project"]["id"], p["member"]["id"]

    def chat(self, sid, msgs, title="Pollen"):
        json.dump({"schema": 2, "title": title, "messages": msgs}, open(os.path.join(self.sessions, sid + ".json"), "w"))

    def test_preview_then_share_then_remove(self):
        self.chat("abc", [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]}, {"role": "tool", "content": "SECRET FILE"}, {"role": "assistant", "content": "hi there", "model": "Qwen"}])
        self.assertEqual([c["id"] for c in self.h.local_chats()], ["abc"])
        pv = self.h.share_preview(self.pid, "abc")
        self.assertEqual((pv["user"], pv["assistant"], pv["tools_skipped"], pv["warnings"]), (1, 1, 2, []))
        r = self.h.share_chat(self.pid, "abc")
        self.assertEqual(r["messages"], 2)
        chats = self.h.project_chats(self.pid); self.assertIn(r["chat"], [c["id"] for c in chats])
        texts = [e["payload"]["text"] for e in self.h.store.read(self.pid, self.owner, limit=100) if e["type"] == "msg" and e["chat"] == r["chat"]]
        self.assertEqual(texts, ["hello", "hi there"]); self.assertNotIn("SECRET FILE", json.dumps(self.h.store.read(self.pid, self.owner, limit=100)))
        self.assertTrue(os.path.exists(os.path.join(self.sessions, "abc.json")), "the local chat is untouched")
        self.h.remove_chat(self.pid, r["chat"]); self.assertNotIn(r["chat"], [c["id"] for c in self.h.project_chats(self.pid)])
        self.assertTrue(os.path.exists(os.path.join(self.sessions, "abc.json")), "removing it from the project leaves the local chat alone")

    def test_a_chat_that_looks_like_it_holds_a_key_needs_a_second_yes(self):
        self.chat("k", [{"role": "user", "content": "my key is ghp_" + "x" * 36}])
        with self.assertRaises(S.CollabError) as cm: self.h.share_chat(self.pid, "k")
        self.assertEqual(cm.exception.code, "conflict"); self.assertIn("GitHub token", str(cm.exception)); self.assertNotIn("xxxx", str(cm.exception))
        self.assertEqual(self.h.project_chats(self.pid)[0]["id"], "main", "nothing was shared")
        self.assertTrue(self.h.share_chat(self.pid, "k", confirm_secrets=True)["chat"])

    def test_bad_ids_and_missing_chats_and_off(self):
        for bad in ("../x", "a/b", "", None, "nope"):
            with self.assertRaises(S.CollabError): self.h.share_preview(self.pid, bad)
        self.h.configure(enabled=False)
        with self.assertRaises(S.CollabError): self.h.local_chats()

    def test_a_very_long_chat_shares_only_the_latest_part_and_says_so(self):
        self.chat("long", [{"role": "user", "content": f"m{i}"} for i in range(S.MAX_IMPORT + 50)])
        r = self.h.share_chat(self.pid, "long"); self.assertEqual((r["messages"], r["dropped_oldest"]), (S.MAX_IMPORT, 50))


class TestGuardHost(Base):
    def make(self, models):
        pol = P.Policy(never=[], home=os.path.join(self.tmp, "home"), sensitive=lambda p: None)
        h = H.Host(self.tmp, remote=FakeRemote(), policy=pol, guard_models=lambda: models); self.addCleanup(h.stop); self.addCleanup(h._stop_engine)
        h.configure(port=0, enabled=True); p = h.create_project("Lab", "Me", self.work); return h, p["project"]["id"]

    def test_only_a_listed_plain_model_may_be_the_guard(self):
        h, pid = self.make([{"id": "good", "label": "Good"}])
        for bad in ({"enabled": True, "model_id": "claude-cli:opus"}, {"enabled": True, "model_id": ""}, {"enabled": True}):
            with self.assertRaises(S.CollabError): h.set_guard(pid, bad)
        c = h.set_guard(pid, {"enabled": True, "model_id": "good", "instructions": "Be strict."})
        self.assertEqual(h.guard(pid)["guard"], c); self.assertEqual(h.guard(pid)["models"][0]["id"], "good")
        h.set_guard(pid, {"enabled": False}); self.assertFalse(h.guard(pid)["guard"]["enabled"])


class TestTwoPersonHost(TestGuardHost):
    def test_set_and_read_back(self):
        h, pid = self.make([])
        self.assertEqual(h.set_two_person(pid, ["install", "delete"]), ["delete", "install"]); self.assertEqual(h.guard(pid)["two_person"], ["delete", "install"])
        with self.assertRaises(S.CollabError): h.set_two_person(pid, ["nope"])


class TestTurnModeHost(TestGuardHost):
    def test_set_and_read_back(self):
        h, pid = self.make([])
        self.assertEqual(h.guard(pid)["turn_mode"], "free")
        self.assertEqual(h.set_turn_mode(pid, "round_robin"), "round_robin"); self.assertEqual(h.guard(pid)["turn_mode"], "round_robin")
        with self.assertRaises(S.CollabError): h.set_turn_mode(pid, "chaos")


class TestChangesHost(TestGuardHost):
    def test_nothing_recorded_means_empty_and_nothing_to_undo(self):
        h, pid = self.make([])
        self.assertEqual(h.recent_changes(pid), [])
        for bad in (999, None, True):
            with self.assertRaises(S.CollabError): h.undo_turn(pid, bad)

    def test_recent_changes_lists_newest_first_and_says_what_can_be_undone(self):
        h, pid = self.make([]); st = h._store()
        for n in (1, 2):
            st.append_system(pid, "turn_changes", {"turn": n, "model": "qwen", "asked_by": "m_x", "asked_by_name": "Mei", "created": [f"f{n}.txt"], "modified": [], "deleted": [], "more": 0, "truncated": False, "undoable": 1}, chat="main")
        h.engine.turn_undo[(pid, 2)] = {"changes": [], "chat": "main"}
        got = h.recent_changes(pid); self.assertEqual([c["turn"] for c in got], [2, 1]); self.assertEqual([c["can_undo"] for c in got], [True, False])


class TestBackupHost(TestGuardHost):
    def test_back_up_then_restore_on_another_host(self):
        h, pid = self.make([]); r = h.backup_project(pid); self.assertTrue(os.path.isfile(r["path"])); self.assertIn("backups", r["path"])
        with self.assertRaises(Exception) as cm: h.restore_project(r["path"])                          # it exists here
        self.assertIn("already exists", str(cm.exception))
        tmp2 = os.path.join(self.tmp, "second"); os.makedirs(tmp2)
        pol = P.Policy(never=[], home=os.path.join(self.tmp, "home"), sensitive=lambda p: None)
        h2 = H.Host(tmp2, remote=FakeRemote(), policy=pol); self.addCleanup(h2.stop); self.addCleanup(h2._stop_engine); h2.configure(port=0, enabled=True)
        got = h2.restore_project(r["path"]); self.assertEqual(got["pid"], pid)
        self.assertEqual([x["id"] for x in h2.status()["projects"]], [pid]); self.assertTrue(h2._store().verify(pid)["ok"])


class TestPeopleHost(TestGuardHost):
    def join(self, h, pid, role="editor"):
        inv = h.invite(pid, role=role, uses=3); st = h._store()
        return st.join(pid, inv["id"], inv["secret"], name="Mei" + role, account={"provider": "orbit", "sub": "acc_" + role})["member"]["id"], inv

    def test_lists_people_and_invitations(self):
        h, pid = self.make([]); m, inv = self.join(h, pid); r = h.people(pid)
        self.assertEqual(sorted((x["owner"], x["account"]) for x in r["members"]), [(False, True), (True, False)])
        self.assertEqual([i["id"] for i in r["invites"]], [inv["id"]]); self.assertNotIn("owner", r["roles"])
        h.member_action(pid, inv["id"], "revoke_invite"); self.assertEqual(h.people(pid)["invites"], [])

    def test_mute_role_budget_remove(self):
        h, pid = self.make([]); m, _ = self.join(h, pid); st = h._store()
        h.member_action(pid, m, "mute"); self.assertEqual(st.member_state(pid, m), "muted"); h.member_action(pid, m, "unmute"); self.assertEqual(st.member_state(pid, m), "active")
        h.member_action(pid, m, "budget", {"turns_per_hour": 3}); h.member_action(pid, m, "budget", {"turns_per_day": 10})
        self.assertEqual(st.grant_of(pid, m)["budget"], {"turns_per_hour": 3, "turns_per_day": 10})
        h.member_action(pid, m, "budget", {"turns_per_hour": None}); self.assertEqual(st.grant_of(pid, m)["budget"], {"turns_per_day": 10})
        h.member_action(pid, m, "role", "viewer"); g = st.grant_of(pid, m); self.assertEqual((g["role"], g["can_post"], g["budget"]), ("viewer", False, {"turns_per_day": 10}))
        for bad in (("role", "owner"), ("role", "king"), ("budget", "x"), ("explode", None)):
            with self.assertRaises(S.CollabError): h.member_action(pid, m, *bad)
        h.member_action(pid, m, "remove"); self.assertEqual([x["owner"] for x in h.people(pid)["members"]], [True])
        with self.assertRaises(S.CollabError): h.member_action(pid, h.people(pid)["members"][0]["id"], "remove")             # not the owner


class TestCheckHost(TestGuardHost):
    def test_a_fresh_project_is_checked_and_problems_are_named(self):
        h, pid = self.make([{"id": "m1", "label": "M"}]); rows = {r["name"]: r for r in h.check(pid)}
        self.assertTrue(rows["Record is intact"]["ok"]); self.assertTrue(rows["Working folder exists"]["ok"]); self.assertTrue(rows["Someone can approve"]["ok"]); self.assertTrue(rows["Not frozen"]["ok"])
        h.panic(pid); self.assertFalse({r["name"]: r for r in h.check(pid)}["Not frozen"]["ok"])
        shutil.rmtree(self.work); self.assertFalse({r["name"]: r for r in h.check(pid)}["Working folder exists"]["ok"])
        self.assertTrue(all(set(r) == {"name", "ok", "detail"} for r in h.check(pid)))


class TestRelayHost(TestGuardHost):
    """Publishing a project through the service: registration, the stored secret, invitation links on the service's address, unpublishing."""
    def setUp(self):
        super().setUp()
        import http.server, threading, socketserver
        outer = self; outer.calls = []
        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def _go(self, code, obj):
                b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0); body = json.loads(self.rfile.read(n) or b"{}"); outer.calls.append(("POST", self.path, self.headers.get("Authorization"), body))
                if self.headers.get("Authorization") != "Bearer good-account-token": return self._go(401, {"error": "missing or malformed bearer token"})
                if body.get("id") == "p_aaaaaaaaaaaa": return self._go(409, {"error": "that project id is already published by someone else"})
                self._go(200, {"id": body["id"], "secret": "S" * 43, "link": "x"})
            def do_DELETE(self): outer.calls.append(("DELETE", self.path, self.headers.get("Authorization"), None)); self._go(200, {"ok": True})
        self.svc = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=self.svc.serve_forever, daemon=True).start(); self.addCleanup(self.svc.shutdown); self.addCleanup(self.svc.server_close)
        self.service = f"http://127.0.0.1:{self.svc.server_address[1]}"; self.token = ["good-account-token"]; self.sockets = []
        import ws_client as W
        class Quiet:
            def __init__(s, url, headers=None, **kw): s.url, s.headers, s.closed = url, headers, False; outer.sockets.append(s)
            def connect(s): return s
            def recv(s):
                import time as _t
                while not s.closed: _t.sleep(0.02)
                return None
            def send_text(s, t): pass
            def close(s): s.closed = True
        self.quiet = Quiet

    def host(self):
        pol = P.Policy(never=[], home=os.path.join(self.tmp, "home"), sensitive=lambda p: None)
        h = H.Host(self.tmp, remote=FakeRemote(), policy=pol, relay_token=lambda: self.token[0], relay_ws=self.quiet); self.addCleanup(h.stop); self.addCleanup(h._stop_engine)
        h.configure(port=0, enabled=True); h.cfg["relay"]["service"] = self.service
        pid = h.create_project("Lab", "Me", self.work)["project"]["id"]; return h, pid

    def test_publishing_registers_stores_the_secret_connects_and_makes_service_links(self):
        h, pid = self.host(); r = h.publish(pid); self.assertEqual(r["link"], f"{self.service}/r/{pid}")
        self.assertEqual(self.calls[0][:3], ("POST", "/relay/projects", "Bearer good-account-token")); self.assertEqual(self.calls[0][3]["id"], pid)
        self.assertEqual(json.load(open(h.cfg_path))["relay"]["projects"][pid], "S" * 43); self.assertEqual(os.stat(h.cfg_path).st_mode & 0o077, 0)
        for _ in range(100):
            if self.sockets: break
            __import__("time").sleep(0.02)
        self.assertEqual(self.sockets[0].url, f"ws://127.0.0.1:{self.svc.server_address[1]}/relay/host/{pid}"); self.assertEqual(self.sockets[0].headers, {"Authorization": "Bearer " + "S" * 43})
        inv = h.invite(pid); self.assertTrue(inv["link"].startswith(f"{self.service}/r/{pid}/join?p={pid}&i=")); self.assertIn(f"{self.service}/r/{pid}", inv["app_link"].replace("%3A", ":").replace("%2F", "/"))
        self.assertEqual(h.relay_status()["projects"][pid]["link"], f"{self.service}/r/{pid}")

    def test_the_secret_survives_a_restart_and_reconnects_with_the_door(self):
        h, pid = self.host(); h.publish(pid); h.stop(); n = len(self.sockets); h.start()
        for _ in range(100):
            if len(self.sockets) > n: break
            __import__("time").sleep(0.02)
        self.assertGreater(len(self.sockets), n)

    def test_unpublishing_forgets_the_secret_disconnects_and_asks_the_service_to_forget(self):
        h, pid = self.host(); h.publish(pid); h.unpublish(pid)
        self.assertEqual(json.load(open(h.cfg_path))["relay"]["projects"], {}); self.assertEqual(self.calls[-1][:3], ("DELETE", f"/relay/projects/{pid}", "Bearer good-account-token")); self.assertTrue(self.sockets[0].closed)
        self.assertNotIn("/r/", h.invite(pid)["link"])
        with self.assertRaises(S.CollabError): h.unpublish(pid)

    def test_not_signed_in_a_refusing_service_and_an_unreachable_one_are_said_plainly(self):
        h, pid = self.host(); self.token[0] = None
        with self.assertRaises(S.CollabError) as cm: h.publish(pid)
        self.assertIn("sign in", str(cm.exception)); self.token[0] = "stale-token"
        with self.assertRaises(S.CollabError) as cm: h.publish(pid)
        self.assertIn("bearer", str(cm.exception)); self.assertEqual(h.relay_status()["projects"], {})
        self.token[0] = "good-account-token"; h.cfg["relay"]["service"] = "http://127.0.0.1:1"
        with self.assertRaises(S.CollabError) as cm: h.publish(pid)
        self.assertIn("could not reach", str(cm.exception))

    def test_publishing_needs_the_door_and_a_real_project(self):
        h, pid = self.host(); h.stop()
        with self.assertRaises(S.CollabError): h.publish(pid)
        h.start()
        with self.assertRaises(S.CollabError): h.publish("p_ffffffffffff")


class TestFilePermissionsHost(TestGuardHost):
    def join(self, h, pid, role="editor"):
        inv = h.invite(pid, role=role, uses=3); st = h._store(); return st.join(pid, inv["id"], inv["secret"], name="Mei")["member"]["id"]

    def test_the_host_sets_the_file_switches_and_folders_for_each_person(self):
        h, pid = self.make([]); m = self.join(h, pid, "viewer"); st = h._store(); row = next(x for x in h.people(pid)["members"] if x["id"] == m)
        self.assertEqual(row["files"], {"files_download": True, "files_browse": False, "files_edit": False, "files_upload_chat": False, "files_upload_dir": False})
        os.makedirs(os.path.join(self.work, "data"))
        h.member_action(pid, m, "files", {"files_browse": True, "files_upload_dir": True, "read_paths": ["data"], "write_paths": ["data"], "deny_paths": ["data/secret"]})
        g = st.grant_of(pid, m); self.assertTrue(g["files_browse"] and g["files_upload_dir"] and g["files_download"]); self.assertEqual((g["read_paths"], g["write_paths"], g["deny_paths"]), ([os.path.join(self.work, "data")], [os.path.join(self.work, "data")], [os.path.join(self.work, "data", "secret")]))
        h.member_action(pid, m, "files", {"files_download": False}); self.assertFalse(st.grant_of(pid, m)["files_download"])
        for bad in ({"files_browse": "yes"}, {"read_paths": "x"}, {"read_paths": [5]}, {"read_paths": ["x"] * 21}, "x"):
            with self.assertRaises(S.CollabError): h.member_action(pid, m, "files", bad)

    def test_an_invitation_can_start_with_its_own_file_switches(self):
        h, pid = self.make([]); inv = h.invite(pid, role="viewer", files={"files_browse": True, "files_download": False, "files_edit": "yes", "other": True}); st = h._store()
        m = st.join(pid, inv["id"], inv["secret"], name="X")["member"]["id"]; g = st.grant_of(pid, m); self.assertEqual((g["files_browse"], g["files_download"], g["files_edit"]), (True, False, False))


class TestNotices(TestGuardHost):
    def test_the_owner_hears_about_requests_and_joins_not_about_their_own(self):
        pol = P.Policy(never=[], home=os.path.join(self.tmp, "home"), sensitive=lambda p: None); got = []
        h = H.Host(self.tmp, remote=FakeRemote(), policy=pol, notify=lambda t, m: got.append((t, m))); self.addCleanup(h.stop); self.addCleanup(h._stop_engine)
        h.configure(port=0, enabled=True); p = h.create_project("Lab", "Me", self.work); pid, owner = p["project"]["id"], p["member"]["id"]
        inv = h.invite(pid, role="editor"); j = h.store.join(pid, inv["id"], inv["secret"], name="Mei")
        self.assertEqual(got[-1][0], "Mei joined Lab")
        h.store.append_system(pid, "approval_request", {"request": "r1", "turn": "t", "tool": "run_shell", "args_summary": "rm src/a.py", "touches": [], "requested_by": j["member"]["id"], "reason": "x"}, chat="main")
        self.assertIn("Needs your answer", got[-1][0]); self.assertIn("Mei", got[-1][1]); self.assertIn("rm src/a.py", got[-1][1])
        n = len(got); h.store.append_system(pid, "approval_request", {"request": "r2", "turn": "t", "tool": "run_shell", "args_summary": "x", "touches": [], "requested_by": owner, "reason": "x"}, chat="main")
        self.assertEqual(len(got), n, "the owner is not told about their own request")

    def test_a_failing_notifier_never_breaks_anything(self):
        pol = P.Policy(never=[], home=os.path.join(self.tmp, "home"), sensitive=lambda p: None)
        def boom(t, m): raise RuntimeError("no notifier")
        h = H.Host(self.tmp, remote=FakeRemote(), policy=pol, notify=boom); self.addCleanup(h.stop); self.addCleanup(h._stop_engine)
        h.configure(port=0, enabled=True); p = h.create_project("Lab", "Me", self.work); inv = h.invite(p["project"]["id"]); self.assertTrue(h.store.join(p["project"]["id"], inv["id"], inv["secret"], name="X")["token"])
