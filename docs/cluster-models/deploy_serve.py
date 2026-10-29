#!/usr/bin/env python3
"""Put a new serve.sbatch on the cluster, but only after vLLM has parsed its arguments there.

    python3 docs/cluster-models/deploy_serve.py [HOST] [MODEL_DIR]

Uses Orbit's shared ssh connection (one login, however many steps). Steps: upload as serve.sbatch.new, check
the bash syntax, parse the exact vLLM arguments on a node with the real vllm (an unknown flag would otherwise
only show after minutes of loading, and with the log off, not at all), keep the old script as serve.sbatch.bak,
then move the new one into place. Nothing is started."""
import os, subprocess, sys

HOST = sys.argv[1] if len(sys.argv) > 1 else "hpc"
D = sys.argv[2] if len(sys.argv) > 2 else "/path/to/project/user/Models/qwen-server"
HERE = os.path.dirname(os.path.abspath(__file__))
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-o", "ControlMaster=auto",
       "-o", "ControlPath=~/.ssh/cm-orbit-%C", "-o", "ControlPersist=300", HOST]

CHECK = r'''
import json, sys
try:
    from vllm.utils.argparse_utils import FlexibleArgumentParser
except Exception:
    from vllm.utils import FlexibleArgumentParser
try:
    from vllm.entrypoints.launchers.cli_args import make_arg_parser      # vLLM 0.32
except Exception:
    from vllm.entrypoints.openai.cli_args import make_arg_parser         # older
D = sys.argv[1]
base = [D + "/model", "--served-model-name", "qwen", "--host", "127.0.0.1", "--port", "30000", "--api-key", "k",
        "--max-num-seqs", "32", "--max-model-len", "262144", "--gpu-memory-utilization", "0.90",
        "--max-num-batched-tokens", "16384", "--tensor-parallel-size", "1",
        "--reasoning-parser", "qwen3", "--enable-auto-tool-choice", "--tool-call-parser", "qwen3_coder",
        "--speculative-config", json.dumps({"method": "mtp", "num_speculative_tokens": 2}),
        "--override-generation-config", json.dumps({"temperature": 0.6, "top_p": 0.95, "top_k": 20}),
        "--no-enable-log-requests"]
extras = {"default": [], "fp8 kv": ["--kv-cache-dtype", "fp8"], "async": ["--async-scheduling"],
          "eager": ["--enforce-eager"], "keep log": ["--enable-log-requests"]}
bad = 0
for name, extra in extras.items():
    p = make_arg_parser(FlexibleArgumentParser())
    try:
        args = [a for a in base if a != "--no-enable-log-requests"] + extra if name == "keep log" else base + extra
        p.parse_args(args)
        print("OK  ", name)
    except SystemExit:
        print("FAIL", name); bad += 1
sys.exit(1 if bad else 0)
'''


def run(cmd, **kw):
    return subprocess.run(SSH + [cmd], capture_output=True, text=True, timeout=240, **kw)


def main():
    new = open(os.path.join(HERE, "serve.sbatch")).read()
    r = run(f"cat > {D}/serve.sbatch.new && chmod 600 {D}/serve.sbatch.new && bash -n {D}/serve.sbatch.new && echo SYNTAX_OK", input=new)
    print(r.stdout.strip() or r.stderr.strip())
    if "SYNTAX_OK" not in r.stdout: sys.exit("the script has a syntax error or could not be uploaded")
    # parse the arguments with the real vllm, on a node (not the login node)
    r = run(f"cat > {D}/.argcheck.py", input=CHECK)             # in the project folder: /tmp is not shared with the nodes
    node = run(f"squeue -u $USER -h -n qwen-serve -t RUNNING -o %N | head -1").stdout.strip()
    where = f"ssh -o BatchMode=yes {node} " if node else ""
    r = run(f"{where}'HF_HUB_OFFLINE=1 VLLM_NO_USAGE_STATS=1 HOME=/tmp timeout 200 {D}/venv/bin/python {D}/.argcheck.py {D} 2>&1 | grep -E \"^(OK|FAIL)|Error\"; rm -f {D}/.argcheck.py'")
    print(r.stdout.strip() or r.stderr.strip())
    if "FAIL" in r.stdout or "Error" in r.stdout or "OK" not in r.stdout: sys.exit("vLLM did not accept the arguments: the old script stays")
    r = run(f"cd {D} && cp -p serve.sbatch serve.sbatch.bak && mv serve.sbatch.new serve.sbatch && echo DEPLOYED")
    print(r.stdout.strip() or r.stderr.strip())


if __name__ == "__main__":
    main()
