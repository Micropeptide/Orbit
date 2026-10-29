"""Crew (bin/crew.py): a builder and a reviewer that keep improving a project until stopped.

The loop runs against a fake host (no model, no chats) and a real git repository in a temp folder."""
import json, os, shutil, subprocess, sys, tempfile, threading, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))

import crew as C                         # noqa: E402


def review(score, issues=(), tasks=(), summary="ok"):
    return "I ran the tests and used it.\n\n" + json.dumps({"score": score, "summary": summary, "issues": list(issues), "next_tasks": list(tasks)})


class FakeHost:
    """Scripted chats. `replies[role]` is a list of answers (or dicts); the last one repeats."""
    def __init__(self, replies, existing=()):
        self.replies, self.calls, self.chats, self.notes, self.slept = replies, [], [], [], []
        self.adopted, self.released = [], []
        for sid, role in existing:                       # chats that already exist, named by their role
            self.chats.append({"sid": sid, "title": f"mine · {role}", "model": None, "folder": None, "instructions": ""})

    def create_chat(self, title, model, instructions, folder, effort=None):
        sid = f"chat{len(self.chats) + 1}"
        self.chats.append({"sid": sid, "title": title, "model": model, "folder": folder, "instructions": instructions, "effort": effort})
        return sid

    def turn(self, sid, text, timeout_s, cancel, key=None, settle=False):
        title = next(c for c in self.chats if c["sid"] == sid)["title"]
        role = "builder" if "builder" in title else "reviewer"
        if "BUILDER in a build" in text: role = "builder"          # a chat doing both jobs is told which one this turn is
        elif "REVIEWER in a build" in text: role = "reviewer"
        self.calls.append((role, sid, text))
        self.keys = getattr(self, "keys", []) + [key]
        self.settles = getattr(self, "settles", []) + [(role, settle)]
        q = self.replies[role]
        r = q.pop(0) if len(q) > 1 else q[0]
        if callable(r): r = r(self)
        return r if isinstance(r, dict) else {"answer": r, "tokens": 100}

    def adopt_chat(self, sid, folder, model=None, effort=None):
        self.adopted.append((sid, folder, model, effort))
        return {"cwd": "/before", "autonomy_mode": "ask", "permission_mode": None}

    def release_chat(self, sid, saved): self.released.append((sid, saved))

    def stop_chat(self, sid): pass
    def notify(self, title, message): self.notes.append((title, message))
    def sleep(self, seconds, cancel): self.slept.append(seconds)


def run_until(run, host, done, timeout=15):
    store = {}
    runner = C.Runner(run, host, lambda: store.update(saved=json.loads(json.dumps(run))))
    runner.start()
    end = time.time() + timeout
    while time.time() < end and not done():
        time.sleep(0.02)
    runner.stop_now()
    if run["state"] == "running": run["state"] = "stopped"
    runner.thread.join(5)
    return runner, store


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orbit-crew-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.folder = os.path.join(self.tmp, "proj")

    def run_obj(self, **kw):
        return C.new_run("Demo", "build a thing", self.folder, ["model-a"], ["model-b"], **kw)


class TestParsing(unittest.TestCase):
    def test_json_after_prose(self):
        r = C.parse_review(review(72, [{"severity": "high", "title": "crash", "detail": "d", "fix": "f"}], ["add tests"]))
        self.assertTrue(r["parsed"]); self.assertEqual(r["score"], 72)
        self.assertEqual(r["issues"][0]["title"], "crash"); self.assertEqual(r["next_tasks"], ["add tests"])

    def test_braces_inside_strings_and_a_last_object_wins(self):
        txt = 'first {"score": 10, "summary": "x"} then ' + json.dumps({"score": 88, "summary": "has } and { in it", "issues": []})
        r = C.parse_review(txt)
        self.assertEqual(r["score"], 88); self.assertIn("} and {", r["summary"])

    def test_score_is_clamped_and_strings_become_issues(self):
        r = C.parse_review(json.dumps({"score": 250, "issues": ["flaky test"]}))
        self.assertEqual(r["score"], 100); self.assertEqual(r["issues"][0]["title"], "flaky test")

    def test_a_reviewer_that_forgot_the_json_is_not_lost(self):
        r = C.parse_review("Honestly this is rough. Score: 41/100. The server crashes on empty input.")
        self.assertFalse(r["parsed"]); self.assertEqual(r["score"], 41); self.assertIn("rough", r["summary"])
        self.assertIsNone(C.parse_review("no numbers here")["score"])

    def test_backlog_orders_worst_first_without_repeats(self):
        b = C.merge_backlog([{"severity": "low", "title": "typo", "fix": "fix typo"}, {"severity": "high", "title": "crash", "fix": "guard input"}],
                            ["Guard input", "write docs"])
        self.assertTrue(b[0].startswith("guard input")); self.assertEqual(sum("guard input" in x.lower() for x in b), 1)
        self.assertIn("write docs", b)


