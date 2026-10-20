"""When a Claude account hits its limit: the chat carries on at once on another account (or
on the model chosen for "every account used up"), instead of waiting for the reset.

The accounts, their marks and the scheduled run all live in temporary files; no model, no
network and no real Claude login are involved.
"""
import importlib.machinery, importlib.util, os, shutil, sys, tempfile, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "bin"))

import harness as H
import harness_usage as U
import claude_accounts as CA
import claude_engine as CE

MODEL = "harness:claude/sonnet"


def load_ui():
    loader = importlib.machinery.SourceFileLoader("orbit_ui_switch_test", os.path.join(ROOT, "bin", "orbit-ui"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class TwoAccounts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ui = load_ui()
        cls.q = cls.ui.q

    def setUp(self):
        q = self.q
        self.tmp = tempfile.mkdtemp(prefix="orbit-switch-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        os.makedirs(os.path.join(self.tmp, "config"))
        saved = (q.ROOT, q.SCHED, q.snapshot_config, q.notify, q.secrets_load,
                 q.S.get("resume_after_limit"), q.S.get("limit_fallback_model"))
        q.ROOT = self.tmp
        q.SCHED = os.path.join(self.tmp, "schedule.json")
        q.snapshot_config = lambda *a, **k: None
        q.notify = lambda *a, **k: None
        q.secrets_load = lambda: {"CLAUDE_CODE_OAUTH_TOKEN": "tok-main", "CLAUDE_CODE_OAUTH_TOKEN_LAB": "tok-lab"}
        q.S["resume_after_limit"] = True
        q.S["limit_fallback_model"] = ""
        def restore():
            (q.ROOT, q.SCHED, q.snapshot_config, q.notify, q.secrets_load) = saved[:5]
            q.S["resume_after_limit"], q.S["limit_fallback_model"] = saved[5], saved[6]
        self.addCleanup(restore)
        q.sched_save({"jobs": []})
        cfg = H.load(self.tmp)
        cfg["providers"]["claude"] = {"accounts": [{"id": "main", "label": "Personal"},
                                                    {"id": "lab", "label": "Lab", "key": "CLAUDE_CODE_OAUTH_TOKEN_LAB"}]}
        H.save(self.tmp, cfg)
        # the Mac's own login is not consulted: both accounts have tokens
        self._login = H.claude_login
        H.claude_login = lambda *a, **k: "yes"
        self.addCleanup(setattr, H, "claude_login", self._login)

    def jobs(self):
        return [j for j in self.q.sched_load()["jobs"] if j.get("kind") == "limit_resume"]

    def watch(self, account="main", hours=5):
        """An answer that ran on `account` and was refused with a reset `hours` away."""
        w = self.ui._LimitWatch()
        w.see("model", {"id": MODEL, "label": "Claude Code", "account": {"id": account, "label": account}})
        w.see("notice", {"kind": "limit", "resets_at": time.time() + hours * 3600,
                         "msg": "Claude's 5-hour limit reached", "account": account})
        return w

    def check(self, w, sid="chat-1"):
        st = self.ui.State(); st.temp = True; st.title = "t"; st.msgs = []
        return w.check(st, 0, model=MODEL, sid=sid)


class TestCarryingOnAtOnce(TwoAccounts):
    def test_the_other_account_takes_over_now_not_at_the_reset(self):
        job = self.check(self.watch("main"))
        self.assertIn("Lab", job["switch"])
        self.assertAlmostEqual(job["at_ts"], time.time() + 3, delta=5)
        self.assertNotIn("model", job)                         # the chat's own model, a different login
        self.assertIn("another one", job["prompt"])

    def test_the_account_that_ran_out_is_marked_so_the_run_cannot_pick_it_again(self):
        self.check(self.watch("main", hours=5))
        e = U.exhausted(self.tmp, "claude", "main")
        self.assertAlmostEqual(e["until"], time.time() + 5 * 3600 + 60, delta=10)
        self.assertEqual(CE.harness_target({"provider": "harness", "provider_cfg": {"subscription": True}},
                                           )["account"]["id"], "lab")

    def test_the_chat_says_so(self):
        self.assertIn("continuing on Lab", self.ui._limit_note(self.check(self.watch("main"))))

    def test_both_used_up_waits_for_whichever_comes_back_first(self):
        CA.note_limit(self.tmp, "lab", time.time() + 2 * 3600, "5-hour")
        job = self.check(self.watch("main", hours=5))
        self.assertNotIn("switch", job)
        self.assertAlmostEqual(job["at_ts"], time.time() + 2 * 3600 + 120, delta=90)

    def test_the_model_for_every_account_used_up(self):
        CA.note_limit(self.tmp, "lab", time.time() + 2 * 3600, "5-hour")
        fb = "harness:opencode-go/deepseek-v4.1-flash"
        self.q.S["limit_fallback_model"] = fb
        saved = self.q.model_catalogue
        self.q.model_catalogue = lambda: [{"id": fb, "label": "DeepSeek V4.1 Flash · OpenCode Go"}]
        self.addCleanup(setattr, self.q, "model_catalogue", saved)
        job = self.check(self.watch("main"))
        self.assertEqual(job["model"], fb)
        self.assertIn("DeepSeek V4.1 Flash", job["switch"])
        self.assertAlmostEqual(job["at_ts"], time.time() + 3, delta=5)

    def test_without_the_switch_it_waits_as_it_always_did(self):
        H.set_policy(self.tmp, auto_switch=False)
        job = self.check(self.watch("main", hours=4))
        self.assertNotIn("switch", job)
        self.assertAlmostEqual(job["at_ts"], time.time() + 4 * 3600 + 120, delta=90)

    def test_a_second_limit_moves_the_one_job_instead_of_adding_another(self):
        self.check(self.watch("main"))
        self.check(self.watch("lab"))                          # the other one ran out as well
        self.assertEqual(len(self.jobs()), 1)
        self.assertNotIn("switch", self.jobs()[0])              # nothing left to go to: back to waiting

    def test_other_models_are_left_alone(self):
        w = self.ui._LimitWatch()
        w.see("notice", {"kind": "limit", "resets_at": time.time() + 3600, "msg": "limit reached"})
        st = self.ui.State(); st.temp = True; st.title = "t"; st.msgs = []
        job = w.check(st, 0, model="harness:opencode-go/glm-5.3")
        self.assertNotIn("switch", job)
        self.assertGreater(job["at_ts"], time.time() + 3000)


class TestWhichAccountARunTakes(TwoAccounts):
    SPEC = {"provider": "harness", "provider_cfg": {"subscription": True, "model": "sonnet", "context": 1000000}}

    def test_the_main_account_with_its_token_and_a_marker(self):
        t = CE.harness_target(self.SPEC)
        self.assertEqual(t["env"], {"CLAUDE_CODE_OAUTH_TOKEN": "tok-main", "ORBIT_CLAUDE_ACCOUNT": "main"})
        self.assertEqual((t["account"]["label"], t["account"]["many"]), ("Personal", True))

    def test_a_chat_pinned_to_an_account_keeps_it(self):
        CE.set_chat_pref("pin-chat", claude_account="lab")
        t = CE.harness_target(self.SPEC, sid="pin-chat")
        self.assertEqual((t["account"]["id"], t["env"]["CLAUDE_CODE_OAUTH_TOKEN"]), ("lab", "tok-lab"))
        self.assertEqual(CE.harness_target(self.SPEC, sid="another-chat")["account"]["id"], "main")

    def test_the_account_is_part_of_what_a_kept_process_is_started_with(self):
        t = CE.harness_target(self.SPEC)
        self.assertEqual(CE.target_env(t)["ORBIT_CLAUDE_ACCOUNT"], "main")
        CA.note_limit(self.tmp, "main", time.time() + 3600, "limit")
        self.assertEqual(CE.target_env(CE.harness_target(self.SPEC))["ORBIT_CLAUDE_ACCOUNT"], "lab")

    def test_one_login_is_still_just_one_login(self):
        cfg = H.load(self.tmp)
        cfg["providers"]["claude"] = {}
        H.save(self.tmp, cfg)
        t = CE.harness_target(self.SPEC)
        self.assertFalse(t["account"]["many"])
        self.assertEqual(t["env"]["CLAUDE_CODE_OAUTH_TOKEN"], "tok-main")      # the token saved before accounts existed


if __name__ == "__main__":
    unittest.main()
