"""Model servers on a cluster: what the panel shows, what starts and stops them, the schedule, and the notices."""
import json, os, sys, tempfile, time, unittest
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin"))
import modelserver as MS                      # noqa: E402


class FakeWorld:
    """A cluster in a dictionary: the one job, the files it wrote, and a record of everything done to it."""
    def __init__(self):
        self.job = None                # {"id","state","elapsed","limit","node"}
        self.run_file = ""             # what the job wrote to run/<id>
        self.model_up = False
        self.max_len = 262144
        self.sacct = "COMPLETED|00:10:00|0:0"
        self.calls, self.secret, self.tunnel, self.desktop_log, self.mails = [], {}, False, [], []
        self.mail_fails = False
        self.test_only = ""            # what the scheduler says to `sbatch --test-only` (sections @@0.. then @@gpus)
        self.unreachable = False
        self.features = ""             # what `sinfo -o %f` says (GPU nodes' features, e.g. "amd-7542,gpu,A100,vmem40G,cuda_cc_8_0")
        self.cause, self.badnodes = "", ""
        self.metrics = "vllm:num_requests_running 0\nvllm:request_success_total{model_name=\"qwen\"} 7\n"

    def ssh(self, host, cmd, timeout=30):
        self.calls.append(cmd)
        if self.unreachable: return 255, "ssh failed: timed out"
        if cmd.startswith("squeue"):
            j = self.job
            return 0, "" if not j else f"{j['id']}|{j['state']}|{j['elapsed']}|{j['limit']}|{j.get('node','')}|None|2026-10-26T10:00:00"
        if "--test-only" in cmd: return 0, self.test_only
        if cmd.startswith("sinfo"): return 0, self.features
        if cmd.startswith("grep"): return 0, self.cause
        if cmd.startswith("cat ") and "/run/badnodes" in cmd: return 0, self.badnodes
        if cmd.startswith("sbatch"):
            self.job = {"id": "900", "state": "PENDING", "elapsed": "0:00", "limit": "1-00:00:00", "node": ""}
            return 0, "900"
        if cmd.startswith("scancel"):
            if self.job: self.job["state"] = "COMPLETING"
            return 0, ""
        if cmd.startswith("cat "): return 0, self.run_file
        if cmd.startswith("sacct"): return 0, self.sacct
        return 0, ""

    PS = ""
    def ps(self): return self.PS
    def kill(self, pid): self.killed = getattr(self, "killed", []) + [int(pid)]
    def monitor_exit(self, host): self.calls.append("monitor-exit " + host)
    def tunnel_pids(self, port): return ["1"] if self.tunnel else []
    def tunnel_open(self, host, lp, node, port): self.tunnel = True
    def tunnel_close(self, port): self.tunnel = False
    def http(self, port, path, key=""):
        if not self.model_up: raise OSError("refused")
        if path == "/v1/models": return json.dumps({"data": [{"id": "qwen", "max_model_len": self.max_len}]})
        return self.metrics
    complete_fails = False
    def complete(self, port, key, content, max_tokens):
        if self.complete_fails: raise OSError("hung")
        long = len(content) > 1000
        seen = self.__dict__.setdefault("seen", set()); cached = content in seen; seen.add(content)      # the second time it is in the cache
        return (0.4 if long and cached else 3.0 if long else 4.15, 25000 if long else 26, 4 if long else 200)
    def set_secret(self, name, value): self.secret[name] = value
    def desktop(self, title, text): self.desktop_log.append((title, text))
    def email(self, host, to, subject, body):
        if self.mail_fails: raise RuntimeError("the cluster did not send it")
        self.mails.append((to, subject, body, host))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.w = FakeWorld(); self.t = [datetime(2026, 10, 26, 9, 0).timestamp()]     # a Monday
        self.m = MS.Manager(os.path.join(self.tmp, "ms.json"), self.w, now=lambda: self.t[0])
        self.m.update("qwen", {"notify": {"email": "me@example.com"}})

    def state(self): return self.m.status("qwen")["state"]


class TestStatusFromTheCluster(Base):
    def test_nothing_running_is_stopped(self):
        self.assertEqual(self.m.tick("qwen")["state"], "stopped")

    def test_queued_then_loading_then_ready_and_the_key_never_leaves(self):
        self.m.start("qwen")
        self.assertEqual(self.state(), "queued")
        self.w.job.update(state="RUNNING", elapsed="1:00", node="g35")
        self.assertEqual(self.m.tick("qwen")["state"], "loading")               # started, not listening yet
        self.w.run_file = "g35 27600 sekret"
        self.assertEqual(self.m.tick("qwen")["state"], "loading")               # tunnel up, model not answering
        self.assertTrue(self.w.tunnel)
        self.w.model_up = True
        st = self.m.tick("qwen")
        self.assertEqual(st["state"], "ready")
        self.assertEqual(st["info"]["max_model_len"], 262144)
        self.assertEqual(self.w.secret["HPC_LLM_KEY"], "sekret")
        self.assertNotIn("sekret", json.dumps(self.m.public()))

    def test_a_job_started_elsewhere_is_picked_up(self):
        self.w.job = {"id": "55", "state": "RUNNING", "elapsed": "5:00", "limit": "1-00:00:00", "node": "g1"}
        self.w.run_file = "g1 27000 k"; self.w.model_up = True
        self.assertEqual(self.m.tick("qwen")["state"], "ready")

    def test_time_left_counts_down(self):
        self.m.start("qwen"); self.w.job.update(state="RUNNING", elapsed="1:00:00", limit="2:00:00")
        self.m.tick("qwen"); self.t[0] += 600
        self.assertEqual(self.m.status("qwen")["left"], 3000)

    def test_an_unreachable_cluster_is_said_not_guessed(self):
        self.m.start("qwen"); self.w.unreachable = True
        st = self.m.tick("qwen")
        self.assertEqual(st["state"], "queued"); self.assertIn("timed out", st["error"])


