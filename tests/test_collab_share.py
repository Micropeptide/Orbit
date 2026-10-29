"""Files in a shared project: every part behind its own switch, every path through the permission engine, uploads in pieces, nothing overwritten, everything on the record."""
import json, os, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
import collab_policy as P          # noqa: E402
import collab_share as F           # noqa: E402
import collab_store as S           # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.work = os.path.join(self.tmp, "work"); os.makedirs(os.path.join(self.work, "src")); os.makedirs(os.path.join(self.work, "private")); os.makedirs(os.path.join(self.work, ".git"))
        for rel, t in (("README.md", "hello"), ("src/a.py", "print(1)\n"), ("private/secret.txt", "s3cret"), (".git/config", "[core]"), ("keys.pem", "KEY")): open(os.path.join(self.work, rel), "w").write(t)
        open(os.path.join(self.work, "bin.dat"), "wb").write(b"\x00\x01\x02")
        self.pol = P.Policy(never=[], home=os.path.join(self.tmp, "home"), sensitive=lambda p: "a key file" if p.endswith("keys.pem") else None)
        self.st = S.Store(os.path.join(self.tmp, "collab"), policy=self.pol)
        p = self.st.create_project("Lab", owner_name="Owner", working_dir=self.work); self.pid, self.owner = p["project"]["id"], p["member"]["id"]
        self.fs = F.FileShare(self.st, self.pol)

    def member(self, name="Mei", role="editor", **kw):
        g = P.template(role, project=self.work); g.update(kw)
        inv = self.st.create_invite(self.pid, self.owner, grant=g); return self.st.join(self.pid, inv["id"], inv["secret"], name=name)["member"]["id"]

    def upload(self, who, data, name="new.txt", target="dir", dir_="", chat="main", text="", piece=F.CHUNK):
        u = self.fs.begin_upload(self.pid, who, name, len(data), target, dir_, chat, text)
        for n, i in enumerate(range(0, len(data), piece)): self.fs.chunk(self.pid, who, u["id"], n, data[i:i + piece])
        return self.fs.finish_upload(self.pid, who, u["id"])

    def forbidden(self, fn, *a, **k):
        with self.assertRaises(S.CollabError) as cm: fn(*a, **k)
        return cm.exception


class TestSwitches(Base):
    def test_every_file_action_needs_its_own_switch(self):
        m = self.member(files_download=False, files_browse=False, files_edit=False, files_upload_chat=False, files_upload_dir=False)
        for fn, a in ((self.fs.list_dir, ("",)), (self.fs.open_file, ("README.md",)), (self.fs.read_text, ("README.md",)), (self.fs.generated, ()), (self.fs.open_attachment, ("a_000000000000",))):
            self.assertEqual(self.forbidden(fn, self.pid, m, *a).code, "forbidden", fn.__name__)
        for target in ("chat", "dir"): self.assertEqual(self.forbidden(self.fs.begin_upload, self.pid, m, "x.txt", 1, target).code, "forbidden")
        self.assertEqual(self.forbidden(self.fs.write_text, self.pid, m, "README.md", "x", "0" * 64).code, "forbidden")

    def test_the_roles_start_with_sensible_switches(self):
        self.assertTrue(all(P.template("editor")[f] for f in P.FILE_FLAGS)); self.assertEqual({f for f in P.FILE_FLAGS if P.template("commenter")[f]}, {"files_download", "files_upload_chat"})
        self.assertEqual({f for f in P.FILE_FLAGS if P.template("viewer")[f]}, {"files_download"}); self.assertEqual({f for f in P.FILE_FLAGS if P.template("guest")[f]}, set())
        self.assertIn("browse and download files", " ".join(P.summary(P.normalize(P.template("editor"), policy=self.pol))))

    def test_removed_and_expired_members_get_nothing(self):
        m = self.member(); self.st.remove_member(self.pid, self.owner, m); self.assertEqual(self.forbidden(self.fs.list_dir, self.pid, m).code, "unauthorized")
        k = self.member("Kai", expires_at=1.0); self.assertEqual(self.forbidden(self.fs.list_dir, self.pid, k).code, "forbidden")


