"""The Claude Code harness provider registry (bin/harness.py)."""
import json, os, shutil, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin"))
import harness as H                    # noqa: E402


class TestRegistry(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="orbit-harness-")
        os.makedirs(os.path.join(self.root, "config"))
        self.addCleanup(shutil.rmtree, self.root, True)

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

    def test_public_view_has_no_key_values(self):
        view = H.public_view(self.root, {"OPENCODE_API_KEY": "sk-secret-value"})
        self.assertNotIn("sk-secret-value", json.dumps(view))
        self.assertTrue(next(p for p in view["providers"] if p["id"] == "opencode-go")["key_set"])


if __name__ == "__main__":
    unittest.main()