class TestPrompts(Base):
    def test_first_round_says_fresh_and_reference_is_read_only_inspiration(self):
        r = self.run_obj(reference="/old/app")
        p = C.build_prompt(r, 1)
        self.assertIn("round 1", p); self.assertIn("/old/app", p); self.assertIn("do not copy", p)
        self.assertIn("CREW_NOTES.md", p); self.assertIn("Never write an API key", p)

    def test_later_rounds_carry_the_review_notes_and_regressions(self):
        r = self.run_obj()
        r["history"] = [{"round": 1, "score": 60, "summary": "meh", "issues": [{"severity": "high", "title": "crash", "fix": "guard"}]}]
        r.update(best=80, best_round=3, backlog=["task one"], notes=["use sqlite"])
        p = C.build_prompt(r, 4)
        for want in ("scored round 1 at 60", "guard", "task one", "use sqlite", "crew-best", "dropped"):
            self.assertIn(want, p)

    def test_standing_orders_reach_builder_and_reviewer_every_round(self):
        r = self.run_obj(); r["pinned"] = ["build the Meta provider", "  "]
        r["history"] = [{"round": 1, "score": 60, "summary": "x", "issues": []}]
        for p in (C.build_prompt(r, 1), C.build_prompt(r, 5)):
            self.assertIn("STANDING ORDERS", p); self.assertIn("1. build the Meta provider", p)
            self.assertNotIn("2.", p.split("STANDING ORDERS")[1].split("\n\n")[0])
        rp = C.review_prompt(r, 5)
        self.assertIn("build the Meta provider", rp); self.assertIn("at most 60", rp)
        r["pinned"] = []
        self.assertNotIn("STANDING ORDERS", C.build_prompt(r, 5)); self.assertNotIn("at most 60", C.review_prompt(r, 5))

    def test_the_reviewer_is_pointed_somewhere_new_when_the_score_stalls(self):
        r = self.run_obj(); r["since_best"] = C.STALL_ROUNDS
        self.assertIn("stopped rising", C.review_prompt(r, 5))
        r["since_best"] = 0
        self.assertNotIn("stopped rising", C.review_prompt(r, 5))
        self.assertIn("Do not edit", C.review_prompt(r, 1))


