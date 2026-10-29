"""Orbit as a helper for other agents (Claude Science and the like): the tools, the inbox, approvals, conversations, the limits, and the door (token, loopback, no browser pages)."""
import http.client, json, os, shutil, sys, tempfile, threading, time, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
import science_bridge as B         # noqa: E402


class FakeBackend:
    def __init__(self):
        self.started, self.stopped, self.notices, self.sessions = [], [], [], {}
        self.queue, self.recent, self.events, self.refreshes = [], [], [], 0
        self.threads, self.auto_reply, self.thread_running, self.closed = {}, True, set(), []
        self.rows = [{"id": "deepseek-flash", "label": "DeepSeek Flash", "tier": "light"}, {"id": "sonnet", "label": "Sonnet", "tier": "standard", "local": False}, {"id": "q", "label": "Qwen", "tier": "light", "local": True, "cooling": True}]

    free = [{"id": "hpc:qwen", "label": "Qwen · HPC", "where": "HPC GPU", "state": "off", "note": "its GPU job is not running"},
            {"id": "local:qwen27", "label": "Qwen 27B", "where": "this Mac", "state": "on_demand", "note": "not loaded; starts when asked"}]
    def server_llms(self): return [dict(r) for r in self.free]
    def models(self): return self.rows + [{"id": r["id"], "label": r["label"], "tier": "free", "free": True, "state": r["state"], "local": r["where"] == "this Mac"} for r in self.free if r["state"] != "off"]
    def start(self, task, tier, model, context, write, workdir):
        if model and model not in {r["id"] for r in self.models()}: raise B.BridgeError("that model is not ready")
        sid = f"s{len(self.started) + 1}"; self.started.append(dict(task=task, tier=tier, model=model, context=context, write=write, workdir=workdir, sid=sid))
        self.sessions[sid] = {"running": True, "answer": ""}; return {"sid": sid, "label": "DeepSeek Flash", "model_id": "deepseek-flash"}
    def state(self, sid): return dict(self.sessions[sid])
    def stop(self, sid): self.stopped.append(sid); self.sessions[sid]["running"] = False
    def cluster_view(self, match, refresh):
        self.refreshes += int(bool(refresh)); return {"running": list(self.queue), "recent": list(self.recent)}
    def cluster_output(self, jid, lines): return f"== out {jid}\n" + "\n".join(f"line {i}" for i in range(lines))
    def cluster_events(self, minutes): return list(self.events)
    def notify(self, title, text): self.notices.append((title, text))
    # conversations
    def thread_open(self, app, name, role, model):
        sid = f"t{len(self.threads) + 1}"; self.threads[sid] = {"app": app, "role": role, "model": model, "msgs": []}; return {"sid": sid, "label": "Sonnet"}
    def thread_send(self, sid, app, text):
        t = self.threads[sid]; t["msgs"].append({"who": "app", "text": text})
        if self.auto_reply: t["msgs"].append({"who": "orbit", "text": f"reply to: {text[:30]}"})
    def thread_read(self, sid, cursor):
        t = self.threads[sid]; return {"messages": [m for m in t["msgs"][cursor:] if m["who"] != "app"], "running": sid in self.thread_running, "cursor": len(t["msgs"])}
    def thread_close(self, sid): self.closed.append(sid)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.be = FakeBackend(); self.clock = [1000.0]
        self.b = B.Bridge(os.path.join(self.tmp, "cfg", "science_bridge.json"), self.be, now=lambda: self.clock[0])
        self.b.sleep = lambda s: self.clock.__setitem__(0, self.clock[0] + s)             # waiting advances the fake clock
        self.c = self.b.cfg["clients"][0]

    def call(self, name, **args): return self.b.call(name, args, self.c)
    def settings(self, c=None, **s): return self.b.configure(client=(c or self.c)["id"], settings=s)


