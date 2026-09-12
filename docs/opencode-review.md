# What Orbit took from opencode

[opencode](https://github.com/anomalyco/opencode) is an open-source coding agent
with a terminal UI, a desktop app and an HTTP server. We went through its feature
set piece by piece and asked, for each one, whether it would help someone using
Orbit for research on their own Mac with a local model. This page records the
answer for each feature.

## Adopted

### Answers and tools

| opencode | In Orbit |
|---|---|
| Tool output over a limit is written to a file, and the model is told where it is | `_truncate_output`. The head and tail stay in context, and the whole output is saved to `workspace/.tool_output/`. Before this, output was silently cut at 14,000 characters, and the cut usually hit the end of a log, which is where the error is. |
| `read` pages through files with line numbers | `read_file(path, offset, limit)` returns 2,000 numbered lines per page, suggests near-miss file names, and refuses binary files. |
| `edit` with a chain of looser matchers | `edit_file` tries, in order: an exact match, a match ignoring surrounding whitespace, whitespace-normalised, first and last lines anchoring a block, escaped newlines, and read_file's line-number prefixes stripped. It keeps the file's own indentation, and refuses a match that isn't unique. |
| Diagnostics after an edit (LSP) | A lighter version with no language servers to run: `.py`, `.json`, `.js` and `.sh` files are syntax-checked after every write or edit, and any error goes straight back to the model. |
| Repairing an invalid tool call | `repair_call` handles loose JSON (code fences, trailing commas, single quotes, a missing `}`), tool names that differ only in case or punctuation, "did you mean" suggestions, missing required arguments, near-miss argument names, and type coercion. Before this, a broken call ran with no arguments at all. |
| Retries that depend on the kind of error | `classify_error`. A context overflow compacts the conversation and carries on. A rate limit or overload backs off with jitter, up to 5 tries. A bad key stops at once. |
| A `task` tool for subagents | `task` hands a sub-task to a helper that starts with an empty context. The helper cannot spawn helpers of its own. |
| A final summary when a step limit is hit | When either cap is reached, one last call without tools summarises what's done and what's left. Both caps are off by default. |
| A compaction template, with earlier summaries merged in | The summary has fixed headings: goal, user instructions, facts, done, failed, open, files. A second compaction merges the first summary rather than cutting it to 1,500 characters. |
| Doom-loop detection | Orbit already had this: a third identical call is refused with a nudge. |

### Projects and extensions

| opencode | In Orbit |
|---|---|
| `AGENTS.md` project rules | A project can point at a folder. The first of `ORBIT.md`, `AGENTS.md` or `CLAUDE.md` found there joins the system prompt, and relative paths resolve against the folder. |
| Custom tools as files (`.opencode/tool/`) | Python files in `tools/` apply to every chat; files in `<folder>/.orbit/tools/` apply to one project. A project's tool files are not imported at all until the project is marked trusted, because importing runs them. |
| Plugins with hooks | Three hooks: `tool_before` (can rewrite the call, or refuse it), `tool_after` and `system_transform`. A plugin that fails is logged and skipped. |
| Commands with `$ARGUMENTS` / `$1` | Saved prompts expand `$ARGUMENTS` and `$1`–`$9`, and quotes group words. |
| `opencode run` for headless use | `orbit run [--json] [--project] [--model] [--save] "prompt"`. |
| `opencode stats` | Usage by model…: turns, tokens, time, each tool's calls and errors, and a per-day breakdown. |

### Interface

| opencode | In Orbit |
|---|---|
| Timed rows for tool calls | Each tool call is a row with a live timer, ✓/✗ and its output. Reopening a chat restores the rows. |
| A reason given with a denial | "Deny with reason…" sends your words back to the model, so it can change course rather than just stop. An approval card for a file edit shows the diff. |
| Notifications and sound | A desktop notification when a chat you aren't looking at finishes or needs you, an unread count, and an optional beep (`/sound`). |
| Forking a session | Fork a chat from any of your messages. |
| Prompt history, drafts, a jump list | ↑/↓ through what you sent, one draft per chat, and `⌘G` / `/jump` to go to any message. |

## Not adopted, and why

- **Share links.** They upload a conversation to a public server, and Orbit's premise is that nothing leaves the Mac unless you send it.
- **Full LSP integration and formatters.** Running language servers is heavy for a research tool on a laptop that is also serving a 27B model. The syntax checks above catch the common failure.
- **Git snapshots for undo.** Orbit already snapshots each workspace file before it is overwritten (`workspace/.checkpoints`), and restoring is itself undoable. A git-based snapshot of arbitrary folders would need a policy for large data directories first.
- **`!shell` injection in commands.** A saved prompt that runs shell commands when you type it would bypass the approval tiers.
- **Remote MCP with OAuth, the GitHub app, IDE/ACP integration, themes.** Worth doing eventually, but they don't bear on research work with a local model.
- **Plan mode as a separate agent.** Orbit's `plan` tool and its autonomy modes already cover "look before you act". A read-only agent is easy to set up under Agents if you want one.
