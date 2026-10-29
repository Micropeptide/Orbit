"""The Orbit helpers skill: well-formed, free of anything personal or secret, and installed only where and how the person asked."""
import os, re, shutil, sys, tempfile, unittest, zipfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
import helper_skill as H           # noqa: E402
import science_bridge as B         # noqa: E402


class TestTheSkillItself(unittest.TestCase):
    def test_the_front_matter_is_what_agents_need(self):
        text = open(os.path.join(H.source(), "SKILL.md"), encoding="utf-8").read()
        m = re.match(r"---\nname: (orbit-helpers)\ndescription: (.+)\n(?:metadata:\n(?:  .*\n)+)?---\n", text); self.assertTrue(m, text[:300])
        self.assertLess(len(m.group(2)), 1024); self.assertGreater(len(m.group(2)), 100); self.assertEqual(H.version(), "1.2")

    def test_every_reference_it_names_exists_and_every_tool_it_names_is_real(self):
        src = H.source(); text = open(os.path.join(src, "SKILL.md")).read()
        for ref in re.findall(r"`(references/[\w\-.]+)`", text): self.assertTrue(os.path.isfile(os.path.join(src, ref)), ref)
        declared = {t["name"] for t in B.TOOLS}
        for rel in H.files():
            for tool in set(re.findall(r"`(orbit_[a-z_]+)`", open(os.path.join(src, rel)).read())): self.assertIn(tool, declared, f"{rel} names {tool}")

    def test_every_tool_is_mentioned_somewhere_in_the_skill(self):
        blob = "".join(open(os.path.join(H.source(), rel)).read() for rel in H.files())
        for t in B.TOOLS: self.assertIn(t["name"], blob, t["name"] + " is not explained in the skill")

    def test_nothing_personal_or_secret_and_the_body_is_short(self):
        for rel in H.files():
            text = open(os.path.join(H.source(), rel)).read()
            for bad in (r"/Users/", r"runtian", r"Bearer [A-Za-z0-9_\-]{20,}", r"[A-Za-z0-9_\-]{43,}", r"@[a-z0-9\-]+\.(com|edu|org)", r"sk-[A-Za-z0-9]{10,}"): self.assertIsNone(re.search(bad, text, re.I), f"{rel}: {bad}")
        self.assertLess(len(open(os.path.join(H.source(), "SKILL.md")).read().split()), 700)

    def test_the_single_file_version_and_the_skill_tell_the_same_rules(self):
        one = open(os.path.join(os.path.dirname(H.SRC), "..", "claude-science-instructions.md")).read(); skill = open(os.path.join(H.source(), "SKILL.md")).read()
        for must in ("orbit_server_llms", "orbit_wait", "orbit_cluster_wait", "orbit_talk", "APPROVED", "[person]"):
            self.assertIn(must, one + "".join(open(os.path.join(H.source(), r)).read() for r in H.files())); 
        self.assertIn("never", skill.lower())


