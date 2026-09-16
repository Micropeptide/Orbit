# Claude Code on the local model

Pick **Claude Code · local Qwen** as a chat's model and Orbit runs that chat
through the real Claude Code harness, pointed at the model on your Mac. Claude
Code brings its own tools, skills, subagents, todo list, permissions and
compaction; Orbit is the window onto it.

Requires Claude Code (`claude`) installed. No Anthropic account or key is used:
every request goes to the local model server.

## What you get

- **One Claude session per chat**, resumed each turn. Its history, todo list and
  file state carry over, and the local model's prompt cache stays warm.
- **Everything visible**: thinking, text, each tool call with its result and
  timing, diffs for edits, subagent activity, compaction.
- **Claude's permissions, your answers.** Claude Code's permission mode and your
  Claude allow/deny rules decide what needs asking. Orbit shows each question in
  its approval box. "Don't ask again" saves a Claude permission rule such as
  `Bash(git diff:*)`. Switch a chat's mode (Ask, Accept edits, Plan, Auto, Don't
  ask, Bypass) next to its title, or with Shift+Tab, even while it is answering.
- **Questions and plans.** AskUserQuestion is Orbit's question box; Claude's todo
  list is Orbit's plan dock. Notes sent mid-answer are queued to Claude.
- **Skills that fit.** Each chat is offered the skills from `~/.claude/skills`
  that match what it is about, with full descriptions, plus a few you choose to
  always offer. Orbit's own saved skills can be loaded too.
- **Terminal history.** Sessions you run with `claude-qwen` appear in the
  sidebar (badge "CC", filter "Claude"). Open one to continue it; continue an
  Orbit chat in a terminal with the command in the Claude panel.
- **Undo** puts back files Claude changed in an answer.

## Profiles

| Profile | Loads | Prompt size |
|---|---|---|
| focused (default) | your Claude user settings, the skills each chat needs, chosen MCP servers | ~14k tokens |
| full | every skill, plugin, hook and MCP server you have | can be 45k+ |
| lean | Claude's built-in tools and bundled skills only | ~20k tokens |

Tools that cannot work on a local model (WebSearch needs Anthropic's servers)
and ones a chat has no use for (Workflow, Cron, worktrees…) are turned off;
the list is editable.

## Settings (Settings → Claude Code)

Profile · permission mode · permission mode for unattended runs · where "don't
ask again" rules are saved · Orbit's own safety rules on top (off by default) ·
MCP servers · Orbit's own tools through an MCP bridge (off by default) · a
project's own tools (on) · skill routing, always-offered skills, cap · Orbit's
skills · Claude hooks · terminal history · tools turned off · extra
instructions.

## The `claude-qwen` command

`bin/claude-qwen` starts the interactive harness with the same setup:

```bash
claude-qwen                       # interactive, in the current folder
claude-qwen -p 'Summarise README.md'
CLAUDE_QWEN_PROFILE=full claude-qwen
CLAUDE_QWEN_BARE=1 claude-qwen    # the old minimal --bare mode
CLAUDE_QWEN_DRY_RUN=1 claude-qwen # print the command instead
```

## Quiet mode

Settings → General → Quiet mode keeps the local model from being started, and
holds scheduled runs, for a few hours, so the fans stay down.

## How it works

`bin/claude_engine.py` starts `claude` with `--input-format stream-json
--output-format stream-json --permission-prompt-tool stdio`, sends the message,
and translates the event stream into Orbit's events. Permission prompts and
questions arrive as control requests and are answered from Orbit. Live changes
(permission mode, context usage, MCP status) are control requests too. The
environment points Claude Code at the local server (`ANTHROPIC_BASE_URL`) with
every model alias mapped to the local model, and drops anything inherited from
another Claude session.

Tests: `tests/test_claude_engine.py` drives the real `claude` binary against a
scripted stand-in for the Messages API (`tests/mock_anthropic.py`).

See also: [200 ideas, and what became of them](claude-code-ideas.md).
