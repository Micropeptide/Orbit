# Running a model on the cluster (HPC) and managing it from Orbit

How the Qwen server on HPC is built, how Orbit starts, watches and talks to it, and everything that went
wrong on the way. Written so the next model (another Qwen, Llama, DeepSeek…) can be set up the same way in an
hour instead of an evening.

## 1. The shape of it

```
Orbit (Mac)                         HPC login node           GPU node (g35…)
  Settings → Cluster models           (login.cluster.example.edu)
  bin/modelserver.py  ── ssh ──────►  sbatch / squeue / scancel ──► vLLM on 127.0.0.1:PORT
  model on 127.0.0.1:8012 ◄── ssh -L (Mac → login node → GPU node) ───────┘
  chats: "Qwen · HPC" (provider hpc, base_url http://127.0.0.1:8012/v1, key HPC_LLM_KEY)
```

* The model is a **SLURM job** (`qwen-serve`) running **vLLM** on one GPU. It listens on `127.0.0.1` of the GPU node
  only, behind a random API key, so nobody else on the cluster can use it.
* Orbit reaches it through an **SSH tunnel in two hops**. The GPU node does not accept the Mac's key, the login node's
  credentials do, so the tunnel is `ssh -L 8012:127.0.0.1:PORT login "ssh -N -L PORT:127.0.0.1:PORT gNN"`.
* Everything lives in one folder per model on the project disk, mode `700`:
  `/path/to/project/user/Models/qwen-server/`

  | path | what |
  |---|---|
  | `serve.sbatch` | the launch script (the only file that matters for behaviour) |
  | `model/` | the weights (safetensors + tokenizer + config) |
  | `venv/`, `python/` | the vLLM environment (built once by `build_env.sbatch`) |
  | `cache/` | compiled kernels (torch.compile / triton), kept between jobs: starts are ~3 min faster |
  | `run/<jobid>` | one line `node port key`, written by a running job and deleted when it ends |
  | `logs/` | only when "keep a log" is on; `700`, files older than 14 days are deleted |

## 2. Using it from Orbit

**Settings → Cluster models** (backend `bin/modelserver.py`, route `/api/servers`, config `config/model_servers.json`).

* **Start / Stop / Restart with these settings.** The state comes from the cluster, never from memory: a job started
  by hand, by `hpc-llm start` or by a chat is seen the same way. States: waiting for a GPU → loading the model →
  ready → stopping → stopped / failed / cluster not reachable.
* **Schedule.** Rows with a start time, a stop time and days (or one date). Runs while Orbit is running; a start is
  up to 30 minutes late if Orbit was off at the minute, but never after that day's stop time. A stop done by hand is
  not undone the same day.
* **Settings** (below, §4) are passed to the job at start: *they apply from the next start*. "Restart with these
  settings" does that now.
* **Tell me.** E-mail is sent **by the job itself, on the cluster** with the cluster's `mail`, to
  `user@mail.cluster.example.edu` (the address the cluster delivers to). It does not use any account of yours and
  arrives with the Mac off. Three events: *ready* (context length, node, how long loading took), *stopped* (and why:
  stopped / time limit), *failed* (ended without ever answering). "Send a test" mails from the login node. The Mac
  only adds a desktop notification.
* **Statistics.** From vLLM's `/metrics` over the tunnel (no ssh): decode speed per answer (1 / inter-token latency),
  throughput over the last minute, time to first word, a whole answer, prompt tokens read per second, prompt-cache hit
  rate, context memory in use, look-ahead guesses accepted, running/waiting, totals. They hold counters and timings,
  no chat text.
* **Health.** Every 3 minutes a one-word request is sent through the tunnel and timed ("answers a test request in
  0.4 s"). A server whose GPU has hung still answers `/v1/models`, but not this. Three misses in a row raise a notice.
* **Run a speed test.** Three requests: writing speed, reading a ~25,000-token prompt cold, and the same prompt again
  (cache). The numbers to compare settings by: change one setting, restart, run it again.
* **Renew after the time limit** (setting). A job ends by itself at its time limit (24 h on the `campus` partition).
  With this on, Orbit starts a new one when that happens: *until* a date and time you set, or until you switch it off.
  A job you stopped is never renewed; a failed one is `keep_alive`'s business. There is a gap of about 10 minutes
  (queue + load) between one job and the next, and the e-mail notices say so (stopped: time limit; ready again).
  If the cluster refuses the new job, Orbit tries again every 2 minutes.
* **Keep it running** (setting). If the job fails, or is up but stops answering, Orbit starts it again — twice a day at
  most, and never after you stopped it.
* **Logins to the cluster.** Lists Orbit's own ssh logins (the shared monitor connection, model tunnels, chats running
  there) and closes them. Other programs' logins are shown, never touched. Closing is safe: the next look opens a
  fresh one and a running model keeps running.
