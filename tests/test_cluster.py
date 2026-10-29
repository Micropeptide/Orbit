"""The cluster page: parsing what the cluster prints, reading errors, and watching the queue."""
import json, os, sys, tempfile, shutil, time, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
import cluster as C        # noqa: E402

SQUEUE = "511028|qwen-serve|PENDING|campus||0:00|1-00:00:00|16|128G|gres/gpu:1|Resources|2026-10-26T20:58:59|N/A\n" \
         "7002|train-model|RUNNING|campus|g12|1:05:09|1-00:00:00|16|64G|gres/gpu:1|None|2026-10-26T08:00:00|2026-10-26T08:05:00"
SACCT = "7000|index-genome|campus|COMPLETED|00:42:10|0:0|2026-10-26T06:00:00|2026-10-26T06:42:10|billing=8,cpu=8,gres/gpu=0,mem=32G|n21\n" \
        "6999|qc-run|campus|FAILED|00:00:31|1:0|2026-10-26T05:00:00|2026-10-26T05:00:31|billing=4,cpu=4,mem=16G|n22\n" \
        "6998|train-model|campus|OUT_OF_MEMORY|10:00:00|0:125|2026-10-25T05:00:00|2026-10-25T15:00:00|billing=16,cpu=16,gres/gpu=1,mem=64G|g12"
QUOTA = """Disk quotas for user demo (uid 22240): 
     Filesystem   space   quota   limit   grace   files   quota   limit   grace
172.16.108.217:/u/home/a
                 34104M  57221M  57221M            456k   5000k   5000k        
172.16.108.209:/scratch
                 374G      0K   1863G           73877       0       0        
172.16.108.222:/u/home/s
                 34104M  57221M  57221M            456k   5000k   5000k        """
DF = """Filesystem                          Type  Size  Used Avail Use% Mounted on
172.16.108.206:/u/home/r            nfs   9.6P   77T  9.5P   1% /u/home/r
172.16.108.233:/path/to/project/lab       nfs    63T   61T  2.2T  97% /path/to/project/lab"""
GPUS = """## GPUs by model (live)

| Model        | VRAM    | CUDA         | Nodes | GPUs | Free |
| ------------ | ------- | ------------ | ----: | ---: | ---: |
| RTXPRO6000Bw | vmem97G | cuda_cc_12_0 |     3 |   17 |    4 |
| A100         | vmem40G | cuda_cc_8_0  |     1 |    4 |    0 |

16 of 21 GPUs free on 4 nodes.

## GPU nodes

| Node | Model        | Free GPUs | State      | Idle CPUs | Free mem | Partitions |
| ---- | ------------ | --------: | ---------- | --------: | -------: | ---------- |
| g34  | RTXPRO6000Bw |       1/8 | mixed      |   114/128 |     199G | campus     |
| g35  | RTXPRO6000Bw |       3/7 | mixed      |    96/128 |      83G | campus     |
| g15  | A100         |       0/4 | idle+drain |      0/32 |       0G | campus     |
"""
WHOAMI = """## demo on HPC

Account: pi_lab. It is selected automatically.

### pi_lab, fairshare 0.226323
- jobs run on campus: 24h max, 126 nodes (58 idle), 6112 CPUs (3495 idle), 13 GPUs; per user: 1024 CPUs, 2 GPUs, 16 nodes, 100 running jobs
"""
LOOK = "@@host\nlogin4|14|1024|0.36, 0.28, 0.33\n@@squeue\n" + SQUEUE + "\n@@sacct\n" + SACCT + "\n@@quota\n" + QUOTA + "\n@@df\n" + DF + \
       "\n@@gpus\n" + GPUS + "\n@@whoami\n" + WHOAMI + "\n@@sinfo\ncampus*|up|1-00:00:00|2617/3495/0/6112\n"


