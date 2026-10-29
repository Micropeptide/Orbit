# The sandbox copy of Orbit

`mac/` is a copy of the live Orbit's code (no data). Run it with `scripts/sandbox start` and it is a complete Orbit on
`http://127.0.0.1:8990` with its own empty data folder (`~/Rdirectory/Crew/orbit-sandbox`), so you can change anything, click through
it, break it and reset it (`scripts/sandbox reset`) without touching the person's real chats, settings, keys or running models.

What is cut off (all of it by environment, plus three small guards in the code under `ORBIT_SANDBOX=1`):

| | live Orbit | sandbox |
|---|---|---|
| port | 8899 (and 8443 through Tailscale) | 8990, loopback only; remote access is forced off: no Tailscale, no LAN, no Bonjour |
| data (`ORBIT_HOME`) | `~/Rdirectory/Qwen` | `~/Rdirectory/Crew/orbit-sandbox` |
| `HOME` | the person's | `…/orbit-sandbox/home`: so it cannot see their Claude Code, Codex or OpenCode chats, keys, ssh config, iCloud |
| harness gateway | 8897 | 8997 |
| the local model server | 8011 | `ORBIT_MODEL_PORT=8991`: nothing listens there until you start a mock |
| backups | iCloud | off |
| desktop and phone notices | on | off |
| the cluster models panel | the real HPC | `SimWorld` (`bin/modelserver.py`): a simulated cluster that queues, loads, answers and runs out; `ORBIT_SIM_SPEED=10` is ten times faster |
| the Claude Code engine | the person's login | an empty config folder: not signed in. Use a mock model (below) |

Chats need a model. Do not use the person's accounts or keys here. `tests/mock_anthropic.py` is a scripted stand-in for the Anthropic
API and the tests use it with the Claude Code engine. `scripts/seed-demo` starts the sandbox, a scripted mock model, and fills it with
invented demo chats: a 1,700-message chat, tool calls with diffs, a plot, an answer that failed, a goal and a scheduled message, several
projects and a crew run. Demo data is invented: no real names, paths or text. It is safe to re-run (it does not duplicate the chats) and
it is sandbox-only: it never reaches the live Orbit.

The iPhone app can pair with the sandbox (`orbit://pair?url=http://127.0.0.1:8990&token=sandbox&name=Sandbox`) from the simulator, so
phone work is tested against demo chats and never against the real ones.

## Getting a change into the live Orbit

Never copy files into `~/Rdirectory/Qwen`. The live Orbit is changed only by its own self-improvement pipeline (`bin/selfimprove.py`, the
`orbit_improve` tool; it is on): the change is tried in a private copy with the whole test suite, scanned, reviewed by another model,
applied with a backup, and rolled back if Orbit does not come up. Up to 10 files and 600,000 bytes a proposal, under `bin/ web/ tests/ tools/ docs/`.
Whatever touches Orbit's safety (the permission rules, secrets, pairing, remote access, the terminal, the pipeline itself) is
protected: it waits for the person and is never applied by a reviewer.

1. Finish a slice here: it works in the sandbox, `scripts/run-tests` is green, you have looked at it.
2. `scripts/to-live status` shows what differs from the live Orbit. A file marked `live-moved` was changed in the live Orbit since this copy
   started: merge the live version into this copy first (a proposal replaces whole files, so sending it would undo that change).
3. `scripts/to-live prepare FILE...` prints the `changes` JSON. Call `mcp__orbit__orbit_improve` with a title, the problem it solves and that JSON.
4. When it says applied, `scripts/to-live applied FILE...`. When it is held for the person, write it in `docs/NEEDS_YOU.md` and carry on.

The phone app is not in the live Orbit: it is `ios/` here, committed on this branch, and the person pulls it into the Orbit-iOS repo.