class TestStartAndStop(Base):
    def test_start_sends_the_chosen_settings(self):
        self.m.start("qwen", overrides={"max_model_len": 65536, "max_num_seqs": 8, "mtp_tokens": 0, "eager": True, "time_limit_h": 6})
        cmd = next(c for c in self.w.calls if c.startswith("sbatch"))
        for want in ("MAXLEN=65536", "SEQS=8", "MTP=0", "EAGER=1", "-t 6:00:00", "--gres=gpu:1", "BATCHED=16384", "GPUS=1",
                     "TEMP=0.6", "TOPP=0.95", "TOPK=20"):
            self.assertIn(want, cmd)

    def test_the_optional_settings_reach_the_job_only_when_chosen(self):
        self.m.start("qwen"); plain = next(c for c in self.w.calls if c.startswith("sbatch"))
        for absent in ("KVDTYPE", "ASYNC", "KEEPLOG"): self.assertNotIn(absent, plain)
        self.w.job = None; self.w.calls.clear(); self.m.rt.clear()
        self.m.start("qwen", overrides={"kv_cache_dtype": "fp8", "async_scheduling": True, "batched_tokens": 32768, "gpus": 2})
        cmd = next(c for c in self.w.calls if c.startswith("sbatch"))
        for want in ("KVDTYPE=fp8", "ASYNC=1", "BATCHED=32768", "GPUS=2", "--gres=gpu:2"): self.assertIn(want, cmd)

    def test_bad_values_for_the_new_settings_are_ignored(self):
        s = MS.clean_settings({"kv_cache_dtype": "int3", "temperature": 9, "top_p": 0, "batched_tokens": 5})
        self.assertEqual((s["kv_cache_dtype"], s["temperature"], s["top_p"], s["batched_tokens"]), ("auto", 2.0, 0.05, 2048))

    def test_start_twice_is_refused(self):
        self.m.start("qwen")
        with self.assertRaises(RuntimeError): self.m.start("qwen")

    def test_settings_are_bounded(self):
        s = MS.clean_settings({"max_num_seqs": 99999, "gpu_mem_util": "x", "max_model_len": "4096", "bogus": 1})
        self.assertEqual((s["max_num_seqs"], s["gpu_mem_util"], s["max_model_len"]), (1024, 0.90, 4096))
        self.assertNotIn("bogus", s)

    def test_stop_cancels_and_ends_stopped_with_a_notice(self):
        self.m.start("qwen"); self.w.job.update(state="RUNNING", node="g1"); self.w.run_file = "g1 1 k"; self.w.model_up = True
        self.m.tick("qwen"); self.w.mails.clear()
        self.m.stop("qwen")
        self.assertEqual(self.state(), "stopping")
        self.w.job = None; self.w.sacct = "CANCELLED by 1|00:20:00|0:0"
        self.assertEqual(self.m.tick("qwen")["state"], "stopped")
        self.assertFalse(self.w.tunnel); self.assertEqual(self.w.secret["HPC_LLM_KEY"], "")
        self.assertIn("stopped", self.w.desktop_log[-1][0])


class TestNotices(Base):
    """E-mail is sent by the job itself, on the cluster; this Mac only says it on the desktop."""
    def up(self):
        self.m.start("qwen"); self.w.job.update(state="RUNNING", node="g35", elapsed="9:00")
        self.w.run_file = "g35 27600 k"; self.w.model_up = True
        self.t[0] += 540; self.m.tick("qwen")

    def sbatch(self): return next(c for c in self.w.calls if c.startswith("sbatch"))

    def test_the_job_is_given_the_address_the_events_and_the_name_to_mail_with(self):
        self.m.start("qwen"); cmd = self.sbatch()
        for want in ("NOTIFY_TO=me@example.com", "NOTIFY_EVENTS=ready:stopped:failed", "MODEL_LABEL=Qwen_HPC", "TLIMIT_H=24"):
            self.assertIn(want, cmd)
        export = cmd.split("--export=")[1].split(" ")[0]          # one argument: every part is NAME=value, no spaces in values
        self.assertTrue(all("=" in part for part in export.split(",")[1:]), export)

    def test_this_mac_sends_no_mail_by_itself(self):
        self.up(); self.m.tick("qwen")
        self.assertEqual(self.w.mails, [])
        self.assertEqual(len(self.w.desktop_log), 1); self.assertIn("is ready", self.w.desktop_log[0][0])

    def test_no_address_or_a_bad_one_means_the_job_is_not_asked_to_mail(self):
        for bad in ("", "not an address", "a@b.c,d@e.f; rm -rf /"):
            self.m.update("qwen", {"notify": {"email": bad}}); self.w.calls.clear(); self.w.job = None; self.m.rt.clear()
            self.m.start("qwen"); self.assertNotIn("NOTIFY_TO", self.sbatch())

    def test_an_event_can_be_switched_off(self):
        self.m.update("qwen", {"notify": {"events": {"ready": False, "stopped": True, "failed": True}}})
        self.m.start("qwen"); self.assertIn("NOTIFY_EVENTS=stopped:failed", self.sbatch())
        self.w.job.update(state="RUNNING", node="g1"); self.w.run_file = "g1 1 k"; self.w.model_up = True; self.m.tick("qwen")
        self.assertEqual(self.w.desktop_log, [])

    def test_the_job_dying_is_a_failure_and_its_time_running_out_is_a_stop_on_the_desktop(self):
        self.up(); self.w.job = None; self.w.sacct = "FAILED|00:02:00|1:0"
        self.m.tick("qwen"); self.assertIn("failed", self.w.desktop_log[-1][0])
        self.m.start("qwen"); self.w.job.update(state="RUNNING", node="g1"); self.w.run_file = "g1 1 k"
        self.m.tick("qwen"); self.w.job = None; self.w.sacct = "TIMEOUT|1-00:00:00|0:0"
        self.m.tick("qwen"); self.assertIn("time limit", self.w.desktop_log[-1][1])

    def test_test_email_is_sent_from_the_cluster_to_the_address(self):
        self.assertEqual(self.m.test_email("qwen"), "me@example.com")
        to, subject, body, host = self.w.mails[-1]
        self.assertEqual((to, host), ("me@example.com", "hpc")); self.assertIn("test", subject)

    def test_a_failed_test_says_why(self):
        self.w.mail_fails = True
        with self.assertRaises(RuntimeError): self.m.test_email("qwen")

    def test_the_address_the_cluster_delivers_to_is_the_default(self):
        fresh = MS.Manager(os.path.join(self.tmp, "fresh.json"), self.w)
        self.assertEqual(fresh.server("qwen")["notify"]["email"], "user@mail.cluster.example.edu")


class TestPrivacyAndLogs(Base):
    def test_private_by_default_and_a_log_only_when_asked(self):
        self.m.start("qwen"); self.assertNotIn("KEEPLOG", next(c for c in self.w.calls if c.startswith("sbatch")))
        self.w.job = None; self.w.calls.clear(); self.m.rt.clear()
        self.m.start("qwen", overrides={"keep_log": True}); self.assertIn("KEEPLOG=1", next(c for c in self.w.calls if c.startswith("sbatch")))


