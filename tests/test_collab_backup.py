"""Backing up a shared project and putting it back: no way in through the file, no change to the record goes unnoticed, nothing is overwritten."""
import json, os, shutil, sys, tempfile, time, unittest, zipfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
import collab_backup as B          # noqa: E402
import collab_policy as P          # noqa: E402
import collab_store as S           # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.work = os.path.join(self.tmp, "work"); os.makedirs(self.work)
        self.pol = P.Policy(never=[], home=os.path.join(self.tmp, "home"), sensitive=lambda p: None)
        self.root = os.path.join(self.tmp, "collab"); self.st = S.Store(self.root, policy=self.pol)
        p = self.st.create_project("Lab notebook", owner_name="Owner", working_dir=self.work, account={"provider": "orbit", "sub": "acc_owner"})
        self.pid, self.owner, self.otok = p["project"]["id"], p["member"]["id"], p["token"]
        inv = self.st.create_invite(self.pid, self.owner, grant=P.template("editor", project=self.work)); j = self.st.join(self.pid, inv["id"], inv["secret"], name="Mei", account={"provider": "orbit", "sub": "acc_mei"})
        self.mei, self.mtok = j["member"]["id"], j["token"]
        for i in range(5): self.st.submit_as(self.pid, self.mei, {"id": f"i{i}", "type": "msg", "chat": "main", "payload": {"text": f"message {i}"}})
        self.dest = os.path.join(self.tmp, "backups")

    def make(self): return B.backup(self.st, self.pid, self.dest, now=lambda: 1_800_000_000)

    def rewrite(self, path, name, fn):
        with zipfile.ZipFile(path) as z: files = {n: z.read(n) for n in z.namelist()}
        files[name] = fn(files[name]); out = path + ".x.zip"
        with zipfile.ZipFile(out, "w") as z:
            for n, b in files.items(): z.writestr(n, b)
        return out


class TestBackup(Base):
    def test_a_backup_has_the_record_and_the_people_but_no_way_in(self):
        r = self.make(); self.assertEqual(r["events"], 7); self.assertEqual(os.stat(r["path"]).st_mode & 0o077, 0)
        with zipfile.ZipFile(r["path"]) as z:
            self.assertEqual(sorted(z.namelist()), sorted(B.NAMES))
            members = json.loads(z.read("members.json")); self.assertEqual({m["name"] for m in members.values()}, {"Owner", "Mei"})
            self.assertTrue(all(m["devices"] == [] for m in members.values()))
            blob = b"".join(z.read(n) for n in z.namelist()); self.assertNotIn(self.otok.encode(), blob); self.assertNotIn(self.mtok.encode(), blob)
        self.assertEqual(self.st._proj(self.pid).members[self.mei]["devices"] != [], True)                  # the live project keeps its devices

    def test_a_record_that_does_not_check_out_is_not_backed_up(self):
        path = os.path.join(self.root, self.pid, "events.jsonl"); lines = open(path).read().splitlines(); e = json.loads(lines[2]); e["payload"] = {"text": "forged"}; lines[2] = json.dumps(e)
        open(path, "w").write("\n".join(lines) + "\n")
        with self.assertRaises(B.BackupError): self.make()


