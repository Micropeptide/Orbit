"""Several accounts for one provider: which one a run uses, when it moves to the next, and
when it goes back.

A Claude subscription runs out (5-hour, weekly), and so does an OpenCode Go account. Orbit
keeps a list of accounts for each, uses the main one, moves to another when the main one
says its allowance is used up, and -- if you want -- returns to the main one once its
allowance is back. Every test runs on a temporary Orbit folder and calls nothing.
"""
import json, os, shutil, sys, tempfile, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))

import harness as H
import harness_usage as U
import claude_accounts as CA

NOW = 1_800_000_000.0


class Root(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="orbit-accounts-")
        self.addCleanup(shutil.rmtree, self.root, True)
        os.makedirs(os.path.join(self.root, "config"))
        self.secrets = {}

    def save_claude(self, **over):
        cfg = H.load(self.root)
        cfg["providers"].setdefault("claude", {}).update(over)
        H.save(self.root, cfg)

    def two(self, **policy):
        """A main login and a second account with its own token."""
        self.secrets.update({"CLAUDE_CODE_OAUTH_TOKEN": "tok-main", "CLAUDE_CODE_OAUTH_TOKEN_LAB": "tok-lab"})
        self.save_claude(accounts=[{"id": "main", "label": "Personal"},
                                   {"id": "lab", "label": "Lab", "key": "CLAUDE_CODE_OAUTH_TOKEN_LAB"}])
        if policy:
            H.set_policy(self.root, **policy)

    def pick(self, **kw):
        return CA.choose(self.root, self.secrets, login="yes", now=NOW, **kw)

    def limit(self, acct, hours=5):
        CA.note_limit(self.root, acct, NOW + hours * 3600, "5-hour limit", now=NOW)


class TestTheList(Root):
    def test_one_login_is_one_account(self):
        rows = CA.accounts(self.root)
        self.assertEqual([(a["id"], a["key"]) for a in rows], [("main", "CLAUDE_CODE_OAUTH_TOKEN")])

    def test_main_always_leads_and_keeps_the_original_token_slot(self):
        self.save_claude(accounts=[{"id": "lab", "label": "Lab", "key": "CLAUDE_CODE_OAUTH_TOKEN_LAB"}])
        rows = CA.accounts(self.root)
        self.assertEqual([a["id"] for a in rows], ["main", "lab"])
        self.assertEqual(rows[0]["key"], "CLAUDE_CODE_OAUTH_TOKEN")      # the token saved before accounts existed

    def test_adding_names_a_token_slot_for_it(self):
        a = CA.add(self.root, "Lab")
        self.assertEqual(a["label"], "Lab")
        self.assertTrue(a["key"].startswith("CLAUDE_CODE_OAUTH_TOKEN_"))
        self.assertEqual([x["id"] for x in CA.accounts(self.root)], ["main", a["id"]])
        b = CA.add(self.root, "Lab")
        self.assertNotEqual(a["key"], b["key"])

    def test_removing_returns_the_secret_to_forget_and_never_removes_main(self):
        a = CA.add(self.root, "Lab")
        self.assertEqual(CA.remove(self.root, a["id"]), a["key"])
        self.assertEqual([x["id"] for x in CA.accounts(self.root)], ["main"])
        self.assertIsNone(CA.remove(self.root, "main"))
        self.assertEqual([x["id"] for x in CA.accounts(self.root)], ["main"])

    def test_renaming_and_choosing_the_main_account(self):
        self.two()
        CA.rename(self.root, "main", "Home")
        self.assertEqual(CA.accounts(self.root)[0]["label"], "Home")
        self.assertEqual(CA.home(self.root), "main")
        CA.set_home(self.root, "lab")
        self.assertEqual(CA.home(self.root), "lab")