class TestParsing(unittest.TestCase):
    def test_jobs_and_time_left(self):
        j = C.parse_squeue(SQUEUE)
        self.assertEqual([(x["id"], x["state"], x["gpus"], x["reason"]) for x in j], [("511028", "PENDING", 1, "Resources"), ("7002", "RUNNING", 1, "")])
        self.assertEqual(j[1]["left"], 86400 - 3909)

    def test_quota_with_wrapped_lines_and_no_soft_quota(self):
        q = C.parse_quota(QUOTA)
        self.assertEqual(len(q), 3)
        self.assertAlmostEqual(q[0]["used_kb"] / 1024 ** 2, 33.3, places=1); self.assertEqual(q[0]["files"], 456000)
        self.assertEqual(q[1]["quota_kb"], 0); self.assertAlmostEqual(q[1]["limit_kb"] / 1024 ** 2, 1863)

    def test_snapshot_shows_the_home_once_and_warns_about_the_full_project_disk(self):
        s = C.snapshot_from(LOOK, "/path/to/project/lab")
        self.assertEqual([x["label"] for x in s["storage"]], ["Home", "Scratch"])
        self.assertEqual(s["storage"][0]["pct"], 60)
        self.assertEqual(s["shared"][0]["pct"], 97)
        self.assertEqual(s["problems"][0]["level"], "bad"); self.assertIn("97%", s["problems"][0]["text"])
        self.assertTrue(any("did not finish well" in p["text"] for p in s["problems"]))           # no "now": every recent failure counts
        later = C.snapshot_from(LOOK, "/path/to/project/lab", now=time.mktime(time.strptime("2027-01-01", "%Y-%m-%d")))
        self.assertFalse(any("did not finish well" in p["text"] for p in later["problems"]))     # months old: only in the list
        t = time.mktime(time.strptime("2026-10-25T20:00:00", "%Y-%m-%dT%H:%M:%S"))
        s2 = C.snapshot_from(LOOK, "/path/to/project/lab", now=t)
        self.assertTrue(any("out of memory" in p["text"] for p in s2["problems"]))
        s3 = C.snapshot_from(LOOK, "/path/to/project/lab", ignore={"train-model"}, now=t)
        self.assertFalse(any("did not finish well" in p["text"] and "train-model" in p["text"] for p in s3["problems"]))
        self.assertEqual(s["account"]["limits"]["gpus"], 2); self.assertEqual(s["host"]["processes"], 14)

    def test_gpu_tables_and_where_a_job_fits(self):
        g = C.parse_gpus(GPUS)
        self.assertEqual((g["free"], g["total"]), (16, 21)); self.assertEqual(g["models"][0]["free"], 4)
        self.assertEqual([n["node"] for n in C.fits(g["nodes"], gpus=1, mem_gb=100)], ["g34"])          # g35 has 83G free
        self.assertEqual([n["node"] for n in C.fits(g["nodes"], gpus=2, mem_gb=10)], ["g35"])
        self.assertEqual(C.fits(g["nodes"], gpus=1, model="A100"), [])                                   # draining: nothing starts there

    def test_whoami_and_partitions(self):
        w = C.parse_whoami(WHOAMI)
        self.assertEqual((w["account"], w["fairshare"], w["limits"]["running_jobs"], w["partition"]["idle_cpus"]), ("pi_lab", 0.226323, 100, 3495))
        self.assertEqual(C.parse_sinfo("campus*|up|1-00:00:00|2617/3495/0/6112")[0]["cpus_idle"], 3495)


class TestReadingErrors(unittest.TestCase):
    def test_what_an_output_says(self):
        out = "epoch 1\nTraceback (most recent call last):\n  File x\ntorch.cuda.OutOfMemoryError: CUDA out of memory. Tried to allocate 2 GiB\n"
        kinds = [f["kind"] for f in C.scan_text(out)]
        self.assertEqual(kinds, ["gpu_oom", "error"])
        self.assertIn("out of memory", C.scan_text(out)[0]["line"])
        self.assertEqual(C.scan_text("all fine\nstep 5 done"), [])

    def test_the_cause_comes_from_the_state_then_the_code_then_the_text(self):
        self.assertEqual(C.cause_of("OUT_OF_MEMORY")["kind"], "oom")
        self.assertEqual(C.cause_of("TIMEOUT")["kind"], "time")
        self.assertEqual(C.cause_of("FAILED", "127:0")["kind"], "missing")
        self.assertEqual(C.cause_of("FAILED", "1:0", C.scan_text("ModuleNotFoundError: No module named 'torch'"))["kind"], "module")
        self.assertEqual(C.cause_of("FAILED", "139:0")["kind"], "segv")
        self.assertEqual(C.cause_of("COMPLETED")["kind"], "ok")

    def test_efficiency_says_what_was_wasted_or_nearly_lacking(self):
        text = ("7000|COMPLETED|01:00:00|16|64Gn||00:30:00\n7000.batch|COMPLETED|01:00:00|16||61440K|00:30:00\n")
        e = C.efficiency_of(text)
        self.assertEqual(e["cpu_eff"], 3); self.assertTrue(any("CPUs" in n for n in e["notes"]))
        big = C.efficiency_of("1|COMPLETED|01:00:00|4|8Gn||03:00:00\n1.batch|COMPLETED|01:00:00|4||7700000K|03:00:00")
        self.assertGreaterEqual(big["mem_eff"], 90); self.assertTrue(any("close to the memory" in n for n in big["notes"]))

    def test_processes_the_login_needs_are_not_for_stopping(self):
        p = C.parse_ps("  100 2-03:00:00 Ss   /usr/lib/systemd/systemd --user\n  200 3-01:02:03 S    python train.py\n  300    00:01 Ss   bash -c ps")
        self.assertEqual([(x["pid"], x["system"]) for x in p], [(100, True), (200, False), (300, True)])
        self.assertEqual(p[1]["age"], 3 * 86400 + 3723)