class TestLoop(Base):
    def test_rounds_alternate_and_everything_is_recorded(self):
        host = FakeHost({"builder": ["Done: v1\nVerified: tests\nRemaining: x"],
                         "reviewer": [review(55, [{"severity": "high", "title": "a", "fix": "fix a"}], ["t1"]), review(70), review(82)]})
        run = self.run_obj()
        run_until(run, host, lambda: run["round"] >= 3)
        self.assertGreaterEqual(run["round"], 3)
        self.assertEqual([h["score"] for h in run["history"][:3]], [55, 70, 82])
        self.assertEqual((run["best"], run["best_round"]), (82, 3))
        roles = [c[0] for c in host.calls[:6]]
        self.assertEqual(roles, ["builder", "reviewer"] * 3)
        self.assertIn("fix a", host.calls[2][2])                      # round 2's brief carries round 1's review
        self.assertGreaterEqual(run["tokens"], 600)
        self.assertTrue(os.path.exists(os.path.join(self.folder, "CREW_REVIEWS.md")))

    def test_each_round_is_checkpointed_in_git_and_the_best_is_tagged(self):
        def build(host):
            open(os.path.join(self.folder, f"f{len(host.calls)}.txt"), "w").write("x")
            return {"answer": "Done: file", "tokens": 1}
        host = FakeHost({"builder": [build], "reviewer": [review(40), review(90), review(60)]})
        run = self.run_obj()
        run_until(run, host, lambda: run["round"] >= 3)
        tags = subprocess.run(["git", "tag"], cwd=self.folder, capture_output=True, text=True).stdout.split()
        self.assertTrue({"crew-round-1", "crew-round-2", "crew-round-3", "crew-best"} <= set(tags))
        best = subprocess.run(["git", "rev-parse", "crew-best"], cwd=self.folder, capture_output=True, text=True).stdout
        r2 = subprocess.run(["git", "rev-parse", "crew-round-2"], cwd=self.folder, capture_output=True, text=True).stdout
        self.assertEqual(best, r2)                                    # round 2 scored 90
        self.assertIn(".env", open(os.path.join(self.folder, ".gitignore")).read())

    def test_it_never_decides_it_is_finished(self):
        host = FakeHost({"builder": ["Done"], "reviewer": [review(100, summary="perfect")]})
        run = self.run_obj()
        run_until(run, host, lambda: run["round"] >= 4)
        self.assertGreaterEqual(run["round"], 4)                      # a perfect score did not end it
        self.assertEqual(run["state"], "stopped")

    def test_failures_wait_and_retry_then_pause_with_a_notice(self):
        host = FakeHost({"builder": [{"failed": "rate limit"}], "reviewer": [review(50)]})
        run = self.run_obj()
        run_until(run, host, lambda: run["state"] == "paused")
        self.assertEqual(run["state"], "paused")
        self.assertIn(f"failed {C.MAX_FAILS} times", run["reason"])
        self.assertEqual(len(host.slept), C.MAX_FAILS - 1)
        self.assertEqual(host.slept[:3], list(C.BACKOFF_S[:3]))
        self.assertTrue(host.notes and "paused" in host.notes[0][0])

    def test_a_failure_then_success_carries_on(self):
        host = FakeHost({"builder": [{"failed": "overloaded"}, {"answer": "Done", "tokens": 5}], "reviewer": [review(60)]})
        run = self.run_obj()
        run_until(run, host, lambda: run["round"] >= 1)
        self.assertEqual(run["round"] >= 1, True)
        self.assertEqual(run["fails"], 0)

    def test_limits_end_the_run(self):
        host = FakeHost({"builder": ["Done"], "reviewer": [review(50)]})
        run = self.run_obj(max_rounds=2)
        run_until(run, host, lambda: run["state"] == "done")
        self.assertEqual((run["state"], run["round"]), ("done", 2))
        self.assertIn("2-round limit", run["reason"])
        run2 = self.run_obj(max_tokens=250); run2["folder"] = os.path.join(self.tmp, "p2")
        host2 = FakeHost({"builder": ["Done"], "reviewer": [review(50)]})
        run_until(run2, host2, lambda: run2["state"] == "done")
        self.assertIn("token limit", run2["reason"])
        run3 = self.run_obj(hours=1); run3["started"] -= 7200
        self.assertIn("1-hour limit", C.limits_hit(run3))

    def test_a_new_builder_session_takes_over_through_the_notes(self):
        host = FakeHost({"builder": ["Done"], "reviewer": [review(50)]})
        run = self.run_obj(rollover=2)
        run_until(run, host, lambda: run["round"] >= 4)
        builders = [c for c in host.chats if "builder" in c["title"]]
        self.assertGreaterEqual(len(builders), 2)                     # rolled over
        first_after = next(c for c in host.calls if c[0] == "builder" and c[1] == builders[1]["sid"])
        self.assertIn("taking over", first_after[2]); self.assertIn("CREW_NOTES.md", first_after[2])
        later = [c for c in host.calls if c[0] == "builder" and c[1] == builders[1]["sid"]]
        if len(later) > 1: self.assertNotIn("taking over", later[1][2])

    def test_the_person_waiting_on_an_approval_is_told(self):
        host = FakeHost({"builder": [{"answer": "Done", "tokens": 1, "attention": "the approval in chat “x” is waiting for you"}],
                         "reviewer": [review(50)]})
        run = self.run_obj()
        run_until(run, host, lambda: bool(host.notes))
        self.assertTrue(any("needs you" in n[0] for n in host.notes))

    def test_users_notes_are_used_once(self):
        host = FakeHost({"builder": ["Done"], "reviewer": [review(50)]})
        run = self.run_obj(); run["notes"] = ["please use sqlite"]
        run_until(run, host, lambda: run["round"] >= 2)
        builds = [c[2] for c in host.calls if c[0] == "builder"]
        self.assertIn("please use sqlite", builds[0])
        self.assertNotIn("please use sqlite", builds[1])
        self.assertEqual(run["notes"], [])

    def test_a_resumed_run_picks_up_in_its_phase(self):
        host = FakeHost({"builder": ["Done"], "reviewer": [review(77)]})
        run = self.run_obj(); run.update(phase="review", round=0)
        run["builders"][0]["sid"] = "x"; run["reviewers"][0]["sid"] = None
        host.chats.append({"sid": "x", "title": "Demo · builder", "model": "m", "folder": self.folder, "instructions": ""})
        C.prepare_folder(run)
        run_until(run, host, lambda: run["round"] >= 1)
        self.assertEqual(host.calls[0][0], "reviewer")                # it did not rebuild round 1