class TestStatistics(Base):
    TEXT1 = ("vllm:num_requests_running 1\nvllm:num_requests_waiting 0\nvllm:kv_cache_usage_perc 0.12\n"
             "vllm:request_success_total{finished_reason=\"stop\"} 4\nvllm:generation_tokens_total 1000\nvllm:prompt_tokens_total 90000\n"
             "vllm:inter_token_latency_seconds_sum 20\nvllm:inter_token_latency_seconds_count 1000\n"
             "vllm:time_to_first_token_seconds_sum 12\nvllm:time_to_first_token_seconds_count 4\n"
             "vllm:prefix_cache_queries_total 1000\nvllm:prefix_cache_hits_total 800\n"
             "vllm:spec_decode_num_draft_tokens_total 200\nvllm:spec_decode_num_accepted_tokens_total 150\n")

    def ready(self):
        self.m.start("qwen"); self.w.job.update(state="RUNNING", node="g1"); self.w.run_file = "g1 1 k"; self.w.model_up = True
        self.w.metrics = self.TEXT1; self.m.tick("qwen")

    def test_speed_and_the_rest_come_from_the_models_own_statistics(self):
        self.ready(); st = self.m.status("qwen")["stats"]
        self.assertEqual(st["decode_tps"], 50.0)             # 20 ms between tokens
        self.assertEqual(st["ttft_s"], 3.0)
        self.assertEqual((st["cache_hit"], st["accepted"], st["kv_used"]), (0.8, 0.75, 0.12))
        self.assertEqual((st["finished"], st["generated_tokens"], st["prompt_tokens"]), (4, 1000, 90000))

    def test_recent_speed_is_measured_between_two_readings(self):
        self.ready()
        self.t[0] += 60
        self.w.metrics = self.TEXT1.replace("inter_token_latency_seconds_sum 20", "inter_token_latency_seconds_sum 30") \
            .replace("inter_token_latency_seconds_count 1000", "inter_token_latency_seconds_count 1500") \
            .replace("generation_tokens_total 1000", "generation_tokens_total 1600")
        self.m.read_metrics(self.m.server("qwen"), self.m.rt["qwen"])
        st = self.m.status("qwen")["stats"]
        self.assertEqual(st["decode_tps"], 50.0)             # (30-20)s over 500 tokens: 20 ms again
        self.assertEqual(st["throughput_tps"], 10.0)         # 600 tokens in 60 s

    def test_a_server_with_statistics_switched_off_says_so(self):
        self.ready(); self.w.metrics = "vllm:tool_call_parser_invocations_total 0\n"
        self.m.read_metrics(self.m.server("qwen"), self.m.rt["qwen"])
        self.assertEqual(self.m.status("qwen")["stats"], {"off": True})


class TestSchedule(Base):
    def at(self, h, mi, day=26):
        self.t[0] = datetime(2026, 10, day, h, mi).timestamp()

    def sched(self, **row):
        self.m.update("qwen", {"schedule": [{"start": "08:00", "stop": "22:00", **row}]})

    def test_it_starts_at_the_time_once(self):
        self.sched(); self.at(7, 59); self.m.run_schedule()
        self.assertEqual(self.state(), "unknown" if "qwen" not in self.m.rt else self.state())
        self.assertFalse(any(c.startswith("sbatch") for c in self.w.calls))
        self.at(8, 1); self.m.run_schedule()
        self.assertEqual(sum(c.startswith("sbatch") for c in self.w.calls), 1)
        self.w.job = None; self.m.tick("qwen"); self.at(8, 5); self.m.run_schedule()
        self.assertEqual(sum(c.startswith("sbatch") for c in self.w.calls), 1, "started again the same day")

    def test_it_stops_at_the_time(self):
        self.sched(); self.at(8, 1); self.m.run_schedule(); self.w.job.update(state="RUNNING")
        self.m.tick("qwen"); self.at(22, 2); self.m.run_schedule()
        self.assertTrue(any(c.startswith("scancel") for c in self.w.calls))

    def test_only_on_the_chosen_days(self):
        self.sched(days=[1]); self.at(8, 1); self.m.run_schedule()          # Monday, wanted Tuesday
        self.assertFalse(any(c.startswith("sbatch") for c in self.w.calls))
        self.at(8, 1, day=27); self.m.run_schedule()
        self.assertTrue(any(c.startswith("sbatch") for c in self.w.calls))

    def test_a_missed_start_is_late_but_not_after_the_stop(self):
        self.sched(); self.at(8, 20); self.m.run_schedule()
        self.assertTrue(any(c.startswith("sbatch") for c in self.w.calls))
        self.w.calls.clear(); self.w.job = None; self.m.rt.clear()
        self.sched(start="08:00", stop="08:10"); self.at(8, 20); self.m.run_schedule()
        self.assertFalse(any(c.startswith("sbatch") for c in self.w.calls))

    def test_a_manual_stop_inside_the_window_is_not_undone(self):
        self.sched(); self.at(8, 1); self.m.run_schedule(); self.m.stop("qwen"); self.w.job = None; self.m.tick("qwen")
        self.at(9, 0); self.m.run_schedule()
        self.assertEqual(sum(c.startswith("sbatch") for c in self.w.calls), 1)

    def test_a_disabled_row_does_nothing_and_a_one_day_row_is_once(self):
        self.sched(enabled=False); self.at(8, 1); self.m.run_schedule()
        self.assertFalse(any(c.startswith("sbatch") for c in self.w.calls))
        self.sched(on="2026-10-27"); self.at(8, 1); self.m.run_schedule()
        self.assertFalse(any(c.startswith("sbatch") for c in self.w.calls))

    def test_next_event(self):
        self.sched(); self.at(9, 0)
        n = self.m.status("qwen")["next"]
        self.assertEqual((n["kind"], datetime.fromtimestamp(n["at"]).strftime("%H:%M")), ("stop", "22:00"))
        self.at(23, 0); n = self.m.status("qwen")["next"]
        self.assertEqual((n["kind"], datetime.fromtimestamp(n["at"]).strftime("%d %H:%M")), ("start", "27 08:00"))

    def test_bad_rows_are_dropped(self):
        self.m.update("qwen", {"schedule": [{"start": "25:99"}, {"start": "7:30", "days": [0, 9]}]})
        rows = self.m.server("qwen")["schedule"]
        self.assertEqual([(r["start"], r["days"]) for r in rows], [("07:30", [0])])


