"""Backing cluster folders up to the lab NAS: the copy script (run for real against a local folder), what is left out, and the job bookkeeping."""
import json, os, shutil, subprocess, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
import nas_backup as N        # noqa: E402


class FakeCluster:
    def __init__(self, **cfg):
        self.cfg = {"label": "X", "profile": "h2", "job_prefix": "", "job_dirs": [], "partitions": "", **cfg}
        self.calls, self.answers = [], {}

    def _ssh(self, cmd, timeout=30):
        self.calls.append(cmd)
        for k, v in self.answers.items():
            if k in cmd: return 0, v
        if cmd.startswith("echo $HOME"): return 0, "/u/home/me"
        if "sbatch" in cmd: return 0, "4242"
        return 0, ""


class TestTheScript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_script(self, src, dest_path, versions=True, dry=False, stamp="20261030-020000"):
        wd = os.path.join(self.tmp, "wd"); os.makedirs(os.path.join(wd, "logs"), exist_ok=True)
        s = N.build_script("orbit-nasbackup-t", wd, src, {"host": "", "path": dest_path, "label": "L"}, "h2", "proj", N.DEFAULT_EXCLUDE, dry=dry, versions=versions, stamp=stamp)
        p = os.path.join(wd, "run.sh"); open(p, "w").write(s)
        r = subprocess.run(["bash", p], capture_output=True, text=True, env={**os.environ, "SLURM_JOB_ID": "1"})
        return s, r

    def test_it_copies_results_and_scripts_and_leaves_out_raw_and_intermediate_files(self):
        src, dst = os.path.join(self.tmp, "src"), os.path.join(self.tmp, "nas")
        os.makedirs(os.path.join(src, "results")); os.makedirs(os.path.join(src, "tmp")); os.makedirs(os.path.join(src, ".snakemake"))
        for rel in ("results/dmr.tsv", "run.sh", "slurm-1.out", "reads.fastq.gz", "aln.bam", "tmp/x", ".snakemake/y"):
            open(os.path.join(src, rel), "w").write("data " + rel)
        s, r = self.run_script(src, dst)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        base = os.path.join(dst, "h2", "proj")
        got = {os.path.relpath(os.path.join(a, f), base) for a, _, fs in os.walk(base) for f in fs}
        self.assertEqual(got, {"results/dmr.tsv", "run.sh", "slurm-1.out"})
        self.assertIn("@@result rc=0", r.stdout); self.assertNotIn("--delete", s)
        self.assertEqual(N.parse_log(r.stdout)["rc"], 0); self.assertEqual(N.parse_log(r.stdout)["files"], 3)

    def test_nothing_on_the_nas_is_deleted_and_a_changed_file_keeps_its_old_version(self):
        src, dst = os.path.join(self.tmp, "src"), os.path.join(self.tmp, "nas")
        os.makedirs(src); open(os.path.join(src, "a.tsv"), "w").write("one"); open(os.path.join(src, "b.tsv"), "w").write("b")
        self.run_script(src, dst)
        os.remove(os.path.join(src, "b.tsv"))                       # gone from the cluster...
        open(os.path.join(src, "a.tsv"), "w").write("two, longer"); os.utime(os.path.join(src, "a.tsv"), (2e9, 2e9))
        s, r = self.run_script(src, dst, stamp="20261031-020000")
        self.assertEqual(r.returncode, 0, r.stderr)
        base = os.path.join(dst, "h2", "proj")
        self.assertTrue(os.path.exists(os.path.join(base, "b.tsv")))                          # ...but kept on the NAS
        self.assertEqual(open(os.path.join(base, "a.tsv")).read(), "two, longer")
        self.assertEqual(open(os.path.join(dst, "_versions", "20261031", "h2", "proj", "a.tsv")).read(), "one")

    def test_a_dry_run_changes_nothing(self):
        src, dst = os.path.join(self.tmp, "src"), os.path.join(self.tmp, "nas")
        os.makedirs(src); open(os.path.join(src, "a.tsv"), "w").write("x")
        s, r = self.run_script(src, dst, dry=True)
        self.assertIn(" -n ", s); self.assertFalse(os.path.exists(os.path.join(dst, "h2", "proj", "a.tsv")))
        self.assertEqual(N.parse_log(r.stdout)["files"], 1)

    def test_the_remote_script_pins_the_host_key_and_uses_the_clusters_own_key(self):
        d = {"host": "nas.example.edu", "port": 2222, "user": "me", "path": "/vol/backup", "host_key": "[nas.example.edu]:2222 ssh-ed25519 AAAAC3x", "label": "NAS"}
        s = N.build_script("MP_nasbackup_x", "/share/mp/nasbackup", "/share/mp/work", d, "cassini", "work", ["*.bam"], partition="lab", node_exclude="compute-6-[11,19,21-23]")
        for need in ("#SBATCH -J MP_nasbackup_x", "#SBATCH -p lab", "--exclude=compute-6-[11,19,21-23]", "StrictHostKeyChecking=yes", "IdentitiesOnly=yes",
                     "/share/mp/nasbackup/nas_key", "me@nas.example.edu:/vol/backup/cassini/work/", "BatchMode=yes", "--exclude='*.bam'"):
            self.assertIn(need, s)
        self.assertNotIn("/tmp/", s.replace("$TMPDIR", ""))


