"""The execution jail: a command run for a member of a shared project can read the project and the system and write the project and its own scratch
folder, and nothing else. These run the REAL macOS sandbox; they are skipped where it does not exist."""
import os, shutil, subprocess, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
import collab_jail as J        # noqa: E402

PY = sys.executable
need = unittest.skipUnless(J.available(), "needs /usr/bin/sandbox-exec")


@need
class TestJail(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home"); self.proj = os.path.join(self.home, "proj"); self.out = os.path.join(self.tmp, "outside")
        for d in (self.proj, os.path.join(self.home, "Documents"), os.path.join(self.home, ".ssh"), self.out): os.makedirs(d)
        for f, t in ((os.path.join(self.home, "Documents", "private.txt"), "diary"), (os.path.join(self.home, ".ssh", "id_rsa"), "KEY"), (os.path.join(self.out, "s.txt"), "outside secret"),
                     (os.path.join(self.proj, "a.txt"), "project file")): open(f, "w").write(t)
        self.jail = J.Jail(self.proj, home=self.home, author="Mei").open(); self.addCleanup(self.jail.close)

    def sh(self, cmd, jail=None, timeout=20):
        j = jail or self.jail
        r = subprocess.run(j.argv_shell(cmd), capture_output=True, text=True, cwd=self.proj, env=j.env({"PATH": os.environ["PATH"], "LANG": "en_US.UTF-8"}), timeout=timeout, stdin=subprocess.DEVNULL)
        return r.returncode, r.stdout + r.stderr

    def py(self, code):
        p = os.path.join(self.jail.tmp, "t.py"); open(p, "w").write(code)
        r = subprocess.run(self.jail.argv_exec([PY, p]), capture_output=True, text=True, cwd=self.proj, env=self.jail.env({"PATH": os.environ["PATH"]}), timeout=30, stdin=subprocess.DEVNULL)
        return r.returncode, r.stdout + r.stderr

    # -- writing
    def test_writes_land_in_the_project_and_the_scratch_folder_only(self):
        self.assertEqual(self.sh("echo hi > new.txt && cat new.txt"), (0, "hi\n"))
        self.assertEqual(self.sh("echo hi > $TMPDIR/s.txt && cat $TMPDIR/s.txt")[0], 0)
        for cmd in (f"echo x > {self.out}/n.txt", f"echo x > {self.home}/Documents/n.txt", "echo x > ../n.txt", f"rm {self.out}/s.txt", f"mv a.txt {self.out}/a.txt", "echo x > /tmp/escape.txt"):
            rc, out = self.sh(cmd); self.assertNotEqual(rc, 0, cmd); self.assertIn("not permitted", out.lower(), cmd)
        self.assertTrue(os.path.exists(os.path.join(self.out, "s.txt"))); self.assertFalse(os.path.exists(os.path.join(self.out, "n.txt")))

    def test_python_is_held_to_the_same_rules(self):
        self.assertEqual(self.py("print(2+2)"), (0, "4\n"))
        self.assertEqual(self.py("open('b.txt','w').write('ok')")[0], 0); self.assertTrue(os.path.exists(os.path.join(self.proj, "b.txt")))
        rc, out = self.py(f"open({self.out!r} + '/p.txt','w').write('x')"); self.assertNotEqual(rc, 0); self.assertIn("not permitted", out.lower())

    def test_git_hooks_and_git_config_cannot_be_written(self):
        subprocess.run(["git", "init", "-q", self.proj], check=True)                                  # the host makes the repository
        rc, out = self.sh("git add a.txt && git commit -qm one && git log --format='%an' | head -1"); self.assertEqual((rc, out.strip()), (0, "Mei"), out)      # members can use it, named as themselves
        for cmd in ("echo '#!/bin/sh' > .git/hooks/pre-commit", "git config core.hooksPath /tmp/x", "echo '[core]' >> .git/config", "git init -q sub"):
            rc, out = self.sh(cmd); self.assertNotEqual(rc, 0, cmd)
        self.assertFalse(os.path.exists(os.path.join(self.proj, ".git", "hooks", "pre-commit")))

    # -- reading
    def test_the_project_and_the_system_are_readable_the_rest_of_the_home_is_not(self):
        self.assertEqual(self.sh("cat a.txt"), (0, "project file")); self.assertEqual(self.sh("ls /usr/bin | head -1")[0], 0)
        for p in (f"{self.home}/Documents/private.txt", f"{self.home}/.ssh/id_rsa", f"{self.home}/Documents"):
            rc, out = self.sh(f"cat {p}" if p.endswith("txt") or p.endswith("rsa") else f"ls {p}"); self.assertNotEqual(rc, 0, p); self.assertNotIn("diary", out); self.assertNotIn("KEY", out)
        rc, out = self.py(f"print(open({self.home!r} + '/Documents/private.txt').read())"); self.assertNotEqual(rc, 0); self.assertNotIn("diary", out)

    def test_a_link_inside_the_project_does_not_lead_out(self):
        os.symlink(os.path.join(self.home, "Documents", "private.txt"), os.path.join(self.proj, "link.txt"))
        rc, out = self.sh("cat link.txt"); self.assertNotEqual(rc, 0); self.assertNotIn("diary", out)

    def test_named_folders_are_unreadable_even_inside_a_readable_place(self):
        j = J.Jail(self.proj, home=self.home, deny_read=[os.path.join(self.proj, "private")]).open(); self.addCleanup(j.close)
        os.makedirs(os.path.join(self.proj, "private")); open(os.path.join(self.proj, "private", "k.txt"), "w").write("hidden")
        rc, out = self.sh("cat private/k.txt", jail=j); self.assertNotEqual(rc, 0); self.assertNotIn("hidden", out)
        self.assertEqual(self.sh("cat a.txt", jail=j)[0], 0)

    def test_extra_read_places_can_be_granted(self):
        j = J.Jail(self.proj, home=self.home, read_allow=[os.path.join(self.home, "Documents")]).open(); self.addCleanup(j.close)
        self.assertEqual(self.sh(f"cat {self.home}/Documents/private.txt", jail=j), (0, "diary"))

    # -- the network and the machine
    def test_the_network_is_off_unless_the_grant_has_it(self):
        rc, out = self.sh("/usr/bin/curl -s -m 4 -o /dev/null -w '%{http_code}' https://example.com"); self.assertNotEqual(out.strip(), "200"); self.assertNotEqual(rc, 0)
        self.assertIn("(deny network*)", self.jail.profile_text()); self.assertNotIn("(allow network", self.jail.profile_text())
        on = J.Jail(self.proj, home=self.home, allow_network=True); self.assertIn("(allow network*)", on.profile_text())

    def test_programs_that_drive_the_machine_do_not_run(self):
        for cmd in ("/usr/bin/osascript -e 'tell application \"Finder\" to get name of startup disk'", "/usr/bin/open -a Calculator", "/usr/bin/security find-generic-password -s x",
                    "/bin/launchctl list", "/usr/bin/defaults read NSGlobalDomain", "/usr/bin/sudo -n true"):
            rc, out = self.sh(cmd); self.assertNotEqual(rc, 0, cmd)

    def test_the_environment_carries_no_secrets_and_names_the_member(self):
        j = self.jail; base = {"PATH": "/usr/bin:/bin", "ANTHROPIC_API_KEY": "sk-ant-xxx", "GITHUB_TOKEN": "ghp_x", "AWS_SECRET_ACCESS_KEY": "x", "SSH_AUTH_SOCK": "/tmp/agent", "ORBIT_HOME": "/x",
                                    "MY_PASSWORD": "p", "LANG": "en_US.UTF-8", "HOME": "/Users/someone", "OPENAI_API_KEY": "x", "NPM_TOKEN": "x", "DB_URL_SECRET": "x"}
        e = j.env(base)
        for k in base:
            if k not in ("PATH", "LANG", "HOME"): self.assertNotIn(k, e, k)
        self.assertEqual(e["TMPDIR"].rstrip("/"), j.tmp.rstrip("/")); self.assertTrue(e["HOME"].startswith(j.tmp)); self.assertEqual(e["GIT_AUTHOR_NAME"], "Mei"); self.assertEqual(e["CI"], "1")
        rc, out = self.sh("env"); self.assertNotIn("SSH_AUTH_SOCK", out)

    # -- the jail itself
    def test_the_scratch_folder_and_profile_are_private_and_removed_at_the_end(self):
        self.assertEqual(os.stat(self.jail.tmp).st_mode & 0o077, 0); self.assertEqual(os.stat(self.jail.profile_path).st_mode & 0o077, 0)
        tmp, prof = self.jail.tmp, self.jail.profile_path; self.jail.close()
        self.assertFalse(os.path.exists(tmp)); self.assertFalse(os.path.exists(prof))

    def test_paths_are_quoted_safely_in_the_profile(self):
        evil = os.path.join(self.tmp, 'a"b) (allow file-write* (subpath "/"))')
        os.makedirs(evil)
        j = J.Jail(evil, home=self.home).open(); self.addCleanup(j.close)
        self.assertNotIn('(allow file-write* (subpath "/"))\n', j.profile_text().replace('\\"', "").replace("\\\\", ""))
        r = subprocess.run(j.argv_shell("echo x > ../zz.txt"), capture_output=True, text=True, cwd=evil, env=j.env({"PATH": "/usr/bin:/bin"}))
        self.assertNotEqual(r.returncode, 0); self.assertFalse(os.path.exists(os.path.join(self.tmp, "zz.txt")))

    def test_a_working_folder_that_is_not_a_real_folder_is_refused(self):
        for bad in ("", "relative/path", "/", self.home, os.path.join(self.tmp, "missing"), None):
            with self.assertRaises(ValueError): J.Jail(bad, home=self.home)


class TestWithoutTheSandbox(unittest.TestCase):
    def test_availability_is_a_plain_check(self):
        self.assertIsInstance(J.available(), bool)
        self.assertFalse(J.available("/nonexistent/sandbox-exec"))


if __name__ == "__main__":
    unittest.main()