class FakeWorld:
    def __init__(self):
        self.calls, self.look, self.queue, self.ended, self.fail, self.out, self.diag = [], LOOK, SQUEUE, "", False, "", ""
        self.path, self.du_job, self.du_out, self.sbatch, self.probe = "/path/to/project/lab", "", "", "", ""
    def ssh(self, host, cmd, timeout=30):
        self.calls.append(cmd)
        if self.fail: return 255, "ssh failed: timed out"
        if cmd.startswith("@@") or "@@squeue" in cmd or cmd.startswith("echo @@host"): return 0, self.look
        if cmd == C.QUEUE_COMMAND: return 0, self.queue
        if cmd.startswith("sacct -X"): return 0, self.ended
        if cmd.startswith("h2 diagnose"): return 0, self.diag
        if cmd.startswith("for j in"): return 0, self.out
        if cmd.startswith("squeue -u $USER -h -o \"%i\""): return 0, "\n".join(l.split("|")[0] for l in self.queue.splitlines())
        if cmd.startswith("ps -u"): return 0, "  100 2-03:00:00 Ss   /usr/lib/systemd/systemd --user\n  200 3-01:02:03 S    python train.py"
        if cmd.startswith(("scancel", "kill")): return 0, ""
        if cmd.startswith("P=$(readlink"): return 0, self.path
        if cmd.startswith("timeout 25 find"): return 0, self.probe
        if cmd.startswith("P=$(timeout 20 readlink"): return 0, "@@path\n" + self.path + "\n" + self.du_out
        if cmd.startswith("squeue -u $USER -h -n orbit-du-"): return 0, self.du_job
        if cmd.startswith("mkdir -p $HOME/.orbit/du"): self.sbatch = cmd; return 0, "9001"
        if cmd.startswith("O=$HOME/.orbit/du"): return 0, self.du_out
        return 0, ""


class TestTheWatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.w, self.t, self.said = FakeWorld(), [1.7e9], []
        self.c = C.Cluster(os.path.join(self.tmp, "cluster.json"), self.w, now=lambda: self.t[0], notify=lambda a, b: self.said.append((a, b)),
                           own_jobs=lambda: {"qwen-serve"}, explain_with=lambda p: "It ran out of GPU memory; use a smaller batch.")
        self.c.update({"project_dir": "/path/to/project/lab"})

    def test_a_look_is_cached_for_a_few_seconds_and_a_failure_backs_off(self):
        self.c.look(); n = len(self.w.calls); self.c.look(); self.assertEqual(len(self.w.calls), n)
        self.t[0] += 20; self.w.fail = True; r = self.c.look()
        self.assertIn("timed out", r["error"]); self.assertEqual(self.c.next_look, self.t[0] + 120)
        self.assertIsNotNone(r["snapshot"])                                  # the last good picture stays

    def test_started_finished_and_failed_jobs_are_events_and_notices(self):
        self.c.update({"notify": {"started": True}})
        self.c.watch_once()                                                  # first sight: nothing is "new"
        self.w.queue = SQUEUE.replace("PENDING", "RUNNING", 1)
        self.t[0] += 100; self.c.watch_once()
        self.assertEqual([e["kind"] for e in self.c.events], ["started"])
        self.assertEqual(self.said, [])                                      # the model server's job is the other panel's news
        self.w.queue = ""                                                    # both gone: one finished, one failed
        self.w.ended = "7002|train-model|campus|OUT_OF_MEMORY|10:00:00|0:125|s|e|billing=16|g12\n511028|qwen-serve|campus|CANCELLED by 1|00:20:00|0:0|s|e|x|g1"
        self.w.diag = "## Job 7002\nlast lines\ntorch.cuda.OutOfMemoryError: CUDA out of memory"
        self.c.watch_once()
        ev = self.c.events[-1] if self.c.events[-1]["job"] == "7002" else next(e for e in self.c.events if e["job"] == "7002")
        self.assertEqual(ev["kind"], "failed"); self.assertEqual(ev["cause"]["kind"], "oom")
        self.assertIn("smaller batch", ev["cause"]["explained"])
        self.assertEqual(len(self.said), 1); self.assertIn("train-model", self.said[0][0]); self.assertIn("memory", self.said[0][1].lower())

    def test_errors_in_a_running_jobs_output_are_said_once(self):
        self.c.watch_once()
        self.w.out = "@@out 7002\nstep 3\nRuntimeError: CUDA out of memory. Tried to allocate 3 GiB\n"
        self.c.scan_running(); self.c.scan_running()
        self.assertEqual([e["kind"] for e in self.c.events], ["error"]); self.assertEqual(len(self.said), 1)
        self.assertIn("GPU ran out of memory", self.said[0][1] if "GPU" in self.said[0][1] else self.c.events[0]["text"])

    def test_a_disk_crossing_a_line_is_said_once_and_the_day_is_kept(self):
        self.c.look(); self.assertTrue(any(e["kind"] == "disk" for e in self.c.events))
        n = len(self.said); self.t[0] += 20; self.c.look(force=True); self.assertEqual(len(self.said), n)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "cluster-history.json")))

    def test_a_job_that_has_waited_hours_is_said(self):
        self.t[0] = time.mktime(time.strptime("2026-10-27T03:00:00", "%Y-%m-%dT%H:%M:%S"))
        self.w.queue = "8001|align|PENDING|campus||0:00|1-00:00:00|8|32G|gres/gpu:1|Resources|2026-10-26T20:00:00|N/A"
        self.c.watch_once(); self.c.watch_once()
        self.assertEqual([e["kind"] for e in self.c.events], ["pending"]); self.assertIn("7 h", self.c.events[0]["text"])

    def test_only_your_own_jobs_and_real_ids_can_be_cancelled_and_only_your_processes_stopped(self):
        self.c.look()
        with self.assertRaises(ValueError): self.c.cancel("999")
        with self.assertRaises(ValueError): self.c.cancel("7002; rm -rf /")
        self.c.cancel("7002"); self.assertTrue(any(x.startswith("scancel") for x in self.w.calls))
        with self.assertRaises(ValueError): self.c.stop_process(100)          # keeps the login alive
        with self.assertRaises(ValueError): self.c.stop_process(5)            # not yours
        self.c.stop_process(200); self.assertTrue(any(x == "kill 200 2>&1" for x in self.w.calls))

    def test_asking_orbit_about_a_job_carries_the_evidence(self):
        self.c.look(); self.w.diag = "## Job\nOutOfMemoryError"
        t = self.c.ask_text("7002"); self.assertIn("7002", t); self.assertIn("OutOfMemoryError", t)

    def test_where_to_run_respects_the_per_user_gpu_limit(self):
        self.c.look()
        r = self.c.where_to_run(gpus=3, mem_gb=1); self.assertTrue(r["over_limit"]); self.assertEqual(r["gpu_limit"], 2)


