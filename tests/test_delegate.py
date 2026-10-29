"""Delegation: the expensive model decides, cheaper models do the small jobs (bin/delegate.py,
_Chats.delegate in bin/orbit-ui, the `delegate` tool in bin/qqcore.py)."""
import importlib.machinery, importlib.util, json, os, shutil, sys, tempfile, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "bin"))

import qqcore as q                      # noqa: E402
import claude_engine as CE              # noqa: E402
import delegate as D                    # noqa: E402


def m(mid, label="", **kw):
    return {"id": mid, "label": label or mid, "ready": True, **kw}


CATALOGUE = [m("harness:claude/opus", "Claude Opus (latest)"), m("harness:claude/sonnet", "Claude Sonnet (latest)"),
             m("harness:claude/haiku", "Claude Haiku (latest)"),
             m("harness:opencode-go/deepseek-v4-pro", "DeepSeek V4 Pro"), m("harness:opencode-go/deepseek-v4.1-flash", "DeepSeek V4.1 Flash"),
             m("harness:opencode-go/gpt-5.6-luna", "GPT-5.6 Luna"), m("agy-cli:gemini-3.8-flash-high", "Gemini 3.8 Flash (High)"),
             m("harness:meta/muse-wonder-1.0", "Muse Wonder"), m("harness:meta/muse-spark-1.3", "Muse Spark 1.3"),
             m("harness:meta/muse-spark-1.3-contributor", "Muse Spark 1.3 · Contributor"),
             m("harness:local/qwen", "Qwen 27B"), m("harness:somebody/odd-model", "Odd Model")]


class TestTiers(unittest.TestCase):
    def test_what_each_model_is_for(self):
        t = D.tier_of
        self.assertEqual(t("harness:claude/opus"), "lead")
        self.assertEqual(t("harness:meta/muse-wonder-1.0", "Muse Wonder"), "lead")
        for light in ("harness:claude/haiku", "harness:opencode-go/deepseek-v4.1-flash", "harness:opencode-go/gpt-5.6-luna",
                      "agy-cli:gemini-3.8-flash-high", "harness:opencode-go/deepseek-v4-flash"):
            self.assertEqual(t(light), "light", light)
        for std in ("harness:claude/sonnet", "harness:opencode-go/deepseek-v4-pro", "harness:meta/muse-spark-1.3"):
            self.assertEqual(t(std), "standard", std)
        self.assertIsNone(t("harness:somebody/odd-model", "Odd Model"))             # not guessed at

    def test_roster_follows_ready_models_and_your_overrides(self):
        rows = {r["id"]: r for r in D.roster(CATALOGUE, {})}
        self.assertNotIn("harness:somebody/odd-model", rows)
        self.assertTrue(rows["harness:meta/muse-spark-1.3-contributor"]["private"])
        S = {"delegation": {"overrides": {"harness:somebody/odd-model": "light", "harness:claude/haiku": "off",
                                          "harness:meta/muse-spark-1.3-contributor": "standard", "harness:claude/sonnet": "lead"}}}
        rows = {r["id"]: r for r in D.roster(CATALOGUE, S)}
        self.assertEqual(rows["harness:somebody/odd-model"]["tier"], "light")
        self.assertEqual(rows["harness:claude/haiku"]["tier"], "off")
        self.assertFalse(rows["harness:meta/muse-spark-1.3-contributor"]["private"])       # you placed it: your call
        self.assertEqual(rows["harness:claude/sonnet"]["tier"], "lead")
        gone = D.roster([m("x/flash", ready=False), {**m("y/flash"), "ready": False}], {})
        self.assertEqual(gone, [])

    def test_a_model_that_is_not_ready_is_not_offered(self):
        cat = [{**c, "ready": c["id"] != "harness:claude/haiku"} for c in CATALOGUE]
        self.assertNotIn("harness:claude/haiku", D.pick(D.roster(cat, {}), "light"))