class TestBrowsing(Base):
    def test_a_member_sees_the_files_they_may_read_and_downloads_them(self):
        m = self.member(); r = self.fs.list_dir(self.pid, m); names = [e["name"] for e in r["entries"]]
        self.assertEqual(names, ["private", "src", "README.md", "bin.dat"] if False else sorted(names, key=lambda n: (not os.path.isdir(os.path.join(self.work, n)), n.lower())))
        self.assertNotIn(".git", names); self.assertNotIn("keys.pem", names)                       # hidden folders and key files are not even listed
        path, name, size = self.fs.open_file(self.pid, m, "src/a.py"); self.assertEqual((name, size, open(path).read()), ("a.py", 9, "print(1)\n"))

    def test_only_the_granted_folders_show_and_parents_are_just_a_way_in(self):
        m = self.member(read_paths=[os.path.join(self.work, "src")], write_paths=[])
        self.assertEqual([e["name"] for e in self.fs.list_dir(self.pid, m)["entries"]], ["src"])
        self.assertEqual([e["name"] for e in self.fs.list_dir(self.pid, m, "src")["entries"]], ["a.py"])
        for rel in ("README.md", "private/secret.txt"): self.assertEqual(self.forbidden(self.fs.open_file, self.pid, m, rel).code, "forbidden")

    def test_refused_folders_links_dotdot_hidden_and_absolute_paths(self):
        m = self.member(deny_paths=[os.path.join(self.work, "private")])
        outside = os.path.join(self.tmp, "outside"); os.makedirs(outside); open(os.path.join(outside, "o.txt"), "w").write("outside"); os.symlink(outside, os.path.join(self.work, "linkdir")); os.symlink(os.path.join(outside, "o.txt"), os.path.join(self.work, "linkfile"))
        for rel in ("private/secret.txt", "linkdir/o.txt", "linkfile", "../outside/o.txt", "src/../../outside/o.txt", ".git/config", "keys.pem", os.path.join(outside, "o.txt"), "src/\x00x", ""):
            with self.assertRaises(S.CollabError, msg=repr(rel)): self.fs.open_file(self.pid, m, rel)
        for rel in ("private", "linkdir", "..", ".git", outside): 
            with self.assertRaises(S.CollabError, msg=repr(rel)): self.fs.list_dir(self.pid, m, rel)
        self.assertNotIn("private", [e["name"] for e in self.fs.list_dir(self.pid, m)["entries"]])
        for bad in (5, ["x"], "a" * 3000): 
            with self.assertRaises(S.CollabError): self.fs.open_file(self.pid, m, bad)

    def test_the_hosts_secrets_are_never_reachable_even_when_the_folder_is_granted(self):
        m = self.member(); self.assertEqual(self.forbidden(self.fs.open_file, self.pid, m, "keys.pem").code, "forbidden")

    def test_big_files_are_refused_and_a_folder_is_not_a_file(self):
        m = self.member(); old = F.MAX_DOWNLOAD; F.MAX_DOWNLOAD = 5; self.addCleanup(setattr, F, "MAX_DOWNLOAD", old)
        self.assertEqual(self.forbidden(self.fs.open_file, self.pid, m, "src/a.py").code, "too_large"); self.assertEqual(self.forbidden(self.fs.open_file, self.pid, m, "src").code, "not_found")