class TestInstall(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.skills = os.path.join(self.tmp, "skills"); os.makedirs(self.skills)

    def test_it_installs_all_the_files_and_a_marker(self):
        r = H.install(self.skills); dest = os.path.join(self.skills, "orbit-helpers")
        self.assertEqual(r["path"], dest); self.assertEqual(sorted(os.listdir(dest)), sorted([".installed-by-orbit", "SKILL.md", "references"]))
        self.assertEqual(sorted(os.listdir(os.path.join(dest, "references"))), sorted(os.path.basename(f) for f in H.files() if f.startswith("references/")))
        self.assertEqual(open(os.path.join(dest, ".installed-by-orbit")).read().strip(), "1.2"); self.assertEqual([n for n in os.listdir(self.skills) if n.startswith(".")], [])

    def test_installing_again_updates_its_own_copy_and_removes_stale_files(self):
        H.install(self.skills); dest = os.path.join(self.skills, "orbit-helpers"); open(os.path.join(dest, "references", "old.md"), "w").write("stale"); open(os.path.join(dest, "SKILL.md"), "w").write("edited")
        H.install(self.skills); self.assertFalse(os.path.exists(os.path.join(dest, "references", "old.md"))); self.assertIn("name: orbit-helpers", open(os.path.join(dest, "SKILL.md")).read())

    def test_a_folder_orbit_did_not_make_is_never_touched(self):
        mine = os.path.join(self.skills, "orbit-helpers"); os.makedirs(mine); open(os.path.join(mine, "SKILL.md"), "w").write("my own skill")
        with self.assertRaises(H.SkillError): H.install(self.skills)
        self.assertEqual(open(os.path.join(mine, "SKILL.md")).read(), "my own skill")
        link_target = os.path.join(self.tmp, "elsewhere"); os.makedirs(link_target); other = os.path.join(self.tmp, "s2"); os.makedirs(other); os.symlink(link_target, os.path.join(other, "orbit-helpers"))
        with self.assertRaises(H.SkillError): H.install(other)
        self.assertEqual(os.listdir(link_target), [])

    def test_a_missing_folder_is_refused(self):
        for bad in (os.path.join(self.tmp, "nope"), None, 5, ""):
            with self.assertRaises(H.SkillError): H.install(bad)

    def test_targets_lists_only_the_agents_that_are_there(self):
        home = os.path.join(self.tmp, "home"); os.makedirs(os.path.join(home, ".claude", "skills")); sci = os.path.join(self.tmp, "sci"); os.makedirs(os.path.join(sci, "skills"))
        t = {x["id"]: x for x in H.targets(sci, home)}; self.assertEqual(sorted(t), ["claude-code", "claude-science"]); self.assertFalse(t["claude-code"]["installed"])
        H.install(t["claude-code"]["dir"]); t = {x["id"]: x for x in H.targets(sci, home)}; self.assertTrue(t["claude-code"]["installed"] and t["claude-code"]["ours"]); self.assertEqual(t["claude-code"]["version"], "1.2")
        self.assertEqual(H.targets("", os.path.join(self.tmp, "empty")), [])

    def test_the_zip_has_one_top_folder_with_the_same_files(self):
        r = H.make_zip(os.path.join(self.tmp, "out")); self.assertTrue(r["path"].endswith("orbit-helpers-1.2.zip"))
        with zipfile.ZipFile(r["path"]) as z: names = z.namelist()
        self.assertEqual(sorted(names), sorted("orbit-helpers/" + f for f in H.files())); self.assertTrue(all(n.startswith("orbit-helpers/") and ".." not in n for n in names))


class TestRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.machinery, importlib.util
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_loader("qqui_skl", importlib.machinery.SourceFileLoader("qqui_skl", os.path.join(root, "bin", "orbit-ui")))
        cls.ui = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.ui)

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.skills = os.path.join(self.tmp, "skills"); os.makedirs(self.skills)
        orig = H.targets; self.addCleanup(setattr, H, "targets", orig)
        H.targets = lambda csci="", home=None: [{"id": "claude-code", "name": "Claude Code", "dir": self.skills, "installed": os.path.isdir(os.path.join(self.skills, "orbit-helpers")), "ours": False, "version": ""}]
        self.old = self.ui.q.ROOT; self.ui.q.ROOT = self.tmp; self.addCleanup(setattr, self.ui.q, "ROOT", self.old)

    def r(self, d): st, raw = self.ui._science_helper_route(d); import json; return st, json.loads(raw)

    def test_status_install_and_zip_through_the_route(self):
        st, j = self.r({"op": "skill_status"}); self.assertEqual((st, [t["id"] for t in j["targets"]], j["version"]), (200, ["claude-code"], "1.2"))
        st, j = self.r({"op": "skill_install", "target": "claude-code"}); self.assertEqual(st, 200); self.assertTrue(os.path.isfile(os.path.join(self.skills, "orbit-helpers", "SKILL.md")))
        st, j = self.r({"op": "skill_zip", "reveal": False}); self.assertEqual(st, 200); self.assertTrue(os.path.isfile(j["path"])); self.assertIn("exports", j["path"])

    def test_only_listed_agents_can_be_installed_into(self):
        for bad in ("../../etc", "codex", None, 5, "/tmp"): self.assertEqual(self.r({"op": "skill_install", "target": bad})[0], 400)
        self.assertEqual(os.listdir(self.skills), [])


if __name__ == "__main__":
    unittest.main()
