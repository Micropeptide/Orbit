# HPC: many parallel jobs without spending tokens

You submit with your own compute tools (the person approves each submission). Orbit watches the queue and tells you how it went.

1. **One script, one job array**, not many submissions: for example 100 tasks with `--array=1-100%50`. Give every job a name with a unique prefix such as `cs-<project>-<date>` so you can ask about just your batch.
2. Right after submitting: `orbit_cluster_wait` with `match` set to the prefix and `wait_s: 600`. It returns when nothing with that name is pending or running, or when the time is up, with counts and the failed task ids. Add `stop_on_failures: 3` to come back early when something is clearly wrong. Call it again if it timed out. Do not read logs while jobs run; do not loop on `orbit_cluster_status`.
3. **When some failed:** `orbit_cluster_events` lists each failure with the cause Orbit worked out (out of memory, time limit, node problem). `orbit_cluster_output` shows the end of one job's output. For many failures, delegate "read these outputs, group the failures by cause, one line each" to a light worker. Fix the cause once, then resubmit only the failed indices (`--array=3,17,41`).
4. For a long batch tell the person you are waiting. Orbit notifies them when long jobs finish; `orbit_notify` sends your own message.
5. Ask the person first for anything over about 100 jobs, GPUs, or more than a few hours per job.

Resources: request memory and time per task, not per array; test one task before the array. The person's cluster etiquette comes from their own notes: when unsure, ask.
