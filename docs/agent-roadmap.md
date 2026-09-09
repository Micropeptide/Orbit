# Roadmap — things Claude Code does that Orbit could learn from

Claude Code is a coding agent; Orbit is a research assistant. Not everything
below translates — a few are marked **(skip)** because they're specific to a
software-engineering workflow Orbit doesn't have (a git repo per task, an
IDE to attach to). Everything else is a genuine candidate, organized by the
part of Claude Code it comes from. Ticked items already exist in Orbit in
some form, usually not identically.

## Permissions and safety — the biggest gap

Claude Code's permission system is far more granular than the three-tier
autonomy mode Orbit just got. Worth closing that gap first.

- [x] A no-ask / ask-for-risky / ask-for-everything spectrum (Ask every time / Auto-approve safe actions / Full computer access)
- [x] A hard floor no mode lifts (disk destruction, fork bombs, protected paths, …)
- [x] Every decision logged, auto-approvals included (`logs/safety.log`)
- [x] **Per-tool, per-pattern rules** — Claude Code's `Bash(git diff:*)` style: allow this exact shell command prefix without asking, deny that one outright, regardless of autonomy mode. Lives in `permission_rules` in settings (allow/deny globs per tool via `fnmatch`), not a separate file.
- [x] A **Settings → Permissions** panel to review and edit those rules, not just toggle autonomy mode
- [x] "Always allow this action from now on" that writes a permission rule from an approval prompt, so the same edit never asks twice — the pattern is editable before confirming
- [x] Deny rules that always refuse a pattern, independent of autonomy mode (a personal, user-authored block-list on top of the built-in one)
- [x] A `/doctor`-equivalent: checks Python version and deps against `requirements.txt`, the model server, `cliclick`, disk space, config file validity, MCP command paths, knowledge index and workspace writability — `/doctor`, the command palette, or Doctor in the sidebar
- [ ] "Allow this exact command for the rest of the session only" as a lighter one-click option — what shipped persists until removed in Settings, there's no session-only variant
- [ ] Per-project permission overrides (a lab notebook project that's always read-only vs. one that's fully trusted)

## Hooks — user-defined scripts on lifecycle events

Claude Code's biggest structural idea that Orbit doesn't have at all: shell
scripts that run automatically at defined moments, with structured JSON in
and (for some) the power to block the action.

