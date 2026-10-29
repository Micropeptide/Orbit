# Orbit

A private research assistant that lives on this Mac. Your chats, notes, papers and
files stay here; the model that answers is your choice, per conversation.

    orbit                 terminal chat      orbit --ui         web app (:8899)
    orbit "question"      one-shot           orbit --stop       stop the local model
    orbit --resume        continue last

    codex-qwen            Codex CLI harness using the local Qwen model
    claude-qwen           Claude Code harness using the local Qwen model

(`qq` and `qq-ui` still work — they call the same programs.)

`codex-qwen` starts the local model and a loopback-only Responses API bridge,
then launches the normal Codex CLI with Qwen selected. Arguments pass through,
so `codex-qwen exec "task"` and the usual Codex sandbox flags work as expected.
The regular `codex` command and its OpenAI configuration are unchanged.

`claude-qwen` launches Claude Code in bare mode and points its Anthropic
Messages API traffic at MTPLX on localhost. It pins the Opus, Sonnet, and Haiku
aliases to the local Qwen model. The regular `claude` command, login, and
Anthropic settings are unchanged. See [CLAUDE-QWEN.md](CLAUDE-QWEN.md) for
interactive, one-shot, permissions, and troubleshooting examples.

## Models

Chosen per chat from the picker at the top of the conversation:

| | |
|---|---|
| **Local** | an MLX model served by MTPLX; starts on demand, sleeps when idle |
| **CLI agents** | `claude`, `codex`, `opencode`, `qwen` — whichever you are signed into, no API key |
| **Hosted APIs** | Anthropic, OpenAI, OpenRouter, or any OpenAI-compatible endpoint, with a key you add in Settings |

On the local model nothing leaves the machine except the lookups you ask for.
Pick a hosted or CLI model and that conversation goes to that provider instead.

## Layout

    bin/           qqcore.py (engine) · providers.py (models) · orbit · orbit-ui
    web/           index.html + vendor/ (katex, mermaid — offline)
    config/        settings · projects · agents · skills prompts · schedule
                   secrets · mcp · instructions.md · mtplx-launch.json
    memory/        durable facts, injected into every chat
    skills/        procedures loaded on demand via use_skill
    knowledge/     your documents, BM25-indexed
    sessions/      chats                trash/     recycle bin
    workspace/     files it creates · uploads/ · papers/
    vendor-tools/  bundled paper-fetch (DOI -> PDF)
    logs/          server · safety · watchdog · ledger

Outside this folder: three symlinks in ~/bin (so `qq` works anywhere) and one
LaunchAgent plist (macOS requires plists in ~/Library/LaunchAgents). Both point
back here. The paper-fetch MCP server keeps its own venv at ~/tools/.

## Organising work

* **Projects** group chats and add shared instructions to every chat inside.
  Drag a chat onto a project to move it.
* **Tags**, **pin**, **archive**, drag-to-reorder, and full-text search across
  every chat (⌘P command palette).
* **Temporary chat** (`temp`) is never written to disk; `burn` erases instantly.
* **Recycle bin** holds deletions for trash_days (default 30) with restore and
  permanent delete.

## Safety

* Destructive commands aimed at protected paths are **blocked** and cannot be
  approved. Anything else destructive asks you first, inline in the chat.
* Web pages, PDFs and files are fenced as untrusted data and scanned for
  prompt-injection; matches raise a banner and log to `logs/safety.log`.
* `run_shell` and HPC write access are off by default. `python` is on.
* HPC: heavy binaries are refused on login nodes; `hpc_submit`
  composes a proper SGE script (memory PER CORE) and dry-runs by default.

## Shared projects

Off until you turn it on in Settings > Shared projects. A project is a folder on this Mac that other people can work in
together with models, through a small separate web door (its own port, bearer tokens, no cookies). You stay the host:
the record lives on your Mac.

* **Group chat** with named authors, several models (`@name`), and an owner-chosen order for questions (first come,
  taking turns, or an approver says yes to each).
* **Permissions per person**: folders they may read or write, tools, shell level, and switches (delete, git push, install,
  network, run programs) that can be off, ask, or on. A model answering for someone runs with that person's rights only.
* **Three checks before a risky action**: the policy engine, then an optional guard model with your written rules, then a
  person's approval (two people for the kinds you choose). Commands run inside a macOS sandbox.
* **Who changed what** after each answer, with undo for what the file tools did; limits on questions per hour or day.
* **Invitations** by link; an invitation can require an Orbit account. Chats from this Mac can be added to a project and
  removed again, and a member can copy a shared chat into their own Orbit.
* **Back up and restore** a project; **freeze** stops everything at once.
* **The web link**: switch a project on at the Orbit service and people open a link and sign in from anywhere, with
  nothing on your Mac exposed (no VPN or address to set up). Tailscale and the local network are still options.
* **Project settings** in one window (people, invitations, access, models, rules, activity, backup), reached from the
  gear above the project or its right-click menu. Each shared model can show people **how much of its allowance is left**.
* **Files**: people can download what models made, and, if you allow it, browse, edit and upload into the folder.
* The member page works at **phone width** (the sidebar becomes a drawer); reply, react, pin, edit and delete work from
  the message menu.

Design, threat model and status: `docs/collab/`.

## Links

https://github.com/Micropeptide

## Testing

Three suites. The last two need the web app running (`orbit --ui`).

```bash
venv/bin/python tests/test_core.py       # 56 unit tests: safety, sessions, knowledge, state
venv/bin/python tests/test_endpoints.py  # every read-only endpoint answers cleanly
venv/bin/python tests/test_api.py        # create/rename/tag/bin/restore round-trips
```

`test_api.py` creates and removes its own data and leaves nothing behind.
