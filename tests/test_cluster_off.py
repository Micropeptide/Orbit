"""Without a cluster set up, the Scheduled pane has no cluster section to show.

It showed "All login nodes failed:" in red to everyone who never configured a cluster:
the job list asked ssh with no hosts at all.
"""
import os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))

import qqcore as q


class TestNoCluster(unittest.TestCase):
    def test_no_hosts_means_off_not_an_error(self):
        saved = q.CLUSTER_HOSTS; q.CLUSTER_HOSTS = []
        self.addCleanup(setattr, q, "CLUSTER_HOSTS", saved)
        called = []
        saved_ssh = q._h2_ssh; q._h2_ssh = lambda *a, **k: called.append(a) or ""
        self.addCleanup(setattr, q, "_h2_ssh", saved_ssh)
        self.assertEqual(q.cluster_jobs_detailed(), {"off": True, "jobs": []})
        self.assertEqual(called, [])                    # and nothing was tried


if __name__ == "__main__":
    unittest.main()
