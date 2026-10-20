"""OpenCode runs as the account Orbit chose, moves to the next when one is used up, and
leaves OpenCode alone when there is only one account.

A stand-in `opencode` program answers according to the key it is given, so nothing
reaches the network and no real OpenCode account is used.
"""
import json, os, shutil, stat, sys, tempfile, textwrap, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))

import harness as H
import harness_usage as U
import providers as P
import qqcore as q

FAKE = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json, os, sys
    key = (((json.loads(os.environ.get("OPENCODE_CONFIG_CONTENT") or "{}").get("provider") or {})
            .get("opencode-go") or {}).get("options") or {}).get("apiKey", "stored")
    if key == "used-up":
        body = {"error": {"type": "GoUsageLimitError", "message": "5 hour limit"}, "metadata": {"limitName": "5 hour"}}
        print(json.dumps({"type": "error", "sessionID": "ses_x", "error": {"name": "APIError", "data": {
            "message": "limit", "statusCode": 429, "responseBody": json.dumps(body),
            "responseHeaders": {"retry-after": "7200"}}}}))
        sys.exit(1)
    print(json.dumps({"type": "text", "sessionID": "ses_x", "part": {"type": "text", "text": "answered as " + key}}))
''')


class Accounts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orbit-oc-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        os.makedirs(os.path.join(self.tmp, "config"))
        exe = os.path.join(self.tmp, "opencode")
        open(exe, "w").write(FAKE)
        os.chmod(exe, os.stat(exe).st_mode | stat.S_IXUSR)
        saved = (P.which, q.ROOT, q.secrets_load, q.USAGE.go_usage)
        eng = q.S.get("look_engines")
        q.S["look_engines"] = []                              # the look tools have their own tests below
        self.addCleanup(lambda: q.S.__setitem__("look_engines", eng) if eng is not None else q.S.pop("look_engines", None))
        P.which = lambda name: exe if name == "opencode" else None
        q.ROOT = self.tmp
        q.secrets_load = lambda: {"K_A": "used-up", "K_B": "good-key"}
        q.USAGE.go_usage = lambda *a, **k: None                  # no call to OpenCode's usage page
        def restore():
            P.which, q.ROOT, q.secrets_load, q.USAGE.go_usage = saved
        self.addCleanup(restore)
        cfg = H.load(self.tmp)
        cfg["providers"]["opencode-go"] = {"accounts": [{"id": "a", "label": "Main", "key": "K_A"},
                                                         {"id": "b", "label": "Lab", "key": "K_B"}], "active": "a"}
        H.save(self.tmp, cfg)

    def run_cli(self, model="opencode-go/deepseek-v4.1-flash"):
        notes = []
        out = P.cli_stream("opencode-cli", model, [{"role": "user", "content": "hi"}],
                           emit=lambda k, p: notes.append((k, p)), cwd=self.tmp,
                           account_for=q._cli_account_for, on_quota=q._cli_quota,
                           on_moved=lambda who: H.moved_to(self.tmp, who["provider"], who["account"]))
        return out, notes


class TestMovingOn(Accounts):
    def test_the_account_that_is_used_up_is_recorded_and_the_next_answers(self):
        out, notes = self.run_cli()
        self.assertEqual(out["content"], "answered as good-key")
        e = U.exhausted(self.tmp, "opencode-go", "a")
        self.assertAlmostEqual(e["until"] - e["at"], 7200, delta=5)                    # the provider's own retry-after
        self.assertTrue(any(k == "notice" and "Main" in p["msg"] and "Lab" in p["msg"] for k, p in notes))

    def test_the_next_run_starts_on_the_account_that_works(self):
        self.run_cli()
        self.assertEqual(self.run_cli()[0]["content"], "answered as good-key")

    def test_and_goes_back_to_the_main_account_by_default(self):
        self.run_cli()
        self.assertEqual(H.accounts(H.providers(self.tmp)["opencode-go"])[0]["id"], "a")

    def test_unless_going_back_is_off(self):
        H.set_policy(self.tmp, switch_back=False)
        self.run_cli()
        self.assertEqual(H.accounts(H.providers(self.tmp)["opencode-go"])[0]["id"], "b")

    def test_with_moving_on_switched_off_the_limit_is_the_answer(self):
        H.set_policy(self.tmp, auto_switch=False)
        with self.assertRaises(P.CliQuotaError):
            self.run_cli()

    def test_every_account_used_up_says_so(self):
        q.secrets_load = lambda: {"K_A": "used-up", "K_B": "used-up"}
        with self.assertRaises(P.CliQuotaError):
            self.run_cli()


class TestLeavingOpenCodeAlone(Accounts):
    def test_one_account_runs_as_opencode_is_set_up(self):
        cfg = H.load(self.tmp)
        cfg["providers"]["opencode-go"]["accounts"] = cfg["providers"]["opencode-go"]["accounts"][:1]
        H.save(self.tmp, cfg)
        self.assertIsNone(q._cli_account_for("opencode-cli", "opencode-go/deepseek-v4.1-flash", [], ()))

    def test_another_provider_or_no_model_is_left_alone(self):
        self.assertIsNone(q._cli_account_for("opencode-cli", "mtplx/local-model", [], ()))
        self.assertIsNone(q._cli_account_for("opencode-cli", "", [], ()))
        self.assertIsNone(q._cli_account_for("codex-cli", "opencode-go/x", [], ()))


class TestEyes(Accounts):
    """OpenCode gets the look tools in its own MCP config, alongside whichever account it runs as."""
    def setUp(self):
        super().setUp()
        q.S["look_engines"] = ["opencode"]

    def test_the_server_is_handed_over_in_opencodes_own_format(self):
        cfg = H.load(self.tmp)
        cfg["providers"]["opencode-go"]["accounts"] = cfg["providers"]["opencode-go"]["accounts"][:1]
        H.save(self.tmp, cfg)                                     # one account: nothing to choose
        env, who = q._cli_account_for("opencode-cli", "opencode-go/deepseek-v4.1-flash", [], ())
        got = json.loads(env["OPENCODE_CONFIG_CONTENT"])
        self.assertIsNone(who)
        self.assertEqual(got["mcp"]["orbit-look"]["type"], "local")
        self.assertEqual(got["mcp"]["orbit-look"]["command"][1:], [q.LOOK_PATH])
        self.assertNotIn("provider", got)

    def test_and_the_chosen_account_goes_in_the_same_config(self):
        env, who = q._cli_account_for("opencode-cli", "opencode-go/deepseek-v4.1-flash", [], ())
        got = json.loads(env["OPENCODE_CONFIG_CONTENT"])
        self.assertIn("orbit-look", got["mcp"])
        self.assertEqual(got["provider"]["opencode-go"]["options"]["apiKey"], "used-up")   # a is first
        self.assertEqual(who["account"], "a")

    def test_the_groups_you_switched_on_are_what_it_is_started_with(self):
        q.S["look_groups"] = ["browser"]
        self.addCleanup(q.S.pop, "look_groups", None)
        env, _ = q._cli_account_for("opencode-cli", "mtplx/anything", [], ())
        self.assertEqual(json.loads(env["OPENCODE_CONFIG_CONTENT"])["mcp"]["orbit-look"]["environment"]["ORBIT_LOOK_GROUPS"],
                         "browser")

    def test_off_means_off(self):
        q.S["look_engines"] = []
        self.assertIsNone(q._cli_account_for("opencode-cli", "mtplx/anything", [], ()))


if __name__ == "__main__":
    unittest.main()