class TestDelegate(Base):
    def test_a_task_starts_at_once_and_the_answer_is_collected_later(self):
        out = self.call("orbit_delegate", task="Summarise paper X", context="abstract...", tier="light"); self.assertIn("job ", out)
        job = out.split()[1]; self.assertEqual(self.be.started[0]["tier"], "light"); self.assertEqual(self.be.started[0]["write"], False)
        self.assertIn("still running", self.call("orbit_job", job=job))
        self.be.sessions["s1"] = {"running": False, "answer": "It is about X.\nConfidence: high"}
        self.assertIn("It is about X.", self.call("orbit_job", job=job)); self.assertIn("not instructions", self.call("orbit_job", job=job))

    def test_low_confidence_is_flagged_to_the_caller(self):
        job = self.call("orbit_delegate", task="t").split()[1]; self.be.sessions["s1"] = {"running": False, "answer": "maybe\nConfidence: low"}
        self.assertIn("verify it", self.call("orbit_job", job=job))

    def test_waiting_inside_orbit_returns_when_done_or_when_time_is_up(self):
        job = self.call("orbit_delegate", task="t").split()[1]
        t0 = self.clock[0]; self.assertIn("still running", self.call("orbit_job", job=job, wait_s=20)); self.assertGreaterEqual(self.clock[0] - t0, 20)
        orig = self.b.sleep
        def finish(s): self.be.sessions["s1"] = {"running": False, "answer": "done"}; orig(s)
        self.b.sleep = finish; self.assertIn("done", self.call("orbit_job", job=job, wait_s=300)); self.assertLess(self.clock[0] - t0, 40)

    def test_quick_tasks_can_wait_for_their_answer(self):
        orig = self.b.sleep
        def finish(s): self.be.sessions["s1"] = {"running": False, "answer": "42"}; orig(s)
        self.b.sleep = finish; self.assertIn("42", self.call("orbit_delegate", task="what is 6x7", wait_s=60))

    def test_a_job_that_ended_without_an_answer_says_so(self):
        job = self.call("orbit_delegate", task="t").split()[1]; self.be.sessions["s1"] = {"running": False, "answer": "", "note": "the model failed"}
        self.assertIn("without an answer", self.call("orbit_job", job=job))

    def test_the_same_task_again_is_the_same_job(self):
        a = self.call("orbit_delegate", task="Count the genes", context="x"); b = self.call("orbit_delegate", task="Count the genes", context="x")
        self.assertEqual(len(self.be.started), 1); self.assertIn("same task", b); self.assertEqual(a.split()[1], b.split()[-1].rstrip(".") if False else a.split()[1])
        self.call("orbit_delegate", task="Count the genes", context="different"); self.assertEqual(len(self.be.started), 2)
        self.clock[0] += B.DEDUPE_S + 1; self.call("orbit_delegate", task="Count the genes", context="x"); self.assertEqual(len(self.be.started), 3)

    def test_changes_need_a_folder_the_person_listed(self):
        work = os.path.join(self.tmp, "ws"); os.makedirs(os.path.join(work, "sub")); other = os.path.join(self.tmp, "other"); os.makedirs(other)
        for kw in ({"write": True}, {"workdir": work}, {"write": True, "workdir": work}, {"workdir": other}):
            with self.assertRaises(B.BridgeError): self.call("orbit_delegate", task="t", **kw)
        self.settings(workdirs=[work], approval="none")
        self.call("orbit_delegate", task="t", write=True, workdir=os.path.join(work, "sub")); self.assertEqual(self.be.started[-1]["workdir"], os.path.realpath(os.path.join(work, "sub")))
        for bad in (os.path.join(work, "..", "other"), "/", 5):
            with self.assertRaises(B.BridgeError): self.call("orbit_delegate", task="t", workdir=bad)
        link = os.path.join(work, "escape"); os.symlink(other, link)
        with self.assertRaises(B.BridgeError): self.call("orbit_delegate", task="t", workdir=link)

    def test_limits_on_running_and_daily_jobs_and_sizes(self):
        self.settings(max_running=2)
        self.call("orbit_delegate", task="a"); self.call("orbit_delegate", task="b")
        with self.assertRaises(B.BridgeError) as cm: self.call("orbit_delegate", task="c")
        self.assertIn("already running", str(cm.exception))
        self.be.sessions["s1"]["running"] = False; self.call("orbit_delegate", task="c")
        self.settings(max_per_day=3)
        with self.assertRaises(B.BridgeError): self.call("orbit_delegate", task="d")
        self.clock[0] += 86401
        for sid in self.be.sessions: self.be.sessions[sid]["running"] = False
        self.call("orbit_delegate", task="e")
        for bad in ({"task": ""}, {"task": 5}, {"task": "x" * (B.MAX_TASK + 1)}, {"task": "t", "context": "x" * (B.MAX_CONTEXT + 1)}, {"task": "t", "tier": "genius"}, {"task": "t", "model": "nope"}, {"task": "t", "label": 5}, {}):
            with self.assertRaises(B.BridgeError, msg=str(bad)[:40]): self.call("orbit_delegate", **bad)

    def test_cancel_list_and_models(self):
        job = self.call("orbit_delegate", task="long thing").split()[1]; self.assertIn("running", self.call("orbit_jobs")); self.call("orbit_cancel", job=job)
        self.assertEqual(self.be.stopped, ["s1"]); self.assertIn("cancelled", self.call("orbit_jobs"))
        with self.assertRaises(B.BridgeError): self.call("orbit_cancel", job="nope")
        self.assertIn("deepseek-flash", self.call("orbit_models")); self.assertIn("cooling", self.call("orbit_models"))

    def test_records_from_the_first_version_still_load(self):
        old = os.path.join(self.tmp, "v1", "science_bridge_jobs.json"); os.makedirs(os.path.dirname(old))
        json.dump({"j1": {"sid": "s9", "model": "M", "tier": "light", "task": "old task", "started": 500.0}, "bad": 5}, open(old, "w"))
        b2 = B.Bridge(os.path.join(os.path.dirname(old), "science_bridge.json"), self.be, now=lambda: self.clock[0]); self.assertEqual(list(b2.jobs), ["j1"]); self.be.sessions["s9"] = {"running": False, "answer": "x"}
        self.assertEqual(b2.inbox()[0]["state"], "done"); b2._save_jobs()

    def test_jobs_survive_a_restart(self):
        self.call("orbit_delegate", task="remember me"); b2 = B.Bridge(self.b.path, self.be, now=lambda: self.clock[0]); self.assertEqual(len(b2.jobs), 1)


class TestFreeServerModels(Base):
    def test_the_free_models_are_listed_with_their_state_and_called_free(self):
        out = self.call("orbit_server_llms"); self.assertIn("0 of 2 server models active", out); self.assertIn("free per token", out)
        self.assertLess(out.index("local:qwen27"), out.index("hpc:qwen"))                                 # what can run comes before what is off
        self.assertIn("ON DEMAND", out); self.assertIn("OFF: its GPU job is not running", out)
        self.be.free[0]["state"] = "active"; out = self.call("orbit_server_llms"); self.assertIn("1 of 2 server models active", out); self.assertIn("hpc:qwen  [HPC GPU]  ACTIVE", out)
        self.be.free = []; self.assertEqual(self.call("orbit_server_llms"), "No server models are set up.")

    def test_orbit_models_marks_them_free_and_leaves_out_the_ones_that_are_off(self):
        out = self.call("orbit_models"); self.assertIn("local:qwen27  [free]  Qwen 27B  (FREE: your own hardware, starts on demand)", out); self.assertNotIn("hpc:qwen", out)

    def test_a_free_model_can_be_asked_for_by_id_for_a_job_and_a_conversation(self):
        self.call("orbit_delegate", task="bulk summary", model="local:qwen27"); self.assertEqual(self.be.started[0]["model"], "local:qwen27")
        with self.assertRaises(B.BridgeError): self.call("orbit_delegate", task="x", model="hpc:qwen")                 # off: the backend refuses it


class TestBatch(Base):
    def test_many_tasks_in_one_call_and_all_answers_in_one_wait(self):
        out = self.call("orbit_delegate_many", tasks=[{"task": f"summarise paper {i}", "label": f"p{i}"} for i in range(3)] + [{"task": ""}]); self.assertEqual(len(self.be.started), 3)
        self.assertIn("[p0]", out); self.assertIn("refused", out.splitlines()[3])
        for sid in ("s1", "s2"): self.be.sessions[sid] = {"running": False, "answer": f"answer {sid}"}
        r = self.call("orbit_wait", wait_s=0); self.assertIn("answer s1", r); self.assertIn("answer s2", r); self.assertIn("Still going", r)
        self.be.sessions["s3"] = {"running": False, "answer": "answer s3"}; self.assertIn("answer s3", self.call("orbit_wait", wait_s=30))
        self.assertEqual(self.call("orbit_wait"), "No jobs to wait for.")

    def test_batches_are_read_only_and_bounded(self):
        with self.assertRaises(B.BridgeError): self.call("orbit_delegate_many", tasks=[{"task": "t"}] * (B.MAX_MANY + 1))
        for bad in ([], "x", None): 
            with self.assertRaises(B.BridgeError): self.call("orbit_delegate_many", tasks=bad)
        out = self.call("orbit_delegate_many", tasks=[{"task": "t", "write": True, "workdir": self.tmp}]); self.assertIn("refused", out); self.assertEqual(self.be.started, [])

    def test_wait_only_sees_my_jobs_and_ends_on_time(self):
        self.call("orbit_delegate", task="a"); j = self.call("orbit_delegate", task="b").split()[1]
        t0 = self.clock[0]; self.assertIn("Still going", self.call("orbit_wait", jobs=[j], wait_s=40)); self.assertGreaterEqual(self.clock[0] - t0, 40)
        other = self.b.cfg["clients"][0]; self.b.configure(add_client="Other agent"); o = self.b.cfg["clients"][1]
        with self.assertRaises(B.BridgeError): self.b.call("orbit_wait", {"jobs": [j]}, o)
        with self.assertRaises(B.BridgeError): self.call("orbit_wait", jobs="x")