- [ ] `PreToolUse` hook — run a script before any tool call; it can block the call and say why
- [ ] `PostToolUse` hook — run after a tool call, given its result (e.g. auto-format a file Orbit just wrote)
- [ ] `UserPromptSubmit` hook — runs on every message you send, before the model sees it (e.g. auto-attach today's lab notebook entry)
- [ ] `SessionStart` / `SessionEnd` hooks — e.g. always load the active project's latest data summary at the start of a chat
- [ ] `Stop` hook — runs when a turn finishes; could trigger a notification, a backup, a log entry
- [ ] A `Settings → Hooks` editor, with a dry-run/test button
- [ ] Hooks scoped per-project, not just globally

## Subagents — spawning focused helpers mid-conversation

- [x] "Agents" — a preset instruction + restricted tool list you switch a whole chat to
- [ ] **A `spawn_agent` tool** — the model can launch a sub-agent for a self-contained subtask (e.g. "search these 30 papers and summarise the ones about CLSY3") and get back a short report, without the sub-agent's own tool calls and reasoning cluttering the main conversation
- [ ] Sub-agents run in parallel — launch three literature-search sub-agents at once, merge results when they're all back
- [ ] A visible "sub-agent working…" indicator in the transcript, expandable to see what it's doing
- [ ] Sub-agent definitions as a file (`agents/lit-search.md`) the model can pick from, mirroring how skills work now
- [ ] A per-agent tool allowlist, so a "just search PubMed" sub-agent literally cannot touch the filesystem

## Plan mode — look before you leap

- [x] A `plan` tool that tracks steps and marks them done
- [ ] **A real plan-then-approve mode**: for a big multi-step request, the model researches with read-only tools, proposes a plan, and waits for your go-ahead before touching anything — a fourth item alongside the three autonomy modes, or a per-message toggle
- [ ] The plan rendered as a checklist in the chat you can edit before approving (uncheck a step, add one)
- [ ] "Keep planning" vs. "start now" as two buttons on a presented plan

## Background work

- [x] **Run a shell command in the background** and keep chatting while it runs — `run_shell_background` returns a job id immediately; `check_background(id)`, `list_background()` and `stop_background(id)` round it out, instead of `run_shell` always blocking the whole turn
- [ ] A "background tasks" panel showing what's running, with a stop button — the tools exist; there's no dedicated UI surface for them yet, only what the model reports in chat
- [ ] The cluster job queue already works this way (`cluster_submit`/`cluster_status`) — generalise the same pattern to local long-running processes
- [ ] Long-running Python (`python` tool) able to run in the background too, with progress checked in periodically rather than blocking on a fixed timeout

## Checkpoints and undo

- [x] Config files snapshot on every write (`config/.history/`, last 20 kept)
- [x] Chats, files and knowledge docs go to a bin, not deleted outright
- [x] **A checkpoint before every `write_file`** to an existing file — not just a diff shown, an actual saved previous version (`workspace/.checkpoints/`, last 20 kept) you can revert to with one click from Files → history, independent of whether the file is in git. Restoring itself checkpoints what was there, so it's never a one-way trip
- [ ] `/rewind`-equivalent: step the whole conversation (and the files it touched) back to an earlier point
- [ ] A visible "3 files changed this turn — revert all" button after a turn that wrote files

## Memory and instructions

- [x] Durable memory, injected into every chat
- [x] General instructions (a CLAUDE.md equivalent)
- [x] Project-scoped instructions
- [ ] **Quick-add memory** — a `#` prefix (or a keyboard shortcut) that saves whatever you just typed as a memory without a separate tool call or confirmation
- [ ] Memory scoped to a project, not just global (already partly true via project instructions — extend to project-scoped *durable facts*, not just standing instructions)
- [ ] A memory editor that shows *why* each fact was saved (which chat, when) with a one-click "forget this"
- [ ] Auto-suggested memories: after a chat that clearly established a lasting fact, a one-tap "save this as a memory" prompt

## Slash commands

- [x] `/new`, `/model`, `/compact`, `/find` on the phone; a command palette on the web
- [ ] `/cost` — tokens and (for hosted models) estimated spend, this session and cumulative
- [ ] `/agents` — list and switch agents from a command instead of a menu
- [ ] `/permissions` — open the permission editor above
- [ ] `/mcp` — list connected MCP servers and their status from a command
- [ ] `/export` — the existing "share as Markdown" as a typed command, with a format choice (Markdown, plain text, PDF)
- [ ] `/init` — for a new project folder, generate a starting `instructions.md` by looking at what's actually in the folder
- [ ] **Custom user-defined slash commands** — a saved prompt becomes `/its-name` automatically (partly true already via the Prompts library; make it feel like a first-class command, with arguments: `/summarize <file>`)
- [ ] `/undo` as a command alias for the checkpoint-revert above
- [ ] `/bashes` — list background shell commands (once background execution exists)

## Output and style

- [x] Markdown, tables, code blocks with copy buttons, plots inline
- [ ] **Output styles** — a small set of answer-style presets (concise / explanatory / formal-for-a-manuscript) you pick per chat or globally, changing how verbose and how hedged answers are
- [ ] A custom "how I want answers written" free-text field, separate from general instructions, specifically about tone/format (partly covered by instructions.md already — worth breaking out as its own setting so it's easier to find)
- [ ] Syntax highlighting in code blocks (currently plain monospace)
- [ ] LaTeX/MathJax rendering for equations
- [ ] A reading-time or word-count badge on long answers

## Multi-directory and scope

- [ ] **`--add-dir`-equivalent**: grant access to one specific additional folder outside the workspace (a shared lab drive, say) without turning on "write anywhere" globally
- [ ] Per-project working directories, so switching projects can switch which folder `write_file`/`python` default to
- [ ] A visible "what can it touch right now" summary in Settings — workspace, plus any extra granted folders, plus write-anywhere/full-access state, all in one place

## Environment and doctor

- [x] `/doctor`-equivalent self-check (see Permissions section above), reachable as its own panel (Doctor in the sidebar) as well as a command
- [x] A visible dependency/version report — Python version, installed packages vs. requirements.txt, cliclick presence (MTPLX version not yet included)
- [ ] One-click "check for updates" (git fetch + diff summary) and "update" (git pull + pip install -r requirements.txt), since Orbit currently only updates by hand
- [ ] A startup self-test that runs once after `install.sh` and reports pass/fail per subsystem (model server, phone pairing, MCP servers, cluster SSH)

## Session and history

- [x] Sessions list, search, pin, archive, projects, tags
- [x] Auto-compact when the context window fills
- [ ] **Fork a conversation** — branch from any point into a new chat, keeping history up to that message (distinct from "edit and resend", which replaces rather than branches)
- [ ] Resume a specific named session from the CLI (`orbit --resume <name>`) rather than always the most recent
- [ ] A "continue where a scheduled job left off" pattern — right now scheduled prompts each start fresh

## Notifications and status

- [x] Idle-stop notice, phone notifications when an answer lands while backgrounded
- [ ] A **statusline** — one customizable line (a small script you provide) shown in the web UI header: current project, git branch of the active repo, model, whatever you want glanceable
- [ ] Desktop notifications on the Mac itself (not just the phone) when a long-running turn finishes while the tab isn't focused
- [ ] A sound on approval-needed, distinct from completion, so a chat waiting for your OK doesn't sit silently

## Tool ecosystem

- [x] MCP servers, browser-use, cloak-fetch, paper-fetch, cluster tools
- [x] Screen control (just added) — the closest Orbit gets to Claude Code's own computer-use
- [ ] **A tool-call timeline view** per message — what ran, in what order, how long each took, expandable, instead of a flat list of chips
- [ ] Re-run a single past tool call with edited arguments, without re-running the whole turn
- [ ] A "why did it call that tool" note — the model's one-line reasoning for reaching for a specific tool, shown alongside the call
- [ ] Tool call retries with backoff shown explicitly in the transcript (a flaky web fetch retried 3 times currently just looks like one slow call)

## IDE / editor integration — mostly (skip)

Claude Code's IDE features (diagnostics, selection context, inline diff
review) are built for editing code inside VS Code/JetBrains. Not a natural
fit for a research assistant, with one exception:

- [ ] A small VS Code / Positron extension for the sgRNA pipeline and similar code-adjacent projects, so Orbit can see the currently open file and selection the way Claude Code's IDE integration does — genuinely useful for the parts of the work that ARE code, (skip) for everything else

## Git and worktrees — mostly (skip)

Isolated git worktrees per parallel task are a software-engineering
concept without much of an analogue in wet-lab/dry-lab research notes.

- [ ] Still worth having: **one-click "back up before this turn"** as a lightweight git commit of the workspace folder, for projects that already are git repos (several of yours are) — not full worktree isolation, just a safety commit
- (skip) parallel isolated worktrees for concurrent agents — Orbit's three-parallel-chats-at-once model already covers the practical need differently

## Scripting and headless use

- [x] `orbit`/`ob` CLI, a background service, a remote/phone API
- [ ] `orbit -p "prompt"` one-shot mode with a chosen output format (text/json/stream-json), for use in shell scripts and cron jobs beyond the existing scheduled-prompts feature
- [ ] A documented JSON schema for scripted output, so a downstream script can reliably parse an answer

## Misc small things worth doing regardless

- [ ] Vim keybindings in the composer (opt-in)
- [ ] Shift+Enter / Enter behavior configurable (already Enter-sends; add an option to flip it)
- [ ] A character/token counter live in the composer for long pastes
- [ ] Paste-an-image-from-clipboard directly into the composer (currently: attach only)
- [ ] A "explain this tool" hover/tap on any tool chip, showing its one-line description from the registry
