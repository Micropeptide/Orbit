"""The model pickers list what runs on this Mac first, then your models on a server, then the rest."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
import qqcore as q


def m(mid, provider, label=""): return {"id": mid, "provider": provider, "provider_label": label or provider}


class TestOrder(unittest.TestCase):
    CAT = [m("claude-cli:x", "claude-cli", "Claude Code CLI"), m("harness:claude/opus", "harness", "Claude Code · Claude"),
           m("hpc:qwen", "hpc", "HPC GPU"), m("local:q", "local", "Local · MTPLX"),
           m("harness:hpc/qwen", "harness", "Claude Code · Qwen · HPC GPU"), m("harness:opencode-go/ds", "harness", "Claude Code · OpenCode Go"),
           m("claude-qwen-cli:q", "claude-qwen-cli", "Claude Code · local Qwen"), m("codex:hpc/qwen", "codex", "Codex · Qwen · HPC GPU"),
           m("harness-direct:hpc/qwen", "harness-direct", "Qwen · HPC GPU")]

    def test_local_then_the_cluster_then_the_rest_each_in_its_own_order(self):
        out = [x["id"] for x in q.order_models(self.CAT, {"hpc"})]
        self.assertEqual(out, ["local:q", "claude-qwen-cli:q",
                               "hpc:qwen", "harness:hpc/qwen", "codex:hpc/qwen", "harness-direct:hpc/qwen",
                               "claude-cli:x", "harness:claude/opus", "harness:opencode-go/ds"])

    def test_nothing_is_lost_and_without_a_cluster_only_local_moves(self):
        out = q.order_models(self.CAT, set())
        self.assertEqual(sorted(x["id"] for x in out), sorted(x["id"] for x in self.CAT))
        self.assertEqual([x["id"] for x in out][:2], ["local:q", "claude-qwen-cli:q"])


if __name__ == "__main__":
    unittest.main()
