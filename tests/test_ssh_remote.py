"""Claude Code chats on another machine over SSH (bin/ssh_remote.py): the remote
wrapper, run here with a stand-in for `claude` (no SSH, no network)."""
import base64, json, os, shutil, stat, subprocess, sys, tempfile, time, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin"))
import ssh_remote as R        # noqa: E402


def _alive(pid):
    try: os.kill(pid, 0); return True
    except ProcessLookupError: return False


class TestRemoteWrapper(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orbit-ssh-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.fake = os.path.join(self.tmp, "claude")
        with open(self.fake, "w") as fh:
            fh.write("#!/bin/bash\n"
                     "echo \"pwd=$(pwd)\"\n"
                     "echo \"args=$*\"\n"
                     "echo \"token=$CLAUDE_CODE_OAUTH_TOKEN\"\n"
                     "echo \"url=$ANTHROPIC_BASE_URL\"\n"
                     "read -r line; echo \"stdin=$line\"\n"
                     "if [ \"$1\" = wait ]; then sleep 60 & wait; fi\n")
        os.chmod(self.fake, os.stat(self.fake).st_mode | stat.S_IEXEC)

    def start(self, args, env, cwd):
        # what ssh would run on the host
        return subprocess.Popen(["bash", "-c", R.WRAPPER, "orbit", *args], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)

    def test_environment_arrives_on_input_and_claude_runs_in_the_folder(self):
        work = os.path.join(self.tmp, "proj with space")
        p = self.start(["--print", "it's quoted"], {}, work)
        env = {"ORBIT_CLAUDE": self.fake, "ORBIT_CWD": work,
               "CLAUDE_CODE_OAUTH_TOKEN": "sk-secret 'x'", "ANTHROPIC_BASE_URL": "http://127.0.0.1:41234/h/opencode-go"}
        out, err = p.communicate(R.env_line(env).encode() + b'{"type":"user"}\n', timeout=30)
        text = out.decode()
        self.assertIn(f"pwd={os.path.realpath(work)}", text.replace(self.tmp, os.path.realpath(self.tmp)))
        self.assertIn("args=--print it's quoted", text)
        self.assertIn("token=sk-secret 'x'", text)
        self.assertIn('stdin={"type":"user"}', text)
        self.assertEqual(p.returncode, 0, err.decode())

    def test_the_token_is_never_on_the_command_line(self):
        argv_seen = []
        old = subprocess.Popen
        class Fake:
            def __init__(self, argv, **kw):
                argv_seen.extend(argv); self.stdin = open(os.devnull, "wb")
        subprocess.Popen = Fake
        try:
            R.popen("somehost", "/opt/claude", "~/x", ["--print"], {"CLAUDE_CODE_OAUTH_TOKEN": "sk-very-secret"},
                    forward=(40000, 8897))
        finally:
            subprocess.Popen = old
        joined = " ".join(argv_seen)
        self.assertNotIn("sk-very-secret", joined)
        self.assertIn("-R 40000:127.0.0.1:8897".replace(" ", " "), " ".join(argv_seen))
        self.assertIn("ExitOnForwardFailure=yes", joined)

    def test_a_dropped_connection_ends_claude_and_its_children(self):
        # the wrapper watches its parent: here a bash in between plays sshd's part
        work = self.tmp
        marker = os.path.join(self.tmp, "child.pid")
        with open(self.fake, "a") as fh:
            fh.write(f"sleep 300 & echo $! > {marker}; wait\n")
        middle = subprocess.Popen(["bash", "-c", 'bash -c "$0" orbit x <&0 & wait', R.WRAPPER], stdin=subprocess.PIPE,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        middle.stdin.write(R.env_line({"ORBIT_CLAUDE": self.fake, "ORBIT_CWD": work}).encode() + b"go\n")
        middle.stdin.flush()
        for _ in range(50):
            if os.path.exists(marker) and open(marker).read().strip(): break
            time.sleep(0.1)
        child = int(open(marker).read().strip())
        os.kill(middle.pid, 9)                               # the connection goes away (only sshd's stand-in)
        gone = False
        time.sleep(0.5)
        self.assertTrue(os.path.exists(f"/proc/{child}") or _alive(child), "ended too early: not the watchdog")
        for _ in range(150):                                 # the watchdog checks every 5 s
            try: os.kill(child, 0)
            except ProcessLookupError: gone = True; break
            time.sleep(0.1)
        if not gone:
            try: os.kill(child, 9)
            except ProcessLookupError: pass
        self.assertTrue(gone, "claude's child outlived the connection")

    def test_remote_env_keeps_only_what_claude_needs(self):
        env = R.remote_env({"PATH": "/usr/bin", "HOME": "/Users/me", "ANTHROPIC_BASE_URL": "u",
                            "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "1", "CLAUDE_CODE_ENTRYPOINT": "desktop",
                            "DISABLE_TELEMETRY": "1", "SECRET_OTHER": "x"})
        self.assertEqual(set(env), {"ANTHROPIC_BASE_URL", "CLAUDE_CODE_MAX_CONTEXT_TOKENS", "DISABLE_TELEMETRY"})
        self.assertFalse(R.valid_host("host; rm -rf /"))
        self.assertTrue(R.valid_host("cluster-login.example.edu"))


if __name__ == "__main__":
    unittest.main()