* **Add another model.** Name + the model's folder on the cluster. Orbit copies `serve.sbatch` into it, gives it its
  own job name, local port (8013, 8014 …) and key name. Then add it as a provider in `config/models.json`.

### Privacy

Default: **private**. `--no-enable-log-requests`, scratch in the job's own `/work`
folder (removed when the job ends), and the key file removed at the end. The persistent `cache/` holds compiled
kernels only. The server's output is kept for the **start only** (`logs/errors.<job>.log`, setting *Server messages*, on by default): the
filter stops writing for good the moment the server first answers, before any chat can reach it, so it cannot hold chat text (it also
drops prompt/message fields, cuts lines at 300 characters and the file at 4000 lines); after that, output is thrown away. Turning on **Keep a log** adds the server log and a log of every request (*including the text*) in
`logs/`, owner-only. Statistics are on in both modes. Neither mode changes speed.

## 2b. The Cluster page (sidebar "Cluster", `/cluster`)

Backend `bin/cluster.py`, route `/api/cluster`, config `config/cluster.json`, events `config/cluster-events.json`, daily disk readings
`config/cluster-history.json`. One look is **one ssh command** over the shared connection that prints marked sections (`squeue`,
`sacct`, `quota -s`, `df`, `h2 gpus`, `h2 whoami`, `sinfo`, host load) which `cluster.py` parses; cached 8 s, backs off 2 to 15 min when the
cluster does not answer. It shows:

* **Needs a look**: the lab's project disk filling up (97% when this was written), your quota, jobs from the last day that failed, jobs
  waiting, all GPUs you may use already in use.