class TestTheLogin(unittest.TestCase):
    PW = "p@ss = w0rd #1"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cas = FakeCluster(job_dirs=["/share/mp"], profile="slurm")
        self.n = N.NasBackup(os.path.join(self.tmp, "nas.json"), {"cassini": self.cas})

    def test_the_login_file_is_private_and_says_only_whether_it_is_filled_in(self):
        r = self.n.login_file()
        self.assertEqual(oct(os.stat(r["path"]).st_mode & 0o777), "0o600"); self.assertEqual((r["user_set"], r["password_set"]), (False, False))
        open(r["path"], "a").write(f"user=alex\npassword={self.PW}\n")
        r = self.n.login_file(); self.assertEqual((r["user_set"], r["password_set"]), (True, True))
        self.assertNotIn(self.PW, json.dumps(r)); self.assertEqual(N.read_login(r["path"]), ("alex", self.PW))     # '=' and '#' inside a password survive

    def test_the_password_reaches_ssh_only_through_the_askpass_helper(self):
        lf = self.n.login_file()["path"]; open(lf, "a").write(f"user=u\npassword={self.PW}\n")
        seen = {}
        real = subprocess.run
        def fake(args, **kw):
            if args and args[0] == "ssh":
                seen["args"], seen["env"] = args, kw["env"]
                seen["asked"] = real([kw["env"]["SSH_ASKPASS"]], capture_output=True, text=True).stdout     # what ssh would be handed
                seen["dir"] = os.path.dirname(kw["env"]["SSH_ASKPASS"])
                return subprocess.CompletedProcess(args, 0, "AUTHORIZED\n", "")
            return real(args, **kw)
        subprocess.run = fake
        try: rc, out = N.ssh_with_password("u", "nas.example", 2222, "[nas.example]:2222 ssh-ed25519 AAAA", lf, "echo AUTHORIZED")
        finally: subprocess.run = real
        self.assertEqual(seen["asked"], self.PW)
        self.assertNotIn(self.PW, " ".join(seen["args"])); self.assertFalse(any(self.PW in v for v in seen["env"].values()))
        self.assertIn("StrictHostKeyChecking=yes", seen["args"]); self.assertIn("PubkeyAuthentication=no", seen["args"])
        self.assertFalse(os.path.exists(seen["dir"]))                                              # the helper is gone afterwards

    def test_authorize_needs_the_fingerprint_and_a_filled_in_file_and_proves_the_key_works(self):
        self.n.update({"dest": {"host": "nas.example", "port": 22, "path": "/vol/b"}})
        with self.assertRaises(ValueError): self.n.authorize("cassini")                            # not trusted yet
        self.n.update({"dest": {"host_key": "nas.example ssh-ed25519 AAAA"}})
        with self.assertRaises(ValueError): self.n.authorize("cassini")                            # nothing filled in
        open(self.n.login_file()["path"], "a").write(f"user=me\npassword={self.PW}\n")
        self.cas.answers["nas_key.pub"] = "ssh-ed25519 AAAAkey orbit-nasbackup@cassini"
        calls = []
        old = N.ssh_with_password
        N.ssh_with_password = lambda *a, **k: (calls.append(a) or (0, "AUTHORIZED"))
        try:
            with self.assertRaises(RuntimeError): self.n.authorize("cassini")                      # the cluster cannot log in with it yet
            self.cas.answers["KEY_OK"] = "KEY_OK"; self.cas.answers["echo \"KEY_OK\""] = "KEY_OK"
            r = self.n.authorize("cassini")
        finally: N.ssh_with_password = old
        self.assertTrue(r["ok"]); self.assertEqual(self.n.cfg["dest"]["user"], "me")
        self.assertIn("no-port-forwarding", calls[-1][-1]); self.assertIn("AAAAkey", calls[-1][-1])