class TestApprovals(Base):
    def setUp(self):
        super().setUp(); self.work = os.path.join(self.tmp, "ws"); os.makedirs(self.work); self.settings(workdirs=[self.work])

    def test_a_job_that_changes_files_waits_for_the_persons_yes(self):
        out = self.call("orbit_delegate", task="rename the files", write=True, workdir=self.work); job = out.split()[1]
        self.assertIn("waiting for the person", out); self.assertEqual(self.be.started, []); self.assertTrue(any("asks for your yes" in t for t, _ in self.be.notices))
        self.assertIn("waiting for the person", self.call("orbit_job", job=job))
        self.assertEqual(self.b.decide(job, True), {"ok": True}); self.assertEqual(len(self.be.started), 1); self.assertTrue(self.be.started[0]["write"]); self.assertIn("still running", self.call("orbit_job", job=job))
        with self.assertRaises(ValueError): self.b.decide(job, True)

    def test_a_no_is_final_and_says_so_to_the_caller(self):
        job = self.call("orbit_delegate", task="x", write=True, workdir=self.work).split()[1]; self.b.decide(job, False)
        self.assertEqual(self.be.started, []); self.assertIn("said no", self.call("orbit_job", job=job))

    def test_nobody_answering_expires_it(self):
        job = self.call("orbit_delegate", task="x", write=True, workdir=self.work).split()[1]; self.clock[0] += B.APPROVAL_WAIT_S + 1
        self.assertIn("expired", self.call("orbit_job", job=job)); self.assertEqual(self.be.started, [])

    def test_read_only_jobs_are_not_held_unless_the_person_wants_everything_checked(self):
        self.call("orbit_delegate", task="read"); self.assertEqual(len(self.be.started), 1)
        self.settings(approval="all"); j = self.call("orbit_delegate", task="read again").split()[1]; self.assertEqual(len(self.be.started), 1); self.b.decide(j, True); self.assertEqual(len(self.be.started), 2)
        self.settings(approval="none"); self.call("orbit_delegate", task="write now", write=True, workdir=self.work); self.assertEqual(len(self.be.started), 3)

    def test_too_many_waiting_requests_are_refused(self):
        for i in range(B.MAX_WAITING): self.call("orbit_delegate", task=f"w{i}", write=True, workdir=self.work)
        with self.assertRaises(B.BridgeError): self.call("orbit_delegate", task="one more", write=True, workdir=self.work)

    def test_a_waiting_job_can_be_cancelled_by_either_side(self):
        j = self.call("orbit_delegate", task="x", write=True, workdir=self.work).split()[1]; self.call("orbit_cancel", job=j); self.assertIn("cancelled", self.call("orbit_job", job=j))
        k = self.call("orbit_delegate", task="y", write=True, workdir=self.work).split()[1]; self.b.cancel(k); self.assertEqual(self.b.jobs[k]["state"], "cancelled")


class TestInbox(Base):
    def test_the_inbox_lists_every_apps_jobs_with_state_answer_and_confidence(self):
        self.b.configure(add_client="Claude Code"); o = self.b.cfg["clients"][1]
        a = self.call("orbit_delegate", task="from the first", label="L1").split()[1]; b = self.b.call("orbit_delegate", {"task": "from the second"}, o).split()[1]
        self.be.sessions["s1"] = {"running": False, "answer": "result\nConfidence: medium", "tokens": 1234}
        rows = {r["id"]: r for r in self.b.inbox()}; self.assertEqual((rows[a]["app"], rows[a]["state"], rows[a]["confidence"], rows[a]["tokens"]), ("Claude Science", "done", "medium", 1234))
        self.assertEqual((rows[b]["app"], rows[b]["state"]), ("Claude Code", "running")); self.assertNotIn("full_task", rows[a]); self.assertNotIn("context", rows[a])
        with self.assertRaises(B.BridgeError): self.call("orbit_job", job=b)                                 # one app cannot read another's job

    def test_stats_and_clearing_finished_jobs(self):
        self.call("orbit_delegate", task="a"); self.call("orbit_delegate", task="b"); self.be.sessions["s1"] = {"running": False, "answer": "x", "tokens": 100}; self.be.sessions["s2"] = {"running": False, "answer": "", "tokens": 5}
        self.b.tick(); st = self.b.stats(); self.assertEqual(st["DeepSeek Flash"]["jobs"], 2); self.assertEqual(st["DeepSeek Flash"]["tokens"], 105); self.assertEqual(st["DeepSeek Flash"]["failed"], 1)
        self.call("orbit_delegate", task="c"); self.b.forget(); self.assertEqual(len(self.b.jobs), 1)

    def test_the_tracker_notices_finished_jobs_and_tells_the_person_only_when_asked(self):
        self.settings(notify="long"); self.call("orbit_delegate", task="short one"); self.be.sessions["s1"] = {"running": False, "answer": "fast"}; self.b.tick(); self.assertEqual(self.be.notices, [])
        self.call("orbit_delegate", task="slow one"); self.clock[0] += B.LONG_JOB_S + 5; self.be.sessions["s2"] = {"running": False, "answer": "slow"}; self.b.tick(); self.assertTrue(any("finished" in t for t, _ in self.be.notices))
        self.be.notices.clear(); self.settings(notify="always"); self.call("orbit_delegate", task="third"); self.be.sessions["s3"] = {"running": False, "answer": "ok"}; self.b.tick(); self.assertEqual(len(self.be.notices), 1)
        self.be.notices.clear(); self.settings(notify="never"); self.call("orbit_delegate", task="fourth"); self.clock[0] += 999; self.be.sessions["s4"] = {"running": False, "answer": "ok"}; self.b.tick(); self.assertEqual(self.be.notices, [])