* **Your jobs** (state, where or why waiting, expected start, time left, what was asked for) with **Why waiting** (`h2 why-pending`),
  **Output** (the end of the job's output file while the scheduler still knows the job), **Cancel** (only your own jobs, validated)
  and **Ask Orbit** (a new chat with the job's record, the cluster's diagnosis and the end of its output already in the composer).
* **Last three days**, with **What went wrong** (`h2 diagnose`) and **Efficiency** (CPU and memory used against asked for, from `sacct`
  steps: it says when a job asked for far more than it used, or came close to its memory).
* **Disk**: home and scratch against their quotas (space and file count), the lab's project disk, how fast each grew over the week, and
  on-demand **Measure** (`du`, 100 s limit: a big home times out and says so).
* **GPUs**: free by model and by node, your per-user limit, and **Where would my job start now?** (fits on which node, by GPUs, memory,
  CPUs, model; says when you ask for more GPUs than you may ever use).
* **Your limits and the queue**: account, fair-share, running jobs and GPUs against your limits, idle CPUs, the longest job allowed.
* **Login node**: how many of your processes of the allowed 1,024 (the old cluster wedged when it filled up), and a list with **Stop** for your
  own stray ones; processes that keep the login alive are not stoppable.
* **What happened**: a log of submitted, started, finished and failed jobs, running jobs that print an error, disks crossing 85% and 95%,
  jobs that waited more than 4 hours. A failed job carries a **cause** from the state, exit code and output (out of memory, time limit,
  node failure, a missing module or file, disk full, a crash...), the usual fix, and (if "Explain failures" is on) a short plain-language
  reading by Orbit's helper model from the cluster's own diagnosis.

* **What is using the disk** (Disk section: "Largest folders", "Who uses it", "My folder"): a small **batch job** (`orbit-du-<key>`, 4 CPUs,
  never on the login node: `du` on this NFS is slow, a 30 GB folder did not finish in 25 s) counts what is directly inside a place, four
  entries at a time, and writes as it goes, so the page shows a partial list that fills in (it asks again every 10 s). The result stays on the
  cluster (`~/.orbit/du/<key>.tsv`) and the page shows it with when it was measured; **nothing is re-measured unless you press Measure / Measure
  again**. Click "Look inside" on a folder to measure that one. For the lab disk the entries are people's folders: the page ranks people by
  how much they use and shows each one's share of the disk. It can take an hour or more and loads the shared disk, so it asks for confirmation.
  Only places inside your home, scratch (`$SCRATCH`) or the lab folder can be measured (checked on the cluster with `readlink -f`).
* **Usage history** (asked for, not automatic): jobs that ran, finished, failed, GPU- and CPU-hours, a bar per day, and per job name how often it
  runs, how it ends, how long it usually waits and runs.
* **A summary each morning** (from 8:00, one notice, only when there is news): what finished overnight, what went wrong, what is still going.

**The watch** (Settings on the page): the queue every 90 s while something of yours is queued or running, every 10 min otherwise; every 5 min the
end of each running job's output is read for errors (once per kind per job). Desktop and phone notices for what you choose (a job starting,
finishing, failing, a running job's error, a disk filling up, a long wait). The model servers' own jobs are left to the Cluster models panel.
In a sandbox copy of Orbit (`ORBIT_SANDBOX=1`) a simulated cluster (`SimCluster`) stands in and nothing touches ssh.

## 3. Setting up a new model (checklist)

1. **Folder.** `mkdir -m 700 /path/to/project/<group>/<you>/Models/<name>`; copy `serve.sbatch` from `qwen-server`.
2. **Environment.** `build_env.sbatch` as a *batch job* (not on a login node): `uv venv --python 3.12`, `uv pip install vllm
   huggingface_hub`. Put uv's cache in the job's `$TMPDIR` (`/work/<user>` cannot be created by hand).
3. **Weights.** `download.sbatch`: `hf download <repo> --local-dir model`. The token in `.hf_token` (mode 600), env
   `HF_HUB_OFFLINE=1` at serve time.
4. **Serve flags.** Edit the `vllm serve` line for the model: `--served-model-name`, the reasoning parser
   (`qwen3`, `deepseek_r1`…) and tool-call parser (`qwen3_coder`, `hermes`…) for its chat template.
5. **Register it in Orbit.** Cluster models → Add another model; then add a provider in `config/models.json`
   (`kind: openai`, `base_url http://127.0.0.1:<port>/v1`, `key: <KEY_NAME>`) with the model's real context length.
6. **First start with "Quick start" (eager) and a log kept**, so a mistake shows up in 2 minutes instead of 10 and
   there is a log to read. Then turn both off.
7. **Try two messages in a chat**, not one (see §6: the second message is where gateway problems show).

## 4. Settings and why

| setting | default | note |
|---|---|---|
| Context length (`MAXLEN`) | 262144 | tokens. Longer leaves less memory for parallel requests |
| Requests at once (`SEQS`) | 32 | must fit the memory: vLLM refuses 1024 when only 998 fit, *after* loading |
| GPU memory share (`GPUUTIL`) | 0.90 | |
| Speculative tokens (`MTP`) | 2 | the model's own look-ahead head; 0 turns it off. Check "accepted" in the statistics |
| Quick start (`EAGER`) | off | skips compile and CUDA graphs: starts in ~2 min, answers slower. For testing |
| Job time limit (`TLIMIT_H`) | 24 | the job ends by itself |
| Privacy (`KEEPLOG`) | private | see above |
| Prompt reading (`BATCHED`) | 16384 | `--max-num-batched-tokens`: prompt tokens per step. Higher reads a long prompt sooner |
| Context memory (`KVDTYPE`) | auto | `fp8` halves the KV cache: twice the context or parallel answers, slightly less exact |
| Sampling (`TEMP`/`TOPP`/`TOPK`) | 0.6 / 0.95 / 20 | server-side defaults (`--override-generation-config`) for requests that do not set them: Qwen's advice when it thinks |
| Async scheduling (`ASYNC`) | off | overlaps scheduling with the GPU; newer, test with Quick start first |
| Renew after the time limit | off | Orbit-side: start again when the limit ends the job; optional end date |
| Keep it running | off | Orbit-side: restart after a failure, twice a day |
| GPUs / CPUs / memory | 1 / 16 / 128 G | `sbatch` flags; GPUs also sets `--tensor-parallel-size` |
| Stop when idle | 0 (never) | minutes without a request, judged from the statistics |

Launch-script details that matter:

* `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` (long contexts fragment memory).
* `TORCHINDUCTOR_COMPILE_THREADS` = the job's CPUs (compiling used one thread).
* Weights are **prefetched in parallel** (`cat shard > /dev/null`) while Python starts: a cold read from the network
  disk took ~5 minutes shard by shard.
* A tiny **warm-up request** after the model answers, so the first real request does not pay for lazy kernels.
* The cache directory is **outside** the job's scratch, so compiled kernels survive between jobs.

## 5. Speed: what is normal

Measured on this setup (one GPU, FP8 27B, MTP 2): **~50 tokens/s** for one answer; a 25,000-token prompt is read in
~3 s the first time and **0.3 s the second time** (prefix cache). Claude Code opens every chat with a ~35,000-token
prompt (its own tools and instructions), so the first message of a chat takes a few seconds and later ones are
cheap. A chat bubble that says "7 tok/s" is mostly that first read, not slow writing.
Cold start from nothing: queue + ~1 min weights (cached) or ~5 min (cold) + ~2.5 min compile + CUDA-graph capture
≈ 8–10 min. With the compile cache and weight prefetch: less.

## 6. Things that went wrong (and the fix)

| symptom | cause | fix |
|---|---|---|
| `uv` build fails in 5 s: `/work/<user>` | cache path not creatable by hand | `UV_CACHE_DIR=$TMPDIR/uvcache` |
| job dies after loading: needs `nvcc` | FlashInfer sampler wants a CUDA toolkit | `VLLM_USE_FLASHINFER_SAMPLER=0` and `module load cuda/12.8` |
| job dies after 10 min: 1024 requests, 998 fit | `--max-num-seqs` too high for the memory left | lower it (32) |
| GPU node refuses the Mac's ssh key | only the login node's credentials reach it | two-hop tunnel (§1) |
| a status check says "closed" while the tunnel is open | `pgrep -f "-L 8012"` read the pattern as an option | `pgrep -f -- "-L 8012"` |
| `hi` fails: *prompt contains at least 262145 tokens* | Claude Code sends **every MCP tool's full definition** to a model that is not on Anthropic's API (334 tools ≈ 315,000 tokens) | Orbit sets `ENABLE_TOOL_SEARCH=true` for such models (tools load on demand); the gateway renders `tool_reference` results as words |
| the **second** message fails: *System message must be at the beginning* | Claude Code puts hook output into the conversation as a message with role `system`; Qwen's template refuses one anywhere but first | gateway turns it into a `<system-reminder>` user message |
| cannot connect to the cluster at all (port 22 times out, ping works) | too many logins in a short time (polling every 15 s, each its own login) | Orbit shares **one** ssh connection (`ControlMaster`), looks every 15–180 s depending on state, backs off 2→15 min when unreachable |
| Orbit shows a 128,000 window for a model that holds 262,144 | Claude Code cannot know the window behind a custom URL and reports 128,000; Orbit saved that and let it override the configured size (`config/learned-windows.json`), and also stored it per chat | a custom provider's own stated window wins; what Claude Code reports is ignored for it; and when the server comes up it tells Orbit its real `max_model_len`, which Orbit writes to the provider's model (picker, meter) and to the compaction point (82% of it). Change the server's context length and Orbit follows |
| a chat stays "running" after its answer | Claude Code merged messages sent mid-answer into one turn, Orbit waited for one result per message | 30-second settle (see `docs/claude-code-engine.md`) |
| chats of yours fail and reconnect again and again while the server starts | nothing told them the server was still queued or loading | Orbit **holds** an answer while the server of its model is queued or loading (it says "waiting for … to finish loading" in the chat, which counts as alive for a crew's stall timer and not against its time), then runs it; after 2 h of waiting it goes on and fails with its own message. Local models load inside the answer as before |
| a start waits a day in the queue on the default partition | the router sends this account to `campus`; the big shared pool `pi_shared` often starts in minutes (no preemption, 24 h, 4 GPUs per user, `sbatch -p pi_shared` accepted) | **Placement** (setting *Where it runs*, default automatic): before each start `sbatch --test-only` (submits nothing) estimates the start for each partition and memory choice (full, and the *least memory*, 48 GB: the server is 6.4 GB resident), and the soonest wins (within 5 min: the default partition, then more memory); *ask a model* lets a chosen model (e.g. a Sonnet) choose among those with the free-GPU table, falling back to the rule; *fixed* uses the settings as they are. The chosen placement and the other estimates show on the card. Caveat: estimates move; one said 01:44, the job started within a minute |
| python imports crawl for 10+ min (state `D`, 1 MB/s) on a cold node | the venv's libraries are read from the project disk by page faults, a few KB at a time | pre-reading them sequentially fills the page cache at disk speed: `find venv -name '*.so*' -size +2M \| xargs -P 8 cat > /dev/null` (took 2.4 min for 8 GB; the job left the `D` state at once). The launch script's weight pre-read does this for the weights; do the same for the libraries |
| a chat goes silent while waiting on a job | Orbit closed Claude Code the moment its background shell finished, before it could answer the report | keep it open 90 s after a background task reports |
| the job is `RUNNING` but Orbit says *loading* for 15+ min, GPU idle, nothing in any log | the **node** cannot read the project disk (seen on g33, 2026-10-27): `vllm serve` sits in uninterruptible I/O wait (`wchan folio_wait_bit_common`, state `D`, 70 KB read in 17 min) while the login node reads the same file at 600 MB/s; the log is off by default, so nothing says so | **preflight** in `serve.sbatch`: a 200 MB read of the biggest weight file in 90 s, else the job resubmits itself without that node (`--exclude`, at most 3 hops) and ends; Orbit's backstop: still loading after `load_timeout_min` (25) → cancel, remember the node for 6 h, start again with `--exclude` (twice at most); setting *Avoid nodes* for a known-bad one. How to see it by hand: `ssh <node> 'ps -u $USER -o pid,etime,stat,args \| grep vllm; cat /proc/<pid>/wchan'` and a timed `dd` of a weight file |

## 7. Cluster etiquette

* Login nodes are shared: do not run vLLM, builds or long loops there. Everything heavy is an `sbatch` job.
* Every ssh login counts. Use the shared connection (Orbit does); never poll faster than needed.
* Rapid repeated connections get an IP **blocked for a while** (port 22 times out). It clears on its own; do not
  hammer it while it is blocked.
* `mail` works from login and GPU nodes; there is no `~/.forward`, so mail goes to the cluster mailbox address.

## 8. Changing the launch script safely

`docs/cluster-models/serve.sbatch` is the reference copy; the live one is `<model folder>/serve.sbatch` on the cluster.

1. Edit the reference copy. `bash -n` it.
2. `python3 docs/cluster-models/deploy_serve.py` uploads it as `serve.sbatch.new`, **parses the exact vLLM arguments with
   the real vLLM on a node** (an unknown flag otherwise shows only after minutes of loading — and with the log off, not
   at all), keeps the old one as `serve.sbatch.bak`, and moves the new one into place. It starts nothing. A running job
   keeps the script it started with.
3. The first start after a change is the real test. Turn on "Quick start" and "Keep a log" for it (a mistake shows in
   about 2 minutes, with a log to read), then turn both off. A second GPU for a trial job was considered and not
   needed: the argument check in step 2 catches the mistakes that are costly to find late.
4. Restart the real one from the panel (it cuts chats off for 8–10 minutes: choose a quiet moment).

vLLM moves things between versions (`vllm.entrypoints.openai.cli_args` became `vllm.entrypoints.launchers.cli_args` in
0.32): the argument check in `deploy_serve.py` tries both.

## 9. Not done yet — ideas, each worth a speed test

* `MTP=3` — more look-ahead; keep it if "look-ahead guesses accepted" stays above ~60%.
* `KVDTYPE=fp8` — more parallel answers at 262k context.
* `ASYNC=1` — throughput; check it works together with MTP first.
* `--cudagraph-capture-sizes` limited to the batch sizes that can occur (SEQS × (MTP+1)): fewer graphs to capture, a
  shorter start.
* A second GPU (`GPUS=2`, tensor parallel) is only worth it for a bigger model: for one 27B it adds communication.
* Prompt caching across chats: Claude Code's opening prompt carries a few per-chat details, so only the common part
  is shared. `--exclude-dynamic-system-prompt-sections` (already used for the small local model) would share all of it.
* One server for several people: needs per-user keys; today there is one key per job.