class TestNotHammeringTheCluster(Base):
    """Every look is an ssh login; the login nodes block a client that makes too many."""
    def test_polling_slows_when_nothing_changes_and_backs_off_when_unreachable(self):
        self.m.tick("qwen")
        self.assertEqual(self.m.rt["qwen"]["next_poll"] - self.t[0], MS.POLL_S["stopped"])
        self.m.start("qwen")
        self.assertEqual(self.m.rt["qwen"]["next_poll"] - self.t[0], MS.POLL_S["queued"])
        self.w.unreachable = True; gaps = []
        for _ in range(6): self.m.tick("qwen"); gaps.append(self.m.rt["qwen"]["next_poll"] - self.t[0])
        self.assertEqual(gaps, [120, 300, 600, 900, 900, 900])

    def test_the_loop_does_not_look_before_it_is_time_and_asking_twice_is_one_look(self):
        import threading
        self.m.tick("qwen"); n = sum(c.startswith("squeue") for c in self.w.calls)
        stop = threading.Event(); orig = MS.time.sleep
        MS.time.sleep = lambda s: stop.set()
        try: self.m.loop(stop)
        finally: MS.time.sleep = orig
        self.assertEqual(sum(c.startswith("squeue") for c in self.w.calls), n)
        self.m.refresh("qwen"); self.assertEqual(sum(c.startswith("squeue") for c in self.w.calls), n)    # looked a moment ago
        self.t[0] += 11; self.m.refresh("qwen"); self.assertEqual(sum(c.startswith("squeue") for c in self.w.calls), n + 1)


PS = """\
21907       07:51 /usr/bin/ssh -o Hostname=login.cluster.example.edu -l user -N -T -o ControlMaster=yes -p 22 -i /Users/x/.ssh/hpc login.cluster.example.edu
22111       07:20 /usr/bin/ssh -s -F /dev/null -T -o ControlMaster=no -S /var/folders/ctl -o BatchMode=yes somewhere-else
23019       06:19 ssh -f -tt -o ExitOnForwardFailure=yes -L 8012:127.0.0.1:30049 hpc exec ssh -N -L 30049:127.0.0.1:30049 g35
24100       02:00 ssh: /Users/x/.ssh/cm-orbit-460eb8681e6126e32068cd12652a597c45e34962 [mux]
25000       10:00 ssh -T -o ExitOnForwardFailure=yes hpc exec bash -c IFS= read orbit --print
26041       00:12 /usr/bin/ssh -v -o BatchMode=yes hpcalt sh -c 'echo codex'
27000       00:01 vim ssh_notes.txt
"""


class TestTheLoginsToTheCluster(Base):
    def test_orbits_logins_are_told_from_other_programs(self):
        self.w.PS = PS
        kinds = {c["pid"]: (c["kind"], c["mine"]) for c in self.m.connections()}
        self.assertEqual(kinds, {21907: ("other", False), 23019: ("tunnel", True), 24100: ("monitor", True),
                                 25000: ("chat", True), 26041: ("other", False)})     # 22111 is another host

    def test_closing_ends_orbits_own_but_not_the_chats_or_other_programs(self):
        self.w.PS = PS; self.m.rt["qwen"] = {"state": "ready", "key_set": ("1", "k"), "next_poll": 9e12, "fails": 3}
        n = self.m.close_connections("qwen")
        self.assertEqual(sorted(self.w.killed), [23019, 24100]); self.assertEqual(n, 2)
        self.assertIn("monitor-exit hpc", self.w.calls)
        self.assertEqual((self.m.rt["qwen"]["next_poll"], self.m.rt["qwen"]["fails"]), (0, 0))      # look again at once, from scratch

    def test_chats_only_when_asked(self):
        self.w.PS = PS; self.m.close_connections("qwen", chats=True)
        self.assertIn(25000, self.w.killed); self.assertNotIn(21907, self.w.killed)


class TestHealthAndKeepAlive(Base):
    def ready(self):
        self.m.start("qwen"); self.w.job.update(state="RUNNING", node="g1"); self.w.run_file = "g1 1 k"; self.w.model_up = True
        self.m.tick("qwen")

    def test_a_real_request_is_timed_and_three_misses_are_reported(self):
        self.ready(); rt = self.m.rt["qwen"]; s = self.m.server("qwen")
        self.m.health(s, rt); self.assertTrue(self.m.status("qwen")["health"]["ok"])
        self.w.complete_fails = True
        for _ in range(3): self.t[0] += 181; self.m.health(s, rt)
        self.assertFalse(self.m.status("qwen")["health"]["ok"]); self.assertIn("stopped answering", self.w.desktop_log[-1][1])

    def test_keep_alive_starts_it_again_after_a_crash_but_not_after_you_stopped_it_and_not_forever(self):
        self.m.update("qwen", {"settings": {"keep_alive": True}}); s = self.m.server("qwen")
        for attempt in (1, 2, 3):
            self.ready(); self.w.job = None; self.w.sacct = "FAILED|00:02:00|1:0"
            self.m.tick("qwen"); self.m.keep_alive(s, self.m.rt["qwen"])
            self.assertEqual(self.m.rt["qwen"]["state"], "queued" if attempt <= 2 else "stopped", attempt)
            if attempt <= 2: self.w.job = None; self.m.rt["qwen"]["state"] = "stopped"
        self.t[0] += 86400; self.m.rt["qwen"]["state"] = "stopped"; self.m.rt["qwen"]["last_end"] = "failed"
        self.m.keep_alive(s, self.m.rt["qwen"]); self.assertEqual(self.m.rt["qwen"]["state"], "queued")      # a new day

    def test_a_stop_by_hand_is_not_a_failure(self):
        self.m.update("qwen", {"settings": {"keep_alive": True}}); self.ready(); self.m.stop("qwen")
        self.w.job = None; self.w.sacct = "CANCELLED by 1|00:20:00|0:0"; self.m.tick("qwen")
        self.m.keep_alive(self.m.server("qwen"), self.m.rt["qwen"]); self.assertEqual(self.m.rt["qwen"]["state"], "stopped")

    def test_the_speed_test_gives_the_numbers_to_compare_settings_by(self):
        self.ready(); b = self.m.speed_test("qwen")
        self.assertEqual(b["prompt_tokens"], 25000); self.assertGreater(b["cold_s"], b["warm_s"])
        self.assertAlmostEqual(b["decode_tps"], 50.0, delta=1)
        self.assertEqual(self.m.status("qwen")["bench"]["at"], b["at"])
        self.m.rt["qwen"]["state"] = "stopped"
        with self.assertRaises(RuntimeError): self.m.speed_test("qwen")


