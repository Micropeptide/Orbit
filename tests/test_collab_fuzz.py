"""Throwing junk at every route of the member door: whatever arrives, the answer is a clean 2xx/4xx, never a crash (5xx), and the door keeps answering."""
import json, os, random, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_collab_server import Base      # noqa: E402
import collab_server as V               # noqa: E402

JUNK = [None, True, False, 0, -1, 1e308, "", " ", "x" * 5000, "‮\u0000\n", "../../etc/passwd", "$(id)", "{{7*7}}", [], [None], {}, {"a": {"b": {"c": [1] * 50}}}, ["model:qwen"] * 30,
        "p_000000000000", "m_deadbeef00", "i_0123456789", "main", "<script>alert(1)</script>", {"__proto__": {"x": 1}}, 2 ** 70, [[[[[]]]]], "\ud800" if False else "é"]
KEYS = ["p", "i", "s", "name", "account", "account_token", "role", "grant", "uses", "expires_in", "account_required", "budget", "action", "member", "id", "type", "chat", "payload", "text", "to",
        "decision", "mode", "request", "note", "target", "visibility", "flags", "turn_mode", "q"]


def fill(rnd, path):
    return path.replace("{PID}", "PID").replace("{IID}", "i_0123456789").replace("{MID}", "m_deadbeef00")


class TestFuzz(Base):
    def routes(self, mid):
        out = []
        for method, pattern, name, auth in V.ROUTES:
            p = pattern.replace(V.PID, self.pid).replace(V.IID, "i_0123456789").replace(V.MID, mid).replace(V.UID, "u_0123456789ab").replace(V.AID, "a_0123456789ab")
            if "(" in p or "\\" in p: p = p.replace(r"/collab\.(js|css)", "/collab.js").replace(r"\.", ".")
            out.append((method, p, name, auth))
        return out

    def test_junk_never_causes_a_server_error_and_the_door_stays_up(self):
        rnd = random.Random(1234)
        m, mtok = self.join("Mei"); routes = self.routes(m); checked = 0
        for method, path, name, auth in routes:
            for who in (None, mtok, self.otok):
                for i in range(25):
                    body = {rnd.choice(KEYS): rnd.choice(JUNK) for _ in range(rnd.randint(0, 6))}
                    if i % 7 == 0: body = rnd.choice(JUNK)
                    qs = ""
                    if method == "GET" and i % 3 == 0: qs = "?" + "&".join(f"{rnd.choice(KEYS)}={rnd.choice(['', 'x', '%00', '9' * 40, '../..', 'a%20b'])}" for _ in range(3))
                    if name in ("panic",) and who == self.otok: continue                  # that one really freezes the project; it has its own tests
                    self.srv.fails.clear()                                    # the per-address throttle would otherwise answer 429 to most of this
                    st, j, _ = self.call(method, path + qs, body if method == "POST" else None, token=who)
                    self.assertLess(st, 500, f"{method} {path}{qs} as {'owner' if who == self.otok else 'member' if who else 'nobody'} with {str(body)[:120]} -> {st} {str(j)[:200]}")
                    checked += 1
        self.assertGreater(checked, 1000); self.srv.fails.clear()
        self.assertEqual(self.call("GET", "/api/collab/proto")[0], 200); self.assertEqual(self.call("GET", f"/api/collab/p/{self.pid}", token=self.otok)[0], 200)
        self.assertTrue(self.st.verify(self.pid)["ok"])                                  # and the record is still an unbroken chain

    def test_malformed_bodies_on_every_post_route(self):
        m, mtok = self.join("Mei")
        for method, path, name, auth in self.routes(m):
            if method != "POST" or name == "panic": continue
            for raw in (b"", b"{", b"[1,2", b"null", b"\xff\xfe", b"{" * 5000, b'{"a":' + b"[" * 3000 + b"]" * 3000 + b"}", b"x" * 300_000):
                self.srv.fails.clear(); st, j, _ = self.call("POST", path, raw=raw, token=mtok)
                self.assertLess(st, 500, f"{path} {raw[:30]!r} -> {st}")


class TestHostRouteFuzz(unittest.TestCase):
    """The host's own window talks to /api/collabhost: junk in every field of every op is a clean 4xx, never an exception or a 5xx, and never touches the real data."""
    OPS = ["status", "configure", "create", "invite", "open", "panic", "resume", "local_chats", "project_chats", "share_preview", "share_chat", "remove_chat", "copy_chat", "project_settings",
           "guard", "set_guard", "set_two_person", "set_turn_mode", "recent_changes", "undo_turn", "people", "member_action", "check", "relay_status", "relay_publish", "relay_unpublish", "backup_project", "restore_project", "join_link", "nope", None, 5]
    FIELDS = ["project", "name", "owner_name", "working_dir", "role", "uses", "expires_in", "account_required", "budget", "enabled", "mode", "port", "public_url", "models", "chat", "chats", "flags",
              "guard", "allow_export", "member", "action", "value", "turn", "force", "path", "link", "local", "title"]

    @classmethod
    def setUpClass(cls):
        import importlib.machinery, importlib.util
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_loader("qqui_fz", importlib.machinery.SourceFileLoader("qqui_fz", os.path.join(root, "bin", "orbit-ui")))
        cls.ui = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.ui)

    def setUp(self):
        import shutil, tempfile
        import collab_host as H, collab_policy as P
        self.tmp = os.path.realpath(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.old = self.ui.COLLAB_HOST; self.addCleanup(setattr, self.ui, "COLLAB_HOST", self.old)
        pol = P.Policy(never=[], home=os.path.join(self.tmp, "home"), sensitive=lambda p: None)
        self.ui.COLLAB_HOST = H.Host(self.tmp, remote=None, policy=pol); self.addCleanup(self.ui.COLLAB_HOST.stop); self.addCleanup(self.ui.COLLAB_HOST._stop_engine)
        self.work = os.path.join(self.tmp, "work"); os.makedirs(self.work)

    def test_every_op_with_junk_fields(self):
        rnd = random.Random(99); H = self.ui.COLLAB_HOST
        for enabled in (False, True):
            if enabled:
                H.configure(port=0, enabled=True); p = H.create_project("Lab", "Me", self.work)["project"]["id"]
                junk = JUNK + [p, self.work, os.path.join(self.tmp, "x.zip")]
            else: junk = JUNK
            for op in self.OPS:
                for _ in range(40):
                    d = {rnd.choice(self.FIELDS): rnd.choice(junk) for _ in range(rnd.randint(0, 5))}; d["op"] = op
                    if op in ("panic", "configure") and enabled: continue
                    try: st, raw = self.ui._collab_route(d)
                    except Exception as e: self.fail(f"{op} {str(d)[:150]} raised {type(e).__name__}: {e}")
                    self.assertLess(st, 500, f"{op} {str(d)[:150]} -> {st} {raw[:150]}")
        self.assertEqual([n for n in os.listdir(self.tmp) if n not in ("collab", "config", "work", "home", "backups")], [])


if __name__ == "__main__":
    unittest.main()
