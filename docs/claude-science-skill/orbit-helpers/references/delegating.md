# Delegating work to Orbit

## Good tasks
Fetching, reading and summarising papers, protocols, web pages and database records; reformatting and converting files; merging tables and extracting fields; boilerplate scripts and routine code described exactly (arguments, inputs, outputs); parsing logs and tabulating results; QC checklists; checking many files for the same thing; triaging many failed jobs.

## Bad tasks
Choosing the approach, designing an experiment, statistical decisions, interpreting biology, anything where a wrong answer is costly and you cannot cheaply check it, and anything that needs a back-and-forth (use `orbit_talk` for that).

## A good task text
- Goal in one sentence.
- Exact inputs: paths in the shared workspace (give `workdir` if Orbit's person listed it), ids, URLs. Not pasted data.
- The output: format, columns, a word limit ("at most 200 words", "a TSV with columns gene, evidence, source").
- What to do when unsure: "say so and stop; do not guess".

## Tools
- `orbit_delegate`: one task. `tier` light (default) for routine, standard when it needs some care. Leave `model` empty to let Orbit pick the cheapest paid one, or pass an id from `orbit_models` / an ACTIVE model from `orbit_server_llms` (free).
- `orbit_delegate_many`: up to 8 independent read-only tasks in one call; give each a `label`.
- `orbit_wait`: all answers in one reply; `wait_s` up to 600; call again if some are still going.
- `orbit_job`: one job; `orbit_jobs`: your recent jobs; `orbit_cancel`: stop one.
- Up to 4 jobs run at once. The same task sent again within 15 minutes is the same job (retries cost nothing).

## Checking answers
They are drafts. Spot-check numbers, run a generated script on one case, verify a citation exists. `Confidence: low` means redo it or use `standard`. A job that "ended without an answer" failed: do it yourself or try the other tier.

## Changing files
`write: true` needs a `workdir` the person listed for you, and by default the person must say yes in Orbit first: the job shows as waiting. Do not wait for it; carry on and `orbit_wait` later. If the answer is "the person said no", do not retry; ask them.