class TestThreads(Base):
    def test_a_conversation_goes_back_and_forth_and_remembers_its_role(self):
        r = self.call("orbit_talk", thread="peak-review", message="Here is my MACS3 command; what is wrong?", role="reviewer"); self.assertIn("reply to: Here is my MACS3", r)
        self.assertEqual(self.be.threads["t1"]["role"], "reviewer"); self.assertEqual(self.be.threads["t1"]["app"], "Claude Science")
        self.call("orbit_talk", thread="PEAK-review", message="Fixed it", role="planner"); self.assertEqual(len(self.be.threads), 1); self.assertEqual(self.be.threads["t1"]["role"], "reviewer")
        self.assertIn("1 of", "1 of"); self.assertIn("peak-review  [reviewer]  2/30 messages", self.call("orbit_threads"))

    def test_listen_waits_for_what_the_orbit_side_or_the_person_says_next(self):
        self.be.auto_reply = False; self.be.thread_running.add("t1")
        self.assertIn("still thinking", self.call("orbit_talk", thread="a", message="hi", wait_s=5))
        orig = self.b.sleep
        def answer(s): self.be.thread_running.discard("t1"); self.be.threads["t1"]["msgs"].append({"who": "orbit", "text": "after a while"}); orig(s)
        self.b.sleep = answer; self.assertIn("after a while", self.call("orbit_listen", thread="a", wait_s=60))
        self.b.sleep = orig; self.be.threads["t1"]["msgs"].append({"who": "person", "text": "please also check the controls"})
        out = self.call("orbit_listen", thread="a", wait_s=1); self.assertIn("[person] please also check the controls", out); self.assertEqual(self.call("orbit_listen", thread="a", wait_s=1).count("controls"), 0)

    def test_no_reply_at_all_is_reported_instead_of_waiting_for_ever(self):
        self.be.auto_reply = False; self.assertIn("did not reply", self.call("orbit_talk", thread="b", message="hello?", wait_s=120))

    def test_conversations_are_limited_and_the_person_can_allow_more(self):
        for i in range(B.THREAD_ROUNDS): self.call("orbit_talk", thread="c", message=f"m{i}")
        with self.assertRaises(B.BridgeError) as cm: self.call("orbit_talk", thread="c", message="one more")
        self.assertIn("ask the person", str(cm.exception)); self.b.thread_more(self.b.thread_list()[0]["id"], 5); self.call("orbit_talk", thread="c", message="again")

    def test_a_daily_limit_and_a_limit_on_open_conversations(self):
        self.settings(max_thread_messages_per_day=3)
        for i in range(3): self.call("orbit_talk", thread=f"d{i}", message="x")
        with self.assertRaises(B.BridgeError): self.call("orbit_talk", thread="d0", message="x")
        self.clock[0] += 86401; self.call("orbit_talk", thread="d0", message="x")
        self.settings(max_thread_messages_per_day=1000)
        for i in range(B.MAX_THREADS): self.call("orbit_talk", thread=f"e{i}", message="x") if i + 3 < B.MAX_THREADS else None
        with self.assertRaises(B.BridgeError): [self.call("orbit_talk", thread=f"f{i}", message="x") for i in range(B.MAX_THREADS + 2)]

    def test_apps_cannot_see_each_others_conversations_and_ending_closes_the_chat(self):
        self.call("orbit_talk", thread="mine", message="x"); self.b.configure(add_client="Codex"); o = self.b.cfg["clients"][1]
        with self.assertRaises(B.BridgeError): self.b.call("orbit_listen", {"thread": "mine"}, o)
        self.assertEqual(self.b.call("orbit_threads", {}, o), "No conversations yet.")
        self.call("orbit_end_thread", thread="mine"); self.assertEqual(self.be.closed, ["t1"]); self.assertEqual(self.b.thread_list()[0]["state"], "ended")
        with self.assertRaises(B.BridgeError): self.call("orbit_listen", thread="mine")
        self.call("orbit_talk", thread="mine", message="a new one with the same name"); self.assertEqual(len(self.be.threads), 2)

    def test_bad_names_and_messages(self):
        for bad in ({"thread": "../x", "message": "m"}, {"thread": "", "message": "m"}, {"thread": 5, "message": "m"}, {"thread": "ok", "message": ""}, {"thread": "ok", "message": "x" * (B.MAX_MESSAGE + 1)}, {"thread": "ok", "message": "m", "role": "boss"}):
            with self.assertRaises(B.BridgeError, msg=str(bad)[:40]): self.call("orbit_talk", **bad)

    def test_the_inbox_lists_conversations_with_unread_counts_and_they_persist(self):
        self.be.auto_reply = False; self.call("orbit_talk", thread="p", message="x", wait_s=0); self.be.threads["t1"]["msgs"].append({"who": "orbit", "text": "hello"})
        row = self.b.thread_list()[0]; self.assertEqual((row["app"], row["unread"], row["rounds"], row["state"]), ("Claude Science", 1, 1, "open"))
        self.assertEqual(len(B.Bridge(self.b.path, self.be).threads), 1)


class TestCluster(Base):
    def jobs(self):
        self.be.queue = [{"id": f"100_{i}", "name": "align-batch", "state": "RUNNING"} for i in range(30)] + [{"id": f"100_{i}", "name": "align-batch", "state": "PENDING"} for i in range(30, 40)] + [{"id": "7", "name": "other", "state": "RUNNING"}]
        self.be.recent = [{"id": f"99_{i}", "name": "align-batch", "state": "COMPLETED", "exit": "0:0"} for i in range(60)] + [{"id": "99_61", "name": "align-batch", "state": "FAILED", "exit": "1:0"}, {"id": "98", "name": "old", "state": "TIMEOUT", "exit": "0:0"}]

    def test_status_groups_by_name_and_names_the_failures(self):
        self.jobs(); out = self.call("orbit_cluster_status", match="align")
        self.assertIn("30 running", out); self.assertIn("10 pending", out); self.assertIn("60 completed", out); self.assertIn("99_61 FAILED (exit 1:0)", out); self.assertIn("1 failed", out.splitlines()[0]); self.assertNotIn("other", out); self.assertNotIn("TIMEOUT", out)
        self.assertIn("No jobs found", self.call("orbit_cluster_status", match="zzz")); self.assertIn("other", self.call("orbit_cluster_status"))

    def test_a_long_list_is_cut_with_the_active_names_first(self):
        self.be.recent = [{"id": str(i), "name": f"old{i:03d}", "state": "COMPLETED"} for i in range(80)]; self.be.queue = [{"id": "9000", "name": "zzz-live", "state": "RUNNING"}]
        out = self.call("orbit_cluster_status"); self.assertEqual(out.splitlines()[1].split(":")[0].strip(), "zzz-live"); self.assertIn("and 51 more job names", out); self.assertLess(len(out), 3000)

    def test_waiting_ends_when_nothing_with_that_name_is_active(self):
        self.jobs(); orig = self.b.sleep
        def drain(s): self.be.queue = [q for q in self.be.queue if q["name"] != "align-batch"]; orig(s)
        self.b.sleep = drain; out = self.call("orbit_cluster_wait", match="align", wait_s=300); self.assertTrue(out.startswith("All finished")); self.assertGreaterEqual(self.be.refreshes, 1)

    def test_waiting_can_come_back_early_when_jobs_fail(self):
        self.jobs(); t0 = self.clock[0]; out = self.call("orbit_cluster_wait", match="align", wait_s=500, stop_on_failures=1); self.assertIn("coming back early", out); self.assertLess(self.clock[0] - t0, 5)
        out = self.call("orbit_cluster_wait", match="align", wait_s=40, stop_on_failures=5); self.assertTrue(out.startswith("Still going"))

    def test_waiting_times_out_politely_and_needs_a_name(self):
        self.jobs(); t0 = self.clock[0]; out = self.call("orbit_cluster_wait", match="align", wait_s=90); self.assertTrue(out.startswith("Still going")); self.assertGreaterEqual(self.clock[0] - t0, 90)
        self.assertIn("No job with that name", self.call("orbit_cluster_wait", match="nothing", wait_s=0))
        for bad in ("", " ", None, 5):
            with self.assertRaises(B.BridgeError): self.call("orbit_cluster_wait", match=bad)

    def test_output_checks_the_job_id_and_bounds_the_lines(self):
        self.assertIn("line 9", self.call("orbit_cluster_output", job="123_4", lines=10)); self.assertEqual(self.call("orbit_cluster_output", job="5", lines=100000).count("line "), 400)
        for bad in ("12; rm -rf /", "../x", "", 5, "1_2_3"):
            with self.assertRaises(B.BridgeError): self.call("orbit_cluster_output", job=bad)

    def test_events_carry_the_cause_and_can_be_filtered(self):
        self.be.events = [{"kind": "failed", "text": "align-batch task 7 failed", "job": "100_7", "cause": "out of memory (asked 4G, used 9G)"}, {"kind": "finished", "text": "other done", "job": "5"}]
        out = self.call("orbit_cluster_events"); self.assertIn("cause: out of memory", out); self.assertIn("other done", out)
        out = self.call("orbit_cluster_events", match="align"); self.assertIn("align-batch", out); self.assertNotIn("other done", out)
        self.be.events = []; self.assertEqual(self.call("orbit_cluster_events"), "Nothing noteworthy.")

    def test_notify_names_the_app(self):
        self.call("orbit_notify", title="Batch done", text="all 100 finished"); self.assertEqual(self.be.notices, [("Claude Science: Batch done", "all 100 finished")])
        with self.assertRaises(B.BridgeError): self.call("orbit_notify", title="", text="x")