class TestWhichOneARunUses(Root):
    def test_the_main_account_when_nothing_is_wrong(self):
        self.two()
        got = self.pick()
        self.assertEqual((got["account"]["id"], got["reason"]), ("main", "home"))

    def test_a_chat_can_stay_on_the_account_it_was_given(self):
        self.two()
        got = self.pick(pinned="lab")
        self.assertEqual((got["account"]["id"], got["reason"]), ("lab", "pinned"))

    def test_main_used_up_moves_to_the_next(self):
        self.two()
        self.limit("main")
        got = self.pick()
        self.assertEqual((got["account"]["id"], got["reason"]), ("lab", "switched"))

    def test_and_goes_back_once_main_is_back(self):
        self.two()
        self.limit("main", hours=5)
        self.assertEqual(self.pick()["account"]["id"], "lab")
        later = CA.choose(self.root, self.secrets, login="yes", now=NOW + 6 * 3600)
        self.assertEqual((later["account"]["id"], later["reason"]), ("main", "home"))

    def test_staying_on_the_new_account_when_going_back_is_off(self):
        self.two(switch_back=False)
        self.limit("main")
        got = self.pick()
        self.assertEqual(got["account"]["id"], "lab")
        CA.settle(self.root, got)                       # the run went ahead on it: it is the main one now
        later = CA.choose(self.root, self.secrets, login="yes", now=NOW + 6 * 3600)
        self.assertEqual(later["account"]["id"], "lab")

    def test_going_back_leaves_main_alone(self):
        self.two(switch_back=True)
        self.limit("main")
        CA.settle(self.root, self.pick())
        self.assertEqual(CA.home(self.root), "main")

    def test_with_automatic_switching_off_it_stays_put_and_lets_the_limit_show(self):
        self.two(auto_switch=False)
        self.limit("main")
        got = self.pick()
        self.assertEqual(got["account"]["id"], "main")

    def test_a_pinned_account_that_is_used_up_moves_on_without_losing_its_pin(self):
        self.two()
        self.limit("lab")
        got = self.pick(pinned="lab")
        self.assertEqual((got["account"]["id"], got["reason"]), ("main", "switched"))

    def test_an_account_without_a_token_is_not_a_place_to_go(self):
        self.save_claude(accounts=[{"id": "main", "label": "Personal"},
                                   {"id": "lab", "label": "Lab", "key": "CLAUDE_CODE_OAUTH_TOKEN_LAB"}])
        self.secrets["CLAUDE_CODE_OAUTH_TOKEN"] = "tok-main"
        self.limit("main")
        got = self.pick()                                # Lab has no token yet
        self.assertEqual(got["account"]["id"], "main")

    def test_main_without_a_token_is_the_macs_own_login_when_that_is_signed_in(self):
        self.save_claude(accounts=[{"id": "main", "label": "Personal"},
                                   {"id": "lab", "label": "Lab", "key": "CLAUDE_CODE_OAUTH_TOKEN_LAB"}])
        self.secrets["CLAUDE_CODE_OAUTH_TOKEN_LAB"] = "tok-lab"
        self.assertEqual(CA.choose(self.root, self.secrets, login="yes", now=NOW)["account"]["id"], "main")
        # not signed in: the account that can answer takes it, and says why
        got = CA.choose(self.root, self.secrets, login="no", now=NOW)
        self.assertEqual((got["account"]["id"], got["reason"]), ("lab", "switched"))

    def test_every_account_used_up_takes_the_one_that_comes_back_first(self):
        self.two()
        CA.note_limit(self.root, "main", NOW + 9 * 3600, "weekly", now=NOW)
        CA.note_limit(self.root, "lab", NOW + 2 * 3600, "5-hour", now=NOW)
        self.assertEqual(self.pick()["account"]["id"], "lab")