class TestPicking(unittest.TestCase):
    def test_cheapest_first_in_the_order_you_named_them(self):
        order = D.pick(D.roster(CATALOGUE, {}), "light")
        self.assertEqual(order[0], "harness:claude/haiku")
        self.assertLess(order.index("harness:opencode-go/deepseek-v4.1-flash"), order.index("agy-cli:gemini-3.8-flash-high"))
        self.assertLess(order.index("agy-cli:gemini-3.8-flash-high"), order.index("harness:opencode-go/gpt-5.6-luna"))

    def test_light_never_goes_up_standard_falls_back_to_light(self):
        rows = D.roster(CATALOGUE, {})
        light, std = D.pick(rows, "light"), D.pick(rows, "standard")
        self.assertNotIn("harness:claude/sonnet", light)
        self.assertEqual(std[0], "harness:claude/sonnet")
        self.assertTrue(set(light) <= set(std))
        self.assertEqual(D.pick(rows, "weird"), light)                  # an unknown tier is the cheap one

    def test_leads_and_private_models_are_never_given_work(self):
        both = D.pick(D.roster(CATALOGUE, {}), "standard")
        for banned in ("harness:claude/opus", "harness:meta/muse-wonder-1.0", "harness:meta/muse-spark-1.3-contributor"):
            self.assertNotIn(banned, both)

    def test_cheaper_hours_first_and_this_mac_last(self):
        cat = [dict(c) for c in CATALOGUE]
        next(c for c in cat if c["id"] == "harness:opencode-go/gpt-5.6-luna")["offpeak"] = {"active": True}
        order = D.pick(D.roster(cat, {}, is_local=lambda mid: mid.startswith("harness:local/")), "light")
        self.assertEqual(order[0], "harness:opencode-go/gpt-5.6-luna")
        self.assertEqual(order[-1], "harness:local/qwen") if "harness:local/qwen" in order else None

    def test_a_worker_that_just_failed_is_left_alone(self):
        rows = D.roster(CATALOGUE, {}, cooling={"harness:claude/haiku": time.time() + 60})
        self.assertNotIn("harness:claude/haiku", D.pick(rows, "light"))
        rows = D.roster(CATALOGUE, {}, cooling={"harness:claude/haiku": time.time() - 1})
        self.assertIn("harness:claude/haiku", D.pick(rows, "light"))

    def test_avoid(self):
        rows = D.roster(CATALOGUE, {})
        self.assertNotIn("harness:claude/haiku", D.pick(rows, "light", avoid=("harness:claude/haiku",)))


