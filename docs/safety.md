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

## Rules, and how long they last

Approving the same call over and over is how a guard stops being read, so a
grant can be given at four sizes. None of them can reach past a `blocked`
verdict or a deny rule — those are a floor, not a default.

| | Where it lives | How long |
|---|---|---|
| **Yes** | nowhere | this call |
| **Yes, for the rest of this chat** | memory only | until that chat ends; it is not written to your settings and it does not follow the chat to another machine |
| **Yes, and allow it in \<project>** | the project's own rules, beside its folder | that project, for good — "let `pytest` run here" is the natural size of such a grant, and it used to be sayable only everywhere. Offered only when the chat belongs to a project |
| **Yes, and don't ask again** | `config/permissions.json` | everywhere, until you edit or remove it in Settings → Tools |

A rule names a tool and a pattern (`Bash(git diff:*)`, `write_file` on
`workspace/**`). A deny rule always beats an allow rule, whichever is more
specific and whichever was added later, and neither can approve a `blocked`
action. Session and project rules are checked the same way as permanent ones,
and every one of them is written to `logs/safety.log` when it decides something.

## Undoing what an answer changed

Every file an answer edits is snapshotted first, with a hash of how the answer
left it. *Undo* and *Rewind chat + files* use both:

- A file that is still exactly as the answer left it is restored.
- A file **you** changed since is not touched, and stops the whole restore —
  all of it or none of it, because a half-undone folder is worse than one left
  alone. The preview says which files are which before anything happens, and
  going ahead anyway is a separate, explicit button.
- A file with no snapshot (it lives outside the workspace) is reported as
  unrestorable rather than silently skipped.
- Each restore is itself checkpointed, so undoing can be undone.

## Orbit's own work

The review of a diff, the check that the work was done, a chat's title, a
compaction summary and a saved memory are all model calls Orbit makes on its
own account. They run on the model named in **Settings → General → Orbit's own
work** — per chat — and they are reads: the reviewer and the checker are given
the diff and the transcript and cannot call tools, so nothing they conclude can
change a file. A check that fails to run passes the work rather than blocking
it, and it may send the model back to work at most twice per answer.

## Helpers

A helper started by the `task` tool gets a fresh, empty context, the chat's own
settings, and — by default — reads only: it may read files, search, and fetch
pages, and it changes nothing. A helper is sent to find something out; it has no
plan of its own and nobody is watching it, so its mistakes belong in its report
rather than in your files. A model that genuinely needs one to build something
sends `profile="build"`, which gives it the tool set the answer itself has.

It cannot start helpers of its own, it has twenty minutes even when the answer
that started it has no limit, and its report is budgeted like any other tool
result — the point of it is to keep an investigation *out* of the conversation.

## Untrusted content

Anything Orbit reads from outside — a web page, a fetched PDF, another agent's
notes — is fenced as untrusted and scanned for prompt injection: instructions to
ignore previous rules, to act as something else, to hide something from you, to
run a destructive command, to send data somewhere. Matches are surfaced in the
conversation and the instructions are not followed.

**The fence cannot be closed from inside it.** Content containing Orbit's own
end marker, its opening marker, or the frame Orbit uses for its automatic notes
has those rewritten before it goes in — otherwise a page could end the fence
early and everything after it would read as Orbit's own narration, which is
exactly the injection the fence exists to prevent. An attempt is reported in the
conversation like any other injection marker.

## What a shell command is allowed to be

`run_shell` is one tool that runs both `ls` and `rm -rf`, so it can never be on
a list of tools that are safe by name. The command line is read instead:

- Commands that only look (`ls`, `cat`, `grep`, `rg`, `wc`, `jq`, `git log`,
  `git status`, `git diff`, `find` without an action, `sed` without `-i`) may
  share a round with each other and do not stop to ask.
- The flag that changes that is caught: `sed -i`, `find -delete`, `find -exec`,
  `git -c` and `--git-dir` (which can run arbitrary code through a config key),
  `git config --unset`, any redirect, `tee`, `xargs`.
- **A command nobody has written a rule for is never "safe"** — it is simply not
  claimed, and everything else decides, exactly as before there was a
  classifier.

A call is only called workspace-confined when every operand of every command on
the line resolves inside the workspace, and never when the line expands a
variable, runs a substitution, or pipes names into `xargs` — Orbit cannot read
where those point, and "I don't know" is not "inside".

## Editing a file you changed

Every file the model reads is remembered with its size and modification time.
If that file changes on disk before the model edits it — you in your editor,
another tool, a build — the edit is refused and the model is told to read it
again. A model editing from what it read three steps ago would otherwise throw
your change away with no word said, and the forgiving edit matchers make a
wrong match likelier, not less likely.

## The local server

Orbit listens on `127.0.0.1` with no login, which means any web page you visit
could otherwise fire requests at it. Requests are refused when they carry a
foreign `Origin`, an unrecognised `Host` (DNS rebinding), or
`Sec-Fetch-Site: cross-site`.

## Nothing is deleted outright

Chats, files and knowledge documents go to a recycle bin with a retention you
set. Config files snapshot their previous version on every write, keeping the
last 20 in `config/.history/`.
