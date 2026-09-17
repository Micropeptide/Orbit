# Claude Code harness mode

Pick a model from one of the **Claude Code** groups in the model picker and that
chat runs through the real Claude Code harness — the `claude-qwen` command in a
window: the same Claude Code command line, your Claude setup exactly as it is
(`~/.claude`: skills, plugins, hooks, MCP servers, permission rules, memory),
pointed at the model you chose. Orbit shows everything the session does and
passes on everything you do. It adds nothing of its own unless you turn an
"Orbit extra" on.

Requires Claude Code (`claude`) installed. The local model needs no key, nor does
your Claude subscription; other providers use the key you add in Settings →
Models & keys, and requests go only to that provider.

## Claude Code mode

The **Claude Code** switch in the top bar turns the mode on. The accent turns
Claude's orange, with a band under the top bar, so it is plain that chats and
settings follow the harness:

- the model picker becomes **Provider ▾ + Model ▾** — pick OpenCode Go, then any of
  its models; each shows its context window;
- new chats start on the last Claude Code model you picked;
- Settings opens on the Claude Code tab; the composer says it is talking to Claude Code.

## One provider list for both modes

Settings → **Models & keys** holds every provider once. In Claude Code mode a model
runs through the harness; with the mode off, Orbit's own chat talks to the same
model directly (through the gateway where its API needs translating), with the
same keys and accounts.

## Several accounts per provider

A provider can have more than one account — two OpenCode Go subscriptions, say.
Under the provider: **+ add another account**, name it and paste its key (each
account's key has its own name, `OPENCODE_API_KEY_2`…). **Use this** picks the
account tried first.

When a provider answers that an account's quota is used up (402, or a 429 that
talks about limits or quota), the gateway marks that account — for the rest of
the 5-hour window, week or month the message names, otherwise an hour — and
sends the same request with the next account, so the chat carries on. **Not used
up** clears a mark. A provider with several accounts always goes through the
gateway so this can happen.

## Usage left

An OpenCode Go account has one allowance shared by all its models, in 5-hour,
weekly and monthly windows. Orbit asks OpenCode for each account's figures
(`/zen/go/v1/usage`, once a minute at most) and shows what is left of each
window and when it resets — with the account in Settings, and next to OpenCode Go
in the provider picker. An account OpenCode reports as rate-limited is skipped
until it resets.

Orbit also counts every request through its gateway per account and model and
prices it with OpenCode's published prices, so each model shows roughly what it
has cost through Orbit.

## OpenCode's session header

OpenCode Go routes and caches by conversation and refuses requests without a
session id. The gateway passes Claude Code's own session id on as
`x-opencode-session`, and gives Orbit's own calls (titles, tests, Orbit-mode
chats) a stable id derived from how the conversation starts.

## Each chat keeps its model

A chat remembers the model it last used and keeps it: changing the default, or
picking a model in another chat, does not move it (and so does not change its
context window). The model picker lists your recent models first.

When you move a chat to a model with a smaller window than the chat now fills,
Orbit compacts it first — on the model it came from, which can still hold it —
then carries on with the new model (Claude Code would otherwise send the whole
chat to the smaller model to be summarised). If a chat still cannot fit, Orbit
says so rather than showing "Prompt is too long".

Thinking written by other vendors' models has no Anthropic signature; when a chat
moves to Claude through the gateway those blocks are dropped (the answers they
led to stay).

## Tool calls from other models

Some models stream tool arguments that are malformed or cut short, or interleave
parallel calls. The gateway collects each call whole, mends its JSON (unclosed
strings and brackets, trailing commas) and sends it once, so the call does not
fail in Claude Code.

## Claude · your subscription

The **Claude · your subscription** provider runs plain Claude Code on your own
Claude login (Pro, Max, Team): no base URL, no key, nothing through the gateway,
Claude's own context windows. Models: Opus, Sonnet and Haiku (latest), and Opus
and Sonnet with 1M context. The `claude` command needs to be signed in once
(`claude auth login` in a terminal — the Claude desktop app keeps a separate
login); Orbit says so if it is not.

Model lists come from [models.dev](https://models.dev) (the catalogue OpenCode
uses: every model's context window, output limit and API) and, once a key is
saved, from the provider's own `/models`. They refresh daily, or with ↻.

**Context window per chat**: a chat on a remote model uses that model's own window
— 1M for DeepSeek V4, 1,048,576 for Kimi K3 — which sets where Claude Code
compacts; a chat on the local Qwen uses the MTPLX server's setting. Replies are
capped at each model's output limit.

## Harness mode: any model

Every model in the **Claude Code** groups of the model picker runs through the
same harness, not only the local Qwen:

| Provider | How Claude Code reaches it |
|---|---|
| Local (MTPLX on this Mac) | directly |
| Claude · your subscription | plain Claude Code, your login |
| OpenCode Go, OpenCode Zen | Orbit's gateway, for every model (DeepSeek, Kimi, GLM, MiMo via OpenAI chat; Qwen, MiniMax via Messages; GPT, Grok via Responses) |
| DeepSeek, Qwen (Model Studio), GLM (Z.ai / BigModel), MiniMax, Kimi, Anthropic | directly, at their Anthropic-compatible endpoints |
| Your own provider | directly (Messages API) or through the gateway (OpenAI chat or Responses) |

- **Keys**: Settings → Models & keys. Paste a provider's key there; it is kept
  in Orbit's secrets. Through the gateway the key never reaches the Claude
  process; the gateway listens on loopback and only answers Orbit's own runs.
- **The gateway** (`bin/harness_gateway.py`) translates Claude Code's Messages API
  to OpenAI chat completions or the Responses API and back: text, thinking,
  tool calls, usage and errors.
- **Switch models freely**: a chat keeps its Claude session when you change its model.
- **New chat with…** (the ▾ next to New chat, or Cmd/Ctrl+Shift+K): model, folder and
  permission mode together, saved as presets.
- **Scheduled tasks** name their model — in the task form, or in words when you ask
  a chat to schedule something ("every morning at 7, on deepseek v4 pro").
- **Terminal**: `claude-harness "<model>"` (e.g. `claude-harness "kimi k3"`,
  `claude-harness --list`).

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
chip next to the title, then type a path or **Choose…** for the Mac's folder
chooser — as if you had run `claude-qwen` there. Recent session
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

See also: [200 ideas, and what became of them](claude-code-ideas.md) · [200 further ideas for harness mode](claude-code-harness-ideas.md).