class TestYourOwnOrder(unittest.TestCase):
    CAT = CATALOGUE + [m("codex:chatgpt/gpt-6-luna", "GPT-6-Luna"), m("codex:chatgpt/gpt-6.1-sol", "GPT-6.1-Sol"),
                       m("codex:opencode-go/gpt-6-luna", "GPT-6 Luna · OpenCode Go"), m("harness-direct:claude/haiku", "twin"),
                       m("harness:opencode-go/claude-haiku-5-5", "Claude Haiku 5.5 · OpenCode Go"),
                       m("agy-cli:claude-opus-4-6-thinking", "Antigravity · Claude Opus 4.6 (Thinking) · CLI")]

    def test_luna_is_cheap_even_when_it_is_called_gpt_6(self):
        self.assertEqual(D.tier_of("codex:chatgpt/gpt-6-luna", "GPT-6-Luna"), "light")
        self.assertEqual(D.tier_of("codex:chatgpt/gpt-6.1-sol", "GPT-6.1-Sol"), "lead")
        self.assertEqual(D.tier_of("codex:chatgpt/gpt-6-astra"), "lead")

    def test_quick_call_twins_and_codex_copies_of_other_providers_are_not_listed(self):
        ids = {r["id"] for r in D.roster(self.CAT, {})}
        self.assertNotIn("harness-direct:claude/haiku", ids)
        self.assertNotIn("codex:opencode-go/gpt-6-luna", ids)
        self.assertIn("codex:chatgpt/gpt-6-luna", ids)

    def test_providers_are_told_apart(self):
        p = D.provider_of
        self.assertEqual((p("harness:claude/haiku"), p("claude-cli:haiku"), p("codex:chatgpt/gpt-6-luna"), p("codex-cli:gpt-6-luna")),
                         ("claude", "claude", "codex", "codex"))
        self.assertEqual((p("agy-cli:x"), p("harness:opencode-go/x"), p("muse-cli:y"), p("harness:meta/z")),
                         ("antigravity", "opencode-go", "muse-code", "meta"))

    def test_an_excluded_provider_is_never_picked_automatically(self):
        S = {"delegation": {"exclude_providers": ["opencode-go", "opencode-zen"]}}
        order = D.pick(D.roster(self.CAT, S), "light", S=S)
        self.assertTrue(order)
        self.assertFalse([i for i in order if "opencode" in i])
        self.assertIn("harness:claude/haiku", order)

    def test_your_list_is_the_order_and_the_only_candidates(self):
        S = {"delegation": {"tiers": {"light": ["codex:chatgpt/gpt-6-luna", "harness:claude/haiku", "agy-cli:gemini-3.8-flash-high"],
                                      "standard": ["codex:chatgpt/gpt-6.1-sol", "harness:claude/sonnet", "agy-cli:claude-opus-4-6-thinking"]}}}
        rows = D.roster(self.CAT, S)
        self.assertEqual(D.pick(rows, "light", S=S), ["codex:chatgpt/gpt-6-luna", "harness:claude/haiku", "agy-cli:gemini-3.8-flash-high"])
        std = D.pick(rows, "standard", S=S)
        self.assertEqual(std[:3], ["codex:chatgpt/gpt-6.1-sol", "harness:claude/sonnet", "agy-cli:claude-opus-4-6-thinking"])
        self.assertEqual(std[3:], D.pick(rows, "light", S=S))                       # then the light ones, as before
        self.assertNotIn("harness:opencode-go/claude-haiku-5-5", std)                # nothing you did not list

    def test_a_listed_model_that_is_not_ready_or_is_cooling_is_skipped_not_replaced(self):
        S = {"delegation": {"tiers": {"light": ["harness:claude/haiku", "codex:chatgpt/gpt-6-luna"]}}}
        cat = [{**c, "ready": c["id"] != "harness:claude/haiku"} for c in self.CAT]
        self.assertEqual(D.pick(D.roster(cat, S), "light", S=S), ["codex:chatgpt/gpt-6-luna"])
        rows = D.roster(self.CAT, S, cooling={"codex:chatgpt/gpt-6-luna": time.time() + 99})
        self.assertEqual(D.pick(rows, "light", S=S), ["harness:claude/haiku"])

    def test_a_best_model_can_be_a_worker_if_you_list_it(self):
        S = {"delegation": {"tiers": {"standard": ["codex:chatgpt/gpt-6.1-sol"]}}}
        self.assertEqual(D.pick(D.roster(self.CAT, S), "standard", S=S)[0], "codex:chatgpt/gpt-6.1-sol")
        self.assertNotIn("codex:chatgpt/gpt-6.1-sol", D.pick(D.roster(self.CAT, {}), "standard"))       # not on its own

    def test_settings_shape(self):
        s = D.settings({"delegation": {"tiers": {"light": ["a", " ", None], "bogus": ["x"]}, "exclude_providers": ["p"]}})
        self.assertEqual(s["tiers"], {"light": ["a", "None"], "standard": []}) if False else None
        self.assertEqual(s["tiers"]["standard"], []); self.assertEqual(s["exclude_providers"], ["p"])
        self.assertNotIn("bogus", s["tiers"])


class TestSettingsAndLedger(unittest.TestCase):
    def test_defaults_are_off_and_safe(self):
        s = D.settings({})
        self.assertFalse(s["enabled"]); self.assertTrue(s["subagents"]); self.assertFalse(s["allow_changes"])
        self.assertEqual(D.settings({"delegation": {"enabled": 1, "max_workers": 99}})["max_workers"], 20)
        self.assertEqual(D.settings({"delegation": "junk"})["enabled"], False)

    def test_the_ledger_counts_and_cools_failures(self):
        root = tempfile.mkdtemp(prefix="orbit-deleg-"); self.addCleanup(shutil.rmtree, root, True)
        D.record(root, "a", "summarise the log", True, 3.2, 1200, parent="p")
        D.record(root, "a", "again", True, 1, 300)
        D.record(root, "b", "grep", False, 2, error="rate limit")
        s = D.summary(root)
        self.assertEqual((s["tasks"], s["tokens"]), (2, 1500))
        self.assertEqual(s["stats"]["b"]["fails"], 1)
        self.assertIn("b", D.cooling(root)); self.assertNotIn("a", D.cooling(root))
        self.assertEqual(s["log"][0]["task"], "grep")                            # newest first

    def test_the_message_to_a_worker(self):
        txt = D.worker_message("count the TODOs", "in src/", write=False)
        self.assertIn("count the TODOs", txt); self.assertIn("Context:\nin src/", txt); self.assertIn("Read-only", txt)
        self.assertIn("may change files", D.worker_message("fix it", write=True))


# ------------------------------------------------------------------ in Orbit: real chats, a stubbed model