class TestEditsReachTheRunningRunner(Base):
    def test_live_returns_the_runners_own_dict_while_it_is_alive(self):
        class T:                                     # a runner whose thread is running
            def __init__(self, alive): self.alive = alive
            def is_alive(self): return self.alive
        class R:
            def __init__(self, run, alive): self.run, self.thread = run, T(alive)
        mine = self.run_obj(); loaded = json.loads(json.dumps(mine))
        self.assertIs(C.live(loaded, R(mine, True)), mine)           # edits must land where the runner will save from
        self.assertIs(C.live(loaded, R(mine, False)), loaded)        # a stopped runner: the saved copy is the truth
        self.assertIs(C.live(loaded, None), loaded)
        other = self.run_obj(); other["id"] = "zzzz"
        self.assertIs(C.live(loaded, R(other, True)), loaded)        # never another run's dict


class TestStall(unittest.TestCase):
    def test_a_moving_answer_is_never_stalled_and_a_frozen_one_is(self):
        s = C.Stall(limit=100)
        self.assertFalse(s.seen((1, 10), 0))
        self.assertFalse(s.seen((1, 10), 99))
        self.assertFalse(s.seen((1, 11), 150))        # it wrote something: the clock starts again
        self.assertFalse(s.seen((1, 11), 249))
        self.assertTrue(s.seen((1, 11), 250))
        self.assertFalse(s.seen((2, 11), 251))


class TestEditing(Base):
    def test_a_new_brief_reaches_the_builder_and_the_folder(self):
        run = self.run_obj(); C.prepare_folder(run)
        note = C.edit_run(run, brief="Build a different thing, broader.", criteria="Judged on benchmarks.", title="BenchLight")
        self.assertEqual(run["brief"], "Build a different thing, broader."); self.assertEqual(run["title"], "BenchLight")
        self.assertIn("CREW_BRIEF.md", note); self.assertIn(note, run["notes"])
        text = open(os.path.join(self.folder, "CREW_BRIEF.md")).read()
        self.assertIn("Build a different thing", text); self.assertIn("Judged on benchmarks", text)
        self.assertIn("Build a different thing", C.build_prompt(run, 2, run["builders"][0]))
        self.assertIn("Build a different thing", C.review_prompt(run, 2))

    def test_nothing_to_change_is_nothing(self):
        run = self.run_obj()
        self.assertEqual(C.edit_run(run, brief="  ", criteria=None), "")
        self.assertEqual(run["brief"], "build a thing")

    def test_a_long_specification_fits(self):
        run = self.run_obj(); C.edit_run(run, brief="x" * 20000)
        self.assertEqual(len(run["brief"]), C.BRIEF_MAX)


