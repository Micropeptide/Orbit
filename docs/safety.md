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
| Screen control | **off** | see the screen, click, type, press keys — see below |

With shell off, Python cannot be used as a back door: `subprocess`, `os.system`,
`pty.spawn` and friends are blocked inside the Python tool. Ordinary analysis
code — pandas, matplotlib, BioPython — is untouched. **Full computer access**
turns the first three on for the session without changing these switches on
disk — turning autonomy back to "Ask every time" turns them back off too.
Screen control is **not** one of the three — see why below.

## Screen control

Turned on separately from everything else, because it is categorically
different: a click or keystroke can land in *any* app, not just this project,
and there is no path-based way to confine it the way `workspace/` confines a
file write.

- `screen_look` takes a screenshot. It is the one screen action that is
  always allowed once the setting is on — it changes nothing on the machine.
  It only actually gets **seen** by a vision-capable model — a hosted Claude
  model, not the local model or a CLI-backed one, today — but it still shows
  up inline in the chat either way, so you see what it saw.
- `screen_click`, `screen_type`, `screen_key`, `screen_scroll`, `screen_drag`
  and `screen_move` are `confirm`-level, like everything else destructive:
  they ask in **Ask every time** and **Auto-approve safe actions** (screen
  actions are never workspace-scoped, so "auto" never silently approves
  them), and only run unattended under **Full computer access** — which
  turning on Screen control does *not* imply, and vice versa. Both have to be
  on for a click to happen without asking.

Two macOS permissions have to be granted **by hand**, in System Settings →
Privacy & Security — nothing in Orbit can grant them for you, and it should
not try to: **Screen Recording** (for `screen_look`) and **Accessibility**
(for everything that moves the mouse or types). The tool tells you which is
missing the first time it is refused.

Screenshots are saved under `workspace/.screenshots/` like anything else the
Python tool creates, so they go to the bin on delete and are excluded from
git the same way the rest of `workspace/` is.

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