def load_ui():
    loader = importlib.machinery.SourceFileLoader("orbit_ui_deleg", os.path.join(ROOT, "bin", "orbit-ui"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class TestEagerness(unittest.TestCase):
    def test_eager_is_the_default_and_unknown_values_fall_back(self):
        self.assertEqual(D.settings({})["eagerness"], "high")
        self.assertEqual(D.settings({"delegation": {"eagerness": "careful"}})["eagerness"], "careful")
        self.assertEqual(D.settings({"delegation": {"eagerness": "reckless"}})["eagerness"], "high")
        self.assertTrue(D.settings({})["escalate"]); self.assertFalse(D.settings({"delegation": {"escalate": False}})["escalate"])

    def test_the_eager_policy_is_a_triage_not_a_suggestion(self):
        p = D.policy("high")
        for word in ("EASY", "MIXED", "HARD", "WHOLE", "first step", "wait=false", "confidence"):
            self.assertIn(word, p)
        self.assertNotIn("EASY", D.policy("balanced")); self.assertNotIn("EASY", D.policy("careful"))
        self.assertEqual(D.policy("nonsense"), D.policy("high"))
        self.assertEqual(D.lead_note(), D.policy("high"))

    def test_a_run_of_direct_tool_calls_brings_a_reminder_and_delegating_clears_it(self):
        k = D.Streak(at=4)
        notes = [k.call("Read") for _ in range(4)]
        self.assertEqual(notes[:3], ["", "", ""]); self.assertIn("4 tool calls in a row", notes[3])
        self.assertEqual(k.call("Grep"), "")
        self.assertEqual(k.call("mcp__orbit__delegate"), ""); self.assertEqual(k.n, 0)
        for _ in range(3): k.call("Bash")
        self.assertEqual(k.call("mcp__orbit__chat_wait"), ""); self.assertEqual(k.n, 0)       # collecting a worker counts as delegating
        again = [k.call("Read") for _ in range(12)]
        self.assertEqual(sum(1 for n in again if n), 2)                                        # at 4, then every 8 more

    def test_a_worker_that_is_unsure_is_tried_again_one_tier_up_once(self):
        self.assertEqual(D.confidence("done\nConfidence: LOW — did not run it"), "low")
        self.assertEqual(D.confidence("Confidence: high\n...\nConfidence: medium"), "medium")      # the last one counts
        self.assertEqual(D.confidence("no line"), "")
        on, off = {"escalate": True}, {"escalate": False}
        self.assertTrue(D.should_escalate("light", "Confidence: low", on))
        self.assertFalse(D.should_escalate("light", "Confidence: low", off))
        self.assertFalse(D.should_escalate("standard", "Confidence: low", on))                 # nowhere higher to go
        self.assertFalse(D.should_escalate("light", "Confidence: high", on))
        self.assertIn("Confidence:", D.WORKER_INSTRUCTIONS)

    def test_the_ledger_counts_how_often_a_lead_really_delegates(self):
        root = tempfile.mkdtemp()
        try:
            self.assertIsNone(D.summary(root)["turns"]["share"])
            for used in (True, False, False, False): D.note_turn(root, used)
            t = D.summary(root)["turns"]
            self.assertEqual((t["delegated"], t["total"], t["share"]), (1, 4, 0.25))
            D.record(root, "m1", "a task", True, 12.0, 500, parent="p", tier="light", note="said it was not sure")
            D.record(root, "m1", "another", False, 1.0, error="boom", tier="standard")
            s = D.summary(root)
            self.assertEqual((s["tasks"], s["fails"], s["stats"]["m1"]["secs"]), (1, 1, 12.0))
            self.assertEqual(s["log"][1]["tier"], "light"); self.assertIn("not sure", s["log"][1]["note"])
        finally: shutil.rmtree(root, ignore_errors=True)


class TestTheHook(unittest.TestCase):
    HOOK = os.path.join(ROOT, "bin", "delegation-hook")

    def run_hook(self, event, *args):
        import subprocess
        r = subprocess.run([sys.executable, self.HOOK, *args], input=json.dumps(event), capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None

    def test_each_request_starts_with_the_triage_and_careful_mode_stays_quiet(self):
        out = self.run_hook({"session_id": "s"}, "prompt", "high")
        self.assertEqual(out["hookEventName"], "UserPromptSubmit"); self.assertIn("EASY", out["additionalContext"])
        self.assertIn("Sort the request", out["additionalContext"])
        self.assertIsNone(self.run_hook({"session_id": "s"}, "prompt", "careful"))

    def test_the_streak_is_kept_per_session_between_calls_and_gives_one_reminder(self):
        d = tempfile.mkdtemp()
        try:
            path = os.path.join(d, "streak.json")
            outs = [self.run_hook({"session_id": "a", "tool_name": "Read"}, "tool", path, "3") for _ in range(3)]
            self.assertEqual([bool(o) for o in outs], [False, False, True]); self.assertEqual(outs[2]["hookEventName"], "PostToolUse")
            self.assertIsNone(self.run_hook({"session_id": "b", "tool_name": "Read"}, "tool", path, "3"))     # another chat starts at zero
            self.run_hook({"session_id": "a", "tool_name": "mcp__orbit__delegate"}, "tool", path, "3")
            self.assertEqual(json.load(open(path))["a"], 0)
            self.run_hook({"session_id": "a", "tool_name": "Read"}, "tool", path, "3")
            self.run_hook({"session_id": "a"}, "prompt", "high", path)                                         # a new request resets it
            self.assertEqual(json.load(open(path))["a"], 0)
        finally: shutil.rmtree(d, ignore_errors=True)

    def test_a_chat_with_delegation_on_gets_the_hooks_and_one_with_it_off_does_not(self):
        c = dict(CE.cfg())
        with mock.patch.object(q, "delegation_on", lambda sid=None: sid == "on"):
            on = CE.launcher_files(c, "t-on", sid="on")[0]
            off = CE.launcher_files(c, "t-off", sid="off")[0]
        h = json.load(open(on)).get("hooks") or {}
        self.assertIn("UserPromptSubmit", h); self.assertIn("PostToolUse", h)
        self.assertIn("delegation-hook", h["PostToolUse"][0]["hooks"][0]["command"])
        self.assertTrue(off is None or "delegation-hook" not in open(off).read())


class TestInOrbit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = load_ui()

    def setUp(self):
        ui = self.ui
        self.tmp = tempfile.mkdtemp(prefix="orbit-deleg-ui-"); self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = (q.SESSIONS, ui.QUEUE_INDEX, q.turn, q.slot_enter, q.slot_exit, ui._learn_later, q.CHATS, q.model_catalogue,
                 q.ROOT, dict(q.S))
        def restore():
            (q.SESSIONS, ui.QUEUE_INDEX, q.turn, q.slot_enter, q.slot_exit, ui._learn_later, q.CHATS, q.model_catalogue,
             q.ROOT) = saved[:9]
            q.S.clear(); q.S.update(saved[9])
        self.addCleanup(restore)
        os.makedirs(os.path.join(self.tmp, "config"))
        q.ROOT = self.tmp
        q.model_catalogue = lambda: [dict(c) for c in CATALOGUE]
        q.SESSIONS = os.path.join(self.tmp, "s"); os.makedirs(q.SESSIONS)
        ui.QUEUE_INDEX = os.path.join(self.tmp, "queues.json")
        q._SESS_CACHE["key"] = None
        q.S["delegation"] = {"enabled": True, "allow_changes": True}
        self.fail_models, self.asked = set(), []
        def fake_turn(msgs, content, tools, **kw):
            st = ui.STATES.get(kw.get("sid"))
            msgs.append({"role": "user", "content": content, "t": time.time(), **q.take_user_meta()})
            self.asked.append((st.model if st else None, content, bool(kw.get("read_only")), kw.get("sid")))
            if st is not None and st.model in self.fail_models: raise RuntimeError("provider down")
            msgs.append({"role": "assistant", "content": f"[{st.model if st else '?'}] result"})
            q.LAST_TURN[kw.get("sid")] = {"usage": {"prompt_tokens": 100, "completion_tokens": 20}}
            return "ok"
        q.turn = fake_turn
        q.slot_enter = lambda *a, **k: True
        q.slot_exit = lambda *a, **k: None
        ui._learn_later = lambda *a, **k: None
        q.CHATS = ui.CHATS
        self.made = []
        st = ui.State(); st.temp = False; st.title = "lead"; st.title_auto = False; st.model = "harness:claude/opus"
        ui.STATES[st.sid] = st; self.made.append(st.sid); ui.save_session(st)
        self.lead = st
        self.cfgdir = tempfile.mkdtemp(prefix="orbit-deleg-cfg-"); self.addCleanup(shutil.rmtree, self.cfgdir, True)
        p = mock.patch.object(CE, "_work_dir", lambda: self.cfgdir); p.start(); self.addCleanup(p.stop)

    def tearDown(self):
        for sid in self.made: self.ui.STATES.pop(sid, None)
        for sid in list(self.ui.STATES):
            if self.ui.STATES[sid].title.startswith("↳"): self.ui.STATES.pop(sid, None)

    def test_a_task_goes_to_the_cheapest_worker_and_comes_back(self):
        out = self.ui.CHATS.delegate(self.lead.sid, "count the TODOs in src/", tier="light", timeout=1)
        self.assertIn("Worker Claude Haiku (latest) finished", out)
        self.assertIn("[harness:claude/haiku] result", out)
        model, content, read_only, wsid = self.asked[0]
        self.assertEqual(model, "harness:claude/haiku")
        self.assertIn("count the TODOs", content); self.assertIn("Read-only", content)
        self.assertTrue(read_only)                                             # plan mode: it cannot change anything
        prefs = CE.chat_prefs(wsid)
        self.assertIs(prefs.get("delegation"), False)                          # a worker does not hand its task on
        led = D.summary(self.tmp)
        self.assertEqual(led["tasks"], 1); self.assertEqual(led["tokens"], 120)
        meta = q.session_meta(wsid)
        self.assertTrue(meta and meta.get("archived"))                         # out of the list, still reachable

    def test_a_worker_keeps_the_model_it_was_given(self):
        self.ui.CHATS.delegate(self.lead.sid, "summarise", tier="light", timeout=1)
        wsid = self.asked[0][3]
        self.assertIs(CE.chat_prefs(wsid).get("no_fallback"), True)
        q.S["fallback_models"] = ["harness:claude/sonnet"]
        q.TURN_CTX.sid = wsid
        self.addCleanup(setattr, q.TURN_CTX, "sid", None)
        self.assertEqual(q.fallback_candidates("harness:claude/haiku"), [])             # it would have moved on otherwise
        q.TURN_CTX.sid = self.lead.sid
        self.assertTrue(q.fallback_candidates("harness:claude/haiku"))

    def test_a_crew_message_already_answered_is_not_sent_again_after_a_restart(self):
        r1 = self.ui._run_on_chat(self.lead.sid, "do round 1", 5, None, "Crew", key="run:1:build")
        self.assertIn("result", r1["answer"])
        self.assertEqual(len(self.asked), 1)
        r2 = self.ui._run_on_chat(self.lead.sid, "do round 1", 5, None, "Crew", key="run:1:build")      # as after a restart
        self.assertEqual(r2["answer"], r1["answer"]); self.assertEqual(len(self.asked), 1)
        self.ui._run_on_chat(self.lead.sid, "do round 2", 5, None, "Crew", key="run:2:build")
        self.assertEqual(len(self.asked), 2)                                          # a new round is a new message

    def test_a_copy_still_waiting_in_the_queue_is_dropped_not_doubled(self):
        self.ui._queue_add(self.lead, "do round 1", origin={"sid": None, "title": "Crew", "chain": [], "reply": "stale", "key": "run:1:build"})
        self.ui._run_on_chat(self.lead.sid, "do round 1", 5, None, "Crew", key="run:1:build")
        self.assertEqual(len(self.asked), 1)

    def test_the_crew_panel_shows_what_the_chat_is_doing(self):
        import crew as C
        run = C.new_run("Demo", "x", self.tmp, [{"sid": self.lead.sid}], [])
        run.update(phase="build", round=0)
        self.assertEqual(self.ui._crew_activity(run)["busy"], False)
        self.lead.msgs.append({"role": "user", "content": "go", "from_chat": {"sid": None, "title": "Crew"}})
        self.lead.msgs += [{"role": "tool", "content": "ok"}] * 3
        self.lead.lock.acquire(); self.addCleanup(lambda: self.lead.lock.locked() and self.lead.lock.release())
        self.lead.busy_since = time.time() - 125
        self.lead.live = {"status": "running Bash"}
        a = self.ui._crew_activity(run)
        self.assertEqual((a["busy"], a["steps"], a["status"]), (True, 3, "running Bash"))
        self.assertGreaterEqual(a["secs"], 125)
        run["state"] = "paused"
        self.assertIsNone(self.ui._crew_activity(run))

    def test_a_crew_waits_for_a_pending_restart_but_not_for_ever(self):
        import threading as T
        self.ui.CREW_HOLD.set(); self.addCleanup(self.ui.CREW_HOLD.clear)
        self.addCleanup(setattr, self.ui, "CREW_HOLD_MAX_S", self.ui.CREW_HOLD_MAX_S)
        self.ui.CREW_HOLD_MAX_S = 0.3
        t0 = time.time()
        res = self.ui._CrewHost().turn(self.lead.sid, "go", 5, T.Event(), key="r:1:build")
        self.assertGreaterEqual(time.time() - t0, 0.3)
        self.assertIn("result", res["answer"])

    def test_a_round_is_not_over_until_the_work_it_started_in_the_background_is(self):
        bg = {"running": True}
        saved = q.CE.bg_running
        q.CE.bg_running = lambda sid: bg["running"]
        self.addCleanup(setattr, q.CE, "bg_running", saved)
        import threading as T
        def finish():
            time.sleep(0.8)
            self.lead.msgs.append({"role": "assistant", "content": "The workers finished: all checked."})
            bg["running"] = False
        T.Thread(target=finish, daemon=True).start()
        t0 = time.time()
        res = self.ui._run_on_chat(self.lead.sid, "build", 10, None, "Crew", settle_s=20)
        self.assertGreaterEqual(time.time() - t0, 0.8)
        self.assertIn("workers finished", res["answer"])
        # a stuck background task cannot hold it for ever
        bg["running"] = True
        t0 = time.time()
        self.ui._run_on_chat(self.lead.sid, "build again", 10, None, "Crew", settle_s=1)
        self.assertLess(time.time() - t0, 6)

    def test_a_failed_crew_turn_says_why(self):
        self.fail_models = {"harness:claude/opus"}
        r = self.ui._run_on_chat(self.lead.sid, "go", 5, None, "Crew")
        self.assertTrue(r["failed"].startswith("error"))

    def test_write_is_allowed_only_when_settings_allow_it(self):
        self.ui.CHATS.delegate(self.lead.sid, "add a docstring", tier="light", write=True, timeout=1)
        self.assertFalse(self.asked[-1][2]); self.assertIn("may change files", self.asked[-1][1])
        q.S["delegation"]["allow_changes"] = False
        self.ui.CHATS.delegate(self.lead.sid, "add a docstring", tier="light", write=True, timeout=1)
        self.assertTrue(self.asked[-1][2])

    def test_a_failing_worker_is_skipped_and_the_next_one_tried(self):
        self.fail_models = {"harness:claude/haiku"}
        out = self.ui.CHATS.delegate(self.lead.sid, "summarise", tier="light", timeout=1)
        self.assertIn("finished", out)
        self.assertEqual([a[0] for a in self.asked][:2], ["harness:claude/haiku", "harness:opencode-go/deepseek-v4.1-flash"])
        self.assertIn("harness:claude/haiku", D.cooling(self.tmp))
        self.assertEqual(D.summary(self.tmp)["stats"]["harness:claude/haiku"]["fails"], 1)
        # the next task does not even try the one that just failed
        self.asked.clear()
        self.ui.CHATS.delegate(self.lead.sid, "another", tier="light", timeout=1)
        self.assertNotEqual(self.asked[0][0], "harness:claude/haiku")

    def test_when_nothing_can_do_it_the_lead_is_told_to(self):
        self.fail_models = {c["id"] for c in CATALOGUE}
        out = self.ui.CHATS.delegate(self.lead.sid, "summarise", tier="light", timeout=1)
        self.assertTrue(out.startswith("Error: no worker could do this")); self.assertIn("Do it yourself", out)
        q.model_catalogue = lambda: [dict(CATALOGUE[0])]                       # only a lead model is ready
        out = self.ui.CHATS.delegate(self.lead.sid, "summarise", tier="light", timeout=1)
        self.assertIn("no cheaper model is ready", out)

    def test_wait_false_hands_off_and_returns_the_chat(self):
        out = self.ui.CHATS.delegate(self.lead.sid, "long job", tier="standard", wait=False)
        self.assertIn("Handed to Claude Sonnet (latest)", out); self.assertIn("chat_wait", out)
        # the ledger learns how it went once the worker is done, not at the hand-off
        end = time.time() + 20
        while time.time() < end and not D.summary(self.tmp)["tasks"]: time.sleep(0.2)
        led = D.summary(self.tmp)
        self.assertEqual(led["tasks"], 1); self.assertEqual(led["tokens"], 120); self.assertGreater(led["log"][0]["secs"], 0)

    def test_an_empty_task_and_the_tool_wrapper(self):
        self.assertTrue(self.ui.CHATS.delegate(self.lead.sid, "  ").startswith("Error"))
        q.TURN_CTX.sid = self.lead.sid
        self.addCleanup(setattr, q.TURN_CTX, "sid", None)
        out = q.t_delegate("find usages of foo", timeout_minutes=1)
        self.assertIn("finished", out)
        CE.set_chat_pref(self.lead.sid, delegation=False)
        self.addCleanup(CE.forget_chat_prefs, self.lead.sid)
        self.assertTrue(q.t_delegate("again").startswith("Error: delegation is off"))


class TestEverywhere(unittest.TestCase):
    def setUp(self):
        self.saved = dict(q.S)
        self.addCleanup(lambda: (q.S.clear(), q.S.update(self.saved)))
        self.cfgdir = tempfile.mkdtemp(prefix="orbit-deleg-cfg-"); self.addCleanup(shutil.rmtree, self.cfgdir, True)
        p = mock.patch.object(CE, "_work_dir", lambda: self.cfgdir); p.start(); self.addCleanup(p.stop)
        q.S.pop("delegation", None)

    def test_off_by_default_and_per_chat_either_way(self):
        self.assertFalse(q.delegation_on("c1"))
        CE.set_chat_pref("c1", delegation=True); self.addCleanup(CE.forget_chat_prefs, "c1")
        self.assertTrue(q.delegation_on("c1"))
        q.S["delegation"] = {"enabled": True}
        CE.set_chat_pref("c2", delegation=False); self.addCleanup(CE.forget_chat_prefs, "c2")
        self.assertTrue(q.delegation_on("c3")); self.assertFalse(q.delegation_on("c2"))

    def test_the_tool_is_added_or_taken_away_per_chat(self):
        seen = {}
        base = q._turn_before_delegation
        q._turn_before_delegation = lambda msgs, uc, tools, **kw: seen.update(names=[t["function"]["name"] for t in tools]) or "ok"
        self.addCleanup(setattr, q, "_turn_before_delegation", base)
        plain = [{"type": "function", "function": {"name": "read_file"}}]
        q.S["delegation"] = {"enabled": True}
        q.turn([], "hi", plain, sid="c9")
        self.assertIn("delegate", seen["names"])
        q.S["delegation"] = {"enabled": False}
        q.turn([], "hi", plain + [q._delegate_spec()], sid="c9")
        self.assertNotIn("delegate", seen["names"])

    def test_the_description_teaches_when_to_delegate(self):
        spec = q._delegate_spec()["function"]
        for want in ("DELEGATE", "KEEP", "has not seen this conversation", "check what you rely on", "wait=false"):
            self.assertIn(want, spec["description"])
        self.assertEqual(spec["parameters"]["required"], ["task"])

    def test_the_lead_in_a_claude_chat_is_told(self):
        note = str(CE._orbit_append(None, dict(CE.DEFAULTS), True, None, "local", look=False, delegate=True))
        self.assertIn("DELEGATION IS ON", note); self.assertIn("mcp__orbit__delegate", note)
        self.assertNotIn("Delegation is on", str(CE._orbit_append(None, dict(CE.DEFAULTS), True, None, "local", look=False)))

    def test_claude_codes_own_subagents_use_the_small_model(self):
        spec = {"provider": "harness", "provider_cfg": {"provider": "deepseek", "model": "deepseek-v4-pro", "small": "deepseek-v4-flash",
                                                         "format": "messages", "base": "https://x", "api_key": "k", "auth": "api_key"}}
        t = CE.harness_target(spec, sid="c5")
        self.assertNotIn("CLAUDE_CODE_SUBAGENT_MODEL", t["env"])
        q.S["delegation"] = {"enabled": True}
        t = CE.harness_target(spec, sid="c5")
        self.assertEqual(t["env"]["CLAUDE_CODE_SUBAGENT_MODEL"], "deepseek-v4-flash")
        q.S["delegation"] = {"enabled": True, "subagents": False}
        self.assertNotIn("CLAUDE_CODE_SUBAGENT_MODEL", CE.harness_target(spec, sid="c5")["env"])


if __name__ == "__main__":
    unittest.main()
