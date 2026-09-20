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

    def test_no_folder_no_switch(self):
        self.assertIn("error", q.switch_local_model("not-here"))


if __name__ == "__main__":
    unittest.main()