class TestBuilderSettles(Base):
    def test_only_the_builder_waits_for_its_background_work(self):
        host = FakeHost({"builder": ["Done"], "reviewer": [review(50)]})
        run = self.run_obj()
        run_until(run, host, lambda: run["round"] >= 1)
        self.assertIn(("builder", True), host.settles); self.assertIn(("reviewer", False), host.settles)


class TestRoundsAreSmall(Base):
    def test_a_round_is_one_increment_not_the_whole_brief(self):
        p = C.build_prompt(self.run_obj(), 1)
        self.assertIn("one focused increment", p); self.assertIn("absolute paths", p)

    def test_what_to_put_back_is_saved_the_moment_a_chat_is_adopted(self):
        host = FakeHost({"builder": ["Done"], "reviewer": [review(50)]}, existing=[("mine1", "builder")])
        run = C.new_run("Demo", "x", self.folder, [{"sid": "mine1"}], [{"model": "m"}])
        saved = []
        C.ensure_chat(run, host, run["builders"][0], "builder", lambda: saved.append(dict(run["saved_prefs"])))
        self.assertEqual(saved and list(saved[0]), ["mine1"])


class TestModelAndEffortChoice(Base):
    def test_party_carries_a_model_and_effort_for_a_designated_chat(self):
        p = C.party({"sid": "mine1", "model": "m-x", "effort": "high"})
        self.assertEqual((p["sid"], p["model"], p["effort"]), ("mine1", "m-x", "high"))
        self.assertTrue(p["existing"])

    def test_a_designated_chat_is_put_on_the_chosen_model_and_effort(self):
        host = FakeHost({"builder": ["Done"], "reviewer": [review(50)]}, existing=[("mine1", "builder")])
        run = C.new_run("Demo", "x", self.folder, [{"sid": "mine1", "model": "m-x", "effort": "high"}], [{"model": "m"}])
        C.ensure_chat(run, host, run["builders"][0], "builder")
        self.assertEqual(host.adopted[0][2:], ("m-x", "high"))          # the model and effort you picked

    def test_a_new_chat_is_made_with_the_chosen_model_and_effort(self):
        host = FakeHost({"builder": ["Done"], "reviewer": [review(50)]})
        run = C.new_run("Demo", "x", self.folder, [{"model": "m-x", "effort": "xhigh"}], [{"model": "m"}])
        C.ensure_chat(run, host, run["builders"][0], "builder")
        self.assertEqual((host.chats[0]["model"], host.chats[0]["effort"]), ("m-x", "xhigh"))

    def test_no_choice_means_the_chat_works_as_it_is(self):
        host = FakeHost({"builder": ["Done"], "reviewer": [review(50)]}, existing=[("mine1", "builder")])
        run = C.new_run("Demo", "x", self.folder, [{"sid": "mine1"}], [{"model": "m"}])
        C.ensure_chat(run, host, run["builders"][0], "builder")
        self.assertEqual(host.adopted[0][2:], (None, None))            # no model or effort override


class TestKeys(Base):
    def test_every_message_carries_a_key_for_its_round_and_phase(self):
        host = FakeHost({"builder": ["Done"], "reviewer": [review(50), review(60)]})
        run = C.new_run("Demo", "x", self.folder, ["a"], ["r1", "r2"])
        run_until(run, host, lambda: run["round"] >= 1)
        self.assertEqual(host.keys[:3], [f"{run['id']}:1:build", f"{run['id']}:1:review:0", f"{run['id']}:1:review:1"])

    def test_a_failed_turns_reason_says_what_the_chat_said(self):
        host = FakeHost({"builder": [{"failed": "setup: Muse Code is not signed in"}], "reviewer": [review(50)]})
        run = self.run_obj()
        run_until(run, host, lambda: run["state"] == "paused")
        self.assertIn("not signed in", run["reason"])


