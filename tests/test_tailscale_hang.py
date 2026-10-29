"""A hung Tailscale CLI used to cost one 5 s wait per question (about seven in the Phone page): 34 s to open it.
Now a hang costs one short wait, and the other questions answer "not running" at once."""
import os, subprocess, sys, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))

import remote as R


class TestTailscaleHang(unittest.TestCase):
    def setUp(self):
        R._TS_DOWN["until"] = 0.0
        self.addCleanup(lambda: R._TS_DOWN.update(until=0.0))

    def test_one_hang_is_paid_once(self):
        calls = []
        def hang(cmd, **kw):
            calls.append(cmd)
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
        with mock.patch.object(R, "TAILSCALE_BINS", [sys.executable]), mock.patch.object(R.subprocess, "run", hang):
            t = time.time()
            self.assertEqual(R.tailscale_ip(), "")
            self.assertEqual(R.tailscale_name(), "")
            self.assertEqual(R.serve_map(8899), [])
            self.assertEqual(R.alt_urls("tailscale", 8899), [])
            self.assertLess(time.time() - t, 1)
        self.assertEqual(len(calls), 1)          # the first call timed out; the rest never ran

    def test_recovers_after_the_pause(self):
        R._TS_DOWN["until"] = time.time() - 1
        ok = mock.Mock(stdout="100.1.2.3\n")
        with mock.patch.object(R, "TAILSCALE_BINS", [sys.executable]), mock.patch.object(R.subprocess, "run", return_value=ok), \
             mock.patch.object(R, "address_is_local", return_value=True):
            self.assertEqual(R.tailscale_ip(), "100.1.2.3")


if __name__ == "__main__":
    unittest.main()