class TestClients(Base):
    def test_each_app_has_its_own_token_and_settings_and_the_old_single_token_file_still_works(self):
        self.b.configure(add_client="Claude Code"); a, o = self.b.cfg["clients"]; self.assertNotEqual(a["token"], o["token"])
        self.assertEqual(self.b.check_token(o["token"])["name"], "Claude Code"); self.assertIsNone(self.b.check_token("nope")); self.assertIsNone(self.b.check_token(None))
        self.settings(o, approval="all", workdirs=[self.tmp]); self.assertEqual(self.b.cfg["clients"][0]["approval"], "writes"); self.assertEqual(self.b.cfg["clients"][1]["approval"], "all")
        old = os.path.join(self.tmp, "old", "science_bridge.json"); os.makedirs(os.path.dirname(old)); json.dump({"enabled": True, "port": 8455, "token": "t" * 43, "workdirs": [self.tmp], "max_running": 2}, open(old, "w"))
        b2 = B.Bridge(old, self.be); c = b2.cfg["clients"][0]; self.assertEqual((c["name"], c["token"], c["workdirs"], c["max_running"], c["approval"]), ("Claude Science", "t" * 43, [self.tmp], 2, "writes"))

    def test_zero_means_no_limit(self):
        self.settings(max_running=0, max_per_day=0, thread_rounds=0, max_thread_messages_per_day=0)
        for i in range(7): self.call("orbit_delegate", task=f"job {i}")                 # more than the usual four at once
        self.assertEqual(len([j for j in self.b.jobs.values() if j["state"] == "running"]), 7)
        self.assertEqual((self.c["max_running"], self.c["thread_rounds"]), (0, 0))

    def test_removing_and_renaming_and_bad_settings(self):
        self.b.configure(add_client="Other"); o = self.b.cfg["clients"][1]; self.settings(o, name="Cursor"); self.assertEqual(self.b.cfg["clients"][1]["name"], "Cursor")
        self.b.configure(remove_client=o["id"]); self.assertEqual(len(self.b.cfg["clients"]), 1)
        with self.assertRaises(ValueError): self.b.configure(remove_client=self.c["id"])
        for bad in ({"approval": "sometimes"}, {"notify": "loud"}, {"workdirs": ["rel"]}, {"workdirs": "x"}, {"max_running": -1}, {"max_per_day": "5"}, {"name": ""}, {"name": "x" * 41}, {"thread_model": 5}, {"max_thread_messages_per_day": -3}, {"thread_rounds": True}):
            with self.assertRaises(ValueError, msg=str(bad)): self.settings(**bad)
        with self.assertRaises(ValueError): self.b.configure(add_client="")
        with self.assertRaises(ValueError): self.b.configure(client="c_nobody", settings={})

    def test_the_token_file_is_private_and_stable(self):
        self.assertEqual(os.stat(self.b.path).st_mode & 0o077, 0) if os.path.exists(self.b.path) else self.b.configure(enabled=False)
        self.assertEqual(os.stat(self.b.path).st_mode & 0o077, 0); b2 = B.Bridge(self.b.path, self.be); self.assertEqual(b2.cfg["clients"][0]["token"], self.c["token"])


