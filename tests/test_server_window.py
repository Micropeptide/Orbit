"""The context window Orbit shows for a model on a server of yours is the one the server holds, not the 128,000 that
Claude Code reports for every endpoint it cannot know (Settings -> Cluster models keeps them in step)."""
import json, os, sys, tempfile, shutil, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin"))
import harness as H                    # noqa: E402
import claude_engine as CE             # noqa: E402
import modelserver as MS               # noqa: E402


def custom(window=262144):
    return {"hpc": {"label": "Cluster", "base": "http://127.0.0.1:8012/v1", "key": "K", "auth": "gateway", "small": "qwen",
                         "models": [{"id": "qwen", "format": "messages", "context": window, "label": "Qwen"}],
                         "env": {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "215000"}}}


class TestWindow(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(); os.makedirs(os.path.join(self.root, "config"))
        self.addCleanup(shutil.rmtree, self.root, True)
        saved = H._learned_path                       # this test's own file, not the run's shared one (see conftest)
        H._learned_path = lambda root: os.path.join(root, "config", "learned-windows.json")
        self.addCleanup(setattr, H, "_learned_path", saved)
        H.save(self.root, {"custom": custom(), "providers": {}, "hidden": [], "contexts": {}, "gateway_port": 8897, "proxy": "", "accounts_policy": {}})
        json.dump({"hpc/qwen": 128000, "claude/opus": 1000000}, open(os.path.join(self.root, "config", "learned-windows.json"), "w"))

    def window(self): return H.providers(self.root)["hpc"]["models"][0]["context"]

    def test_what_claude_code_reported_does_not_override_a_custom_providers_window(self):
        self.assertEqual(self.window(), 262144)

    def test_a_fetched_model_list_does_not_bring_back_a_default_window(self):
        """The list fetched from the server has no window in it of its own; the default 128,000 replaced the stated one."""
        os.makedirs(os.path.dirname(H._fetched_path(self.root)), exist_ok=True)
        json.dump({"hpc": {"at": 1, "source": "live", "models": [{"id": "qwen", "format": "chat", "label": "Qwen", "context": 128000}]}},
                  open(H._fetched_path(self.root), "w"))
        self.assertEqual(self.window(), 262144)

    def test_a_server_that_reports_its_window_in_its_model_list_is_believed(self):
        import http.server, threading
        class Models(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                b = json.dumps({"data": [{"id": "qwen", "max_model_len": 65536}]}).encode()
                self.send_response(200); self.send_header("content-length", str(len(b))); self.end_headers(); self.wfile.write(b)
        srv = http.server.HTTPServer(("127.0.0.1", 0), Models); threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        cfg = H.load(self.root); cfg["custom"]["hpc"]["base"] = f"http://127.0.0.1:{srv.server_port}/v1"
        cfg["custom"]["hpc"]["models"] = []; H.save(self.root, cfg)
        saved = H._fetched_path; H._fetched_path = lambda root: os.path.join(root, "config", "harness-models.json")
        self.addCleanup(setattr, H, "_fetched_path", saved)
        n, note = H.refresh_models(self.root, "hpc", secrets={"K": "key"})
        self.assertEqual(H.fetched(self.root)["hpc"]["models"][0]["context"], 65536)

    def test_the_windows_it_reports_for_its_own_models_still_count(self):
        self.assertEqual(H.learned_windows(self.root)["claude/opus"], 1000000)

    def test_the_servers_window_is_written_through_with_a_compaction_point_below_it(self):
        self.assertTrue(H.sync_server_window(self.root, "hpc", "qwen", 131072))
        c = H.load(self.root)["custom"]["hpc"]
        self.assertEqual(c["models"][0]["context"], 131072)
        self.assertEqual(int(c["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"]), int(131072 * 0.82))
        self.assertNotIn("hpc/qwen", H.learned_windows(self.root))
        self.assertFalse(H.sync_server_window(self.root, "hpc", "qwen", 131072))        # nothing more to change
        self.assertFalse(H.sync_server_window(self.root, "nobody", "qwen", 131072))

    def test_an_old_override_is_dropped_because_it_would_hide_the_truth(self):
        cfg = H.load(self.root); cfg["contexts"]["hpc/qwen"] = 100000; H.save(self.root, cfg)
        H.sync_server_window(self.root, "hpc", "qwen", 262144)
        self.assertEqual(H.load(self.root)["contexts"], {})

    def test_the_engines_report_for_such_a_model_is_not_kept(self):
        saved = (CE.Q.ROOT, dict(CE.Q.SESSION_WINDOW), CE.set_chat_pref, CE.chat_prefs)
        CE.Q.ROOT = self.root; CE.Q.SESSION_WINDOW["c1"] = 128000
        calls = []
        CE.set_chat_pref = lambda sid, **kw: calls.append((sid, kw)); CE.chat_prefs = lambda sid=None: {"context_window": 128000}
        try:
            CE.note_context_window("c1", {"modelUsage": {"qwen": {"contextWindow": 128000}}}, model_hint="harness:hpc/qwen")
            self.assertNotIn("c1", CE.Q.SESSION_WINDOW); self.assertEqual(calls, [("c1", {"context_window": None})])
            self.assertEqual(H.learned_windows(self.root).get("hpc/qwen"), 128000)       # (the old file, untouched here)
            calls.clear()
            CE.note_context_window("c2", {"modelUsage": {"opus": {"contextWindow": 1000000}}}, model_hint="harness:claude/opus")
            self.assertEqual(CE.Q.SESSION_WINDOW["c2"], 1000000)                              # its own models still report truly
        finally:
            CE.Q.ROOT, CE.set_chat_pref, CE.chat_prefs = saved[0], saved[2], saved[3]
            CE.Q.SESSION_WINDOW.clear(); CE.Q.SESSION_WINDOW.update(saved[1])


class TestServerTellsOrbit(unittest.TestCase):
    def test_orbit_is_told_once_per_job_and_size(self):
        from test_modelserver import FakeWorld
        tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, tmp, True)
        w = FakeWorld(); told = []
        m = MS.Manager(os.path.join(tmp, "ms.json"), w, now=lambda: 1.0e9, on_window=lambda s, n: told.append((s["provider"], s["model"], n)))
        m.start("qwen"); w.job.update(state="RUNNING", node="g1"); w.run_file = "g1 1 k"; w.model_up = True
        m.tick("qwen"); m.tick("qwen")
        self.assertEqual(told, [("hpc", "qwen", 262144)])
        w.max_len = 131072; m.tick("qwen")
        self.assertEqual(told[-1], ("hpc", "qwen", 131072))


if __name__ == "__main__":
    unittest.main()
