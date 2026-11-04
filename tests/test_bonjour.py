import os, sys, unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))
import remote as R


class Bonjour(unittest.TestCase):
    def test_the_announcement_is_tied_to_this_server_and_stale_ones_are_cleared_first(self):
        calls = {"run": [], "popen": []}
        with mock.patch.object(R.os.path, "exists", return_value=True), \
             mock.patch.object(R.subprocess, "run", side_effect=lambda a, **k: calls["run"].append(a)), \
             mock.patch.object(R.subprocess, "Popen", side_effect=lambda a, **k: calls["popen"].append(a) or mock.Mock(poll=lambda: None)):
            self.assertTrue(R.advertise(8899, "Test Mac"))
        self.assertTrue(any("pkill" in a[0] and "_orbit._tcp" in a[-1] for a in calls["run"]), "an earlier one is ended first")
        argv = calls["popen"][0]
        self.assertEqual(argv[0], "/bin/sh")
        self.assertIn("kill -0", argv[2], "it ends itself when the server does")
        self.assertEqual(argv[4:], [str(os.getpid()), "Orbit on Test Mac", "8899"], "the server's pid, the name and the port are arguments, never part of the script")
        R._BONJOUR["proc"] = None


if __name__ == "__main__":
    unittest.main()
