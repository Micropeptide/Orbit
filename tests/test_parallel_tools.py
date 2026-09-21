"""Read-only calls in one round run together. A round that asks for five greps used to
cost the sum of their latencies; it now costs the longest of them — but only when every
call in the round is safe to run beside another."""
import json, os, sys, tempfile, threading, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bin"))
import qqcore as q


class TestWhoMayRunTogether(unittest.TestCase):
    def test_reading_is_fine(self):
        self.assertTrue(q._parallel_ok("read_file", {"path": "/etc/hosts"}))
        self.assertTrue(q._parallel_ok("grep_files", {"query": "x"}))

    def test_writing_is_not(self):
        self.assertFalse(q._parallel_ok("write_file", {"path": "/tmp/x", "text": "y"}))
        self.assertFalse(q._parallel_ok("edit_file", {"path": "/tmp/x"}))
        # run_shell is judged by its command line, not by its name: `ls` reads,
        # `rm -rf` does not, and a command nobody classified claims nothing
        self.assertTrue(q._parallel_ok("run_shell", {"command": "ls"}))
        self.assertFalse(q._parallel_ok("run_shell", {"command": "rm -rf build"}))
        self.assertFalse(q._parallel_ok("run_shell", {"command": "ls > out.txt"}))
        self.assertFalse(q._parallel_ok("run_shell", {"command": "samtools sort in.bam"}))

    def test_a_tool_that_would_ask_you_something_is_not(self):
        """An approval prompt has to be answered one at a time."""
        self.assertFalse(q._parallel_ok("self_patch", {"file": "qqcore.py"}))
        self.assertFalse(q._parallel_ok("python", {"code": "import os"}))

    def test_an_unknown_tool_is_not(self):
        self.assertFalse(q._parallel_ok("something_new", {}))


class TestRunningThemTogether(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orbit-par-")
        for i in range(4):
            open(os.path.join(self.tmp, f"f{i}.txt"), "w").write(f"file {i}\n")
        self.calls = [({"id": f"c{i}", "function": {"name": "read_file"}}, "read_file",
                       {"path": os.path.join(self.tmp, f"f{i}.txt")}) for i in range(4)]

    def test_results_come_back_in_the_order_they_were_asked(self):
        msgs = []
        q._run_batch(self.calls, msgs, lambda k, p: None, None, {})
        self.assertEqual([m["tool_call_id"] for m in msgs], ["c0", "c1", "c2", "c3"])

    def test_they_really_do_overlap(self):
        seen = []
        real = q.dispatch
        def slow(fn, args):
            seen.append(threading.current_thread().name)
            time.sleep(0.3)
            return real(fn, args)
        q.dispatch = slow
        self.addCleanup(setattr, q, "dispatch", real)
        msgs = []
        t = time.time()
        q._run_batch(self.calls, msgs, lambda k, p: None, None, {})
        elapsed = time.time() - t
        self.assertLess(elapsed, 0.3 * len(self.calls) * 0.6, "they ran one after another")
        self.assertEqual(len(set(seen)), len(self.calls), "every call had its own thread")

    def test_a_worker_keeps_the_turns_context(self):
        """TURN_CTX is thread-local: a worker without it would lose the chat id and plan
        mode, which is to say the safety checks would read differently inside a thread."""
        q.TURN_CTX.sid = "the-chat"
        q.TURN_CTX.read_only = True
        self.addCleanup(lambda: (setattr(q.TURN_CTX, "sid", None),
                                 setattr(q.TURN_CTX, "read_only", False)))
        inside = {}
        real = q.dispatch
        def peek(fn, args):
            inside["sid"] = getattr(q.TURN_CTX, "sid", None)
            inside["read_only"] = getattr(q.TURN_CTX, "read_only", None)
            return real(fn, args)
        q.dispatch = peek
        self.addCleanup(setattr, q, "dispatch", real)
        q._run_batch(self.calls[:1], [], lambda k, p: None, None, {})
        self.assertEqual(inside["sid"], "the-chat")
        self.assertTrue(inside["read_only"])

    def test_one_call_failing_does_not_lose_the_others(self):
        real = q.dispatch
        def half(fn, args):
            if args.get("path", "").endswith("f1.txt"): raise RuntimeError("disk gone")
            return real(fn, args)
        q.dispatch = half
        self.addCleanup(setattr, q, "dispatch", real)
        msgs = []
        q._run_batch(self.calls, msgs, lambda k, p: None, None, {})
        self.assertEqual(len(msgs), 4)
        bad = [m for m in msgs if "disk gone" in str(m.get("content"))]
        self.assertEqual(len(bad), 1)


if __name__ == "__main__":
    unittest.main()