class TestGenerated(Base):
    def test_files_the_models_made_can_be_downloaded_without_browse_rights(self):
        m = self.member("Mei", "viewer"); self.assertEqual(self.fs.generated(self.pid, m), {"files": [], "attachments": []})
        open(os.path.join(self.work, "summary.txt"), "w").write("made by the model")
        self.st.append_system(self.pid, "turn_changes", {"turn": "t1", "model": "qwen", "asked_by": self.owner, "asked_by_name": "Owner", "created": ["summary.txt", "src/gone.txt"], "modified": ["src/a.py"], "deleted": [], "more": 0, "truncated": False, "undoable": 1}, chat="main")
        g = self.fs.generated(self.pid, m); self.assertEqual(sorted(f["path"] for f in g["files"]), ["src/a.py", "summary.txt"])        # a created file that no longer exists is not listed
        path, name, size = self.fs.open_file(self.pid, m, "summary.txt"); self.assertEqual(open(path).read(), "made by the model")
        self.assertEqual(self.forbidden(self.fs.open_file, self.pid, m, "README.md").code, "forbidden")                                    # not generated, and no browse right
        self.assertEqual(self.forbidden(self.fs.list_dir, self.pid, m).code, "forbidden")

    def test_a_generated_name_that_is_a_refused_place_stays_refused_and_private_chats_stay_private(self):
        m = self.member("Mei", "viewer", deny_paths=[os.path.join(self.work, "private")])
        self.st.append_system(self.pid, "turn_changes", {"turn": "t1", "model": "qwen", "asked_by": self.owner, "asked_by_name": "O", "created": ["private/secret.txt", "keys.pem"], "modified": [], "deleted": [], "more": 0, "truncated": False, "undoable": 0}, chat="main")
        self.assertEqual(self.fs.generated(self.pid, m)["files"], [])
        for rel in ("private/secret.txt", "keys.pem"): self.assertEqual(self.forbidden(self.fs.open_file, self.pid, m, rel).code, "forbidden")
        self.st.create_chat(self.pid, self.owner, "hush", name="Hush", visibility={"mode": "members", "members": [self.owner]})
        open(os.path.join(self.work, "hushed.txt"), "w").write("x"); self.st.append_system(self.pid, "turn_changes", {"turn": "t2", "model": "qwen", "asked_by": self.owner, "asked_by_name": "O", "created": ["hushed.txt"], "modified": [], "deleted": [], "more": 0, "truncated": False, "undoable": 0}, chat="hush")
        self.assertEqual(self.fs.generated(self.pid, m)["files"], []); self.assertEqual(self.forbidden(self.fs.open_file, self.pid, m, "hushed.txt").code, "forbidden")


class TestEditing(Base):
    def test_a_text_file_is_opened_and_saved_with_a_check_that_it_did_not_change_underneath(self):
        m = self.member(); t = self.fs.read_text(self.pid, m, "src/a.py"); self.assertEqual(t["content"], "print(1)\n")
        r = self.fs.write_text(self.pid, m, "src/a.py", "print(2)\n", t["sha"]); self.assertEqual(open(os.path.join(self.work, "src", "a.py")).read(), "print(2)\n"); self.assertNotEqual(r["sha"], t["sha"])
        self.assertEqual(self.forbidden(self.fs.write_text, self.pid, m, "src/a.py", "stale\n", t["sha"]).code, "conflict")
        ev = [e for e in self.st.read(self.pid, self.owner, limit=100) if e["type"] == "file_edit"][0]["payload"]; self.assertEqual((ev["by"], ev["path"]), (m, "src/a.py"))
        self.assertEqual([n for n in os.listdir(os.path.join(self.work, "src")) if n.endswith(".tmp")], [])

    def test_binary_big_missing_and_read_only_places_are_refused(self):
        m = self.member(); self.assertEqual(self.forbidden(self.fs.read_text, self.pid, m, "bin.dat").code, "bad_input"); self.assertEqual(self.forbidden(self.fs.read_text, self.pid, m, "nope.txt").code, "not_found")
        t = self.fs.read_text(self.pid, m, "README.md"); self.assertEqual(self.forbidden(self.fs.write_text, self.pid, m, "README.md", "x\x00y", t["sha"]).code, "too_large")
        r = self.member("Ro", write_paths=[]); self.assertEqual(self.forbidden(self.fs.read_text, self.pid, r, "README.md").code, "forbidden")
        for rel in ("private/../../x", "../x"): self.assertEqual(self.forbidden(self.fs.read_text, self.pid, m, rel).code, "forbidden")
        self.assertTrue(next(e for e in self.fs.list_dir(self.pid, m)["entries"] if e["name"] == "README.md")["editable"]); self.assertFalse(next(e for e in self.fs.list_dir(self.pid, r)["entries"] if e["name"] == "README.md")["editable"])

    def test_a_frozen_project_cannot_be_edited(self):
        m = self.member(); t = self.fs.read_text(self.pid, m, "README.md"); self.st.panic(self.pid, self.owner)
        self.assertEqual(self.forbidden(self.fs.write_text, self.pid, m, "README.md", "x", t["sha"]).code, "forbidden")