class TestRestore(Base):
    def elsewhere(self):
        other = os.path.join(self.tmp, "other"); return other

    def test_restoring_into_a_fresh_host_brings_back_the_project_and_the_chain(self):
        r = self.make(); other = self.elsewhere(); got = B.restore(other, r["path"])
        self.assertEqual((got["pid"], got["name"], got["events"]), (self.pid, "Lab notebook", 7))
        st2 = S.Store(other, policy=self.pol); self.assertEqual(st2.verify(self.pid), {"ok": True, "events": 7})
        texts = [e["payload"]["text"] for e in st2.read(self.pid, self.owner, limit=100) if e["type"] == "msg"]; self.assertEqual(texts, [f"message {i}" for i in range(5)])
        self.assertIsNone(st2.authenticate(self.pid, self.otok)); self.assertIsNone(st2.authenticate(self.pid, self.mtok))      # the old tokens do not work
        dev = st2.add_device_for(self.pid, self.owner, "this Mac"); self.assertTrue(st2.authenticate(self.pid, dev["token"]))      # the host opens it again
        self.assertEqual(st2.sign_in(self.pid, {"provider": "orbit", "sub": "acc_mei"})["member"]["id"], self.mei)                  # and a member comes back with the account
        st2.append_system(self.pid, "config", {"restored": True}); self.assertTrue(st2.verify(self.pid)["ok"])                       # the chain goes on

    def test_it_never_overwrites_an_existing_project(self):
        r = self.make()
        with self.assertRaises(B.BackupError) as cm: B.restore(self.root, r["path"])
        self.assertIn("already exists", str(cm.exception)); self.assertEqual(self.st.verify(self.pid)["events"], 7)

    def test_a_changed_record_is_refused(self):
        r = self.make(); other = self.elsewhere()
        def forge(b):
            lines = b.decode().splitlines(); e = json.loads(lines[1]); e["payload"] = {"name": "x"}; lines[1] = json.dumps(e); return ("\n".join(lines) + "\n").encode()
        for name, fn in (("events.jsonl", forge), ("events.jsonl", lambda b: b.splitlines(True)[0] + b"".join(b.splitlines(True)[2:])),           # an event cut out
                         ("MANIFEST.json", lambda b: json.dumps(dict(json.loads(b), events=99)).encode())):
            bad = self.rewrite(r["path"], name, fn)
            with self.assertRaises(B.BackupError, msg=name): B.restore(other, bad)
        self.assertFalse(os.path.exists(os.path.join(other, self.pid))); self.assertEqual([n for n in (os.listdir(other) if os.path.isdir(other) else []) if n.startswith(".restore")], [])

    def test_only_the_five_expected_files_and_sane_sizes(self):
        r = self.make(); other = self.elsewhere()
        with zipfile.ZipFile(r["path"]) as z: files = {n: z.read(n) for n in z.namelist()}
        extra = os.path.join(self.tmp, "extra.zip")
        with zipfile.ZipFile(extra, "w") as z:
            for n, b in files.items(): z.writestr(n, b)
            z.writestr("../../evil.txt", "x")
        with self.assertRaises(B.BackupError): B.restore(other, extra)
        missing = os.path.join(self.tmp, "missing.zip")
        with zipfile.ZipFile(missing, "w") as z:
            for n, b in files.items():
                if n != "grants.json": z.writestr(n, b)
        with self.assertRaises(B.BackupError): B.restore(other, missing)
        for junk in (os.path.join(self.tmp, "nothing.zip"), self.tmp):
            with self.assertRaises(B.BackupError): B.restore(other, junk)
        notzip = os.path.join(self.tmp, "x.zip"); open(notzip, "w").write("hello")
        with self.assertRaises(B.BackupError): B.restore(other, notzip)

    def test_a_bad_project_id_in_the_label_is_refused(self):
        r = self.make(); other = self.elsewhere()
        bad = self.rewrite(r["path"], "MANIFEST.json", lambda b: json.dumps(dict(json.loads(b), pid="../escape")).encode())
        with self.assertRaises(B.BackupError): B.restore(other, bad)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "escape")))

    def test_devices_in_a_tampered_members_file_are_dropped(self):
        r = self.make(); other = self.elsewhere()
        def plant(b):
            m = json.loads(b); k = next(iter(m)); m[k]["devices"] = [{"id": "d_x", "name": "x", "hash": S._sha("secret-token"), "created": 1}]; return json.dumps(m).encode()
        B.restore(other, self.rewrite(r["path"], "members.json", plant)); st2 = S.Store(other, policy=self.pol)
        self.assertIsNone(st2.authenticate(self.pid, "secret-token"))


if __name__ == "__main__":
    unittest.main()