HIST = ("1|align|campus|COMPLETED|01:00:00|0:0|2026-10-20T08:00:00|2026-10-20T10:00:00|2026-10-20T11:00:00|billing=8,cpu=8,gres/gpu=1,mem=32G|8\n"
        "2|align|campus|COMPLETED|02:00:00|0:0|2026-10-21T08:00:00|2026-10-21T08:30:00|2026-10-21T10:30:00|billing=8,cpu=8,gres/gpu=2,mem=32G|8\n"
        "3|train|campus|OUT_OF_MEMORY|00:10:00|0:125|2026-10-21T09:00:00|2026-10-21T09:05:00|2026-10-21T09:15:00|billing=4,cpu=4,mem=16G|4\n"
        "4|pending-one|campus|PENDING|00:00:00|0:0|2026-10-22T09:00:00|Unknown|Unknown|billing=1,cpu=1|1")


class TestHistory(unittest.TestCase):
    def test_hours_success_and_the_typical_wait_per_job_name(self):
        h = C.summarize_history(HIST)
        self.assertEqual((h["jobs"], h["ran"], h["completed"], h["failed"]), (4, 3, 2, 1))
        self.assertEqual(h["gpu_hours"], 5.0)                                  # 1 GPU x 1 h + 2 GPUs x 2 h
        a = next(r for r in h["by_name"] if r["name"] == "align")
        self.assertEqual((a["jobs"], a["ok"], a["median_wait"], a["median_run"]), (2, 2, (7200 + 1800) / 2, 5400))
        self.assertEqual([d["day"] for d in h["daily"]], ["2026-10-20", "2026-10-21"])

    def test_gpus_in_the_allocation(self):
        self.assertEqual(C.tres_gpus("billing=8,cpu=8,gres/gpu=2,mem=1G"), 2); self.assertEqual(C.tres_gpus("billing=1,cpu=1"), 0)