class TestMacAndRoutes(unittest.TestCase):
    GATE_FORBIDS = {"--rsync-path", "--backup-dir", "--partial-dir", "--temp-dir", "--log-file", "--files-from", "--link-dest", "--copy-dest", "--compare-dest", "--rsh"}

    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.h2, self.cas = FakeCluster(host="hpc"), FakeCluster(host="cassini", job_prefix="MP_", job_dirs=["/share/mp"], partitions="lab", profile="slurm")
        self.n = N.NasBackup(os.path.join(self.tmp, "nas.json"), {"hpc": self.h2, "cassini": self.cas})
        self.route = {"id": "h2-cassini", "label": "HPC → Cassini", "from": "hpc", "host": "cassini2.example.edu", "port": 22, "user": "yuxing",
                      "path": "/share/mp/inbox", "host_key": "cassini2.example.edu ssh-ed25519 AAAAx"}

    def test_a_weekly_schedule_is_the_default(self):
        self.assertEqual(self.n.cfg["every_h"], 168)

    def test_the_transfer_script_uses_only_options_the_far_gate_allows_and_never_deletes(self):
        for direction in ("push", "pull"):
            s = N.build_transfer_script("MP_xfer_x", "/share/mp/nasbackup", self.route, direction, "/u/a/b", "/share/mp/inbox/b", exclude=["*.bam"])
            self.assertNotIn("--delete", s)
            for bad in self.GATE_FORBIDS: self.assertNotIn(bad, s)
            for need in ("StrictHostKeyChecking=yes", "IdentitiesOnly=yes", "h2-cassini_key", "BatchMode=yes", "--exclude='*.bam'"): self.assertIn(need, s)
        push = N.build_transfer_script("j", "/w", self.route, "push", "/u/a/b", "/share/mp/inbox/b")
        pull = N.build_transfer_script("j", "/w", self.route, "pull", "/share/mp/results", "/u/a/in")
        self.assertIn("/u/a/b/ yuxing@cassini2.example.edu:/share/mp/inbox/b/", push)
        self.assertIn("yuxing@cassini2.example.edu:/share/mp/results/ /u/a/in/", pull); self.assertIn("mkdir -p /u/a/in", pull)

    def test_routes_are_checked_and_a_transfer_needs_the_key_and_the_trusted_host(self):
        with self.assertRaises(ValueError): self.n.update({"routes": [{**self.route, "from": "nowhere"}]})
        with self.assertRaises(ValueError): self.n.update({"routes": [{**self.route, "user": "a b;"}]})
        self.n.update({"routes": [{**self.route, "host_key": ""}]})
        with self.assertRaises(ValueError): self.n.transfer("h2-cassini", "push", "/u/a/b", "/share/mp/inbox/b")      # not trusted
        self.n.update({"routes": [self.route]})
        with self.assertRaises(ValueError): self.n.transfer("h2-cassini", "push", "/u/a/b", "/share/mp/inbox/b")      # no key yet
        self.h2.answers["h2-cassini_key\" ] && echo ok"] = "ok"
        r = self.n.transfer("h2-cassini", "push", "/u/a/b", "/share/mp/inbox/b", dry=True)
        self.assertEqual((r["state"], r["route"], r["dry"]), ("submitted", "h2-cassini", True))
        with self.assertRaises(ValueError): self.n.transfer("h2-cassini", "sideways", "/u/a/b", "/x/y")

    def test_the_mac_copies_into_a_mounted_nas_folder_and_says_how_it_went(self):
        mount = os.path.join(self.tmp, "Volumes", "backup2", "me")
        with self.assertRaises(ValueError): self.n.update({"dest": {"mode": "mac", "mount": "/etc/passwd"}})          # only under /Volumes
        self.n.cfg["dest"].update(mode="mac", mount=mount)                                                           # (a temp folder stands in for /Volumes)
        self.n.cfg["sources"] = [{"id": "hpc-res", "cluster": "hpc", "path": "/u/a/res", "label": "res"}]
        with self.assertRaises(ValueError): self.n.run()                                                             # not mounted
        os.makedirs(mount)
        seen = {}
        real = subprocess.run
        def fake(cmd, **kw):
            if cmd[0] == "rsync":
                seen["cmd"] = cmd
                return subprocess.CompletedProcess(cmd, 0, "Number of regular files transferred: 4\nTotal transferred file size: 1.2M bytes\n", "")
            return real(cmd, **kw)
        subprocess.run = fake
        try:
            out = self.n.run()
            for _ in range(50):
                if self.n.status()["latest"]["hpc-res"]["state"] != "running": break
                import time; time.sleep(0.05)
        finally: subprocess.run = real
        c = seen["cmd"]
        self.assertIn("hpc:/u/a/res/", c); self.assertTrue(c[-1].endswith("/hpc/res/")); self.assertNotIn("--delete", c); self.assertIn("--backup", c)
        r = self.n.status()["latest"]["hpc-res"]
        self.assertEqual((r["state"], r["files"], r["bytes"]), ("done", 4, "1.2M")); self.assertEqual(out[0]["via"], "mac")


