# Claude Code on the local model

Pick **Claude Code · local Qwen** as a chat's model and that chat is the
`claude-qwen` command in a window: the same Claude Code command line, your
Claude setup exactly as it is (`~/.claude`: skills, plugins, hooks, MCP servers,
permission rules, memory), pointed at the model on your Mac. Orbit shows
everything the session does and passes on everything you do. It adds nothing of
its own unless you turn an "Orbit extra" on.

Requires Claude Code (`claude`) installed. No Anthropic account or key is used:
every request goes to the local model server.

## What you see

- **One Claude session per chat**, resumed each turn, so history, todo list,
  compaction and file state carry over, and the same session opens with
  `claude-qwen --resume` in a terminal.
- **Every step**: thinking, text, each tool call with its result and timing,
  diffs for edits, subagents, hooks as they run, background tasks, compaction,
  retries, and the output of Claude's own commands (`/context`, `/cost`, `/compact`…).
- **Claude's permission prompts** in Orbit's approval box. Claude decides what
  needs asking (its mode and your allow/ask/deny rules); "Don't ask again" saves a
  Claude permission rule. Each chat has a mode switch next to its title
  (Shift+Tab cycles it), which applies even while it is answering.
- **Claude's questions** (AskUserQuestion) in Orbit's question box, its todo list
  as Orbit's plan, notes you send mid-answer queued to Claude, and Stop as an
  interrupt.
- **Every slash command and skill** Claude has, in Orbit's `/` menu; anything Orbit
  itself does not handle goes straight to Claude.
- **Terminal sessions** from `claude-qwen` in the sidebar ("CC" badge, "Claude"
  filter). Open one to continue it.

## Working folder

A new chat's Claude session starts in the folder you choose — click the folder
chip next to the title — as if you had run `claude-qwen` there. Recent session
folders and Orbit's project folders are offered. You can also allow more folders
(`--add-dir`). A chat that has started stays in its folder; choosing another
starts a new chat there.

## Your Claude setup (Settings → Claude Code)

Changes here are made to Claude, not to a copy in Orbit, so the terminal sees
them too:

- **Permissions**: default mode; allow, ask and deny rules; extra folders; hooks
  on/off — written to `~/.claude/settings.json` (the previous file is backed up).
- **Skills** (`~/.claude/skills`): turn each on or off (Claude's
  `skillOverrides`), remove (to the Trash), or install from a git URL,
  `owner/repo` or a folder — every folder with a `SKILL.md` becomes a skill.
- **Plugins**: enable, disable, update, uninstall, install, add a marketplace — via
  `claude plugin`.
- **MCP servers**: health and removal via `claude mcp`.

"Save as skill" under an answer in a Claude Code chat writes a Claude skill.
When Claude itself installs a skill or edits its settings during a chat, that
goes to the same place, and Orbit shows it next time it reads them.

## The `claude-qwen` launcher

Options that shape the command for the terminal and Orbit alike:
profile (**standard**: Claude as you have it set up; **lean**: built-in tools and
skills only), which MCP servers load, and tools turned off because they cannot
work on a local model (WebSearch needs Anthropic's servers) or have no use
locally.

```bash
claude-qwen                       # interactive, in the current folder
claude-qwen -p 'Summarise README.md'
CLAUDE_QWEN_PROFILE=lean claude-qwen
CLAUDE_QWEN_BARE=1 claude-qwen    # the old minimal --bare mode
CLAUDE_QWEN_DRY_RUN=1 claude-qwen # print the command instead
```

## Orbit extras (all off)

Each adds something Claude itself would not do: Orbit's safety rules and folder
limit on top of Claude's; Orbit's own tools or a project's `.orbit/tools` through
an MCP bridge; offering only the skills that match each chat (a much shorter
prompt for a small model); skill hints; Orbit's saved skills as a plugin; Orbit's
project rules in the prompt; time stamps on messages.

## Speed on a local model

With a large Claude setup the prompt is big: with ~1,200 skills, hooks and one MCP
server it is about 45k tokens, and the model reads all of it before the first
reply (a couple of minutes at ~300 tokens/s). Within an answer the model's cache
makes later steps fast. After a new message, Qwen's chat template drops earlier
turns' thinking, so part of the prompt is read again. If that is too slow: the
lean profile, turning off skills you do not use, or the skill-routing extra.

## Fans

MTPLX's fan mode is in Settings → Local server: **default** lets macOS manage the
fans; **smart** boosts them while generating. Settings → General → Quiet mode
uses "default" for a few hours.

## How it works

`bin/claude_engine.py` builds the `claude-qwen` command line, adds
`--input-format stream-json --output-format stream-json
--permission-prompt-tool stdio --include-hook-events`, and translates the event
stream into Orbit's events. Permission prompts and questions arrive as control
requests and are answered from Orbit; live changes (permission mode, context
usage, MCP status) are control requests too. The environment points Claude Code
at the local server with every model alias mapped to the local model, and drops
anything inherited from another Claude session.

Tests: `tests/test_claude_engine.py` drives the real `claude` binary against a
scripted stand-in for the Messages API (`tests/mock_anthropic.py`).

See also: [200 ideas, and what became of them](claude-code-ideas.md).