class TestMorningNotice(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.said = []
        self.t = [time.mktime(time.strptime("2026-10-27 07:30:00", "%Y-%m-%d %H:%M:%S"))]
        self.c = C.Cluster(os.path.join(self.tmp, "cluster.json"), FakeWorld(), now=lambda: self.t[0], notify=lambda a, b: self.said.append((a, b)))

    def test_one_notice_after_eight_and_only_when_there_is_news(self):
        self.c.events = [{"t": self.t[0] - 3600, "kind": "finished", "text": "align (1) finished after 1 h 0 min", "job": "1"},
                         {"t": self.t[0] - 1800, "kind": "failed", "text": "train (3) out of memory after 10 min", "job": "3"}]
        self.c.maybe_digest(); self.assertEqual(self.said, [])                 # 7:30: too early
        self.t[0] += 3600; self.c.maybe_digest(); self.c.maybe_digest()
        self.assertEqual(len(self.said), 1); self.assertIn("1 job finished", self.said[0][1]); self.assertIn("1 went wrong", self.said[0][1])
        self.t[0] += 86400; self.c.events = []; self.c.maybe_digest(); self.assertEqual(len(self.said), 1)      # quiet night: nothing to say

    def test_it_can_be_switched_off(self):
        self.c.update({"notify": {"digest": False}}); self.c.events = [{"t": self.t[0] - 60, "kind": "finished", "text": "x", "job": "1"}]
        self.t[0] += 7200; self.c.maybe_digest(); self.assertEqual(self.said, [])


class TestWhatUsesTheDisk(unittest.TestCase):
    TSV = "5000000\t/path/to/project/lab/ann\tann\td\n3000000\t/path/to/project/lab/bob\tbob\td\n2500000\t/path/to/project/lab/bob2\tbob\td\n10\t/path/to/project/lab/notes.txt\tcy\tf\n"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.w = FakeWorld()
        self.c = C.Cluster(os.path.join(self.tmp, "cluster.json"), self.w); self.c.update({"project_dir": "/path/to/project/lab"})

    def test_rows_are_ranked_and_people_are_summed_over_their_folders(self):
        rows = C.parse_du(self.TSV)
        self.assertEqual([r["path"].split("/")[-1] for r in rows], ["ann", "bob", "bob2", "notes.txt"])
        people = C.rank_people(rows)
        self.assertEqual([(p["owner"], p["kb"]) for p in people], [("ann", 5000000), ("bob", 5500000), ("cy", 10)][0:0] or [("bob", 5500000), ("ann", 5000000), ("cy", 10)])

    def test_the_job_script_measures_the_folder_in_parallel_and_never_runs_on_the_login_node(self):
        self.c.du_start("lab")
        cmd = self.w.sbatch
        self.assertIn("sbatch --parsable -J orbit-du-", cmd); self.assertIn("-c 4", cmd); self.assertIn("base64 -d", cmd)
        import base64, re
        script = base64.b64decode(re.search(r"printf %s (\S+) \|", cmd)[1]).decode()
        self.assertIn("xargs -0 -P 2", script)       # the lab disk is measured gently; self.assertIn("du -sk -x", script); self.assertIn("/path/to/project/lab", script)
        self.assertNotIn("rm -rf", script)

    def test_a_second_request_while_it_runs_does_not_start_another(self):
        self.w.du_job = "9001"
        r = self.c.du_start("lab"); self.assertTrue(r["already"]); self.assertEqual(self.w.sbatch, "")

    def test_only_places_inside_your_own_areas_can_be_measured(self):
        for bad in ("relative/path", "/path/to/project/lab/../../etc", "/tmp; rm -rf /", "/a b"):
            with self.assertRaises(ValueError): self.c.du_start(bad)
        self.w.path = "not inside your home, scratch or the lab folder"            # what the cluster's own check says about /etc and the like
        with self.assertRaises(ValueError): self.c.du_start("/etc")

    def test_status_shows_partial_results_then_the_final_ranking(self):
        self.w.du_out = "@@state\nstart=1700000000\ndone=\ntotal=40\n@@job\n9001|RUNNING\n@@tsv\n@@tmp\n" + self.TSV
        st = self.c.du_status("lab")
        self.assertTrue(st["running"]); self.assertFalse(st["done"]); self.assertEqual((st["entries"], st["total_entries"]), (4, 40))
        self.assertEqual(st["people"][0]["owner"], "bob")
        self.w.du_out = "@@state\nstart=1700000000\ndone=1700003600\ntotal=4\n@@job\n@@tsv\n" + self.TSV + "@@tmp\n"
        st = self.c.du_status("lab", refresh=True)
        self.assertTrue(st["done"]); self.assertFalse(st["running"]); self.assertEqual(st["measured_at"], 1700003600)
        self.assertIsNone(self.c.du_status("home")["people"])                      # only the lab disk is ranked by person

    def test_the_last_reading_is_shown_without_asking_the_cluster_again(self):
        self.w.du_out = "@@state\nstart=1\ndone=1700003600\ntotal=4\n@@job\n@@tsv\n" + self.TSV + "@@tmp\n"
        first = self.c.du_status("lab"); self.assertFalse(first["cached"]); n = len(self.w.calls)
        again = self.c.du_status("lab"); self.assertTrue(again["cached"]); self.assertEqual(len(self.w.calls), n)       # no ssh at all
        self.assertEqual(again["read_at"], first["read_at"])
        self.assertFalse(self.c.du_status("lab", refresh=True)["cached"]); self.assertGreater(len(self.w.calls), n)
        c2 = C.Cluster(self.c.path, self.w, now=self.c.now)                                                            # and after a restart
        n = len(self.w.calls); self.assertTrue(c2.du_status("lab")["cached"]); self.assertEqual(len(self.w.calls), n)

    def test_reading_a_measurement_is_one_ssh_call(self):
        self.w.du_out = "@@state\nstart=\ndone=\ntotal=\n@@job\n@@tsv\n@@tmp\n"
        n = len(self.w.calls); self.c.du_status("home"); self.assertEqual(len(self.w.calls) - n, 1)
        self.assertIn("sha1sum", self.w.calls[-1])

    def test_a_new_measurement_makes_the_old_reading_stale(self):
        self.w.du_out = "@@state\nstart=\ndone=\ntotal=\n@@job\n@@tsv\n@@tmp\n"
        self.c.du_status("home"); self.c.du_start("home"); self.assertNotIn("home", self.c.du_cache)

    def test_the_files_are_listed_for_my_places_but_not_for_the_whole_lab(self):
        self.assertIn("-printf", C.du_script("k", "/u/home/me")); self.assertNotIn("-printf", C.du_script("k", "/path/to/project/lab", files=False))
        self.w.du_out = ("@@state\nstart=1\ndone=2\ntotal=1\n@@job\n@@tsv\n" + self.TSV + "@@tmp\n@@files\n9437184\t1700000000\t/h/big.bam\n5242880\t1700000001\t/h/r.fastq.gz\n"
                         "@@ext\nbam\t2\t9437184\nfastq.gz\t1\t5242880\n@@sum\n7\t19925102\t2\t3147776\n")
        st = self.c.du_status("home", refresh=True)
        self.assertEqual((st["files"][0]["path"], st["files"][0]["kb"]), ("/h/big.bam", 9216))
        self.assertEqual((st["ext"][0]["ext"], st["ext"][0]["count"]), ("bam", 2))
        self.assertEqual(st["summary"], {"files": 7, "kb": 19458, "old_files": 2, "old_kb": 3074})
        self.assertIsNone(C.parse_sum("garbage")); self.assertEqual(C.parse_files("x"), [])
        self.assertEqual(C.parse_ext("a\t1\t2048\nb\tx\ty")[0]["kb"], 2)

    def test_a_measuring_job_is_not_news(self):
        self.assertTrue(self.c._own("orbit-du-abc123")); self.assertFalse(self.c._own("align"))


class TestSlowThingsAreKept(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.w, self.t = FakeWorld(), [1.7e9]
        self.c = C.Cluster(os.path.join(self.tmp, "cluster.json"), self.w, now=lambda: self.t[0]); self.c.update({"project_dir": "/path/to/project/lab"})

    def test_quotas_and_disks_are_read_once_then_kept_until_asked_for(self):
        self.c.look(); self.assertIn("quota -s", self.w.calls[-1]); t0 = self.c.slow_at
        self.t[0] += 60; r = self.c.look(force=True)
        self.assertNotIn("quota -s", self.w.calls[-1])                       # the queue and GPUs only
        self.assertEqual(r["snapshot"]["slow_at"], t0); self.assertTrue(r["snapshot"]["storage"]); self.assertTrue(r["snapshot"]["shared"])      # the disks are still there
        self.t[0] += 60; r = self.c.look(force=True, slow=True); self.assertIn("quota -s", self.w.calls[-1]); self.assertGreater(r["snapshot"]["slow_at"], t0)

    def test_every_slow_command_has_its_own_time_limit(self):
        cmd = C.look_command("/path/to/project/lab")
        for part in ("quota -s", "df -hPT", "h2 whoami", "h2 gpus", "squeue -u", "sacct -S", "sinfo -h"): self.assertRegex(cmd, r"timeout \d+ " + part)
        self.assertNotIn("quota", C.look_command("/path/to/project/lab", slow=False))

    def test_the_page_can_open_on_the_last_reading_without_a_new_look(self):
        self.c.look(); n = len(self.w.calls)
        c2 = C.Cluster(self.c.path, self.w, now=lambda: self.t[0] + 3600)                                 # Orbit restarted, an hour later
        r = c2.look(cached=True); self.assertEqual(len(self.w.calls), n); self.assertTrue(r["snapshot"]["jobs"]); self.assertEqual(r["at"], self.c.snap_at)


class TestWarningsCanBePutAway(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.w, self.t = FakeWorld(), [1.7e9]
        self.c = C.Cluster(os.path.join(self.tmp, "cluster.json"), self.w, now=lambda: self.t[0]); self.c.update({"project_dir": "/path/to/project/lab"})

    def shown(self, r): return {p["key"] for p in r["snapshot"]["problems"] if not p["dismissed"]}

    def test_a_dismissed_warning_stays_away_until_it_changes(self):
        r = self.c.look(); self.assertIn("disk:lab", self.shown(r))
        r = self.c.dismiss("disk:lab"); self.assertNotIn("disk:lab", self.shown(r)); self.assertEqual(len([p for p in r["snapshot"]["problems"] if p["dismissed"]]), 1)
        self.t[0] += 60; r = self.c.look(force=True, slow=True); self.assertNotIn("disk:lab", self.shown(r))      # same again: still away
        self.assertNotIn("disk:lab", self.shown(C.Cluster(self.c.path, self.w, now=lambda: self.t[0]).public()))     # and after a restart
        self.w.look = LOOK.replace("97%", "99%"); self.t[0] += 60; r = self.c.look(force=True, slow=True)          # worse: back
        self.assertIn("disk:lab", self.shown(r))

    def test_the_other_ways_a_warning_comes_back(self):
        P = {"key": "pending", "level": "info", "ids": ["1", "2"]}
        rec = {"level": "info", "value": None, "ids": ["1", "2"]}
        self.assertTrue(C.dismissed(P, rec)); self.assertFalse(C.dismissed(dict(P, ids=["1", "2", "3"]), rec)); self.assertFalse(C.dismissed(dict(P, level="warn"), rec))
        V = {"key": "disk:lab", "level": "warn", "value": 91}; r2 = {"level": "warn", "value": 90, "ids": []}
        self.assertTrue(C.dismissed(V, r2)); self.assertFalse(C.dismissed(dict(V, value=92), r2)); self.assertFalse(C.dismissed(V, None))

    def test_a_warning_that_went_away_is_forgotten_and_can_be_brought_back(self):
        self.c.look(); self.c.dismiss("disk:lab")
        self.w.look = LOOK.replace("97%", "50%"); self.t[0] += 60; self.c.look(force=True, slow=True)
        self.assertNotIn("disk:lab", self.c.cfg.get("dismissed", {}))
        self.w.look = LOOK; self.t[0] += 60; self.assertIn("disk:lab", self.shown(self.c.look(force=True, slow=True)))      # back full: news again
        self.c.dismiss("disk:lab"); self.c.restore("disk:lab"); self.assertIn("disk:lab", self.shown(self.c.public()))
        with self.assertRaises(ValueError): self.c.dismiss("nope")


class TestReadAgainByItself(unittest.TestCase):
    def at(self, y, mo, d, h, mi=0): return time.mktime((y, mo, d, h, mi, 0, 0, 0, -1))

    def test_daily_at_three(self):
        last = self.at(2026, 10, 26, 3, 0)
        self.assertEqual(C.next_refresh(last, 24, "03:00", last + 60), self.at(2026, 10, 27, 3, 0))
        self.assertEqual(C.next_refresh(last, 48, "03:00", last + 60), self.at(2026, 10, 28, 3, 0))
        self.assertEqual(C.next_refresh(self.at(2026, 10, 26, 14, 20), 24, "03:00", 0), self.at(2026, 10, 27, 3, 0))   # a late catch-up still lands on 3:00
        self.assertEqual(C.next_refresh(last, 6, "03:00", 0), last + 6 * 3600)                                         # shorter: just the hours
        self.assertEqual(C.next_refresh(0, 24, "03:00", self.at(2026, 10, 26, 10)), self.at(2026, 10, 27, 3, 0))      # none yet: the next 3:00
        self.assertEqual(C.next_refresh(0, 24, "03:00", self.at(2026, 10, 26, 1)), self.at(2026, 10, 26, 3, 0))

    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.w, self.t = FakeWorld(), [self.at(2026, 10, 26, 10)]
        self.c = C.Cluster(os.path.join(self.tmp, "cluster.json"), self.w, now=lambda: self.t[0]); self.c.update({"project_dir": "/path/to/project/lab"})

    def test_it_is_on_by_default_daily_at_three_and_the_settings_are_checked(self):
        self.assertEqual(self.c.cfg["refresh"], {"on": True, "every_h": 24, "at": "03:00", "remeasure": True})
        self.c.update({"refresh": {"every_h": "12", "at": "25:99", "remeasure": False}})
        self.assertEqual((self.c.cfg["refresh"]["every_h"], self.c.cfg["refresh"]["at"], self.c.cfg["refresh"]["remeasure"]), (12, "03:00", False))
        self.c.update({"refresh": {"at": "04:30", "every_h": 9999}}); self.assertEqual((self.c.cfg["refresh"]["at"], self.c.cfg["refresh"]["every_h"]), ("04:30", 720))

    def test_nothing_is_read_before_the_time_and_everything_slow_after_it(self):
        self.c.update({"refresh": {"remeasure": False}}); self.c.look(); self.c.history(7); self.w.du_out = "@@state\nstart=\ndone=\ntotal=\n@@job\n@@tsv\n@@tmp\n"; self.c.du_status("home")
        self.c.maybe_refresh(); n = len(self.w.calls); self.t[0] += 3600; self.c.maybe_refresh(); self.assertEqual(len(self.w.calls), n)     # the clock starts; 11:00 is not 3:00
        self.t[0] = self.at(2026, 10, 27, 3, 1); self.c.maybe_refresh()
        cmds = "\n".join(self.w.calls[n:])
        self.assertIn("quota -s", cmds); self.assertIn("sacct -S now-7days", cmds); self.assertIn("sha1sum", cmds); self.assertNotIn("sbatch", cmds)
        n = len(self.w.calls); self.t[0] += 60; self.c.maybe_refresh(); self.assertEqual(len(self.w.calls), n)            # once, not every few seconds
        self.assertEqual(self.c.events[-1]["kind"], "refresh")

    def test_it_can_be_off(self):
        self.c.update({"refresh": {"on": False}}); self.assertIsNone(self.c.refresh_at()); n = len(self.w.calls); self.t[0] += 10 * 86400; self.c.maybe_refresh(); self.assertEqual(len(self.w.calls), n)

    def done_tsv(self, at): return f"@@state\nstart={at - 60}\ndone={at}\ntotal=4\n@@job\n@@tsv\n" + TestWhatUsesTheDisk.TSV + "@@tmp\n"

    def test_a_folder_that_never_changed_is_not_measured_again_and_one_that_did_is(self):
        self.c.look(); self.w.path = "/u/home/demo"
        self.w.du_out = self.done_tsv(int(self.t[0]) - 3600); self.c.du_status("home", refresh=True)
        q = self.c.snap["storage"][0]; self.assertEqual(q["label"], "Home")
        self.c.du_marks["home"] = {"t": 0, "used_kb": q["used_kb"] + 1024, "files": q["files"]}                        # a megabyte of drift: the same
        self.assertEqual(self.c.unchanged("home"), (True, "the quota has not moved"))
        self.c.du_marks["home"] = {"t": 0, "used_kb": q["used_kb"] - 5 * 1024 * 1024, "files": q["files"]}            # five gigabytes since: changed
        self.assertEqual(self.c.unchanged("home"), (False, "the quota moved"))
        self.c.du_marks["home"] = {"t": 0, "used_kb": q["used_kb"], "files": q["files"] - 5000}                        # many new files: changed
        self.assertFalse(self.c.unchanged("home")[0])

    def test_other_places_are_checked_with_one_find_and_old_readings_are_not_trusted(self):
        self.c.look(); self.w.path = "/path/to/project/lab/me"; self.w.du_out = self.done_tsv(int(self.t[0]) - 3600)
        self.c.du_status("mine", refresh=True); n = len(self.w.calls)
        self.w.probe = ""; self.assertTrue(self.c.unchanged("mine")[0]); self.assertEqual(len(self.w.calls) - n, 1); self.assertIn("-newermt", self.w.calls[-1])
        self.w.probe = "/path/to/project/lab/me/new.txt"; self.assertEqual(self.c.unchanged("mine"), (False, "something was modified"))
        self.t[0] += 8 * 86400; self.w.probe = ""; self.assertEqual(self.c.unchanged("mine"), (False, "last measured over a week ago"))
        self.assertFalse(C.Cluster(os.path.join(self.tmp, "x.json"), FakeWorld(), now=lambda: self.t[0]).unchanged("home")[0])      # never measured

    def test_the_night_refresh_measures_what_changed_and_says_what_it_skipped(self):
        self.w.path = "/path/to/project/lab/me"; self.w.du_out = self.done_tsv(int(self.t[0]) - 3600)
        self.c.look(); self.c.du_status("mine", refresh=True); self.c.du_status("home", refresh=True); self.c.du_status("scratch", refresh=True)
        q = {x["label"].lower(): x for x in self.c.snap["storage"]}
        self.c.du_marks["home"] = {"t": 0, "used_kb": q["home"]["used_kb"], "files": q["home"]["files"]}                # unchanged
        self.c.du_marks["scratch"] = {"t": 0, "used_kb": 0, "files": 0}                                                 # changed
        self.w.probe = ""; self.w.sbatch = ""; self.c.refresh_all()
        text = self.c.events[-1]["text"]; self.assertIn("measuring scratch", text); self.assertIn("unchanged, not measured again: home, mine", text)
        self.assertTrue(self.w.sbatch)

    def test_my_biggest_folders_are_measured_too(self):
        self.w.path = "/path/to/project/lab/me"
        self.w.du_out = "@@state\nstart=1\ndone=%d\ntotal=3\n@@job\n@@tsv\n3145728\t/path/to/project/lab/me/big\tme\td\n2097152\t/path/to/project/lab/me/also\tme\td\n10\t/path/to/project/lab/me/tiny\tme\td\n@@tmp\n" % (int(self.t[0]) - 3600)
        self.c.look(); self.c.du_status("mine", refresh=True); self.w.probe = "x"; self.w.calls.clear(); self.c.refresh_all()
        text = self.c.events[-1]["text"]
        self.assertIn("/path/to/project/lab/me/big", text); self.assertIn("/path/to/project/lab/me/also", text); self.assertNotIn("tiny", text)

    def test_the_lab_wide_count_and_other_peoples_folders_are_never_done_by_the_schedule(self):
        self.w.path = "/path/to/project/lab/me"; self.w.du_out = self.done_tsv(int(self.t[0]) - 3600); self.c.look(); self.c.du_status("mine", refresh=True)
        self.w.path = "/path/to/project/lab"; self.w.du_out = self.done_tsv(int(self.t[0]) - 3600); self.c.du_status("lab", refresh=True)
        self.w.path = "/path/to/project/lab/someone"; self.c.du_status("/path/to/project/lab/someone", refresh=True)               # looked into from the lab ranking
        self.w.path = "/path/to/project/lab/me/data"; self.c.du_status("/path/to/project/lab/me/data", refresh=True)               # looked into from my folder
        self.w.probe = "x"; self.w.calls.clear(); self.c.update({"refresh": {"lab": True}}); self.c.refresh_all()
        started = [x for x in self.w.calls if "sbatch" in x]
        self.assertNotIn("lab", self.c.cfg["refresh"])
        self.assertTrue(started)
        import base64, re
        for cmd in started:
            script = base64.b64decode(re.search(r"printf %s (\S+) \|", cmd)[1]).decode()
            self.assertNotIn("someone", script); self.assertTrue("/path/to/project/lab/me" in script or "$HOME" in script or "SCRATCH" in script, script)
            self.assertNotRegex(script, r"find /path/to/project/lab -mindepth")

    def test_the_history_is_kept_with_its_time(self):
        a = self.c.history(7); b = self.c.history(7)
        self.assertFalse(a["cached"]); self.assertTrue(b["cached"]); self.assertIn("read_at", b); self.assertIn("7", self.c.public()["history"])


class TestSimulated(unittest.TestCase):
    def test_the_sandbox_cluster_gives_a_complete_picture_and_runs_nothing(self):
        tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, tmp, True)
        c = C.Cluster(os.path.join(tmp, "cluster.json"), C.SimCluster()); c.update({"project_dir": "/path/to/project/lab"})
        s = c.look()["snapshot"]
        self.assertEqual(len(s["jobs"]), 2); self.assertGreater(s["gpus"]["total"], 0); self.assertEqual(s["shared"][0]["pct"], 97)
        c.cancel("7001"); self.assertEqual(len(c.look(force=True)["snapshot"]["jobs"]), 1)


if __name__ == "__main__":
    unittest.main()
