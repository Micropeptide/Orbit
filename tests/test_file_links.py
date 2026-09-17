"""Files a chat names (bin/file_links.py): finding them where the chat works, what
may be shown in a page, preview links that cannot leave their folder, and previews
of documents, spreadsheets and archives. Nothing is opened on the Mac."""
import json, os, shutil, subprocess, sys, tempfile, unittest, urllib.parse, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin"))
import file_links as F        # noqa: E402
import ssh_remote as R        # noqa: E402


class TestNames(unittest.TestCase):
    def test_names_as_models_write_them(self):
        self.assertEqual(F.clean("`src/app.py:42`"), ("src/app.py", 42))
        self.assertEqual(F.clean("src/app.py:42:7"), ("src/app.py", 42))
        self.assertEqual(F.clean("src/app.py#L12-L20"), ("src/app.py", 12))
        self.assertEqual(F.clean("file:///Users/x/a%20b.png"), ("/Users/x/a b.png", None))
        self.assertEqual(F.clean("**report.html**,"), ("report.html", None))
        self.assertEqual(F.clean("<notes.md>."), ("notes.md", None))

    def test_what_looks_like_a_file(self):
        for yes in ("figure.html", "./out/plot.png", "~/x.csv", "/tmp/a", "data/seqs.fasta", "Makefile", "run.sh"):
            self.assertTrue(F.looks_like_file(yes), yes)
        for no in ("1.2.3", "https://example.com/a.html", "hello", "two words"):
            self.assertFalse(F.looks_like_file(no), no)

    def test_open_commands_in_shell_blocks(self):
        self.assertEqual(F.open_targets("open deepseek-claude-code-figure.html"), ["deepseek-claude-code-figure.html"])
        self.assertEqual(F.open_targets("$ open -a Preview 'my plot.png'\nls\ncode src/a.py"), ["my plot.png", "src/a.py"])
        self.assertEqual(F.open_targets("open https://example.com"), [])


class TestFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="orbit-files-", dir=os.path.expanduser("~/Library/Caches")
                                                     if os.path.isdir(os.path.expanduser("~/Library/Caches")) else None))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.work = os.path.join(self.tmp, "chat folder")
        self.other = os.path.join(self.tmp, "workspace")
        os.makedirs(os.path.join(self.work, "figures"))
        os.makedirs(self.other)
        self.write("figures/plot.png", b"\x89PNG\r\n\x1a\nfake")
        self.write("report.html", b"<img src='figures/plot.png'>")
        self.write("résumé final.txt", b"hi")
        open(os.path.join(self.other, "only-there.md"), "w").write("# x")

    def write(self, rel, data):
        p = os.path.join(self.work, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").write(data)
        return p

    def test_relative_names_mean_the_chats_folder_first(self):
        roots = F.roots_for(self.work, (), None, self.other)
        f = F.resolve("`report.html`", roots)
        self.assertTrue(f["exists"])
        self.assertEqual(f["path"], os.path.join(self.work, "report.html"))
        self.assertEqual((f["category"], f["kind"]), ("html", "file"))
        self.assertTrue(F.resolve("./figures/plot.png", roots)["exists"])
        self.assertTrue(F.resolve("résumé final.txt", roots)["exists"])
        self.assertTrue(F.resolve("only-there.md", roots)["exists"])           # the next folder in line
        miss = F.resolve("src/nothing.py:12", roots)
        self.assertFalse(miss["exists"])
        self.assertEqual((miss["line"], miss["path"]), (12, os.path.join(self.work, "src", "nothing.py")))
        # a bare name the chat wrote somewhere else
        elsewhere = os.path.join(self.tmp, "deep", "made.csv")
        os.makedirs(os.path.dirname(elsewhere)); open(elsewhere, "w").write("a,b")
        self.assertEqual(F.resolve("made.csv", roots, changed=[elsewhere])["path"], elsewhere)
        folder = F.resolve("figures/", roots)
        self.assertEqual((folder["kind"], folder["category"]), ("folder", "folder"))

    def test_secrets_and_scripts(self):
        key = self.write(".ssh/id_ed25519", b"PRIVATE")
        env = self.write(".env", b"KEY=1")
        sec = self.write("config/secrets.json", b"{}")
        for p in (key, env, sec):
            self.assertFalse(F.servable(p), p)
        self.assertTrue(F.servable(os.path.join(self.work, "report.html")))
        self.assertFalse(F.servable("/etc/hosts"))
        sh = self.write("run.sh", b"#!/bin/sh\necho hi\n"); os.chmod(sh, 0o755)
        self.assertTrue(F.describe(sh)["runs"])
        self.assertFalse(F.describe(os.path.join(self.work, "report.html"))["runs"])

    def test_a_preview_link_opens_one_folder_and_nothing_above_it(self):
        url = F.grant(os.path.join(self.work, "report.html"))
        self.assertTrue(url.startswith("/fs/") and url.endswith("/report.html"))
        base = url.rsplit("/", 1)[0]
        self.assertEqual(F.granted_file(base + "/figures/plot.png"), os.path.join(self.work, "figures", "plot.png"))
        self.assertEqual(F.granted_file(base + "/" + urllib.parse.quote("résumé final.txt")),
                         os.path.join(self.work, "résumé final.txt"))
        self.assertIsNone(F.granted_file(base + "/../workspace/only-there.md"))
        self.assertIsNone(F.granted_file(base + "/%2e%2e/workspace/only-there.md"))
        self.assertIsNone(F.granted_file("/fs/not-a-real-token-at-all/report.html"))
        self.write(".env", b"KEY=1")
        self.assertIsNone(F.granted_file(base + "/.env"))
        # the same folder reuses its link
        self.assertEqual(F.grant(os.path.join(self.work, "figures", "..", "report.html")).rsplit("/", 1)[0], base)
        h = F.preview_headers(os.path.join(self.work, "report.html"))
        self.assertIn("sandbox", h["Content-Security-Policy"])
        self.assertNotIn("allow-same-origin", h["Content-Security-Policy"])

    def test_previews_of_documents_spreadsheets_and_archives(self):
        cache = os.path.join(self.tmp, "cache")
        z = os.path.join(self.work, "bundle.zip")
        with zipfile.ZipFile(z, "w") as zf: zf.writestr("inside/a.txt", "x")
        kind, out = F.render_preview(z, cache)
        self.assertEqual(kind, "html")
        self.assertIn("inside/a.txt", open(out).read())
        if shutil.which("textutil"):
            md = self.write("memo.txt", b"Hello memo")
            docx = os.path.join(self.work, "memo.docx")
            subprocess.run(["textutil", "-convert", "docx", "-output", docx, md], check=True, capture_output=True)
            kind, out = F.render_preview(docx, cache)
            self.assertEqual(kind, "html")
            self.assertIn("Hello memo", open(out, encoding="utf-8", errors="replace").read())
        try:
            import openpyxl
        except ImportError:
            openpyxl = None
        if openpyxl:
            wb = openpyxl.Workbook(); wb.active.title = "Results"; wb.active.append(["gene", "<b>x</b>"]); wb.active.append(["AT1", 2])
            x = os.path.join(self.work, "t.xlsx"); wb.save(x)
            kind, out = F.render_preview(x, cache)
            html = open(out).read()
            self.assertEqual(kind, "html")
            self.assertIn("Results", html); self.assertIn("AT1", html)
            self.assertIn("&lt;b&gt;", html)                                      # cell text is never markup

    def test_open_with_offers_only_installed_apps(self):
        apps = F.open_with_apps(os.path.join(self.work, "report.html"))
        self.assertTrue(all(os.path.isdir(a["app"]) for a in apps))
        ok, why = F.open_path(os.path.join(self.work, "report.html"), app="/Applications/NotAnApp.app")
        self.assertFalse(ok)

    def test_names_on_an_ssh_host(self):
        # the remote lookup script, run here with bash instead of over SSH
        saved = R.run
        R.run = lambda host, script, timeout=60, shared=True: (lambda r: (r.returncode, r.stdout, r.stderr))(
            subprocess.run(["bash", "-s"], input=script, capture_output=True, text=True))
        try:
            found = R.stat_paths("cluster", ["report.html", "figures", "nope.txt", "résumé final.txt"], self.work)
        finally:
            R.run = saved
        self.assertEqual(set(found), {"report.html", "figures", "résumé final.txt"})
        self.assertEqual(found["report.html"]["path"], os.path.join(self.work, "report.html"))
        self.assertEqual(found["figures"]["kind"], "folder")
        self.assertEqual(found["report.html"]["size"], len(b"<img src='figures/plot.png'>"))


if __name__ == "__main__":
    unittest.main()
