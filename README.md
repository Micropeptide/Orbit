<img src="assets/icon-512.png" width="88" align="right" alt="">

# Orbit

**A research and coding assistant that lives on your own Mac.** Your chats, notes,
papers and files stay in one folder you can open in Finder. The model that answers
is your choice, per conversation: a local model that never leaves the machine, your
Claude subscription, OpenCode Go, DeepSeek, Kimi, GLM, Qwen, MiniMax, any
OpenAI-compatible endpoint, or the coding CLI you are already signed into.

It works two ways, and you can switch at any time:

- **Orbit's own agent** — a frugal tool-using assistant built for a 27B model on a
  laptop: your document library, memory, projects, Python, PubMed and friends.
- **Claude Code mode** — the real Claude Code harness in a desktop window, on *any*
  of those models: its tools, skills, subagents, plugins, MCP servers, permission
  modes and memory, with every step shown and every approval answered in Orbit. A
  chat can even run on another machine over SSH.

It is a Python server and one HTML file. No account, no telemetry, no build step,
no Electron. There is an iPhone app.

![Orbit](docs/screenshots/chat.png)

*A local model answering with the Python tool and an inline plot. The byline under
each answer names the model that wrote it.*

---

## Contents

- [Highlights](#highlights)
- [Two ways to chat](#two-ways-to-chat)
- [Models, providers and accounts](#models-providers-and-accounts)
- [Claude Code mode](#claude-code-mode)
- [Codex mode](#codex-mode)
- [Chats on another machine (SSH)](#chats-on-another-machine-ssh)
- [Sessions from other agents](#sessions-from-other-agents)
- [Many chats at once, and the message queue](#many-chats-at-once-and-the-message-queue)
- [Scheduled messages](#scheduled-messages)
- [When a model keeps failing](#when-a-model-keeps-failing)
- [Answers, files and previews](#answers-files-and-previews)
- [Orbit's own agent](#orbits-own-agent)
- [The interface](#the-interface)
- [Safety](#safety)
- [On your phone](#on-your-phone)
- [Install](#install) · [First ten minutes](#first-ten-minutes) · [Where your data lives](#where-your-data-lives) · [Configuration](#configuration) · [Background service](#running-it-as-a-background-service) · [Tests](#tests) · [Troubleshooting](#troubleshooting) · [Documentation](#documentation)

---

## Highlights

- **Any model, one conversation at a time.** Pick a model per chat; two chats can use
  two different models at once, and a chat can switch model mid-way. Each answer is
  labelled with the model that wrote it.
- **Codex too.** Codex's own agent — tools, sandbox, skills, plugins — on your ChatGPT
  account or on any provider in Orbit's list, in a green Codex mode beside Claude Code's
  orange one. A chat can move between Orbit's agent, Claude Code and Codex and keep its
  conversation.
- **When a provider fails, the answer carries on.** After a few failed attempts it moves
  to the same model on another provider, or the next model on your fallback list, and
  says so.
- **Claude Code on any model.** Claude Code's harness driving DeepSeek, Kimi, GLM,
  Qwen or a local MLX model — through a built-in gateway that translates Anthropic's
  Messages API to OpenAI's chat and Responses APIs — or plainly on your own Claude
  subscription, with no API key.
- **One provider list, several accounts each.** Keys for every provider in one place;
  add a second OpenCode Go account and Orbit moves to it by itself when the first is
  used up. What is left of each account's 5-hour, weekly and monthly allowance is
  shown next to the models.
- **Context that follows the model.** A chat's context window is the model's own (1M
  for DeepSeek V4, the server's setting for a local model); moving a chat to a model
  with a smaller window compacts it first, on the model that can still hold it.
- **Chats on a cluster.** Run a Claude Code chat on an HPC login node or a lab server
  over SSH: it edits files and runs commands there, your models still come from the
  Mac, and nothing is left running on the node afterwards.
- **Continue other agents' conversations.** Sessions from the Claude CLI, Claude's
  desktop app, Codex and OpenCode appear in their own sidebar sections; open one and
  keep going in that agent's own session.
- **A queue, not interruptions.** Messages sent while a chat is answering wait their
  turn and start by themselves; drag to reorder, edit, or push one in right away.
  Any number of chats answer at once on hosted models.
- **Send later.** Write a message now and have it go out at 9:00 tomorrow, or every
  weekday at 8:30, into that chat with its model and folder.
- **Files you can use, not just read about.** Every file an answer names or writes is a
  link and a card under the answer: open it, preview it in Orbit (pages, PDFs, notebooks,
  spreadsheets, Word files, images), Quick Look, show in Finder, copy the file or its
  path, drag it out, attach it to your next message — on the Mac or from an SSH host.
- **Answers formatted the way models write them.** Tables, math, callouts, footnotes,
  Mermaid, highlighted code with Run / Open / Preview buttons, and copy that keeps the
  formatting for Word, Excel and Google Docs.
- **Your own library, searched before the web.** PDFs, Word files, spreadsheets and
  notes indexed locally (BM25 — no embedding service, nothing uploaded) and cited.
- **Frugal with context on purpose.** A fresh Orbit-agent conversation costs about
  7.9k tokens with all its tools loaded, so a 27B local model on a 48 GB Mac runs
  everything with room to work.
- **Guardrails that hold.** Approvals with diffs, a hard floor of refused commands,
  writes confined to a workspace, fenced web content, keys that never leave the Mac.
- **Plain files in one folder.** Chats, notes and settings are JSON and Markdown.
  Backed up daily to iCloud Drive (keys left out). Delete the folder and Orbit is gone.

---

## Two ways to chat

| | Orbit's own agent | Claude Code mode |
|---|---|---|
| What answers | Orbit's tool loop, on the model you pick | The Claude Code harness (`claude`), on the model you pick |
| Tools | Orbit's: library search, Python, web, PubMed/NCBI/UniProt/AlphaFold, papers by DOI, cluster jobs, MCP | Claude Code's: Read/Edit/Write, Bash, Grep, subagents, todo list, web, your plugins and MCP servers |
| Instructions and memory | Orbit's memory and instructions | Claude's own `CLAUDE.md` files and per-folder memory — edited from Orbit |
| Skills | Orbit's skills, loaded on demand | Your `~/.claude/skills`, plugins and slash commands |
| Permissions | Orbit's autonomy setting and safety rules | Claude's permission modes (Auto by default) and allow/ask/deny rules; prompts come to Orbit |
| Where it works | Orbit's workspace or a project folder | Any folder on this Mac, or on another machine over SSH |
| Best for | Research on a local model, your documents, long unattended tasks | Coding and file work, anything you would do in Claude Code |

The **Claude Code** switch in the top bar turns the mode on: the accent turns orange,
the model picker becomes *Provider ▾ + Model ▾*, new chats start on the last Claude
Code model you used, and Settings opens on the Claude Code tab. Each chat keeps the
model it was started on.

---

## Models, providers and accounts

Settings → **Models & keys** holds one provider list for both ways of chatting. Keys
are typed by you and stored in `config/secrets.json` (chmod 600) on the Mac; spaces
and line breaks picked up when copying a key are removed.

| Provider | How it is reached | Notes |
|---|---|---|
| **Local** (MTPLX on Apple Silicon) | directly | Starts on demand, sleeps when idle; one answer at a time |
| **Claude · your subscription** | plain Claude Code on your own login | No API key; a long-lived token from `claude setup-token` can be saved instead of relying on the Keychain |
| **OpenCode Go**, **OpenCode Zen** | Orbit's gateway, for every model | Each model on its own API (chat, Messages or Responses); the per-conversation session header OpenCode Go requires is sent for you |
| **DeepSeek**, **Qwen** (Model Studio), **GLM** (Z.ai / BigModel), **MiniMax**, **Kimi**, **Anthropic** | directly, at their Anthropic-compatible endpoints | Region choice where a provider has two |
| **OpenAI, OpenRouter, Ollama, LM Studio**, any OpenAI-compatible server | natively (Orbit's own agent) | Add your own with a base URL and key name |
| **CLI agents** — `claude`, `codex`, `opencode`, `qwen` | spawned as subprocesses | Signed-in CLIs, no API key; Codex and OpenCode chats continue their own sessions |
| **Your own provider** | directly (Messages API) or through the gateway (OpenAI chat / Responses) | Any base URL, your model list |

- **Model lists** come from [models.dev](https://models.dev) (context window, output
  limit and API per model) and, once a key is saved, from the provider's own
  `/models`. They refresh daily, or with ↻.
- **Several accounts per provider.** *+ add another account* under a provider; each
  account has its own key name. When a provider answers that an account's quota is
  used up (OpenCode Go's `GoUsageLimitError`, a 402, a quota 429), the gateway marks
  it until the window it names resets — using `retry-after` when given — and sends
  the same request with the next account, so the chat carries on. A plain rate limit
  is a short wait, not a used-up account.
- **Usage left.** For OpenCode Go, Orbit asks OpenCode for each account's real usage
  (5-hour, weekly, monthly, with reset times) and shows it with the account and in
  the provider picker; an account reported rate-limited is skipped before a request
  fails. Every request through the gateway is also counted per account and model and
  priced, so each model shows roughly what it has cost.
- **The gateway** (`bin/harness_gateway.py`) listens on loopback only and needs
  Orbit's private token, so no other program — or other user of a shared machine —
  can spend your keys. It translates text, thinking, tool calls (collecting them whole
  and mending malformed JSON from models that send it), images, usage and errors;
  retries brief upstream failures; caps replies at each model's output limit; drops
  unsigned thinking when a chat moves to Claude; and asks reasoning models for no
  reasoning on quick calls such as titles.
- **Test** next to any model sends one short request through the same route a chat
  uses.

![Models and keys](docs/screenshots/models.png)

On a local model nothing leaves the machine except the lookups you ask for. Pick a
hosted model and that conversation goes to that provider — the picker always shows
which one is answering.

---

## Claude Code mode

Everything Claude Code does in a terminal, in a window — and your Claude setup exactly
as it is (`~/.claude`: skills, plugins, hooks, MCP servers, permission rules, memory).
Orbit shows what the session does and passes on what you do; it adds nothing of its
own unless you turn an *Orbit extra* on. Full guide:
[docs/claude-code-engine.md](docs/claude-code-engine.md).

**What you see**

- One Claude session per chat, resumed each message, so history, todo list,
  compaction and file state carry over.
- Every step: thinking, text, each tool call with its result and timing, diffs for
  edits, subagents, hooks as they run, background tasks, compaction and retries.
- Claude's permission prompts in Orbit's approval box ("Don't ask again" saves a Claude
  rule) and its questions in Orbit's question box; its todo list as Orbit's plan.
- Every slash command and skill Claude has, in Orbit's `/` menu.
- A permission-mode switch on each chat (Shift+Tab cycles it) that applies even while
  it is answering.

**Where a chat works.** The folder chip next to the title chooses the chat's working
folder — on this Mac (with the macOS folder chooser) or on an SSH host (with a folder
browser). Bookmarks and recently used folders are kept for each machine; ☆ saves one.

**Defaults for new chats.** Settings → Claude Code → *Defaults for new chats*: model,
permission mode (**Auto** unless you change it — Claude runs what it judges safe and
asks about the rest), reasoning effort, which machine new chats run on, and their
folder. Each chat can still change its own.

**Instructions and memory are Claude's.** In Claude Code mode, Settings → Memory &
instructions shows and edits `~/.claude/CLAUDE.md`, the folder's `CLAUDE.md` /
`.claude/CLAUDE.md` / `CLAUDE.local.md`, and the memory Claude keeps for each folder —
in place, with the previous version backed up. A chat's own instructions (`/sysprompt`)
go into Claude's system prompt for that chat. Orbit's memory notes and compaction are
for Orbit's own chats only.

**Your Claude setup, managed from Orbit** (Settings → Claude Code): default permission
mode and allow/ask/deny rules, skills (turn on/off, install from a git URL or folder,
remove), plugins and marketplaces, MCP server health — all written to Claude itself, so
the terminal sees the same.

**Model switches keep the conversation.** A chat can move between models and keep its
Claude session. Its context window follows the new model; if the chat no longer fits,
Orbit compacts it on the model it came from before carrying on. If it still cannot
fit, you are told what to do instead of seeing "Prompt is too long".

**In a terminal:** `claude-harness "deepseek v4 pro"` runs the harness on any model
(`claude-harness --list` shows them); `claude-qwen` runs it on the local model. Their
sessions show up in Orbit's sidebar.

---

## Codex mode

Codex's own agent, as the Codex CLI and app run it — its tools, sandbox, `AGENTS.md`,
skills, plugins and MCP servers — with every step shown in Orbit. Turn it on with
**Codex** at the top (Orbit takes on Codex's green); pick the provider and model beside it.

- **Your ChatGPT account.** *ChatGPT account (Codex)* uses the account `codex login`
  signed in on this Mac, with its own models and limits (shown in the chat's Codex panel).
- **Any other provider.** Every provider in *Models & keys* — OpenCode Go and Zen,
  DeepSeek, Kimi, GLM, Qwen, OpenRouter, your own — works in Codex too. Codex speaks
  OpenAI's Responses API; Orbit's gateway answers it in each provider's own format
  (chat completions, Anthropic messages, or Responses), with your key, which never
  reaches Codex. MCP tool groups are offered to such models as plain functions and
  mapped back.
- **Approvals.** The chat's permission mode maps onto Codex. *Auto*: everyday commands run
  and edits inside the chat's folder go ahead; anything Orbit's safety check finds risky is
  put to you, and the unrecoverable is refused. *Accept edits*: edits go ahead, commands
  ask. *Ask* asks before every command; *Plan* is read-only; *Bypass* has no sandbox and no
  questions. *Allow for this session* stops Codex asking again about the same thing in that
  chat. On a host where Codex's sandbox cannot start (Linux without bubblewrap), commands
  run unsandboxed and these rules decide. Stop interrupts
  the answer; a note sent while it works is steered into it.
- **On an SSH host.** Choose a host with the chat's folder chip, as for Claude Code: Codex
  runs there (installed for you in `~/.local/bin` the first time, the official Linux build
  of your Mac's version), works in that machine's folders, and reaches your models through
  an SSH tunnel back to Orbit's gateway — keys stay on the Mac. One connection serves every
  Codex chat on that host, and it closes after `remote_keep_alive_min` idle minutes so
  nothing lingers on a login node. Your ChatGPT account's models there need Codex signed in
  on that machine (`codex login --device-auth`, or *Copy this Mac's sign-in* in the chat's
  Codex panel); other providers need nothing there.
- **Settings → Codex.** Codex's own tab, beside Claude Code's: whether Codex is installed
  and signed in (and your ChatGPT limits); defaults for new Codex chats (model, permission
  mode, reasoning effort, machine, folder, what scheduled runs may do); Orbit's context and
  extra instructions; `~/.codex/AGENTS.md`; Codex on each SSH machine (install or check it,
  copy your sign-in, keep-alive); and Codex's skills, plugins and MCP servers, changed
  through Codex itself so the CLI and app see the same.
- **Shared sessions.** Each chat is a Codex thread in `~/.codex/sessions`, so
  `codex resume <thread>` continues it in a terminal, and a Codex session started
  elsewhere can be opened and continued in Orbit.
- **Moving between harnesses.** Switch a chat's model to Claude Code, to Orbit's own
  agent, or back to Codex: whoever answers next is given what was said since it last
  saw the conversation.

---

## Chats on another machine (SSH)

A Claude Code chat can run on a cluster's login node or a lab server, as Claude Code's
own SSH sessions do. Choose the host under **Where** in the folder picker or in *New
chat with…*; hosts come from `~/.ssh/config` and need key-based login. Settings →
Claude Code → *Remote machines* checks each host: whether Claude Code is there (the
newest copy on PATH, in `~/.local/bin`, or left by Claude's desktop app), whether it is
signed in, and how many processes you are running against the node's limit.

- **Claude Code runs there**, in the chat's folder: files are edited and commands run
  on that machine, while Orbit shows every step and asks for approvals as usual.
- **Your models still come from the Mac.** An SSH reverse tunnel reaches Orbit's
  gateway (which needs Orbit's token), so provider keys never leave the Mac. A Claude
  subscription token goes over the connection's input — never on a command line other
  users could see in `ps`.
- **Nothing is left running.** On the host, Claude Code runs in its own process group
  under a watchdog that ends it when the answer stops or the connection drops. Login
  nodes have per-user process limits; leftovers used to fill them.
- **Fast follow-ups.** Claude Code stays running between messages (30 idle minutes by
  default), so only a chat's first message waits for the connection and startup — the
  next ones answer in about a second.
- **Few connections.** Checks and folder listings share one SSH connection, so Orbit
  does not trip the connection limits clusters enforce.
- **History holds.** The session lives on the host and each message resumes it — on
  any login node sharing your home folder, after Orbit restarts too. A message you
  edit or regenerate in Orbit resumes at the last answer Orbit still has, and a
  session you continue in a terminal on the host comes back into the chat.

---

## Sessions from other agents

The sidebar lists conversations that began elsewhere, each source in its own folded
section:

| Section | Where they come from | Continuing one |
|---|---|---|
| **From Claude Code** | The Claude CLI and Claude's desktop app (`~/.claude/projects`) — in Claude Code mode, every such session | `claude --resume`, on the model the session used (Claude models continue on your subscription) |
| **From Codex** | `~/.codex/sessions` | `codex exec resume` |
| **From OpenCode** | OpenCode's database | `opencode run --session` |

Programs' one-shot calls (from temporary folders, SDK scripts, single-message runs)
are left out. A chat that moves to another model and back tells the agent what was said
in between. Deleting one hides it from Orbit; the agent's own history is left alone.

---

## Many chats at once, and the message queue

- **No limit on hosted models.** Any number of chats answer at the same time; chats on
  the local model take turns, since they share one model server. Each answer keeps its
  own model and settings on its own thread.
- **Messages wait their turn.** Send while a chat is answering and the message joins
  that chat's queue, shown above the composer. When the answer ends the next one starts
  by itself — in this window or not, and after a restart. Drag to reorder, click to
  edit, × to remove. **now** (or ⌘Enter as you send) puts a message into the running
  answer at its next step instead. Stop pauses the queue.
- **A sidebar that stays put.** Chats are ordered by the last message you sent, not by
  background saves, so the list does not reshuffle while answers run. Each row shows
  its state — answering, waiting for you, queued, unread — and chips at the top filter
  to the chats that need attention.

---

## Scheduled messages

- **The Scheduled tab** (in the sidebar) lists everything scheduled: messages waiting in
  any chat and tasks that run on their own. Edit either in place — a message's text, time,
  repeat and **model** (it can go out on a different model than the chat's); a task's
  name, prompt, repeat, time, stop time, model, chat, project and agent — or send, run,
  pause or remove it.
- **⏱ beside Send** (or right-click Send): in 30 minutes, this evening, tomorrow morning,
  Monday morning, or any date and time — once, every day, every weekday or every week.
  From the keyboard: `/later 21:30 …`, `/later tomorrow 9am …`, `/later in 2h …`,
  `/later daily 8:00 …`, `/later fri 5pm …`.
- **It goes out as if you sent it**: in that chat, on its model, in its folder or on its
  SSH host, with the usual approvals. Scheduled messages wait under *Scheduled* in the
  chat's queue, where you can change the time, edit, send now or remove them; a queued
  message can be given a time too. They never hold back what you send meanwhile, and
  Stop does not cancel them.
- **Sleep and restarts.** Scheduled messages survive restarts. If the Mac was asleep at
  the time, a message still goes when Orbit is back — up to 6 hours late
  (`schedule_send_grace_h`); an older one-off is marked *missed* for you to send or
  drop, and a repeating one waits for its next time. `/scheduled` lists everything
  scheduled in every chat. (For prompts that run unattended in a fresh chat, use
  **Tasks**.)

---

## When a model keeps failing

Settings → Models & keys → *When a model keeps failing*. After a few failed attempts
(3 by default; Claude Code and Codex first retry on their own), the answer moves on:
first to the same model from another provider (DeepSeek on OpenCode Zen when OpenCode
Go is down), then down your fallback list. A chat stays in its harness — a Claude Code
chat falls back to Claude Code models, a Codex chat to Codex ones. The answer says what
happened and which model finished it; the chat keeps its own model for the next message.
A bad request or a conversation too long for the window never falls back.

---

## Answers, files and previews

**Formatting.** Answers are parsed as GitHub-flavoured Markdown (marked) and sanitised
(DOMPurify): tables with alignment, nested and task lists, callouts (`> [!NOTE]`),
footnotes, `==highlights==`, `<details>`, `<kbd>`, math typeset as it streams (`$…$`,
`$$…$$`, `\(…\)`, `\[…\]` — prices like `$5 and $10` stay prices), Mermaid diagrams, and
code highlighted in ~40 languages. Nothing in an answer can run script in Orbit.

**Code blocks** have Copy (shell prompts stripped), Wrap, Save as a file and Insert into
your message; shell blocks get **▶ Run** (in Terminal, in the chat's folder, after you
confirm) and `open report.html` becomes a one-click **Open report.html**; HTML and SVG
get a sandboxed **Preview**, CSV a **Table** view, JSON **Format**.

**Files.** A name in an answer — `report.html`, `./out/fig.png`, `src/app.py:42`,
`~/data.csv`, a Markdown link or image, a `file://` URL — is looked up where the chat
works (a Claude Code chat's folder, else its project's folder, else Orbit's workspace;
on the SSH host for a remote chat) and becomes a link only if it exists.
Click opens it in its app (at the line, in VS Code/Cursor/Zed, for `file:line`);
⌥-click shows it in Finder; right-click offers Preview, Quick Look, Open with…, copy
path / relative path / Markdown link, copy the file itself (to paste into Finder or
Mail), copy contents, download, attach to your next message, or insert the path. Apps
and scripts are only ever shown in Finder, never launched. A path that does not exist
offers *Find files named …*. Files an answer names or wrote are also listed as cards
under it — drag one to the desktop, or onto the message box to attach it — and
`/files` lists every file in the chat.

**Previews** open in Orbit: images (HEIC and TIFF included), PDFs, HTML pages (in a
sandbox that loads the page's own images and scripts but cannot reach Orbit), Markdown,
CSV/TSV as sortable tables, Jupyter notebooks with their outputs, code, Word/RTF, Excel
sheets, zip and tar contents, and a Quick Look picture of anything else (Keynote,
Pages, PowerPoint…). Secrets (`.ssh`, `.env`, keychains, `secrets.json`) are never shown.

**Copying.** Tables copy with formatting (they paste as tables into Word, Excel,
Numbers and Google Docs), or as Markdown, CSV or TSV, and download as CSV or Excel; they
sort by any column. Images copy as pictures, save, and open larger (← → between an
answer's images); diagrams copy as SVG or PNG. A whole answer copies as Markdown, with
formatting, or as plain text, saves as Markdown or HTML, or prints to PDF; a formula
copies as LaTeX or MathML; select text anywhere to quote it into your reply.

---

## Orbit's own agent

**It reads your library.** Drop PDFs, Word files, spreadsheets or notes into Knowledge
and it indexes them (BM25, no embedding service, no upload), searches them before the
web and cites the file it used.

**It remembers.** Durable facts about you and your work go into Memory — you can add
them, and it saves them itself after substantial answers — and standing instructions go
into one file prepended to every chat.

**It runs things.** Python in a workspace folder with matplotlib plots inline; shell
commands if you switch that on; files it creates are tracked back to the chat that made
them.

**It looks things up.** Web search and page fetch (with a stealth-browser fallback for
bot walls), PubMed, NCBI, UniProt, AlphaFold, paper PDFs by DOI, citation checks against
Crossref, jobs on an SGE/UGE cluster over SSH, and any MCP server you add.

**It keeps its shape over long work.** Projects with shared instructions and a folder of
their own (its `ORBIT.md` / `AGENTS.md` / `CLAUDE.md` become the project's rules; a
trusted project's `.orbit/tools/` become its own tools); skills loaded on demand; a plan
it tracks; helpers with an empty context for side investigations; no cap on steps or
minutes unless you set one; scheduled prompts that run on their own, each on the model
you name.

**It recovers instead of giving up.** A malformed tool call is repaired or explained
back to the model; a context overflow compacts and carries on; a rate limit backs off
and retries; a bad key stops at once with a clear message; tool output too long for the
window is saved to a file the model can page through.

### Frugal with context, on purpose

A 27B model on a laptop does not have a million-token window to waste, so Orbit does not
fill one:

| | |
|---|---|
| A fresh conversation | ~7.9k tokens — the system prompt plus all tool schemas |
| Skills | Loaded only when a request matches one |
| Your documents | Retrieved by search and cited, never pasted in wholesale |
| Old tool output | Trimmed first when the window fills; the conversation is compacted only if that is not enough, and a later compaction merges the earlier summary |
| Files | Read on demand, a page at a time |

A **27B local model on a 48 GB M4 Max** runs all of it with most of a 64k window left for
the work. The context meter in the header counts the tool schemas too.

**Tools:** web search · fetch a URL · read files a page at a time (pdf, docx, xlsx, pptx,
csv converted) · write files · edit part of a file (forgiving about whitespace,
syntax-checked afterwards) · hand a sub-task to a helper · run Python · run shell · list
and grep · paper PDFs by DOI · PubMed · NCBI · UniProt · AlphaFold · sequence utilities ·
citation checks · knowledge search · remember · save a skill · plan · cluster jobs ·
schedule tasks · screen control (off by default) · anything an MCP server adds. Each can
be switched off in Settings → Tools; one Python file in `tools/` adds another
([docs/extending.md](docs/extending.md)).

---

## The interface

| | |
|---|---|
| **Chats** | Ordered by last use, with state on each row (answering, waiting for you, queued, unread); folding date groups, projects and other agents' sections; search, pin, tag, archive, drag onto a project, ⋯ menu on every row. |
| **Composer** | ⏱ send later; `/` for commands and skills (saved prompts take `$ARGUMENTS`, `$1`, `$2`), `@` for files, drag-and-drop or paste to attach, ↑/↓ for earlier messages, a draft kept per chat, the message queue above it. |
| **Answers** | Thinking, text and each tool call as its own step with a live timer and ✓/✗; diffs; time and tokens per answer; undo the files an answer changed; fork from any message; files as links and cards with previews ([more](#answers-files-and-previews)); copy as Markdown, formatted or plain. |
| **Files** | Everything Orbit created or you attached, with the chat it came from. |
| **Library** | Knowledge documents, skills, agents, saved prompts. |
| **Scheduled** | Messages scheduled in any chat and tasks that run on their own — edit text, time, repeat and model in place — and a live view of cluster jobs. |
| **Trash** | Deleted chats and files, restorable, auto-purged after a retention you set. |

Also: `⌘P` searches chats, messages, files and commands; `⌘G` jumps to any message;
`⌘K` starts a new chat and `⌘⇧K` *New chat with…* (model, machine, folder, permission
mode, saved as presets); `?` lists shortcuts; a temporary chat is never written to disk;
export to Markdown or self-contained HTML; notifications when a chat you are not looking
at finishes or needs you, answerable from any window.

---

## Safety

This matters when a model can run code on your machine.

- **Destructive commands are blocked or gated.** `rm -rf` at a protected path is refused
  outright in every mode; recursive deletes, disk operations, history rewrites, `sudo`,
  piping a download into a shell and reading the keychain need your approval, per call.
  Ordinary work (`ls`, `git push`, `samtools`, `curl … | jq`) is not nagged.
- **Autonomy is yours to set** — ask every time, auto-approve safe workspace-scoped
  actions, or full computer access. In Claude Code mode Claude's own permission modes and
  rules decide, and its prompts come to Orbit.
- **Python cannot be used as a shell** when shell is off; **writes are confined** to the
  workspace unless you allow otherwise, `../` included.
- **Untrusted content is fenced.** Web pages, fetched files and other agents' notes are
  wrapped and scanned for prompt injection.
- **Keys stay on the Mac.** API keys are sent only to their provider; for Claude Code on
  other providers the gateway adds the key, so it never enters the Claude process; remote
  machines reach the gateway through a token-protected tunnel.
- **Links in chats never run programs.** Apps and scripts named in a chat are only shown
  in Finder.
- **The server refuses cross-site requests**, and remote access (the phone) is off until
  you pair a device, with a token on every request.
- **Deletes are reversible.** Chats, files and documents go to a recycle bin; config files
  keep their last 20 versions.

Full rules: [docs/safety.md](docs/safety.md).

---

## On your phone

The Mac stays the source of truth; the iPhone app is a window onto it — the same chats,
live, with the same model picker and a Files tab.

- Chats grouped by day; pin, archive, rename, bin; filter by project; search titles and
  every message and jump to the line.
- Streaming answers with Markdown, code, collapsible thinking and tool chips;
  edit-and-resend, ask again, share as PDF or image.
- Photos, camera and files as attachments; plots render inline.
- Start, stop or switch the local model server; set the default model.
- Messages sent while a chat is answering are queued on the Mac, as on the desktop.
- If the phone loses the connection mid-answer the Mac carries on and the app rejoins.

Turn it on in **Settings → Phone**, choose Tailscale (anywhere, HTTPS through Tailscale
Serve) or Local network, and scan the QR.

<p align="center"><img src="docs/screenshots/phone.png" width="260" alt="Orbit for iPhone"></p>

The app lives at [Micropeptide/Orbit-iOS](https://github.com/Micropeptide/Orbit-iOS), with
an unsigned IPA in its [releases](https://github.com/Micropeptide/Orbit-iOS/releases/latest)
for sideloading, or build it from `ios/` with Xcode. Details in
[docs/phone.md](docs/phone.md) and [docs/tailnet-playbook.md](docs/tailnet-playbook.md).

---

## Install

Requires macOS and Python 3.9+. Apple Silicon only for the local model; everything else
works on any Mac.

```bash
git clone https://github.com/Micropeptide/Orbit.git
cd Orbit
./install.sh
```

The installer makes a virtualenv, installs dependencies, creates your data folders,
copies default settings (never overwriting existing ones), and links `orbit` and `ob`
into `~/bin`. It is safe to re-run. Then:

```bash
orbit --ui
```

which opens `http://127.0.0.1:8899`.

**Nothing else is required to start.** With no local model and no key, pick a CLI model
if you have `claude` or `codex` installed, or add a key in **Settings → Models & keys**.

**Optional pieces**

- **The local model:** install [MTPLX](https://github.com/Youssofal/MTPLX), download a
  model through it, and re-run `./install.sh`. Tuning (context window, KV quantization,
  speculative decoding, fan mode): [docs/models.md](docs/models.md).
- **Claude Code mode:** install [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
  (`claude` on your PATH). For your subscription, sign in with `claude auth login`, or run
  `claude setup-token` and paste the token under *Claude · your subscription*.
- **Chats on another machine:** a host in `~/.ssh/config` with key-based login and Claude
  Code installed there.

---

## First ten minutes

1. **Tell it who you are.** Settings → Memory → *General instructions* (or, in Claude Code
   mode, your `CLAUDE.md`). Two or three sentences: your field, how you want answers.
2. **Add a provider.** Settings → Models & keys: paste a key (OpenCode Go covers many
   open models at once) and press **test**.
3. **Give it your papers.** Library → Knowledge → add documents, then ask something only
   they know.
4. **Try Claude Code mode.** Flip the switch in the top bar, pick a provider and model,
   choose a folder with the chip by the title, and ask it to change something there.
5. **Make a project.** Group related chats; project instructions apply to all of them.

---

## Where your data lives

Everything is inside the install folder — one directory to back up, inspect or delete.
Set `ORBIT_HOME` to keep data somewhere other than the code.

```
config/      settings, agents, projects, schedule, MCP, secrets, instructions,
             provider registry (harness.json), gateway token and usage (claude/)
memory/      durable facts for Orbit's own chats
skills/      Orbit's procedures loaded on demand
knowledge/   your documents, indexed for search
sessions/    your chats, one JSON file each (queued messages included)
workspace/   files Orbit creates; the only place its agent may write by default
uploads/     files you attach
trash/       deleted items, restorable
logs/        model server, safety decisions, usage ledger, Claude Code runs
```

Claude Code's own data stays where Claude keeps it (`~/.claude`), and other agents' where
they keep theirs; Orbit reads it and writes Claude settings, skills and memory only when
you change them.

---

## Configuration

Everything is editable in Settings; the files are plain JSON if you prefer. A selection:

| Setting | Default | What it does |
|---|---|---|
| `max_tool_rounds` | 0 | Tool calls one answer may make. 0 = no limit. |
| `max_turn_minutes` | 0 | Minutes one answer may run. 0 = no limit. |
| `long_run_notice_min` | 30 | A progress notice every N minutes of a long answer. |
| `max_parallel` | none | A cap on chats answering at once, if you want one (the local model always takes turns). |
| `one_chat_at_a_time` | true | On the local model, answers wait in line rather than run side by side. |
| `resume_after_restart` | true | If Orbit stops mid-answer, pick the work up again in the same chat. |
| `keep_awake` | true | Hold off idle sleep while an answer runs. |
| `autocompact_pct` | 80 | Context fullness that triggers trimming (Orbit's own chats). |
| `idle_min` | 90 | Minutes before the local model server is stopped. |
| `trash_days` | 30 | Retention before the recycle bin auto-purges. |
| `shell_enabled` | false | Whether Orbit's agent may run shell commands at all. |
| `write_any` | false | Whether its writes may leave the workspace. |
| `agent_history` | true | List Codex and OpenCode sessions in the sidebar. |
| `claude_qwen.permission_mode` | auto | Permission mode for new Claude Code chats. |
| `claude_qwen.default_host` / `default_dir` / `default_effort` | — | Where new Claude Code chats run, their folder, reasoning effort. |
| `claude_qwen.profile` | standard | `standard`: Claude as you set it up; `lean`: built-in tools and skills only. |

---

## Running it as a background service

So the web app is always there and survives a crash or a logout:

```bash
cp docs/launchagent.plist ~/Library/LaunchAgents/com.orbit.ui.plist
# edit the two paths inside, then:
launchctl load ~/Library/LaunchAgents/com.orbit.ui.plist
```

Details, including the idle watchdog that stops the local model when unused:
[docs/service.md](docs/service.md).

---

## Tests

```bash
venv/bin/python -m unittest discover -s tests -p "test_*.py"
```

Over 300 tests, none needing a model or network: the core agent loop, safety, sessions
and ordering, the provider registry, the gateway's translations and account failover,
the message queue, scheduled messages and tasks (editing, validation, starvation),
model fallback, Codex mode against a stand-in app-server, the Responses gateway
translations, concurrent chats, finding and previewing the
files a chat names (and refusing secrets or paths outside a preview's folder),
Codex/OpenCode session import and resume, the SSH
wrapper and its watchdog, and Claude Code end to end — the real `claude` binary against a
scripted stand-in for the Messages API. `tests/test_endpoints.py` and `tests/test_api.py`
check a running app and clean up after themselves.

---

## Troubleshooting

**`orbit: command not found`** — `~/bin` is not on your PATH. Add
`export PATH="$HOME/bin:$PATH"` to `~/.zshrc`, or run `./bin/orbit` directly.

**The first message after a pause takes ~15 seconds** — the local model server sleeps
when idle and reloads its weights. Raise `idle_min` if it bothers you.

**A provider's test fails** — check the key under Settings → Models & keys (and the region,
where there is one). For OpenCode Go, the account's usage is shown there: a used-up window
says when it resets.

**"Claude · your subscription" says not signed in** — run `claude setup-token` in a
terminal and paste the token under that provider, then press *check again*.

**A chat on another machine will not start** — Settings → Claude Code → Remote machines →
*check* shows what is missing (the host unreachable, no Claude Code there, the process
limit nearly reached). Clusters may briefly block an address after many connections.

**A CLI model is missing from the picker** — Orbit looks on `PATH` plus the usual install
locations; symlink yours into `~/.local/bin` if it is elsewhere.

**Something looks stale after an update** — a banner appears when the code on disk is
newer than the running process; click *Restart interface*.

---

## Documentation

| | |
|---|---|
| [docs/claude-code-engine.md](docs/claude-code-engine.md) | Claude Code mode, providers and the gateway, accounts and usage, SSH chats, other agents' sessions |
| [docs/models.md](docs/models.md) | The local model: MTPLX, context, quantization, fans |
| [docs/safety.md](docs/safety.md) | The safety rules and how to change them |
| [docs/extending.md](docs/extending.md) | Tools and plugins in one Python file |
| [docs/phone.md](docs/phone.md) · [docs/tailnet-playbook.md](docs/tailnet-playbook.md) | The iPhone app and remote access |
| [docs/service.md](docs/service.md) | Running as a background service |
| [docs/answers-files-ideas.md](docs/answers-files-ideas.md) | 200 ideas for answers, files, previews and scheduled messages — which are built |
| [docs/claude-code-harness-ideas.md](docs/claude-code-harness-ideas.md) · [docs/agent-roadmap.md](docs/agent-roadmap.md) | What has been built, what is next, and why |

---

Built by **Micropeptide** · MIT licensed · [github.com/Micropeptide](https://github.com/Micropeptide)