class TestUploads(Base):
    def test_a_file_in_pieces_lands_in_the_folder_once_and_never_overwrites(self):
        m = self.member(); data = os.urandom(900_000)
        r = self.upload(m, data, "data.bin", dir_="src", piece=400_000); self.assertEqual(r["path"], "src/data.bin"); self.assertEqual(open(os.path.join(self.work, "src", "data.bin"), "rb").read(), data)
        self.assertEqual(os.stat(os.path.join(self.work, "src", "data.bin")).st_mode & 0o111, 0)
        r2 = self.upload(m, b"second", "data.bin", dir_="src"); self.assertEqual(r2["path"], "src/data (2).bin"); self.assertEqual(open(os.path.join(self.work, "src", "data.bin"), "rb").read(), data)
        ev = [e["payload"] for e in self.st.read(self.pid, self.owner, limit=100) if e["type"] == "file_upload"]; self.assertEqual([(x["by"], x["path"]) for x in ev], [(m, "src/data.bin"), (m, "src/data (2).bin")])
        self.assertEqual(os.listdir(os.path.join(self.st._proj(self.pid).path, "uploads")), [])

    def test_names_are_only_names_and_the_folder_must_be_writable(self):
        m = self.member()
        for bad in ("", "   ", "..", "...", "x" * 300, 5, None):
            with self.assertRaises(S.CollabError, msg=repr(bad)): self.fs.begin_upload(self.pid, m, bad, 1, "dir", "")
        self.assertEqual([self.upload(m, b"x", n)["path"] for n in ("../x.txt", "a/b.txt", ".hidden")], ["_x.txt", "a_b.txt", "hidden"])         # a name is only a name: folders and leading dots are taken out
        self.assertEqual(self.upload(m, b"x", "we‮ird\x07name.txt")["path"], "weird_name.txt")
        ro = self.member("Ro", write_paths=[os.path.join(self.work, "src")]); self.upload(ro, b"ok", "ok.txt", dir_="src")
        for d in ("", "private", "..", "nope", "linkdir"): 
            with self.assertRaises(S.CollabError, msg=d): self.fs.begin_upload(self.pid, ro, "x.txt", 1, "dir", d)

    def test_order_size_ownership_and_limits_are_enforced(self):
        m = self.member(); o = self.member("Other"); u = self.fs.begin_upload(self.pid, m, "f.bin", 10, "dir", "src")["id"]
        self.assertEqual(self.forbidden(self.fs.chunk, self.pid, o, u, 0, b"x").code, "not_found")                              # someone else's upload
        self.assertEqual(self.forbidden(self.fs.chunk, self.pid, m, u, 1, b"x").code, "conflict"); self.assertEqual(self.forbidden(self.fs.chunk, self.pid, m, u, 0, b"x" * 11).code, "too_large")
        self.fs.chunk(self.pid, m, u, 0, b"12345"); self.assertEqual(self.forbidden(self.fs.finish_upload, self.pid, m, u).code, "conflict")           # not complete
        self.fs.chunk(self.pid, m, u, 1, b"67890"); self.fs.finish_upload(self.pid, m, u); self.assertEqual(self.forbidden(self.fs.chunk, self.pid, m, u, 2, b"x").code, "not_found")
        for bad in ("../x", "u_zzzz", 5, None): self.assertEqual(self.forbidden(self.fs.finish_upload, self.pid, m, bad).code, "not_found")
        old = F.MAX_DIR_FILE; F.MAX_DIR_FILE = 100; self.addCleanup(setattr, F, "MAX_DIR_FILE", old); self.assertEqual(self.forbidden(self.fs.begin_upload, self.pid, m, "big", 101, "dir", "src").code, "too_large")
        for _ in range(F.UPLOADS_PER_MEMBER): self.fs.begin_upload(self.pid, m, "p.bin", 5, "dir", "src")
        self.assertEqual(self.forbidden(self.fs.begin_upload, self.pid, m, "p.bin", 5, "dir", "src").code, "rate_limited")

    def test_turning_the_switch_off_before_the_end_stops_it_and_a_freeze_does_too(self):
        m = self.member(); u = self.fs.begin_upload(self.pid, m, "f.txt", 3, "dir", "src")["id"]; self.fs.chunk(self.pid, m, u, 0, b"abc")
        g = dict(self.st.grant_of(self.pid, m), files_upload_dir=False); self.st.set_grant(self.pid, self.owner, m, g)
        self.assertEqual(self.forbidden(self.fs.finish_upload, self.pid, m, u).code, "forbidden"); self.assertFalse(os.path.exists(os.path.join(self.work, "src", "f.txt")))
        self.st.set_grant(self.pid, self.owner, m, dict(g, files_upload_dir=True)); self.st.panic(self.pid, self.owner)
        self.assertEqual(self.forbidden(self.fs.begin_upload, self.pid, m, "g.txt", 1, "dir", "src").code, "forbidden")