def estimate(*rows):
    """The scheduler's answers for the four choices (campus 128G, campus 64G, pi_shared 128G, pi_shared 64G): rows of (minutes from 09:00, node, partition) or None."""
    out = []
    for i, r in enumerate(rows):
        out.append(f"@@{i}\n" + ("sbatch: error: not possible" if r is None else
                   f"sbatch: Job {900 + i} to start at {(datetime(2026, 10, 26, 9, 0) + timedelta(minutes=r[0])).strftime('%Y-%m-%dT%H:%M:%S')} using 16 processors on nodes {r[1]} in partition {r[2]}"))
    return "\n".join(out) + "\n@@gpus\n| g34 | RTX | 1/8 |\n"


class TestChoosingWhereToRun(Base):
    def sb(self): return [c for c in self.w.calls if c.startswith("sbatch") and "--test-only" not in c][-1]

    def test_the_soonest_start_wins_and_the_job_is_submitted_there(self):
        self.w.test_only = estimate((27 * 60, "g35", "campus"), (10 * 60, "g35", "campus"), (60, "g34", "pi_shared"), (60, "g34", "pi_shared"))
        self.m.start("qwen"); cmd = self.sb()
        self.assertIn("-p pi_shared", cmd); self.assertIn("--mem=128G", cmd)                       # a tie in time: the more generous memory
        pl = self.m.status("qwen")["placement"]; self.assertEqual(pl["chosen"]["partition"], "pi_shared"); self.assertEqual(len(pl["options"]), 4); self.assertEqual(pl["how"], "auto")

    def test_less_memory_is_used_when_that_starts_it_sooner(self):
        self.w.test_only = estimate((600, "g35", "campus"), (10, "g35", "campus"), (600, "g34", "pi_shared"), (600, "g34", "pi_shared"))
        self.m.start("qwen"); self.assertIn("--mem=48G", self.sb()); self.assertNotIn(" -p ", self.sb())          # the router's own partition, with the least memory

    def test_within_five_minutes_the_default_partition_is_preferred(self):
        self.w.test_only = estimate((60, "g35", "campus"), (62, "g35", "campus"), (58, "g34", "pi_shared"), (58, "g34", "pi_shared"))
        self.m.start("qwen"); self.assertNotIn(" -p ", self.sb()); self.assertIn("--mem=128G", self.sb())

    def test_when_the_scheduler_cannot_say_the_settings_are_used(self):
        self.w.test_only = ""; self.m.start("qwen"); self.assertNotIn(" -p ", self.sb()); self.assertIn("--mem=128G", self.sb()); self.assertIsNone(self.m.status("qwen")["placement"])

    def test_fixed_placement_and_an_explicit_partition_are_not_second_guessed(self):
        self.w.test_only = estimate((600, "g35", "campus"), (600, "g35", "campus"), (1, "g34", "pi_shared"), (1, "g34", "pi_shared"))
        self.m.start("qwen", overrides={"placement": "fixed"}); self.assertNotIn(" -p ", self.sb()); self.assertFalse(any("--test-only" in c for c in self.w.calls))
        self.w.job = None; self.m.rt.clear(); self.m.start("qwen", overrides={"partition": "campus"}); self.assertIn(" -p campus", self.sb())

    def test_a_model_can_choose_and_a_bad_answer_falls_back(self):
        self.w.test_only = estimate((600, "g35", "campus"), (600, "g35", "campus"), (60, "g34", "pi_shared"), (60, "g34", "pi_shared"))
        asked = []
        def advise(prompt, model): asked.append((prompt, model)); return 'Sure. {"choice": 0, "why": "stay on campus, it is steadier"}'
        self.m.advise = advise
        self.m.start("qwen", overrides={"placement": "ask", "placement_model": "claude/sonnet"})
        self.assertNotIn(" -p ", self.sb()); self.assertEqual(self.m.status("qwen")["placement"]["how"], "model"); self.assertIn("steadier", self.m.status("qwen")["placement"]["why"])
        self.assertEqual(asked[0][1], "claude/sonnet"); self.assertIn("campus", asked[0][0]); self.assertIn("pi_shared", asked[0][0])
        self.w.job = None; self.m.rt.clear(); self.m.advise = lambda p, m: "no idea"
        self.m.start("qwen", overrides={"placement": "ask"}); self.assertIn("-p pi_shared", self.sb()); self.assertIn("could not be used", self.m.status("qwen")["placement"]["how"])
        self.w.job = None; self.m.rt.clear(); self.m.advise = lambda p, m: '{"choice": 9}'
        self.m.start("qwen", overrides={"placement": "ask"}); self.assertIn("-p pi_shared", self.sb())                # a choice that is not an option is ignored

    def test_nodes_known_to_be_bad_are_left_out_of_the_estimates(self):
        self.w.test_only = estimate(None, None, None, None); self.m.rt["qwen"] = {"state": "unknown", "bad_nodes": {"g33": self.t[0] + 3600}}
        self.m.start("qwen"); plan_cmd = next(c for c in self.w.calls if "--test-only" in c); self.assertIn("--exclude=g33", plan_cmd)


class TestWaitingForTheModel(Base):
    def test_a_loading_server_is_reported_for_its_provider_only(self):
        self.assertIsNone(self.m.loading_for("hpc"))                                   # nothing running
        self.m.start("qwen"); info = self.m.loading_for("hpc")
        self.assertEqual((info["state"], info["label"]), ("queued", "Qwen · HPC")); self.assertIsNone(self.m.loading_for("claude"))
        self.w.job = {"id": "900", "state": "RUNNING", "elapsed": "1:00", "limit": "1-00:00:00", "node": "g34"}; self.w.run_file = ""; self.m.tick("qwen")
        self.assertEqual(self.m.loading_for("hpc")["state"], "loading")
        self.w.run_file = "g34 30000 key"; self.w.model_up = True; self.m.tick("qwen"); self.assertIsNone(self.m.loading_for("hpc"))        # ready: nothing to wait for

    def test_a_chat_waits_while_it_loads_says_so_and_goes_on_when_ready(self):
        import threading
        states = [{"state": "queued", "label": "Qwen", "node": None}, {"state": "loading", "label": "Qwen", "node": "g34"}, {"state": "loading", "label": "Qwen", "node": "g34"}, None]
        said, waits = [], []
        def loading(): return states.pop(0) if len(states) > 1 else states[0]
        ok = MS.wait_until_ready(loading, threading.Event(), lambda k, p: said.append((k, p.get("msg") or p)), wait=waits.append)
        self.assertTrue(ok); self.assertEqual(waits, [5, 5, 5])
        self.assertEqual([k for k, _ in said], ["queued", "queued", "dequeued"])                  # once per change of state, not per poll
        self.assertIn("g34", said[1][1])

    def test_nothing_is_said_or_waited_when_it_is_not_loading(self):
        import threading
        said = []; self.assertTrue(MS.wait_until_ready(lambda: None, threading.Event(), lambda k, p: said.append(k), wait=lambda s: 1 / 0)); self.assertEqual(said, [])

    def test_cancelling_stops_the_wait_and_a_very_long_wait_gives_up(self):
        import threading
        ev = threading.Event(); n = [0]
        def wait(s): n[0] += 1; ev.set() if n[0] == 2 else None
        self.assertFalse(MS.wait_until_ready(lambda: {"state": "loading", "label": "Q"}, ev, None, wait=wait))
        t = [0]; self.assertTrue(MS.wait_until_ready(lambda: {"state": "loading", "label": "Q"}, threading.Event(), None, now=lambda: t[0], wait=lambda s: t.__setitem__(0, t[0] + 3000), max_s=7200))


