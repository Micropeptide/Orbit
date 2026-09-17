"""The Claude Code harness provider registry (bin/harness.py)."""
import json, os, shutil, sys, tempfile, time, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin"))
import harness as H                    # noqa: E402


class TestRegistry(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="orbit-harness-")
        os.makedirs(os.path.join(self.root, "config"))
        self.addCleanup(shutil.rmtree, self.root, True)
        # keys saved on this Mac reach os.environ once Orbit's core is imported: not here
        saved = {k: os.environ.pop(k) for k in list(os.environ) if k.endswith("_API_KEY") or "_API_KEY_" in k}
        self.addCleanup(os.environ.update, saved)

    def test_opencode_go_is_there_with_each_models_api(self):
        go = H.PRESETS["opencode-go"]
        fmt = {m["id"]: m["format"] for m in go["models"]}
        self.assertEqual(fmt["deepseek-v4-pro"], "chat")
        self.assertEqual(fmt["qwen3.8-max"], "messages")
        self.assertEqual(go["base"], "https://opencode.ai/zen/go/v1")
        self.assertEqual(go["auth"], "gateway")
        for pid in ("deepseek", "qwen", "glm", "minimax", "kimi", "anthropic", "opencode-zen", "local"):
            self.assertIn(pid, H.PRESETS)

    def test_catalogue_shows_ready_providers_and_resolve_carries_the_key(self):
        cat = H.catalogue(self.root, {}, "mtplx-q", include_unready=True)
        ids = {m["id"] for m in cat}
        self.assertIn("harness:local/mtplx-q", ids)
        self.assertNotIn("harness:local/mtplx-q", {m["id"] for m in H.catalogue(self.root, {}, "mtplx-q")})
        self.assertFalse(any(i.startswith("harness:opencode-go/") for i in
                             {m["id"] for m in H.catalogue(self.root, {}, "mtplx-q")}))   # no key yet
        secrets = {"OPENCODE_API_KEY": "sk-test"}
        cat = H.catalogue(self.root, secrets, "mtplx-q")
        self.assertIn("harness:opencode-go/deepseek-v4-pro", {m["id"] for m in cat})
        spec = H.resolve(self.root, "harness:opencode-go/deepseek-v4-pro", secrets, "mtplx-q")
        pc = spec["provider_cfg"]
        self.assertEqual((pc["kind"], pc["format"], pc["api_key"], pc["auth"]), ("harness", "chat", "sk-test", "gateway"))
        self.assertEqual(spec["provider"], "harness")
        self.assertIsNone(H.resolve(self.root, "harness:nope/x", secrets, "mtplx-q"))

    def test_find_by_words(self):
        secrets = {"OPENCODE_API_KEY": "k", "DEEPSEEK_API_KEY": "d"}
        self.assertEqual(H.find(self.root, "deepseek v4 pro opencode go", secrets, "m")["id"],
                         "harness:opencode-go/deepseek-v4-pro")
        self.assertEqual(H.find(self.root, "deepseek pro direct", secrets, "m")["id"],
                         "harness:deepseek/deepseek-v4-pro")
        self.assertEqual(H.find(self.root, "local qwen", secrets, "mtplx-qwen")["id"], "harness:local/mtplx-qwen")
        self.assertEqual(H.find(self.root, "harness:opencode-go/glm-5.3", secrets, "m")["id"],
                         "harness:opencode-go/glm-5.3")
        self.assertIsNone(H.find(self.root, "no such thing zzz", secrets, "m"))

    def test_custom_provider_and_choices_round_trip(self):
        cfg = H.load(self.root)
        cfg["custom"]["mylab"] = {"label": "Lab server", "base": "http://10.0.0.5:8000/v1", "key": "LAB_KEY",
                                  "auth": "gateway", "models": [{"id": "big-model", "format": "chat", "context": 64000}]}
        cfg["providers"]["qwen"] = {"base": H.PRESETS["qwen"]["alt_bases"][0]}
        H.save(self.root, cfg)
        again = H.load(self.root)
        self.assertEqual(again["custom"]["mylab"]["label"], "Lab server")
        spec = H.resolve(self.root, "harness:mylab/big-model", {"LAB_KEY": "x"}, "m")
        self.assertEqual(spec["provider_cfg"]["context"], 64000)
        q = H.resolve(self.root, "harness:qwen/qwen3-coder-plus", {"DASHSCOPE_API_KEY": "x"}, "m")
        self.assertEqual(q["provider_cfg"]["base"], H.PRESETS["qwen"]["alt_bases"][0])
        # keys never stored in the registry file
        self.assertNotIn("sk-", open(os.path.join(self.root, "config", "harness.json")).read())

    def test_model_lists_come_from_models_dev_and_the_providers_own_list(self):
        dev = {"opencode-go": {"models": {
            "deepseek-v4-pro": {"name": "DeepSeek V4 Pro", "limit": {"context": 1000000, "output": 384000}, "reasoning": True},
            "minimax-m3": {"name": "MiniMax M3", "limit": {"context": 1000000, "output": 131072},
                           "provider": {"npm": "@ai-sdk/anthropic"}},
            "gpt-x": {"limit": {"context": 400000}, "provider": {"npm": "@ai-sdk/openai"}},
            "gemini-y": {"limit": {"context": 1}, "provider": {"npm": "@ai-sdk/google"}}}},
               "deepseek": {"models": {"deepseek-v4-pro": {"limit": {"context": 1000000, "output": 384000}}}}}
        old_dev, old_http = H.models_dev, H._http_json
        H.models_dev = lambda root, **k: dev
        seen = []
        def http(url, headers=None, timeout=20):
            seen.append((url, headers))
            return {"data": [{"id": "deepseek-v4-pro"}, {"id": "brand-new-model"}]}
        H._http_json = http
        try:
            n, note = H.refresh_models(self.root, "opencode-go", {})          # no key: models.dev only
            self.assertEqual(n, 3)                                         # gemini's API is not supported
            go = {m["id"]: m for m in H.providers(self.root)["opencode-go"]["models"]}
            self.assertEqual((go["deepseek-v4-pro"]["context"], go["deepseek-v4-pro"]["output"]), (1000000, 384000))
            self.assertEqual(go["minimax-m3"]["format"], "messages")
            self.assertEqual(go["gpt-x"]["format"], "responses")
            self.assertFalse(seen)
            n, _ = H.refresh_models(self.root, "opencode-go", {"OPENCODE_API_KEY": "k"})   # with a key: the live list
            self.assertEqual({m["id"] for m in H.providers(self.root)["opencode-go"]["models"]},
                             {"deepseek-v4-pro", "brand-new-model"})
            self.assertEqual(seen[-1][0], "https://opencode.ai/zen/go/v1/models")
            H.refresh_models(self.root, "deepseek", {"DEEPSEEK_API_KEY": "k"})
            self.assertEqual(seen[-1][0], "https://api.deepseek.com/anthropic/v1/models")
            spec = H.resolve(self.root, "harness:opencode-go/deepseek-v4-pro", {"OPENCODE_API_KEY": "k"}, "m")
            self.assertEqual((spec["provider_cfg"]["context"], spec["provider_cfg"]["max_output"]), (1000000, 384000))
        finally:
            H.models_dev, H._http_json = old_dev, old_http

    def test_several_accounts_are_tried_in_order_and_force_the_gateway(self):
        import harness_usage as U
        cfg = H.load(self.root)
        cfg["providers"]["deepseek"] = {"accounts": [{"id": "main", "label": "Main", "key": "DEEPSEEK_API_KEY"},
                                                     {"id": "two", "label": "Work", "key": "DEEPSEEK_API_KEY_2"}],
                                        "active": "two"}
        H.save(self.root, cfg)
        secrets = {"DEEPSEEK_API_KEY": "k1", "DEEPSEEK_API_KEY_2": "secret-two-zz"}
        pc = H.resolve(self.root, "harness:deepseek/deepseek-v4-pro", secrets, "m")["provider_cfg"]
        self.assertEqual([a["id"] for a in pc["accounts"]], ["two", "main"])
        self.assertEqual((pc["api_key"], pc["auth"]), ("secret-two-zz", "gateway"))
        U.mark_exhausted(self.root, "deepseek", "two", "weekly limit reached")
        pc = H.resolve(self.root, "harness:deepseek/deepseek-v4-pro", secrets, "m")["provider_cfg"]
        self.assertEqual(pc["account"], "main")
        self.assertTrue(U.exhausted(self.root, "deepseek", "two")["until"] > time.time() + 6 * 86400)
        # one account with a key: straight to the provider, as before
        pc = H.resolve(self.root, "harness:deepseek/deepseek-v4-pro", {"DEEPSEEK_API_KEY": "k1"}, "m")["provider_cfg"]
        self.assertEqual((pc["auth"], pc["api_key"]), ("api_key", "k1"))
        view = H.public_view(self.root, secrets)
        accs = next(p for p in view["providers"] if p["id"] == "deepseek")["accounts"]
        self.assertEqual([(a["label"], a["active"], bool(a["exhausted"])) for a in accs],
                         [("Work", True, True), ("Main", False, False)])
        self.assertNotIn("secret-two-zz", json.dumps(view))

    def test_usage_is_priced_against_the_allowance(self):
        import harness_usage as U
        with open(U.limits_path(self.root), "w") as fh:
            json.dump({"at": 1, "models": {"deepseek-v4-pro": {"price": {"input": 1.0, "output": 4.0, "cache_read": 0.1},
                                                                "monthly": 15.0}}}, fh)
        now = time.time()
        U.record(self.root, "opencode-go", "main", "deepseek-v4-pro",
                 {"input_tokens": 1_000_000, "output_tokens": 250_000}, t=now - 60)        # $2
        U.record(self.root, "opencode-go", "main", "deepseek-v4-pro", {"input_tokens": 500_000}, t=now - 3 * 86400)  # $0.5
        U.record(self.root, "opencode-go", "other", "deepseek-v4-pro", {"input_tokens": 9_000_000}, t=now - 60)
        u = U.summary(self.root, "opencode-go", "main", "deepseek-v4-pro")
        self.assertEqual(u["windows"]["5h"]["spent"], 2.0)
        self.assertEqual(u["windows"]["5h"]["allowance"], 3.0)          # 20% of $15
        self.assertEqual(u["windows"]["5h"]["left_pct"], 33)
        self.assertEqual(u["windows"]["week"]["spent"], 2.5)
        self.assertEqual(u["windows"]["month"]["left_pct"], 83)
        self.assertTrue(U.is_quota_error(429, "You have exceeded your 5-hour usage limit"))
        self.assertFalse(U.is_quota_error(429, "Too many requests, slow down"))
        self.assertFalse(U.is_quota_error(400, "bad request"))
        self.assertEqual(U._dollars("$15 $60 4x · Ends Sep 20", min), 15.0)
        go = json.dumps({"type": "error", "error": {"type": "GoUsageLimitError", "message": "Subscription quota exceeded."},
                         "metadata": {"workspace": "w", "limitName": "weekly"}})
        self.assertEqual(U.quota_block(429, go, "3600"), 3600.0)            # retry-after wins
        self.assertEqual(U.quota_block(429, go), 7 * 86400)                   # else the window it names
        self.assertEqual(U.quota_block(429, json.dumps({"error": {"type": "RateLimitError", "message": "Rate limit exceeded"}}), "20"), 20.0)
        self.assertIsNone(U.quota_block(500, "upstream exploded"))

    def test_claude_subscription_needs_no_key(self):
        spec = H.resolve(self.root, "harness:claude/opus", {}, "m")
        pc = spec["provider_cfg"]
        self.assertTrue(pc["subscription"])
        self.assertEqual((pc["model"], pc["api_key"]), ("opus", ""))
        self.assertEqual(H.find(self.root, "claude sonnet subscription", {}, "m")["id"], "harness:claude/sonnet")
        old, H.claude_login = H.claude_login, (lambda max_age=120: "yes")
        try:
            self.assertEqual(H.find(self.root, "claude opus", {"OPENCODE_API_KEY": "k"}, "m")["id"], "harness:claude/opus")
        finally:
            H.claude_login = old

    def test_public_view_has_no_key_values(self):
        view = H.public_view(self.root, {"OPENCODE_API_KEY": "sk-secret-value"})
        self.assertNotIn("sk-secret-value", json.dumps(view))
        self.assertTrue(next(p for p in view["providers"] if p["id"] == "opencode-go")["key_set"])


if __name__ == "__main__":
    unittest.main()