class TestAttachments(Base):
    def test_a_file_attached_to_a_chat_is_a_message_others_can_download_and_the_model_can_find(self):
        m = self.member("Mei"); k = self.member("Kai", "viewer"); r = self.upload(m, b"figure data", "fig.png", target="chat", text="here is the figure"); aid = r["attachment"]
        self.assertEqual(r["path"], f".orbit-attachments/{aid}/fig.png"); self.assertEqual(open(os.path.join(self.work, r["path"]), "rb").read(), b"figure data")
        msg = [e for e in self.st.read(self.pid, k, limit=100) if e["type"] == "msg"][-1]; self.assertEqual((msg["author"], msg["payload"]["text"], msg["payload"]["attachments"]), (m, "here is the figure", [{"id": aid, "name": "fig.png", "size": 11}]))
        path, name, size = self.fs.open_attachment(self.pid, k, aid); self.assertEqual((name, size, open(path, "rb").read()), ("fig.png", 11, b"figure data"))
        self.assertEqual([a["id"] for a in self.fs.generated(self.pid, k)["attachments"]], [aid])
        self.assertNotIn(".orbit-attachments", [e["name"] for e in self.fs.list_dir(self.pid, m)["entries"]]); self.assertEqual(self.forbidden(self.fs.open_file, self.pid, m, f".orbit-attachments/{aid}/fig.png").code, "forbidden")

    def test_attachments_in_private_chats_and_without_download_rights_stay_private(self):
        m = self.member("Mei"); k = self.member("Kai"); self.st.create_chat(self.pid, m, "side", name="Side", visibility={"mode": "members", "members": [m]})
        aid = self.upload(m, b"x", "x.txt", target="chat", chat="side")["attachment"]
        self.assertEqual(self.forbidden(self.fs.open_attachment, self.pid, k, aid).code, "not_found"); self.assertEqual(self.fs.generated(self.pid, k)["attachments"], [])
        g = self.member("Gus", files_download=False); aid2 = self.upload(m, b"y", "y.txt", target="chat")["attachment"]; self.assertEqual(self.forbidden(self.fs.open_attachment, self.pid, g, aid2).code, "forbidden")

    def test_chat_uploads_need_the_right_to_post_and_a_visible_chat_and_have_a_size_limit(self):
        c = self.member("Cee", "commenter", can_post=False)
        with self.assertRaises(S.CollabError): self.fs.begin_upload(self.pid, c, "x.txt", 1, "chat", "", "main")
        m = self.member("Mei")
        for chat in ("nope", None, 5): 
            with self.assertRaises(S.CollabError): self.fs.begin_upload(self.pid, m, "x.txt", 1, "chat", "", chat)
        old = F.MAX_CHAT_FILE; F.MAX_CHAT_FILE = 10; self.addCleanup(setattr, F, "MAX_CHAT_FILE", old); self.assertEqual(self.forbidden(self.fs.begin_upload, self.pid, m, "b.bin", 11, "chat").code, "too_large")


if __name__ == "__main__":
    unittest.main()
