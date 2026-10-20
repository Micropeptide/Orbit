"""Gemini as a provider: its models and their real token limits come from Google, and a model
like gemini-3.8-flash can drive Claude Code through Orbit's gateway.

Google's answers are made up here; nothing reaches the network.
"""
import json, os, shutil, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))

import harness as H

LIST = {"models": [
    {"name": "models/gemini-3.8-flash", "displayName": "Gemini 3.8 Flash", "inputTokenLimit": 1048576,
     "outputTokenLimit": 65536, "thinking": True, "supportedGenerationMethods": ["generateContent", "countTokens"]},
    {"name": "models/gemini-3.1-pro-preview", "displayName": "Gemini 3.1 Pro Preview", "inputTokenLimit": 2097152,
     "outputTokenLimit": 65536, "thinking": True, "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-embedding-001", "displayName": "Embedding", "inputTokenLimit": 2048,
     "supportedGenerationMethods": ["embedContent"]},
    {"name": "models/gemini-3.5-flash-preview-tts", "displayName": "TTS", "inputTokenLimit": 8192,
     "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-3-pro-image-preview", "displayName": "Image", "inputTokenLimit": 65536,
     "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemma-3-27b-it", "displayName": "Gemma", "inputTokenLimit": 131072,
     "supportedGenerationMethods": ["generateContent"]},
]}


class Root(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="orbit-gemini-")
        self.addCleanup(shutil.rmtree, self.root, True)
        os.makedirs(os.path.join(self.root, "config"))
        json.dump({}, open(os.path.join(self.root, "config", "models-dev.json"), "w"))     # no catalogue to fetch
        self.asked = []
        saved = H._http_json
        def fake(url, headers=None, timeout=20):
            self.asked.append((url, dict(headers or {})))
            return LIST
        H._http_json = fake
        self.addCleanup(setattr, H, "_http_json", saved)


class TestTheList(Root):
    def test_only_models_that_chat_and_their_real_limits(self):
        got = {m["id"]: m for m in H.gemini_models("k")}
        self.assertEqual(sorted(got), ["gemini-3.1-pro-preview", "gemini-3.8-flash"])
        self.assertEqual((got["gemini-3.8-flash"]["context"], got["gemini-3.8-flash"]["output"]), (1048576, 65536))
        self.assertEqual(got["gemini-3.1-pro-preview"]["context"], 2097152)        # not a guess of a million
        self.assertTrue(got["gemini-3.8-flash"]["reasoning"])
        self.assertEqual(got["gemini-3.8-flash"]["label"], "Gemini 3.8 Flash")

    def test_the_key_goes_in_a_header_not_the_address(self):
        H.gemini_models("secret-key")
        url, headers = self.asked[0]
        self.assertNotIn("secret-key", url)
        self.assertEqual(headers["x-goog-api-key"], "secret-key")


class TestAsAProvider(Root):
    def test_it_is_a_gateway_provider_with_models_before_any_key(self):
        p = H.providers(self.root)["gemini"]
        self.assertEqual((p["auth"], p["key"]), ("gateway", "GEMINI_API_KEY"))
        self.assertTrue(p["base"].endswith("/v1beta/openai"))
        ids = [m["id"] for m in p["models"]]
        self.assertIn("gemini-3.8-flash", ids)
        self.assertTrue(all(m["format"] == "chat" for m in p["models"]))

    def test_refreshing_takes_the_models_and_limits_google_reports(self):
        n, note = H.refresh_models(self.root, "gemini", {"GEMINI_API_KEY": "k"})
        self.assertEqual(n, 2)
        p = H.providers(self.root)["gemini"]
        by = {m["id"]: m for m in p["models"]}
        self.assertEqual(sorted(by), ["gemini-3.1-pro-preview", "gemini-3.8-flash"])
        self.assertEqual(by["gemini-3.1-pro-preview"]["context"], 2097152)
        self.assertEqual(by["gemini-3.8-flash"]["format"], "chat")

    def test_the_offline_catalogue_is_filtered_the_same_way(self):
        dev = {"google": {"models": {
            "gemini-3.8-flash": {"name": "Gemini 3.8 Flash", "limit": {"context": 1048576, "output": 65536}},
            "gemini-2.5-flash-preview-tts": {"name": "TTS", "limit": {"context": 8000}},
            "gemini-2.5-flash-image": {"name": "Nano Banana", "limit": {"context": 33000}},
            "deep-research-preview": {"name": "Deep Research"},
            "gemma-3-27b-it": {"name": "Gemma"}}}}
        json.dump(dev, open(os.path.join(self.root, "config", "models-dev.json"), "w"))
        n, _ = H.refresh_models(self.root, "gemini", {})            # no key: the catalogue is all there is
        self.assertEqual(n, 1)
        (m,) = H.providers(self.root)["gemini"]["models"]
        self.assertEqual((m["id"], m["context"], m["format"]), ("gemini-3.8-flash", 1048576, "chat"))
        self.assertEqual(self.asked, [])

    def test_without_a_key_or_a_catalogue_the_preset_list_stands(self):
        self.assertEqual(H.refresh_models(self.root, "gemini", {})[0], 0)
        self.assertEqual(self.asked, [])
        self.assertEqual(len(H.providers(self.root)["gemini"]["models"]), 7)

    def test_a_model_drives_claude_code_through_the_gateway_with_its_window(self):
        H.refresh_models(self.root, "gemini", {"GEMINI_API_KEY": "k"})
        spec = H.resolve(self.root, "harness:gemini/gemini-3.8-flash", {"GEMINI_API_KEY": "k"})
        self.assertEqual(spec["context"], 1048576)
        pc = spec["provider_cfg"]
        self.assertEqual((pc["auth"], pc["format"], pc["provider"]), ("gateway", "chat", "gemini"))
        self.assertTrue(spec["ready"])

    def test_not_ready_without_a_key(self):
        spec = H.resolve(self.root, "harness:gemini/gemini-3.8-flash", {})
        self.assertFalse(spec["ready"])


if __name__ == "__main__":
    unittest.main()