class TestServerMessages(Base):
    def test_the_error_log_is_on_by_default_and_can_be_switched_off(self):
        self.m.start("qwen"); self.assertNotIn("ERRLOG", next(c for c in self.w.calls if c.startswith("sbatch")))
        self.w.job = None; self.w.calls.clear(); self.m.rt.clear(); self.m.start("qwen", overrides={"error_log": False})
        self.assertIn("ERRLOG=0", next(c for c in self.w.calls if c.startswith("sbatch")))

    def test_the_newest_log_is_read_from_the_cluster(self):
        self.w.ssh_out = None
        orig = self.w.ssh
        def ssh(host, cmd, timeout=30):
            if "logs/errors" in cmd: self.w.calls.append(cmd); return 0, "@@errors.900.log\nINFO starting\nERROR cuda out of memory\n"
            return orig(host, cmd, timeout)
        self.w.ssh = ssh
        r = self.m.server_log("qwen"); self.assertEqual(r["name"], "errors.900.log"); self.assertIn("cuda out of memory", r["text"])
        self.w.ssh = lambda host, cmd, timeout=30: (0, "")
        self.assertEqual(self.m.server_log("qwen"), {"name": "", "text": ""})

    def test_the_script_keeps_messages_but_drops_lines_that_could_carry_a_chat(self):
        s = open(os.path.join(os.path.dirname(__file__), "..", "docs", "cluster-models", "serve.sbatch")).read()
        self.assertIn("errors.$SLURM_JOB_ID.log", s); self.assertIn("no-enable-log-requests", s)
        import re, subprocess
        awk = re.search(r"<<'AWK'\n(.*?)\nAWK", s, re.S)[1]
        lines = "INFO Started server\nERROR out of memory\n{'role': 'user', 'content': 'my secret'}\nprompt_token_ids=[1,2]\n" + "x" * 500 + "\n"
        import tempfile
        flag = os.path.join(tempfile.mkdtemp(), "ready")
        run = lambda: subprocess.run(["awk", "-v", "flag=" + flag, awk], input=lines, capture_output=True, text=True).stdout.splitlines()
        out = run()
        self.assertEqual(out[:2], ["INFO Started server", "ERROR out of memory"]); self.assertNotIn("secret", "\n".join(out)); self.assertNotIn("prompt_token_ids", "\n".join(out))
        self.assertLess(max(len(l) for l in out), 310)
        open(flag, "w").write("5")                                   # the server answers: nothing at all is kept from then on, whatever it prints
        self.assertEqual(run(), [])


class TestAStuckNodeIsLeft(Base):
    def loading(self, node, elapsed):
        self.w.job = {"id": "900", "state": "RUNNING", "elapsed": elapsed, "limit": "1-00:00:00", "node": node}; self.w.run_file = ""

    def sbatches(self): return [c for c in self.w.calls if c.startswith("sbatch")]

    def test_nodes_to_avoid_reach_the_job_and_are_checked(self):
        self.assertEqual(MS.clean_settings({"exclude_nodes": "g33, g34;rm -rf /,g35"})["exclude_nodes"], "g33,g35")      # anything that is not a node name is dropped
        self.assertNotIn(";", MS.clean_settings({"exclude_nodes": "g33;x"})["exclude_nodes"]); self.assertNotIn("/", MS.clean_settings({"exclude_nodes": "/etc"})["exclude_nodes"])
        self.m.start("qwen", overrides={"exclude_nodes": "g33, g34"}); self.assertIn("--exclude=g33,g34", self.sbatches()[-1])

    def test_the_partition_reaches_the_job_and_is_checked(self):
        self.assertEqual(MS.clean_settings({"partition": "pi_shared"})["partition"], "pi_shared")
        self.assertEqual(MS.clean_settings({"partition": "campus,pi_shared"})["partition"], "campus,pi_shared")
        self.assertEqual(MS.clean_settings({"partition": "x; rm -rf /"})["partition"], "")
        self.m.start("qwen"); self.assertNotIn(" -p ", self.sbatches()[-1])
        self.w.job = None; self.m.rt.clear(); self.m.start("qwen", overrides={"partition": "pi_shared"}); self.assertIn(" -p pi_shared", self.sbatches()[-1])

    def test_a_job_still_loading_long_after_it_should_have_answered_is_moved_to_another_node(self):
        self.m.start("qwen"); self.assertNotIn("--exclude", self.sbatches()[-1])
        self.loading("g33", "10:00"); self.m.tick("qwen"); self.assertEqual(len(self.sbatches()), 1)                  # 10 minutes: still allowed
        self.loading("g33", "26:00"); self.w.calls.clear(); self.m.tick("qwen")
        self.assertTrue(any(c.startswith("scancel 900") for c in self.w.calls)); self.assertIn("--exclude=g33", self.sbatches()[-1])
        self.assertIn("moved off g33", self.m.status("qwen")["started_by"])

    def test_it_is_moved_at_most_twice_and_the_node_is_remembered_for_hours(self):
        self.m.start("qwen")
        self.loading("g33", "26:00"); self.m.tick("qwen"); self.loading("g34", "26:00"); self.m.tick("qwen")
        self.assertIn("--exclude=g33,g34", self.sbatches()[-1])
        n = len(self.sbatches()); self.loading("g35", "26:00"); self.m.tick("qwen")
        self.assertEqual(len(self.sbatches()), n); self.assertIn("left alone", self.m.status("qwen")["error"])
        self.m.stop("qwen"); self.w.job = None; self.m.tick("qwen"); self.t[0] += 7 * 3600; self.m.start("qwen")           # hours later, a fresh start tries every node again
        self.assertNotIn("--exclude", self.sbatches()[-1])

    def test_it_can_be_switched_off(self):
        self.m.update("qwen", {"settings": {"load_timeout_min": 0}}); self.m.start("qwen"); self.loading("g33", "300:00"); self.m.tick("qwen")
        self.assertEqual(len(self.sbatches()), 1)