class TestWhatTheRunIsGiven(Root):
    def test_a_token_account_hands_its_token_over_and_says_which_it_is(self):
        self.two()
        env = CA.env_for(self.secrets, CA.accounts(self.root)[1])
        self.assertEqual(env, {"CLAUDE_CODE_OAUTH_TOKEN": "tok-lab", "ORBIT_CLAUDE_ACCOUNT": "lab"})

    def test_the_macs_own_login_hands_over_no_token(self):
        env = CA.env_for({}, CA.accounts(self.root)[0])
        self.assertEqual(env, {"ORBIT_CLAUDE_ACCOUNT": "main"})

    def test_the_view_for_settings_never_carries_a_token(self):
        self.two()
        self.limit("main")
        rows = CA.public(self.root, self.secrets, login="yes", now=NOW)
        self.assertNotIn("tok-lab", json.dumps(rows))
        main, lab = rows
        self.assertTrue(main["exhausted"] and main["home"])
        self.assertTrue(lab["token_set"] and not lab["exhausted"])


class TestTheLimitNote(Root):
    def test_a_limit_marks_the_account_until_it_resets(self):
        self.two()
        self.limit("main", hours=3)
        e = U.exhausted(self.root, "claude", "main", now=NOW + 60)
        self.assertAlmostEqual(e["until"], NOW + 3 * 3600 + 60, delta=5)     # a minute past the reset

    def test_an_alternative_exists_only_when_one_can_answer(self):
        self.two()
        self.assertEqual(CA.alternative(self.root, self.secrets, "main", login="yes", now=NOW)["id"], "lab")
        self.limit("lab")
        self.assertIsNone(CA.alternative(self.root, self.secrets, "main", login="yes", now=NOW))

    def test_no_alternative_when_switching_is_off(self):
        self.two(auto_switch=False)
        self.assertIsNone(CA.alternative(self.root, self.secrets, "main", login="yes", now=NOW))


class TestTheSameForOpenCodeGo(Root):
    """The gateway's accounts follow the same two switches."""
    def setUp(self):
        super().setUp()
        cfg = H.load(self.root)
        cfg["providers"]["opencode-go"] = {"accounts": [
            {"id": "a", "label": "Main", "key": "K_A"}, {"id": "b", "label": "Lab", "key": "K_B"}], "active": "a"}
        H.save(self.root, cfg)
        self.secrets = {"K_A": "aaa", "K_B": "bbb"}
        self.p = H.providers(self.root)["opencode-go"]

    def keys(self):
        return [a["id"] for a in H.account_keys(self.p, self.secrets, self.root, "opencode-go")]

    def test_used_up_goes_last_and_the_active_one_comes_back_first(self):
        self.assertEqual(self.keys(), ["a", "b"])
        U.mark_exhausted(self.root, "opencode-go", "a", "5 hour limit", seconds=3600)
        self.assertEqual(self.keys(), ["b", "a"])
        U.clear_exhausted(self.root, "opencode-go", "a")
        self.assertEqual(self.keys(), ["a", "b"])

    def test_automatic_switching_off_means_one_account_and_the_limit_shows(self):
        H.set_policy(self.root, auto_switch=False)
        U.mark_exhausted(self.root, "opencode-go", "a", "5 hour limit", seconds=3600)
        self.assertEqual(self.keys(), ["a"])

    def test_a_request_that_moved_on_can_make_the_new_account_the_main_one(self):
        H.set_policy(self.root, switch_back=False)
        H.moved_to(self.root, "opencode-go", "b")
        self.assertEqual(H.accounts(H.providers(self.root)["opencode-go"])[0]["id"], "b")

    def test_or_leave_the_main_one_alone(self):
        H.moved_to(self.root, "opencode-go", "b")                  # switch_back is on by default
        self.assertEqual(H.accounts(H.providers(self.root)["opencode-go"])[0]["id"], "a")


class TestThePolicy(Root):
    def test_both_on_by_default_and_remembered(self):
        self.assertEqual(H.policy(self.root), {"auto_switch": True, "switch_back": True})
        H.set_policy(self.root, switch_back=False)
        self.assertEqual(H.policy(self.root), {"auto_switch": True, "switch_back": False})

    def test_nonsense_is_ignored(self):
        H.set_policy(self.root, auto_switch="maybe", other=1)
        self.assertEqual(H.policy(self.root), {"auto_switch": True, "switch_back": True})


if __name__ == "__main__":
    unittest.main()
