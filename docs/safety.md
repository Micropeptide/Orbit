# Safety

A model that can run code on your machine needs guardrails that hold even when
the model is wrong, confused, or being manipulated by something it read.

## Three verdicts

Every tool call is classified before it runs:

- **blocked** — refused outright, and never approvable — not by you clicking
  "Allow", not by any autonomy setting. Reserved for actions with essentially
  no legitimate use here and no way back: wiping a disk, a fork bomb, a
  reverse shell, piping a download straight into a shell, killing every
  process, mass job deletion, a crontab wipe, and anything — of any kind —
  aimed at a protected path (`/`, your home directory, `/System`,
  `/Applications`, `/scratch`, …), plus the Python tool reaching for a shell
  while shell is switched off.
- **confirm** — destructive, but with a legitimate everyday use, so it can
  always be approved by you in the chat. What happens without your input
  depends on **Settings → Tools → Autonomy** (below).
- **allowed** — everything else, including the everyday commands a guard must
  not cry wolf about: `ls`, `grep`, `git push`, `python analysis.py`,
  `curl … | jq`, and a plain `write_file` to a new or existing file.

Every blocked, confirmed, denied and auto-approved decision is written to
`logs/safety.log`.

## Autonomy — how much runs without asking

**Settings → Tools → Autonomy**, three modes:

| Mode | What changes |
|---|---|
| **Ask every time** (default) | Every `confirm`-level action stops for your explicit approval, exactly as above. |
| **Auto-approve safe actions** | File edits and deletions that stay inside `workspace/` run without asking — a `rm -rf` or a Python `os.remove` that names a path under the workspace, or a `write_file` there. Anything that reaches outside the workspace, the machine, the network, or Orbit's own source still asks. |
| **Full computer access** | Orbit's equivalent of Claude Code's `--dangerously-skip-permissions`. Turns on shell, write-anywhere and cluster-write for the session, and every `confirm`-level action runs without asking — **except** a fixed list that always asks regardless of mode: `sudo`, shutting the machine down, removing a background service, changing system preferences, reading the keychain, rewriting git history, force-pushing or resetting a git repo, publishing a package, destructive SQL, file shredding, a recursive `chmod`/`chown`, and Orbit patching or rolling back its own source. |

`blocked`-level actions are refused in every mode, full access included — that
floor is not a setting and nothing turns it off. Turning on Full access shows
a confirmation dialog explaining exactly this before it takes effect.

Every action Orbit takes — approved by you, denied by you, auto-approved, or
refused — is written to `logs/safety.log` with which one it was, so an
autonomous session is auditable after the fact even though nothing stopped to
ask.

## Permissions you control

Settings → Tools:

| | Default | |
|---|---|---|
| Code execution | on | the Python tool runs real code in the workspace |
| Enable shell | **off** | the model may run shell commands |
| Write anywhere | **off** | writes stay inside `workspace/` |
| Cluster write access | **off** | job submission and remote commands |

With shell off, Python cannot be used as a back door: `subprocess`, `os.system`,
`pty.spawn` and friends are blocked inside the Python tool. Ordinary analysis
code — pandas, matplotlib, BioPython — is untouched. **Full computer access**
turns all four on for the session without changing these switches on disk —
turning autonomy back to "Ask every time" turns them back off too.

## Untrusted content

Anything Orbit reads from outside — a web page, a fetched PDF, another agent's
notes — is fenced as untrusted and scanned for prompt injection: instructions to
ignore previous rules, to act as something else, to hide something from you, to
run a destructive command, to send data somewhere. Matches are surfaced in the
conversation and the instructions are not followed.

## The local server

Orbit listens on `127.0.0.1` with no login, which means any web page you visit
could otherwise fire requests at it. Requests are refused when they carry a
foreign `Origin`, an unrecognised `Host` (DNS rebinding), or
`Sec-Fetch-Site: cross-site`.

## Nothing is deleted outright

Chats, files and knowledge documents go to a recycle bin with a retention you
set. Config files snapshot their previous version on every write, keeping the
last 20 in `config/.history/`.