class TestRenewAfterTheTimeLimit(Base):
    def ran_out(self):
        self.m.start("qwen"); self.w.job.update(state="RUNNING", node="g1"); self.w.run_file = "g1 1 k"; self.w.model_up = True
        self.m.tick("qwen"); self.w.job = None; self.w.sacct = "TIMEOUT|1-00:00:00|0:0"; self.m.tick("qwen")

    def count(self): return sum(c.startswith("sbatch") for c in self.w.calls)

    def test_it_starts_again_when_the_time_limit_ends_it(self):
        self.m.update("qwen", {"settings": {"renew": True}}); self.ran_out()
        self.assertEqual(self.m.rt["qwen"]["last_end"], "timeout")
        self.m.renew(self.m.server("qwen"), self.m.rt["qwen"])
        self.assertEqual((self.count(), self.m.rt["qwen"]["state"]), (2, "queued"))
        self.assertIn("renewed", self.w.desktop_log[-1][0])

    def test_off_means_it_stays_stopped_and_a_stop_by_hand_is_never_renewed(self):
        self.ran_out(); self.m.renew(self.m.server("qwen"), self.m.rt["qwen"]); self.assertEqual(self.count(), 1)
        self.m.update("qwen", {"settings": {"renew": True}}); self.w.job = None; self.m.rt.clear()
        self.m.start("qwen"); self.w.job.update(state="RUNNING", node="g1"); self.w.run_file = "g1 1 k"; self.m.tick("qwen")
        self.m.stop("qwen"); self.w.job = None; self.w.sacct = "CANCELLED by 1|00:20:00|0:0"; self.m.tick("qwen")
        self.m.renew(self.m.server("qwen"), self.m.rt["qwen"]); self.assertEqual(self.count(), 2)

    def test_it_stops_renewing_at_the_moment_you_set_and_says_so_once(self):
        self.m.update("qwen", {"settings": {"renew": True, "renew_until": "2026-10-26T08:00"}})      # it is 09:00
        self.ran_out(); self.m.renew(self.m.server("qwen"), self.m.rt["qwen"])
        self.assertEqual(self.count(), 1); self.assertIn("will not be renewed", self.w.desktop_log[-1][0])
        self.assertFalse(self.m.server("qwen")["settings"]["renew"])
        n = len(self.w.desktop_log); self.m.renew(self.m.server("qwen"), self.m.rt["qwen"]); self.assertEqual(len(self.w.desktop_log), n)

    def test_before_that_moment_it_renews(self):
        self.m.update("qwen", {"settings": {"renew": True, "renew_until": "2026-10-30T08:00"}}); self.ran_out()
        self.m.renew(self.m.server("qwen"), self.m.rt["qwen"]); self.assertEqual(self.count(), 2)
        self.assertEqual(self.m.status("qwen")["renew"], {"on": True, "until": "2026-10-30T08:00"})

    def test_when_the_cluster_says_no_it_waits_two_minutes_before_trying_again(self):
        self.m.update("qwen", {"settings": {"renew": True}}); self.ran_out()
        orig = self.w.ssh
        self.w.ssh = lambda host, cmd, timeout=30: (1, "no GPU for you") if cmd.startswith("sbatch") else orig(host, cmd, timeout)
        self.m.renew(self.m.server("qwen"), self.m.rt["qwen"]); self.m.renew(self.m.server("qwen"), self.m.rt["qwen"])
        self.assertEqual(self.count(), 1)                                   # (only the first start; the retry waits)
        self.assertIn("could not renew", self.m.rt["qwen"]["error"])

    def test_a_bad_date_is_dropped(self):
        self.assertEqual(MS.clean_settings({"renew_until": "tomorrow"})["renew_until"], "")


class TestIdleStop(Base):
    def test_it_stops_when_nothing_is_asked_of_it(self):
        self.m.update("qwen", {"settings": {"idle_stop_min": 30}})
        self.m.start("qwen"); self.w.job.update(state="RUNNING", node="g1"); self.w.run_file = "g1 1 k"; self.w.model_up = True
        self.m.tick("qwen"); self.t[0] += 600; self.m.tick("qwen")
        self.assertFalse(any(c.startswith("scancel") for c in self.w.calls))
        self.t[0] += 1500; self.m.tick("qwen")
        self.assertTrue(any(c.startswith("scancel") for c in self.w.calls))


class TestAddingAnotherModel(Base):
    def test_a_second_server_has_its_own_job_port_and_key(self):
        s = self.m.add({"label": "Llama big", "dir": "/path/to/project/x/llama"})
        self.assertEqual((s["id"], s["local_port"]), ("llama-big", 8013))
        self.assertNotEqual(s["job_name"], self.m.server("qwen")["job_name"])
        self.assertNotEqual(s["key_name"], "HPC_LLM_KEY")
        self.assertTrue(any("cp /path/to/project" in c and "/llama/serve.sbatch" in c for c in self.w.calls))
        with self.assertRaises(ValueError): self.m.add({"label": "x", "dir": "relative; rm -rf /"})
        self.m.remove("llama-big"); self.assertEqual(len(self.m.cfg["servers"]), 1)

    def test_a_config_saved_before_a_setting_existed_still_starts(self):
        old = {"servers": [dict(MS.DEFAULT_SERVER, settings={"max_model_len": 65536, "max_num_seqs": 8})]}
        json.dump(old, open(os.path.join(self.tmp, "old.json"), "w"))
        m = MS.Manager(os.path.join(self.tmp, "old.json"), self.w)
        st = m.server("qwen")["settings"]
        self.assertEqual((st["max_model_len"], st["batched_tokens"], st["renew"]), (65536, 16384, False))
        m.start("qwen"); self.assertIn("MAXLEN=65536", next(c for c in self.w.calls if c.startswith("sbatch")))

    def test_what_is_saved_comes_back(self):
        self.m.update("qwen", {"settings": {"max_model_len": 32768}, "schedule": [{"start": "06:00"}]})
        again = MS.Manager(os.path.join(self.tmp, "ms.json"), self.w)
        self.assertEqual(again.server("qwen")["settings"]["max_model_len"], 32768)
        self.assertEqual(again.server("qwen")["schedule"][0]["start"], "06:00")