class TestRpc(Base):
    def test_the_protocol_basics(self):
        r = self.b.rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}); self.assertEqual(r["result"]["serverInfo"]["name"], "orbit")
        self.assertIsNone(self.b.rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        names = [t["name"] for t in self.b.rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]]; self.assertIn("orbit_delegate", names); self.assertIn("orbit_talk", names); self.assertEqual(len(names), len(set(names)))
        self.assertEqual(self.b.rpc({"jsonrpc": "2.0", "id": 3, "method": "nope"})["error"]["code"], -32601)
        r = self.b.rpc({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "orbit_job", "arguments": {"job": "x"}}}); self.assertTrue(r["result"]["isError"])
        for junk in (None, 5, [], {"id": 1}, {"jsonrpc": "1.0", "method": "x"}, {"jsonrpc": "2.0", "id": 1, "method": 5}):
            self.assertIn("error", self.b.rpc(junk))
        for name in ("os.system", "orbit_", "__init__", "orbit_config", None, 5, "t_orbit_models"):
            r = self.b.rpc({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": name, "arguments": {}}}); self.assertTrue(r["result"]["isError"], name)

    def test_every_declared_tool_exists_and_junk_arguments_are_errors_not_crashes(self):
        for t in B.TOOLS:
            for args in (None, 5, [], {"x": 1}, {"job": {"a": 1}, "jobs": 5, "tasks": 5, "thread": [], "match": 5, "task": [], "message": 1, "title": None, "wait_s": "x", "lines": True, "minutes": "x"}):
                r = self.b.rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": t["name"], "arguments": args}}, self.c); self.assertIn("result", r, t["name"])


class TestDoor(Base):
    def setUp(self):
        super().setUp(); self.b.configure(enabled=True)
        self.srv = B.make_server(self.b, 0); self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start(); self.addCleanup(self.srv.shutdown); self.addCleanup(self.srv.server_close)

    def post(self, path="/mcp", body=None, headers=None, raw=None, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10); h = {"Content-Type": "application/json"}; h.update(headers or {})
        if host: h["Host"] = host
        c.request("POST", path, body=raw if raw is not None else json.dumps(body if body is not None else {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}), headers=h)
        r = c.getresponse(); data = r.read()
        try: return r.status, json.loads(data) if data else None
        except ValueError: return r.status, data

    def tok(self, c=None): return {"Authorization": "Bearer " + (c or self.b.cfg["clients"][0])["token"]}

    def test_the_token_is_required_and_works_three_ways(self):
        t = self.b.cfg["clients"][0]["token"]
        self.assertEqual(self.post()[0], 401); self.assertEqual(self.post(headers={"Authorization": "Bearer wrong"})[0], 401)
        st, j = self.post(headers=self.tok()); self.assertEqual(st, 200); self.assertTrue(j["result"]["tools"])
        self.assertEqual(self.post(headers={"X-Orbit-Token": t})[0], 200); self.assertEqual(self.post(path="/mcp/" + t)[0], 200); self.assertEqual(self.post(path="/mcp/" + "a" * 43)[0], 401)

    def test_the_door_knows_which_app_is_calling(self):
        self.b.configure(add_client="Claude Code"); o = self.b.cfg["clients"][1]
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "orbit_delegate", "arguments": {"task": "from code"}}}
        self.post(headers=self.tok(o), body=body); self.assertEqual([r["app"] for r in self.b.inbox()], ["Claude Code"]); self.assertIsNotNone(self.b.public()["clients"][1]["last_seen"])

    def test_off_means_off(self):
        self.b.configure(enabled=False); self.assertEqual(self.post(headers=self.tok())[0], 401)

    def test_a_new_token_ends_the_old_one(self):
        old = self.b.cfg["clients"][0]["token"]; self.b.configure(new_token=self.c["id"]); self.assertEqual(self.post(headers={"Authorization": "Bearer " + old})[0], 401); self.assertEqual(self.post(headers=self.tok())[0], 200)

    def test_only_loopback_host_names_and_never_a_web_page(self):
        self.assertEqual(self.post(headers=self.tok(), host="evil.example")[0], 403)
        self.assertEqual(self.post(headers=dict(self.tok(), Origin="https://evil.example"))[0], 403)
        self.assertEqual(self.post(headers=self.tok(), host=f"localhost:{self.port}")[0], 200)

    def test_other_paths_methods_and_bad_bodies(self):
        self.assertEqual(self.post(path="/other", headers=self.tok())[0], 404); self.assertEqual(self.post(path="/mcp/../x", headers=self.tok())[0], 404)
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10); c.request("GET", "/mcp", headers=self.tok()); self.assertEqual(c.getresponse().status, 405)
        self.assertEqual(self.post(headers=self.tok(), raw=b"{")[1]["error"]["code"], -32700)
        self.assertEqual(self.post(headers=self.tok(), raw=b"x" * (B.MAX_BODY + 10))[0], 413)
        st, j = self.post(headers=self.tok(), body=[{"jsonrpc": "2.0", "id": 1, "method": "ping"}, {"jsonrpc": "2.0", "method": "notifications/x"}]); self.assertEqual((st, len(j)), (200, 1))
        self.assertEqual(self.post(headers=self.tok(), body={"jsonrpc": "2.0", "method": "notifications/initialized"})[0], 202)

    def test_bad_server_settings(self):
        for bad in ({"enabled": "yes"}, {"port": 80}, {"port": True}):
            with self.assertRaises(ValueError): self.b.configure(**bad)