class TestTheBookkeeping(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.h2, self.cas = FakeCluster(), FakeCluster(job_prefix="MP_", job_dirs=["/share/mp"], partitions="lab", profile="slurm")
        self.told = []
        self.n = N.NasBackup(os.path.join(self.tmp, "nas.json"), {"hpc": self.h2, "cassini": self.cas}, notify=lambda t, x: self.told.append((t, x)))

    def ready(self):
        self.n.update({"dest": {"host": "nas.example.org", "user": "me", "path": "/vol/backup", "host_key": "[h]:2222 ssh-ed25519 AAAA"},
                       "sources": [{"cluster": "hpc", "path": "/path/to/project/lab/me/results", "label": "Results"},
                                   {"cluster": "cassini", "path": "/share/mp/analysis", "label": "Analysis"}]})

    def test_settings_are_checked(self):
        for bad in ({"dest": {"port": 99999}}, {"dest": {"user": "me; rm -rf /"}}, {"dest": {"path": "../etc"}}, {"dest": {"host_key": "garbage"}},
                    {"sources": [{"cluster": "nope", "path": "/a/b"}]}, {"sources": [{"cluster": "hpc", "path": "/a/../b"}]}):
            with self.assertRaises(ValueError): self.n.update(bad)

    def test_nothing_runs_until_the_nas_is_set_up(self):
        self.n.update({"sources": [{"cluster": "hpc", "path": "/u/a/b", "label": "x"}]})
        with self.assertRaises(ValueError): self.n.run()                     # no folder on the NAS yet
        self.n.update({"dest": {"host": "nas.example.org", "path": "/vol/backup"}})
        with self.assertRaises(ValueError): self.n.run()                     # no user
        self.n.update({"dest": {"user": "me"}})
        with self.assertRaises(ValueError): self.n.run()                     # host key not confirmed

    def test_a_job_is_submitted_per_folder_named_the_way_each_cluster_requires(self):
        self.ready(); self.h2.answers["nas_key\" ] && echo ok"] = "ok"; self.cas.answers["nas_key\" ] && echo ok"] = "ok"
        out = self.n.run()
        self.assertEqual([r["state"] for r in out], ["submitted", "submitted"])
        h2s = next(c for c in self.h2.calls if "sbatch" in c); cs = next(c for c in self.cas.calls if "sbatch" in c)
        import base64, re
        body = lambda c: base64.b64decode(re.search(r"printf %s (\S+) \|", c)[1]).decode()
        self.assertIn("#SBATCH -J orbit-nasbackup-results", body(h2s)); self.assertIn("/u/home/me/.orbit/nasbackup/logs", body(h2s))
        self.assertIn("#SBATCH -J MP_nasbackup_analysis", body(cs)); self.assertIn("-p lab", body(cs)); self.assertIn("/share/mp/nasbackup", cs)

    def test_a_missing_key_is_said_not_silently_skipped(self):
        self.ready()
        out = self.n.run(only="hpc-results")
        self.assertEqual(out[0]["state"], "failed"); self.assertIn("Set up the key", out[0]["error"])

    def test_how_a_job_ended_is_read_and_told_once(self):
        self.ready(); self.h2.answers["nas_key\" ] && echo ok"] = "ok"
        self.n.run(only="hpc-results")
        self.h2.answers["squeue -j 4242"] = "\n@@acct\nCOMPLETED|0:0"
        self.h2.answers["tail -n 60"] = "Number of regular files transferred: 12\nTotal transferred file size: 3.4M bytes\n@@result rc=0\n"
        self.n.refresh(); self.n.refresh()
        r = self.n.status()["latest"]["hpc-results"]
        self.assertEqual((r["state"], r["files"], r["bytes"]), ("done", 12, "3.4M")); self.assertEqual(len(self.told), 1)

    def test_a_failed_copy_says_why(self):
        self.ready(); self.h2.answers["nas_key\" ] && echo ok"] = "ok"
        self.n.run(only="hpc-results")
        self.h2.answers["squeue -j 4242"] = "\n@@acct\nFAILED|12:0"
        self.h2.answers["tail -n 60"] = "Permission denied (publickey).\nrsync: connection unexpectedly closed\n@@result rc=255\n"
        self.n.refresh()
        r = self.n.status()["latest"]["hpc-results"]
        self.assertEqual(r["state"], "failed"); self.assertIn("rsync", r["error"]); self.assertEqual(self.told[0][0], "NAS backup failed")

    def test_the_cluster_page_does_not_announce_the_backup_jobs(self):
        import cluster as C
        c = C.Cluster(os.path.join(self.tmp, "c.json"), object())
        self.assertTrue(c._own("orbit-nasbackup-results")); self.assertTrue(c._own("MP_nasbackup_analysis")); self.assertFalse(c._own("MP_af3"))

    def test_a_scheduled_run_that_cannot_reach_a_cluster_is_tried_again_every_half_hour_until_it_works(self):
        self.ready(); self.n.cfg["enabled"] = True; self.n.cfg["last_start"] = 1.0
        clock = {"t": 1000.0}; self.n.now = lambda: clock["t"]
        self.h2.answers["nas_key\" ] && echo ok"] = "ok"
        orig = self.h2._ssh
        up = {"on": False}
        def ssh(cmd, timeout=30):
            if not up["on"]: self.h2.calls.append(cmd); return 255, "ssh failed: timed out"
            return orig(cmd, timeout)
        self.h2._ssh = ssh
        self.n.cfg["sources"] = [s for s in self.n.cfg["sources"] if s["cluster"] == "hpc"]
        out = self.n.run(reason="schedule")
        self.assertEqual(out[0]["state"], "failed"); rt = self.n.cfg["retry"]["hpc-results"]; self.assertEqual(rt["at"], 1000.0 + N.RETRY_S)
        calls = len(self.h2.calls); clock["t"] += 600; self.n.maybe_run(); self.assertEqual(len(self.h2.calls), calls)     # too early
        clock["t"] += 1300; self.n.maybe_run()                                                                          # half an hour on: tried again, still down
        self.assertGreater(len(self.h2.calls), calls); self.assertEqual(self.n.cfg["retry"]["hpc-results"]["n"], 2)
        up["on"] = True; clock["t"] += N.RETRY_S + 1; self.n.maybe_run()
        self.assertNotIn("hpc-results", self.n.cfg["retry"]); self.assertEqual(self.n.status()["latest"]["hpc-results"]["state"], "submitted")

    def test_a_manual_run_that_fails_is_not_retried_behind_your_back(self):
        self.ready()
        out = self.n.run(only="hpc-results", reason="manual")        # no key yet: failed, and not a reachability problem anyway
        self.assertEqual(out[0]["state"], "failed"); self.assertFalse(self.n.cfg.get("retry"))


if __name__ == "__main__":
    unittest.main()