class TestParsing(unittest.TestCase):
    def test_slurm_times(self):
        self.assertEqual([MS._secs(x) for x in ("1-02:03:04", "10:00", "UNLIMITED", "")], [93784, 600, None, None])

    def test_metrics(self):
        m = MS.parse_metrics('vllm:num_requests_running{a="b"} 2\nvllm:request_success_total{a="b"} 3\nvllm:request_success_total{a="c"} 4\n')
        self.assertEqual((m["running"], m["finished"], m["waiting"]), (2.0, 7.0, None))


class TestOnlyBigEnoughGpusAndNoRepeatedFailures(Base):
    """A 40 GB card cannot hold the model: it failed after two minutes four times in a row on the same node, each with its own mail."""
    FEATURES = "amd-7542,campus,pi_shared,gpu,A100,vmem40G,cuda_cc_8_0\nintel,pi_miao,gpu,P4,vmem8G,cuda_cc_6_1\namd-epyc,gpu,RTXPRO6000Bw,vmem97G,cuda_cc_12_0\nintel,cpu-only"

    def sbatches(self): return [c for c in self.w.calls if c.startswith("sbatch")]

    def test_the_job_is_kept_to_nodes_whose_gpus_have_enough_memory(self):
        self.w.features = self.FEATURES; self.m.start("qwen"); cmd = self.sbatches()[-1]
        self.assertIn("--constraint='vmem97G'", cmd); self.assertIn("CONSTRAINT=vmem97G", cmd); self.assertIn("MINVRAM_GB=60", cmd); self.assertIn("--export='ALL,", cmd)

    def test_a_lower_need_admits_more_cards_and_zero_means_no_limit(self):
        self.w.features = self.FEATURES; self.m.start("qwen", overrides={"min_vram_gb": 32}); self.assertIn("--constraint='vmem40G|vmem97G'", self.sbatches()[-1])
        self.w.job = None; self.m.rt.clear(); self.m.start("qwen", overrides={"min_vram_gb": 0}); self.assertNotIn("--constraint", self.sbatches()[-1]); self.assertNotIn("MINVRAM_GB", self.sbatches()[-1])

    def test_the_placement_questions_carry_the_constraint_too(self):
        self.w.features = self.FEATURES; self.w.calls.clear(); cands, _ = self.m.plan(self.m.server("qwen"), self.m.server("qwen")["settings"])
        self.assertTrue(any("--test-only" in c and "--constraint='vmem97G'" in c for c in self.w.calls))

    def test_no_gpu_big_enough_is_an_error_not_a_job_that_will_fail(self):
        self.w.features = "gpu,P4,vmem8G"
        with self.assertRaises(RuntimeError) as cm: self.m.start("qwen")
        self.assertIn("no GPU on the cluster has 60 GB", str(cm.exception)); self.assertEqual(self.sbatches(), [])

    def test_a_cluster_that_will_not_say_does_not_block_a_start(self):
        self.w.features = ""; self.m.start("qwen"); self.assertNotIn("--constraint", self.sbatches()[-1])

    def test_nodes_a_job_found_unusable_are_kept_out_of_the_next_start(self):
        t = int(self.t[0]); self.w.badnodes = f"g15 {t - 3600} its GPU has 40960 MB\ng304 {t - 99 * 3600} old\n../x {t} bad name\n"
        self.m.start("qwen"); self.assertIn("--exclude=g15", self.sbatches()[-1]); self.assertNotIn("g304", self.sbatches()[-1]); self.assertNotIn("..", self.sbatches()[-1].split("--exclude=")[1].split()[0])

    def fail_fast(self, node="g15"):
        self.w.job = {"id": "900", "state": "RUNNING", "elapsed": "2:22", "limit": "1-00:00:00", "node": node}; self.w.run_file = ""; self.m.tick("qwen")
        self.w.job = None; self.w.sacct = "FAILED|00:02:22|1:0"; self.m.tick("qwen")

    def test_a_job_that_ends_in_minutes_without_answering_marks_its_node_and_says_why(self):
        self.w.cause = "torch.OutOfMemoryError: CUDA out of memory"; self.m.start("qwen"); self.fail_fast()
        ev = [t for t in self.w.desktop_log if "failed" in t[0]]; self.assertTrue(ev); self.assertIn("without answering", ev[0][1]); self.assertIn("out of memory", ev[0][1].lower())
        self.w.job = None; self.m.rt["qwen"]["state"] = "stopped"; self.m.start("qwen"); self.assertIn("--exclude=g15", self.sbatches()[-1])

    def test_it_is_not_started_again_by_itself_after_the_same_failure_twice(self):
        self.m.update("qwen", {"settings": {"keep_alive": True}}); self.m.start("qwen"); self.fail_fast()
        n = len(self.sbatches()); self.m.tick("qwen"); self.m.keep_alive(self.m.server("qwen"), self.m.rt["qwen"]); self.assertGreater(len(self.sbatches()), n)            # the first failure: one restart
        self.fail_fast("g16"); n = len(self.sbatches()); self.m.keep_alive(self.m.server("qwen"), self.m.rt["qwen"]); self.assertEqual(len(self.sbatches()), n)
        self.assertIn("not started again by itself", self.m.rt["qwen"]["error"])

    def test_a_job_that_does_answer_resets_the_count(self):
        self.m.start("qwen"); self.fail_fast(); self.assertEqual(self.m.rt["qwen"]["fast_fails"], 1)
        self.w.job = {"id": "901", "state": "RUNNING", "elapsed": "5:00", "limit": "1-00:00:00", "node": "g33"}; self.w.run_file = "g33 20000 key"; self.w.model_up = True; self.m.rt["qwen"]["state"] = "queued"; self.m.tick("qwen")
        self.assertEqual(self.m.rt["qwen"]["fast_fails"], 0)

    def test_the_setting_is_checked(self):
        self.assertEqual(MS.clean_settings({"min_vram_gb": 80})["min_vram_gb"], 80); self.assertEqual(MS.clean_settings({"min_vram_gb": -5})["min_vram_gb"], 0); self.assertEqual(MS.clean_settings({"min_vram_gb": "x"}).get("min_vram_gb", 60), 60)


if __name__ == "__main__":
    unittest.main()