class TestWhoTheChatsAre(Base):
    def test_a_chat_you_designate_is_used_not_replaced(self):
        host = FakeHost({"builder": ["Done"], "reviewer": [review(60)]}, existing=[("mine1", "builder"), ("mine2", "reviewer")])
        run = C.new_run("Demo", "build a thing", self.folder, [{"sid": "mine1"}], [{"sid": "mine2"}])
        run_until(run, host, lambda: run["round"] >= 2)
        self.assertEqual(len(host.chats), 2)                                   # none was made
        self.assertEqual({c[1] for c in host.calls}, {"mine1", "mine2"})
        self.assertEqual(sorted(a[0] for a in host.adopted), ["mine1", "mine2"])
        self.assertEqual(host.adopted[0][1], self.folder)
        self.assertEqual(set(run["saved_prefs"]), {"mine1", "mine2"})          # kept, to put back

    def test_stopping_puts_a_designated_chats_settings_back(self):
        host = FakeHost({"builder": ["Done"], "reviewer": [review(60)]}, existing=[("mine1", "builder")])
        run = C.new_run("Demo", "x", self.folder, [{"sid": "mine1"}], [{"model": "m"}])
        run_until(run, host, lambda: run["round"] >= 1)
        C.release_chats(run, host)
        self.assertEqual(host.released, [("mine1", {"cwd": "/before", "autonomy_mode": "ask", "permission_mode": None})])
        self.assertEqual(run["saved_prefs"], {})

    def test_reaching_a_limit_releases_them_too(self):
        host = FakeHost({"builder": ["Done"], "reviewer": [review(60)]}, existing=[("mine1", "builder")])
        run = C.new_run("Demo", "x", self.folder, [{"sid": "mine1"}], [{"model": "m"}], max_rounds=1)
        run_until(run, host, lambda: run["state"] == "done")
        self.assertEqual(run["state"], "done"); self.assertTrue(host.released)

    def test_one_chat_builds_and_reviews_itself(self):
        host = FakeHost({"builder": ["Done"], "reviewer": [review(66)]}, existing=[("solo", "builder")])
        run = C.new_run("Demo", "x", self.folder, [{"sid": "solo"}], [])
        run_until(run, host, lambda: run["round"] >= 2)
        self.assertEqual(len(host.chats), 1)
        self.assertEqual({c[1] for c in host.calls}, {"solo"})
        self.assertEqual([c[0] for c in host.calls[:4]], ["builder", "reviewer", "builder", "reviewer"])
        self.assertIn("You built this project earlier in this chat", host.calls[1][2])
        self.assertEqual([h["score"] for h in run["history"][:2]], [66, 66])
        self.assertEqual(len(host.adopted), 1)                                   # adopted once, not once per job

    def test_the_same_chat_named_for_both_roles_works_too(self):
        host = FakeHost({"builder": ["Done"], "reviewer": [review(50)]}, existing=[("solo", "builder")])
        run = C.new_run("Demo", "x", self.folder, [{"sid": "solo"}], [{"sid": "solo"}])
        run_until(run, host, lambda: run["round"] >= 1)
        self.assertEqual(len(host.adopted), 1)

    def test_several_builders_take_turns(self):
        host = FakeHost({"builder": ["Done"], "reviewer": [review(50)]})
        run = C.new_run("Demo", "x", self.folder, ["model-a", "model-b"], ["model-r"])
        run_until(run, host, lambda: run["round"] >= 4)
        builder_chats = [c[1] for c in host.calls if c[0] == "builder"][:4]
        self.assertEqual(builder_chats[0], builder_chats[2]); self.assertEqual(builder_chats[1], builder_chats[3])
        self.assertNotEqual(builder_chats[0], builder_chats[1])
        # the second builder is new to the project: it reads the notes first
        second = next(c for c in host.calls if c[0] == "builder" and c[1] == builder_chats[1])
        self.assertIn("taking over", second[2])
        models = {c["sid"]: c["model"] for c in host.chats}
        self.assertEqual([models[builder_chats[0]], models[builder_chats[1]]], ["model-a", "model-b"])

    def test_several_reviewers_each_score_and_the_mean_counts(self):
        host = FakeHost({"builder": ["Done"], "reviewer": [review(60, [{"severity": "high", "title": "crash", "fix": "guard"}], ["t1"]),
                                                            review(80, [{"severity": "low", "title": "crash", "fix": "guard"}], ["t2"])]})
        run = C.new_run("Demo", "x", self.folder, ["model-a"], ["model-r1", "model-r2"])
        run_until(run, host, lambda: run["round"] >= 1)
        first = run["history"][0]
        self.assertEqual(first["score"], 70); self.assertEqual(first["each"], [60, 80])
        self.assertEqual([i["title"] for i in first["issues"]], ["crash"])           # the same issue is listed once
        self.assertEqual(first["next_tasks"], ["t1", "t2"])
        self.assertIn("Reviewer 1 (60)", first["summary"])
        reviewers = [c for c in host.calls if c[0] == "reviewer"][:2]
        self.assertNotEqual(reviewers[0][1], reviewers[1][1])
        self.assertIn("Look hard at one thing", reviewers[1][2])                     # the second one is pointed somewhere different

    def test_a_designated_chat_is_never_rolled_over(self):
        host = FakeHost({"builder": ["Done"], "reviewer": [review(50)]}, existing=[("mine1", "builder")])
        run = C.new_run("Demo", "x", self.folder, [{"sid": "mine1"}], [{"model": "m"}], rollover=2)
        run_until(run, host, lambda: run["round"] >= 4)
        self.assertEqual({c[1] for c in host.calls if c[0] == "builder"}, {"mine1"})

    def test_a_crew_needs_a_builder(self):
        with self.assertRaises(ValueError): C.new_run("x", "y", self.folder, [], [])
        self.assertEqual(C.party("some-model")["model"], "some-model")
        self.assertTrue(C.party({"sid": "c1"})["existing"])


