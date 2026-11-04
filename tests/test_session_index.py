import json, os, sys, tempfile, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))
import qqcore as q


class SessionIndex(unittest.TestCase):
    """The chat list survives a restart: only chats that changed since are read again."""
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.sess = os.path.join(self.d, "sessions"); os.makedirs(self.sess)
        self.saved = (q.SESSIONS, q.ROOT, dict(q._SESS_ROWS), dict(q._SESS_INDEX), dict(q._SESS_CACHE))
        q.SESSIONS, q.ROOT = self.sess, self.d
        q._SESS_ROWS.clear(); q._SESS_CACHE.update(key=None, val=[]); q._SESS_INDEX.update(loaded=False, saved_at=0.0)
        self.addCleanup(self._restore)
        for i in range(3):
            json.dump({"title": f"chat {i}", "messages": [{"role": "user", "content": "hi"}]}, open(os.path.join(self.sess, f"c{i}.json"), "w"))

    def _restore(self):
        q.SESSIONS, q.ROOT = self.saved[0], self.saved[1]
        q._SESS_ROWS.clear(); q._SESS_ROWS.update(self.saved[2]); q._SESS_INDEX.update(self.saved[3]); q._SESS_CACHE.update(self.saved[4])

    def _fresh_start(self):
        q._SESS_ROWS.clear(); q._SESS_CACHE.update(key=None, val=[]); q._SESS_INDEX.update(loaded=False, saved_at=0.0)

    def test_a_restart_reads_only_what_changed(self):
        for i in range(3, 120):        # more than one checkpoint's worth: the saved index must hold all of them
            json.dump({"title": f"chat {i}", "messages": []}, open(os.path.join(self.sess, f"c{i}.json"), "w"))
        rows = q._session_rows()
        self.assertEqual(len(rows), 120)
        saved = json.load(open(os.path.join(self.d, "cache", "sessions-index.json")))
        self.assertEqual(len(saved["rows"]), 120)
        self._fresh_start()                                    # a new Orbit process
        opened = []
        real = json.load
        def spy(fh, *a, **k):
            name = getattr(fh, "name", "")
            if name.startswith(self.sess): opened.append(os.path.basename(name))
            return real(fh, *a, **k)
        json.load = spy
        self.addCleanup(setattr, json, "load", real)
        try:
            rows = q._session_rows()
            self.assertEqual(len(rows), 120); self.assertEqual(opened, [], "nothing was parsed: the index served it")
            with open(os.path.join(self.sess, "c1.json"), "w") as fh:
                json.dump({"title": "renamed", "messages": [{"role": "user", "content": "hi again!!"}]}, fh)
            opened.clear(); q._SESS_CACHE.update(key=None)
            titles = sorted(r["title"] for r in q._session_rows())
            self.assertEqual(opened, ["c1.json"], "only the changed chat was read")
            self.assertIn("renamed", titles); self.assertEqual(len(titles), 120)
        finally:
            json.load = real

    def test_a_damaged_index_is_ignored(self):
        os.makedirs(os.path.join(self.d, "cache"), exist_ok=True)
        open(os.path.join(self.d, "cache", "sessions-index.json"), "w").write("{not json")
        self._fresh_start()
        self.assertEqual(len(q._session_rows()), 3)


if __name__ == "__main__":
    unittest.main()
