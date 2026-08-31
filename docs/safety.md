# Safety

A model that can run code on your machine needs guardrails that hold even when
the model is wrong, confused, or being manipulated by something it read.

## Three verdicts

Every tool call is classified before it runs:

- **blocked** — refused, and cannot be approved. Recursive deletes aimed at a
  protected path (`/`, your home directory, `/System`, `/Applications`), mass job
  deletion, and the Python tool reaching for a shell while shell is switched off.
- **confirm** — you are asked, in the interface, with the exact command shown.
  Recursive or wildcard deletes, disk operations, `sudo`, `shutdown`, removing a
  background service, reading the keychain, rewriting git history, publishing a
  package, piping a download into a shell, a reverse shell, and Orbit patching
  its own source.
- **allowed** — everything else, including the everyday commands a guard must not
  cry wolf about: `ls`, `grep`, `git push`, `python analysis.py`, `curl … | jq`.

Every blocked or confirmed decision is written to `logs/safety.log`.

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
code — pandas, matplotlib, BioPython — is untouched.

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