class TestStore(Base):
    def test_a_run_saved_by_the_older_one_builder_one_reviewer_shape_still_runs(self):
        root = self.tmp; os.makedirs(os.path.join(root, "config"))
        old = {"id": "abc", "title": "rebuilt", "state": "running", "phase": "review", "round": 4, "folder": self.folder,
               "builder": {"model": "muse-cli:muse-spark-1.3", "sid": "b1"}, "reviewer": {"model": "harness:claude/opus", "sid": "r1"},
               "builder_rounds": 3, "handover": True, "history": [], "backlog": [], "notes": [], "brief": "rebuild it",
               "criteria": "judged", "reference": "", "started": time.time(), "limits": {}, "rollover": 10, "tokens": 0, "best": None,
               "best_round": 0, "since_best": 0, "fails": 0}
        json.dump({"abc": old}, open(os.path.join(root, "config", "crews.json"), "w"))
        run = C.load(root)["abc"]
        self.assertEqual(run["builders"][0]["sid"], "b1"); self.assertEqual(run["builders"][0]["rounds"], 3)
        self.assertTrue(run["builders"][0]["handover"]); self.assertFalse(run["builders"][0]["existing"])
        self.assertEqual(run["reviewers"][0]["sid"], "r1")
        self.assertNotIn("builder", run); self.assertEqual(run["saved_prefs"], {})
        host = FakeHost({"builder": ["Done"], "reviewer": [review(80)]}, existing=[("b1", "builder"), ("r1", "reviewer")])
        C.prepare_folder(run)
        run_until(run, host, lambda: run["round"] >= 5)
        self.assertGreaterEqual(run["round"], 5)
        self.assertEqual(host.calls[0][0], "reviewer")                      # it was in the middle of a review, and carries on there
        self.assertEqual(len(host.chats), 2)                                # no new chats

    def test_runs_survive_a_restart_on_disk(self):
        root = self.tmp; os.makedirs(os.path.join(root, "config"))
        run = self.run_obj(); C.save(root, {run["id"]: run})
        back = C.load(root)
        self.assertEqual(back[run["id"]]["title"], "Demo")
        self.assertEqual(C.load(os.path.join(root, "nowhere")), {})

    def test_public_view_drops_long_texts(self):
        run = self.run_obj(); run["history"] = [{"round": 1, "score": 5, "builder_text": "x" * 500}] * 40
        pub = C.public(run)
        self.assertEqual(len(pub["history"]), 30); self.assertNotIn("builder_text", pub["history"][0])


if __name__ == "__main__":
    unittest.main()
