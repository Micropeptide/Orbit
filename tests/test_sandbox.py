"""The sandbox copy of Orbit: a simulated cluster, and nothing that reaches outside."""
import json, os, sys, tempfile, shutil, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin"))
import modelserver as MS               # noqa: E402


class TestSimulatedCluster(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.t = [1.0e9]
        self.w = MS.SimWorld(os.path.join(self.tmp, "world.json"), now=lambda: self.t[0])
        self.m = MS.Manager(os.path.join(self.tmp, "ms.json"), self.w, now=lambda: self.t[0])

    def at(self, s): self.t[0] += s; return self.m.tick("qwen")

    def test_a_job_queues_loads_answers_and_runs_out(self):
        self.m.start("qwen", overrides={"max_model_len": 65536, "time_limit_h": 1})
        self.assertEqual(self.m.status("qwen")["state"], "queued")
        self.assertEqual(self.at(10)["state"], "loading")
        st = self.at(25)
        self.assertEqual(st["state"], "ready"); self.assertEqual(st["info"]["max_model_len"], 65536)
        self.assertGreater(self.at(120)["stats"]["decode_tps"], 0)
        self.at(1); self.m.health(self.m.server("qwen"), self.m.rt["qwen"])
        self.assertTrue(self.m.status("qwen")["health"]["ok"])
        self.t[0] += 3700
        self.assertEqual(self.m.tick("qwen")["state"], "stopped")
        self.assertEqual(self.m.rt["qwen"]["last_end"], "timeout")

    def test_stop_ends_it_and_start_twice_is_refused(self):
        self.m.start("qwen")
        with self.assertRaises(RuntimeError): self.m.start("qwen")
        self.at(40); self.m.stop("qwen"); self.at(1); self.assertEqual(self.m.status("qwen")["state"], "stopping")
        self.assertEqual(self.at(6)["state"], "stopped")

    def test_it_never_runs_anything_outside_the_process(self):
        import subprocess
        real = subprocess.run
        subprocess.run = lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran a real command: %r" % (a,)))
        self.m.cfg["servers"][0]["notify"]["email"] = "someone@example.com"        # a release ships no default address
        try:
            self.m.start("qwen"); self.at(40); self.m.test_email("qwen"); self.m.stop("qwen"); self.m.close_connections("qwen")
        finally: subprocess.run = real
        self.assertTrue(any(l.startswith("mail to") for l in self.w.log))


if __name__ == "__main__":
    unittest.main()