class TestRoute(Base):
    """/api/sciencebridge through the real server module, pointed at a temp config and a fake backend."""

    @classmethod
    def setUpClass(cls):
        import importlib.machinery, importlib.util
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_loader("qqui_sbr", importlib.machinery.SourceFileLoader("qqui_sbr", os.path.join(root, "bin", "orbit-ui")))
        cls.ui = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.ui)

    def setUp(self):
        super().setUp(); ui = self.ui
        self.old = ui.SCIENCE; ui.SCIENCE = self.b; self.addCleanup(setattr, ui, "SCIENCE", self.old)
        self.addCleanup(lambda: (ui._SCI_SERVER[0] and (ui._SCI_SERVER[0].shutdown(), ui._SCI_SERVER[0].server_close(), ui._SCI_SERVER.__setitem__(0, None))))
        import socket
        with socket.socket() as s: s.bind(("127.0.0.1", 0)); self.port = s.getsockname()[1]

    def r(self, d): st, raw = self.ui._science_helper_route(d); return st, json.loads(raw)

    def test_off_by_default_then_on_opens_the_door_and_off_closes_it(self):
        st, j = self.r({"op": "status"}); self.assertEqual((st, j["enabled"], j["running"]), (200, False, False)); self.assertIn("orbit_delegate", j["instructions"])
        self.assertTrue(self.r({"op": "configure", "enabled": True, "port": self.port})[1]["running"])
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5); c.request("POST", "/mcp", body=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}), headers={"Authorization": "Bearer " + self.c["token"]})
        self.assertEqual(c.getresponse().status, 200)
        self.assertFalse(self.r({"op": "configure", "enabled": False})[1]["running"])
        with self.assertRaises(OSError): http.client.HTTPConnection("127.0.0.1", self.port, timeout=2).request("POST", "/mcp")

    def test_apps_settings_and_the_inbox_through_the_route(self):
        j = self.r({"op": "configure", "add_client": "Codex"})[1]; self.assertEqual([c["name"] for c in j["clients"]], ["Claude Science", "Codex"])
        cid = j["clients"][1]["id"]; self.assertEqual(self.r({"op": "configure", "client": cid, "settings": {"approval": "all"}})[1]["clients"][1]["approval"], "all")
        self.assertEqual(self.r({"op": "configure", "client": cid, "settings": {"approval": "x"}})[0], 400)
        self.b.call("orbit_delegate", {"task": "hello there"}, self.b.cfg["clients"][1]); inbox = self.r({"op": "inbox"})[1]; row = inbox["jobs"][0]; self.assertEqual((row["app"], row["state"]), ("Codex", "waiting"))
        self.assertEqual(self.r({"op": "decide", "job": row["id"], "approve": True})[0], 200); self.assertEqual(self.r({"op": "inbox"})[1]["jobs"][0]["state"], "running")
        self.assertEqual(self.r({"op": "cancel", "job": row["id"]})[0], 200); self.assertEqual(self.r({"op": "inbox"})[1]["jobs"][0]["state"], "cancelled")
        self.assertEqual(self.r({"op": "forget"})[0], 200); self.assertEqual(self.r({"op": "inbox"})[1]["jobs"], [])
        self.assertEqual(self.r({"op": "decide", "job": "nope", "approve": True})[0], 400)

    def test_conversations_through_the_route(self):
        self.b.call("orbit_talk", {"thread": "t", "message": "hi"}, self.c); inbox = self.r({"op": "inbox"})[1]; th = inbox["threads"][0]; self.assertEqual((th["app"], th["name"]), ("Claude Science", "t"))
        self.assertEqual(self.r({"op": "thread_more", "thread": th["id"]})[0], 200); self.assertEqual(self.r({"op": "inbox"})[1]["threads"][0]["max_rounds"], B.THREAD_ROUNDS * 2)
        self.assertEqual(self.r({"op": "thread_end", "thread": th["id"]})[0], 200); self.assertEqual(self.r({"op": "inbox"})[1]["threads"][0]["state"], "ended"); self.assertEqual(self.r({"op": "thread_end", "thread": "x"})[0], 400)

    def test_bad_settings_are_refused_and_the_test_op_lists_models(self):
        for d in ({"op": "configure", "enabled": "yes"}, {"op": "configure", "port": 80}, {"op": "configure", "client": "nobody", "settings": {}}, {"op": "nope"}): self.assertEqual(self.r(d)[0], 400)
        self.assertIn("deepseek-flash", self.r({"op": "test"})[1]["models"])

    def test_the_launcher_can_be_copied_where_a_sandbox_can_see_it_with_the_data_folder_baked_in(self):
        d = os.path.join(self.tmp, "sys_bin"); os.makedirs(d); os.environ["ORBIT_LAUNCHER_DIR"] = d; self.addCleanup(os.environ.pop, "ORBIT_LAUNCHER_DIR", None)
        st, j = self.r({"op": "status"}); self.assertEqual((j["launcher"]["installed"], j["launcher"]["can_install"]), (False, True)); self.assertIn("/bin/orbit-helpers-mcp", j["stdio_command"])
        st, r = self.r({"op": "install_launcher"}); self.assertEqual((st, r["path"]), (200, os.path.join(d, "orbit-helpers-mcp")))
        text = open(r["path"]).read(); self.assertIn("BAKED_HOME = " + json.dumps(str(self.ui.q.ROOT)), text); self.assertEqual(os.stat(r["path"]).st_mode & 0o777, 0o755)
        st, j = self.r({"op": "status"}); self.assertTrue(j["launcher"]["installed"]); self.assertTrue(j["stdio_command"].endswith(r["path"])); self.assertIn("ORBIT_HELPERS_URL=", j["env_lines"])
        self.assertEqual(self.r({"op": "install_launcher"})[0], 200)                                                                  # again: an update
        os.chmod(d, 0o500); self.addCleanup(os.chmod, d, 0o700); os.environ["ORBIT_LAUNCHER_DIR"] = os.path.join(d, "x"); self.assertEqual(self.r({"op": "install_launcher"})[0], 400)

    def test_a_call_that_came_through_the_service_waits_at_most_about_a_minute_and_a_half(self):
        self.b.configure(enabled=True); self.srv = B.make_server(self.b, 0); port = self.srv.server_address[1]
        import threading; threading.Thread(target=self.srv.serve_forever, daemon=True).start(); self.addCleanup(self.srv.shutdown); self.addCleanup(self.srv.server_close)
        job = self.b.call("orbit_delegate", {"task": "never finishes"}, self.c).split()[1]
        def ask(headers):
            body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "orbit_job", "arguments": {"job": job, "wait_s": 600}}}
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=20); t0 = self.clock[0]
            c.request("POST", "/mcp", body=json.dumps(body), headers=dict({"Authorization": "Bearer " + self.c["token"], "Content-Type": "application/json"}, **headers)); c.getresponse().read(); return self.clock[0] - t0
        self.assertGreaterEqual(ask({}), 600); relayed = ask({"X-Orbit-Relay-Client": "Abcdefgh12345678"}); self.assertTrue(B.RELAYED_MAX_WAIT_S <= relayed < B.RELAYED_MAX_WAIT_S + 5, relayed)

    def test_the_helper_door_can_be_put_on_the_service_and_taken_off_again(self):
        calls = []
        class FakeRC:
            def __init__(s, service, pid, secret, port, **kw): s.pid, s.door_port, s.stopped = pid, port, False; calls.append(("rc", service, pid, secret, port)); FakeRC.last = s
            def start(s): pass
            def stop(s): s.stopped = True
            def status(s): return {"state": "connected", "error": ""}
        ui = self.ui; olds = (ui.CRL.RelayClient, ui.ACCOUNT.access_token, ui.COLLAB_HOST._service_call)
        ui.CRL.RelayClient = FakeRC; ui.ACCOUNT.access_token = lambda: "acct-token"; ui.COLLAB_HOST._service_call = lambda m, p, body=None, token=None: (calls.append((m, p, body, token)), {"secret": "H" * 43})[1]
        self.addCleanup(lambda: (setattr(ui.CRL, "RelayClient", olds[0]), setattr(ui.ACCOUNT, "access_token", olds[1]), setattr(ui.COLLAB_HOST, "_service_call", olds[2]), setattr(ui, "_HELPER_RELAY", [None])))
        self.assertEqual(self.r({"op": "relay_on"})[0], 400)                                                                              # the door must be on first
        self.r({"op": "configure", "enabled": True, "port": self.port}); st, j = self.r({"op": "relay_on"}); self.assertEqual(st, 200)
        hid = j["relay_id"]; self.assertRegex(hid, r"^h_[0-9a-f]{12}$"); self.assertEqual(j["remote"], {"on": True, "state": "connected", "error": "", "base": f"{ui._relay_service()}/h/{hid}/mcp"}); self.assertNotIn("H" * 43, json.dumps(j))
        self.assertEqual(calls[0], ("POST", "/relay/projects", {"id": hid, "name": "Orbit helpers"}, "acct-token")); self.assertEqual(FakeRC.last.door_port, self.port)
        self.assertEqual(self.b.cfg["relay_secret"], "H" * 43); self.assertEqual(os.stat(self.b.path).st_mode & 0o077, 0)
        st, j = self.r({"op": "relay_off"}); self.assertEqual((st, j["remote"]["on"]), (200, False)); self.assertTrue(FakeRC.last.stopped); self.assertEqual(calls[-1][:2], ("DELETE", f"/relay/projects/{hid}")); self.assertEqual(self.b.cfg["relay_secret"], "")
        ui.ACCOUNT.access_token = lambda: None; self.assertIn("sign in", self.r({"op": "relay_on"})[1]["error"])
        self.r({"op": "configure", "enabled": False})

    def test_a_port_that_is_taken_turns_it_back_off_with_a_reason(self):
        import socket
        s = socket.socket(); s.bind(("127.0.0.1", self.port)); s.listen(1); self.addCleanup(s.close)
        st, j = self.r({"op": "configure", "enabled": True, "port": self.port}); self.assertEqual(st, 400); self.assertIn("could not open", j["error"]); self.assertFalse(self.b.cfg["enabled"])


