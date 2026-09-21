"""Model folders MTPLX keeps on this Mac: which of them are models you can pick,
what they are called in the picker, and refusing a switch MTPLX would fail. A
temporary folder of fake models; MTPLX itself is never run."""
import json, os, shutil, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))
import qqcore as q


class TestLocalModelFolders(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orbit-mtplx-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = q.MTPLX_MODELS
        q.MTPLX_MODELS = self.tmp
        self.addCleanup(setattr, q, "MTPLX_MODELS", saved)
        q._DIR_LABEL.clear(); q._INSPECT.clear()
        self.addCleanup(q._DIR_LABEL.clear)
        self.addCleanup(q._INSPECT.clear)

    def model(self, name, weights=True, quant=None):
        d = os.path.join(self.tmp, name)
        os.makedirs(d)
        if weights: open(os.path.join(d, "model-00001-of-00002.safetensors"), "w").write("x")
        cfg = {"model_type": "qwen3_5"}
        if quant: cfg["quantization"] = {"bits": quant}
        json.dump(cfg, open(os.path.join(d, "config.json"), "w"))
        return d

    def test_a_download_in_progress_is_not_offered_as_a_model(self):
        self.model("orcarouter--Qwen3.8-27B-Uncensored-MLX", quant=4)
        self.model(".staging-orca-4bit", weights=False)      # MTPLX stages into a dot-folder
        self.model("half-arrived", weights=False)            # folder and config, no weights yet
        self.assertEqual(q.local_model_dirs(), ["orcarouter--Qwen3.8-27B-Uncensored-MLX"])

    def test_the_picker_reads_the_model_not_the_folder(self):
        self.model("orcarouter--Qwen3.8-27B-Uncensored-MLX", quant=4)
        self.assertEqual(q.local_dir_label("orcarouter--Qwen3.8-27B-Uncensored-MLX"),
                         "Qwen3.8 27B Uncensored · 4-bit")
        self.model("Someone--Plain-Model")
        self.assertEqual(q.local_dir_label("Someone--Plain-Model"), "Plain Model")

    def test_a_model_mtplx_cannot_run_is_refused_before_anything_stops(self):
        self.model("weird--Model")
        stopped = []
        saved = q.stop_server
        q.stop_server = lambda *a, **k: stopped.append(1)
        self.addCleanup(setattr, q, "stop_server", saved)
        q._INSPECT[(os.path.join(self.tmp, "weird--Model"),
                    os.path.getmtime(os.path.join(self.tmp, "weird--Model", "config.json")))] = {
            "can_run": False, "verified": False, "arch": "", "message": "no MLX implementation"}
        out = q.switch_local_model("weird--Model")
        self.assertIn("cannot run", out["error"])
        self.assertIn("no MLX implementation", out["error"])
        self.assertEqual(stopped, [])              # the running server was left alone

    def test_each_model_keeps_the_draft_depth_measured_for_it(self):
        """MTPLX tunes a draft depth per model; the last model's depth must not be
        carried over to the next one, which used to cost ~13% of its speed."""
        d = self.model("orcarouter--Qwen3.8-27B-Uncensored-MLX", quant=4)
        tuning = os.path.join(self.tmp, "tuning.json")
        json.dump({"records": {
            "small-sample": {"key_material": {"model": d},
                             "payload": {"best": {"depth": 3},
                                         "results": [{"depth": 3, "drafted_by_depth": [4]}]}},
            "real-run": {"key_material": {"model": d},
                         "payload": {"best": {"depth": 2},
                                     "results": [{"depth": 2, "drafted_by_depth": [131]}]}},
            "another-model": {"key_material": {"model": os.path.join(self.tmp, "elsewhere")},
                              "payload": {"best": {"depth": 1},
                                          "results": [{"depth": 1, "drafted_by_depth": [200]}]}},
        }}, open(tuning, "w"))
        saved = q.MTPLX_TUNING
        q.MTPLX_TUNING = tuning
        self.addCleanup(setattr, q, "MTPLX_TUNING", saved)
        # the run with the most drafted tokens wins, not the last one written
        self.assertEqual(q.local_model_depth("orcarouter--Qwen3.8-27B-Uncensored-MLX"), 2)
        self.assertIsNone(q.local_model_depth("never-tuned"))

    def test_switching_writes_that_depth_into_the_settings(self):
        d = self.model("orcarouter--Qwen3.8-27B-Uncensored-MLX", quant=4)
        json.dump({"records": {"r": {"key_material": {"model": d},
                                     "payload": {"best": {"depth": 2},
                                                 "results": [{"depth": 2, "drafted_by_depth": [131]}]}}}},
                  open(os.path.join(self.tmp, "tuning.json"), "w"))
        launch = os.path.join(self.tmp, "launch.json")
        json.dump({"command": "/bin/true", "args": ["serve", "--depth", "3", "--model", "/old"]},
                  open(launch, "w"))
        settings = os.path.join(self.tmp, "settings.json")
        json.dump({"server": {"depth": 3}}, open(settings, "w"))
        for k, v in (("MTPLX_TUNING", os.path.join(self.tmp, "tuning.json")),
                     ("LAUNCH", launch), ("SETTINGS", settings),
                     ("stop_server", lambda *a, **k: "stopped"),
                     ("ensure_model", lambda *a, **k: "served"),
                     # MTPLX itself is not run here: its verdict is stood in for
                     ("local_model_check", lambda d: {"can_run": True, "verified": True})):
            old_v = getattr(q, k)
            setattr(q, k, v)
            self.addCleanup(setattr, q, k, old_v)
        saved_sleep = q.time.sleep
        q.time.sleep = lambda n: None
        self.addCleanup(setattr, q.time, "sleep", saved_sleep)
        saved_S = q.S
        self.addCleanup(setattr, q, "S", saved_S)
        q.S = {"server": {"depth": 3}}          # what is configured now, not this Mac's

        out = q.switch_local_model("orcarouter--Qwen3.8-27B-Uncensored-MLX")
        self.assertEqual(out["depth"], 2)
        self.assertIn("depth 3 → 2", out["note"])
        # the next start composes its arguments from the settings, so that is where it goes
        self.assertEqual(json.load(open(settings))["server"]["depth"], 2)

    def test_the_served_model_is_named_like_the_others(self):
        """MTPLX answers with a short id of its own; the picker should still show the
        name you went looking for."""
        self.model("orcarouter--Qwen3.8-27B-Uncensored-MLX", quant=4)
        for k, v in (("local_model_name", lambda: "orcarouter-qwen3.8-27b-uncensored-mlx"),
                     ("local_model_configured", lambda: "orcarouter--Qwen3.8-27B-Uncensored-MLX"),
                     ("secrets_load", lambda: {})):
            old_v = getattr(q, k); setattr(q, k, v)
            self.addCleanup(setattr, q, k, old_v)
        served = [m for m in q.model_catalogue() if str(m["id"]).startswith("local:")]
        self.assertEqual([m["label"] for m in served], ["Qwen3.8 27B Uncensored · 4-bit"])

    def test_reordering_is_one_write(self):
        """Ten saves raced the Claude-group sync, which reads the list and writes it
        back, and the drag came out looking like it had done nothing."""
        import tempfile as _tf
        path = os.path.join(self.tmp, "projects.json")
        json.dump({"a": {"name": "A", "order": 0}, "b": {"name": "B", "order": 1},
                   "c": {"name": "C", "order": 2}}, open(path, "w"))
        old_p = q.PROJECTS
        q.PROJECTS = path
        self.addCleanup(setattr, q, "PROJECTS", old_p)
        writes = []
        real = q.projects_save
        q.projects_save = lambda d: (writes.append(1), real(d))[1]
        self.addCleanup(setattr, q, "projects_save", real)
        q.projects_reorder(["c", "a", "b"])
        self.assertEqual(len(writes), 1)
        d = json.load(open(path))
        self.assertEqual(sorted(d, key=lambda k: d[k]["order"]), ["c", "a", "b"])
        # a project the page did not know about keeps its place at the end
        json.dump({**d, "z": {"name": "Z", "order": 9}}, open(path, "w"))
        d = q.projects_reorder(["b", "a"])
        self.assertEqual([k for k in sorted(d, key=lambda k: d[k]["order"])], ["b", "a", "c", "z"])

    def test_the_local_window_is_the_one_it_is_served_with(self):
        """The window is a setting; a number written into the harness preset was right
        until someone changed it."""
        import harness as H
        os.makedirs(os.path.join(self.tmp, "config"), exist_ok=True)
        json.dump({"server": {"context_window": 262144}},
                  open(os.path.join(self.tmp, "config", "settings.json"), "w"))
        self.assertEqual(H._local_context(self.tmp), 262144)
        provs = H.providers(self.tmp, "some-local-model")
        self.assertEqual([m["context"] for m in provs["local"]["models"]], [262144])
        json.dump({"server": {}}, open(os.path.join(self.tmp, "config", "settings.json"), "w"))
        self.assertEqual(H._local_context(self.tmp), 131072)          # nothing set: a sane default
        self.assertEqual(H._local_context(os.path.join(self.tmp, "nowhere")), 131072)

    def test_no_folder_no_switch(self):
        self.assertIn("error", q.switch_local_model("not-here"))


if __name__ == "__main__":
    unittest.main()