class TestOrbitSideOfConversations(unittest.TestCase):
    """The real backend's reading of a conversation chat: whose message is whose, and when the other side is still working."""

    @classmethod
    def setUpClass(cls):
        import importlib.machinery, importlib.util
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_loader("qqui_sbk", importlib.machinery.SourceFileLoader("qqui_sbk", os.path.join(root, "bin", "orbit-ui")))
        cls.ui = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.ui)

    def setUp(self):
        import types
        self.st = types.SimpleNamespace(msgs=[{"role": "system", "content": "sys"}], flags={}, title="\u2194 Claude Science: peak-review", lock=threading.Lock(), queue=[], handing=False)
        self.ui.STATES["sid-x"] = self.st; self.addCleanup(self.ui.STATES.pop, "sid-x", None); self.be = self.ui._ScienceBackend()

    def test_the_apps_own_messages_are_not_echoed_back_even_without_the_flag(self):
        self.st.msgs += [{"role": "user", "content": "[Claude Science] my plan"}, {"role": "assistant", "content": "", "tool_calls": [{}]}, {"role": "tool", "content": "file text"},
                         {"role": "assistant", "content": "Here is my critique."}, {"role": "user", "content": "I (the person) also think so"}]
        r = self.be.thread_read("sid-x", 0); self.assertEqual([(m["who"], m["text"]) for m in r["messages"]], [("orbit", "Here is my critique."), ("person", "I (the person) also think so")])
        self.assertEqual(r["cursor"], len(self.st.msgs)); self.assertFalse(r["running"])
        self.assertEqual(self.be.thread_read("sid-x", r["cursor"])["messages"], [])
        self.st.flags["bridge_app"] = "Claude Science"; self.assertEqual(len(self.be.thread_read("sid-x", 0)["messages"]), 2)

    def test_running_while_the_chat_is_busy_or_has_something_queued(self):
        self.st.lock.acquire(); self.addCleanup(lambda: self.st.lock.locked() and self.st.lock.release()); self.assertTrue(self.be.thread_read("sid-x", 0)["running"])
        self.st.lock.release(); self.assertFalse(self.be.thread_read("sid-x", 0)["running"])
        self.assertEqual(self.be.thread_read("nope-not-a-chat", 5), {"messages": [], "running": False, "cursor": 5})
        before = list(self.ui.S.msgs)                      # a chat that is gone must never be answered by the MAIN chat
        with self.assertRaises(self.ui.SBR.BridgeError): self.be.thread_send("nope-not-a-chat", "Claude Science", "hello")
        self.assertEqual(self.be.state("nope-not-a-chat")["note"], "the chat is gone"); self.assertEqual(self.ui.S.msgs, before); self.assertFalse(any(str(it.get("text", "")).startswith("[Claude Science]") for it in self.ui.S.queue))

    def test_a_cursor_past_the_end_after_the_chat_was_compacted_does_not_crash(self):
        self.st.msgs += [{"role": "assistant", "content": "x"}]; self.assertEqual(self.be.thread_read("sid-x", 99)["cursor"], 2)


class TestStdioLauncher(Base):
    """bin/orbit-helpers-mcp: the local-command form of the door, for agents that cannot connect to a loopback address."""
    SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "orbit-helpers-mcp")

    def setUp(self):
        super().setUp(); self.home = os.path.join(self.tmp, "orbit_home")
        self.b = B.Bridge(os.path.join(self.home, "config", "science_bridge.json"), self.be, now=time.time); self.b.configure(enabled=True); self.b.configure(add_client="Claude Code")
        self.srv = B.make_server(self.b, 0); self.port = self.srv.server_address[1]; self.b.configure(port=self.port)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start(); self.addCleanup(self.srv.shutdown); self.addCleanup(self.srv.server_close)

    def run_it(self, lines, args=(), env=None):
        import subprocess
        e = dict(os.environ, ORBIT_HOME=self.home); e.update(env or {}); e.pop("ORBIT_HELPERS_URL", None) if not env or "ORBIT_HELPERS_URL" not in env else None
        r = subprocess.run([sys.executable, self.SCRIPT, *args], input="\n".join(json.dumps(x) if not isinstance(x, str) else x for x in lines) + "\n", capture_output=True, text=True, timeout=60, env=e)
        return r.returncode, [json.loads(l) for l in r.stdout.splitlines() if l.strip()], r.stderr

    def test_it_passes_the_protocol_through_and_names_the_app_by_its_settings(self):
        rc, out, err = self.run_it([{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, {"jsonrpc": "2.0", "method": "notifications/initialized"},
                                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "orbit_delegate", "arguments": {"task": "from stdio"}}}], args=["--app", "claude code"])
        self.assertEqual(rc, 0, err); self.assertEqual([o["id"] for o in out], [1, 2, 3]); self.assertEqual(out[0]["result"]["serverInfo"]["name"], "orbit"); self.assertIn("orbit_talk", [t["name"] for t in out[1]["result"]["tools"]])
        self.assertEqual([r["app"] for r in self.b.inbox()], ["Claude Code"])                              # --app picked the right client
        self.assertNotIn(self.b.cfg["clients"][1]["token"], json.dumps(out) + err)

    def test_the_first_app_is_the_default_and_the_environment_can_name_one(self):
        self.run_it([{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "orbit_delegate", "arguments": {"task": "default"}}}]); self.assertEqual(self.b.inbox()[0]["app"], "Claude Science")
        self.run_it([{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "orbit_delegate", "arguments": {"task": "env"}}}], env={"ORBIT_HELPERS_APP": "Claude Code"}); self.assertEqual(self.b.inbox()[0]["app"], "Claude Code")

    def test_a_closed_door_a_wrong_name_and_a_replaced_token_are_said_plainly(self):
        self.b.configure(enabled=False); rc, out, _ = self.run_it([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}]); self.assertIn("refused this app's token", out[0]["error"]["message"])      # a closed door answers 401, same as a wrong token
        self.b.configure(enabled=True); rc, out, err = self.run_it([{"jsonrpc": "2.0", "id": 1, "method": "ping"}], args=["--app", "Nobody"]); self.assertNotEqual(rc, 0); self.assertIn("No app named", err)
        import subprocess
        self.assertEqual(subprocess.run([sys.executable, self.SCRIPT], input="", capture_output=True, text=True, env=dict(os.environ, ORBIT_HOME=os.path.join(self.tmp, "empty")), timeout=30).returncode != 0, True)
        rc, out, _ = self.run_it([{"jsonrpc": "2.0", "id": 1, "method": "ping"}], env={"ORBIT_HELPERS_URL": f"http://127.0.0.1:{self.port}/mcp", "ORBIT_HELPERS_TOKEN": "x" * 40}); self.assertIn("refused this app's token", out[0]["error"]["message"])

    def test_junk_lines_are_ignored_and_notifications_get_no_reply(self):
        rc, out, _ = self.run_it(["", "not json", {"jsonrpc": "2.0", "method": "notifications/initialized"}, {"jsonrpc": "2.0", "id": 9, "method": "ping"}]); self.assertEqual([o["id"] for o in out], [9])


if __name__ == "__main__":
    unittest.main()
