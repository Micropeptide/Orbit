# Using Orbit

Orbit is your own research assistant. It runs on your Mac, keeps your chats and files there, and
answers with whichever model you choose: a local model on Apple Silicon, a hosted one with your
key, or Claude Code and Codex running as themselves. You reach it from the Mac app, any browser
on the Mac, or the iPhone app; they are all windows onto the same chats.

This guide walks through everything you can do, in the order you are likely to need it.

## Getting started

**Open Orbit.** Start *Orbit for Mac* from Applications, or open `http://127.0.0.1:8899` in a
browser. If Orbit's server is not running, the Mac app starts it for you.

**Pick who answers.** The model picker sits in the top bar (and above the message box on the
phone). Three ways of working are side by side:

| Mode | What runs the chat | Good for |
| --- | --- | --- |
| **Orbit** | Orbit's own agent, on any model you have: local, a hosted key, or a CLI | everyday questions, papers, your documents |
| **Claude Code** | Claude Code itself, on the provider and model you pick | changing code and files in a folder |
| **Codex** | Codex's own agent, on your ChatGPT account or any provider | the same, with OpenAI's agent |

Switch with the **Claude Code** and **Codex** chips in the top bar. The chip that is on shows
its colour, and a thin band in that colour runs under the top bar, so you always know which
engine a chat uses.

**Tell it who you are.** Settings → Memory → *General instructions* (in Claude Code mode, your
`CLAUDE.md`). Two or three sentences about your field and how you like answers go a long way.

**Add a model if you have none.** Settings → Models & keys: paste a key and press **test**. With
`claude` or `codex` installed, their CLI models work with no key at all.

## Chats

**New chat:** ⌘N in the Mac app (⌘K in a browser), the **+ New chat** button, or the pencil on
the phone. **New chat with…** (⌘⇧N, or the ▾ beside the button) lets you choose the model,
machine, folder and permission mode up front, and save that choice as a preset.

**Tabs.** Every chat you open gets a tab along the top. Switch with ⌘1–⌘9 (Alt+1–9 in a
browser), close with ⌘W, bring the last one back with ⌘⇧T, and drag tabs to reorder them. A tab
shows a pulsing dot while its chat answers, an amber dot when it waits for you, and a blue dot
when there is something new.

**The chat list** in the sidebar shows each chat's state at a glance:

- a small planet going round its ring: answering now
- an amber mark: waiting for you (an approval or a question)
- a blue dot: new since you last looked
- a tray: messages queued; a clock: something scheduled

Right-click a row (or use its ⋯) to rename, pin, tag, archive, move to a project, export, or
delete it. Deleted chats go to the Trash and can be restored.

**Search:** ⌘P searches chats, messages, files and commands at once. ⌘F finds within the chat
you are reading. ⌘G jumps to any message you sent.

**Projects** group related chats. A project can carry its own instructions and folder, which
apply to every chat in it. Drag a chat onto a project to file it.

## Writing a message

Type and press **Enter** to send; **Shift+Enter** for a new line. While an answer is running,
Enter **queues** your message (it starts when the answer is done) and **⌘Enter** slips it into
the running answer as a note it reads at its next step.

Shortcuts inside the box:

| Type | What happens |
| --- | --- |
| `/` | commands and saved prompts — `/goal`, `/terminal`, `/worktree`, `/diff`, `/compact`, `/help`… |
| `@` | mention a file (or another chat) to include it |
| `!` | shell mode: run a command yourself; its output joins the chat |
| `#` | save this line to memory |
| ↑ / ↓ | walk through what you sent before (empty box) |
| Ctrl+R | search what you sent before |

**Attach** files and images with **+**, by dragging them in, or by pasting. **Send later** (⏱
beside the box) schedules a message once or every day. Long pastes fold into a chip you can
expand.

## While it works

You see each step as it happens: thinking, then tool calls as `⏺` lines with their results
folded under them. **Ctrl+O** shows every call in full; **Ctrl+T** shows the todo list.

- **Stop:** Esc, the Stop button, or ⌘. in the Mac app.
- **Rewind:** Esc Esc goes back to an earlier message; the files it changed can be undone too.
- **Approvals:** when a step needs your yes, Orbit asks in the chat, on the phone's Lock
  Screen, and as a Mac notification. Answer from wherever you are.
- **Permission mode:** Shift+Tab cycles *ask*, *accept edits*, *plan* and *auto*. The current
  mode is written under the message box.

Under each answer: the time and tokens it took, the files it changed (with a diff and **undo**),
and buttons to copy, retry, fork from that point, or quote it in your next message.

## Goals: keep going until it is done

Give a chat a **goal** and it carries on by itself, answer after answer, until the work is done.
After each answer Orbit checks the work against the goal and either continues or stops and says
why: done, stuck, over its token budget, or out of turns.

- Start one with `/goal what done looks like`, or send a message with **Keep going until done**.
- When an answer ends with work still listed as remaining, Orbit offers to make it a goal. If
  you don't answer within two minutes, it goes ahead (you can turn the offer off in Settings).
- The goal bar above the message box shows progress, the history of each check, and Pause,
  Edit and Clear.

## Chats that talk to each other

A chat can start other chats and hand them work, for example sending a routine task to a
cheaper model and waiting for its answer. It can also message an existing chat, wait for
replies, and set goals on the chats it starts. You can talk to any of those chats yourself
at any time.

The dock above the message box lists the chats this one talks to and what each is doing; a
"waiting for…" line shows whom it is waiting on. Messages one chat sends another are marked
**from** the sender, with a link back.

## Files, Library and Scheduled

- **Files** (⌘J): everything Orbit made or you attached, with the chat it came from. Click a
  file for a preview; Reveal opens it in Finder.
- **Library:** your knowledge documents (add PDFs, Word files, Markdown, CSV and ask about
  them), skills, agents and saved prompts.
- **Scheduled:** messages and tasks that run on their own, with their next time. Edit the text,
  time, repeat and model in place, or run one now.
- **Trash:** deleted chats and files, kept for the time you set.

## Working in a folder

In Claude Code or Codex mode a chat works in a **folder**: pick it with the folder chip by the
title. Under the chat's title Orbit shows the git branch, what is uncommitted and how far you
are from upstream; click it for the changed files and their diffs.

**Terminal** (Ctrl+\` or `/terminal`): a shell in the chat's folder at the foot of the window.
Open several, drag the edge to resize, and hide it while the shells keep running. Reload the
page or open another window and they are still there. For a chat that works on another machine,
the terminal opens there over SSH.

**A separate copy** (`/worktree`, or ⋯ → *Work in a separate copy*): the chat works in a git
worktree of the repository on a branch of its own (`orbit/…`). Your checkout stays exactly as
it is, and two chats can work on one repository at once. When it is done:

- **Merge back** commits what is left, merges the branch into the one it came from, and removes
  the copy. If the merge would conflict, nothing changes and Orbit tells you which files.
- **Throw the copy away** deletes the copy and its branch.

Only committed work goes into a copy; uncommitted changes in your checkout stay where they are.

## Orbit for Mac

The Mac app is Orbit in a window of its own, with:

- **Tabs** where the title bar would be.
- **A menu bar icon** listing the chats answering or waiting for you; click one to open it.
- **A Dock badge** counting chats that need you or have news.
- **Notifications** when an answer is ready or a chat needs your approval. Click to open it.
- **Quick Ask** with ⌥Space from anywhere: type and press Enter for a new chat, or ⌘Enter to ask
  in the background and be told when the answer is in.
- **Export a chat as PDF** with ⌘⇧E.
- **Links:** `orbit://chat/<id>` opens a chat; `orbit://new?text=…` fills the message box (it
  never sends by itself).
- **Launch at login** and **Keep running in the menu bar** in the Orbit menu.

**Menu shortcuts:** ⌘N new chat · ⌘⇧N new chat with… · ⌘P search everything · ⌘B sidebar ·
Ctrl+\` terminal · ⌘J files · ⌘. stop · ⌘1–9 tabs · Ctrl+Tab next tab · ⌘W close tab ·
⌘⇧T reopen · ⌘, settings.

**Updates.** Settings → General → *Orbit for Mac*, or Orbit → Updates in the menu bar:

- **Install automatically:** downloads in the background and installs when no chat is answering
  and you are away, or when you quit.
- **Tell me, I install:** a notification says a new version is ready; you choose when.
- **Don't check by itself:** only when you choose *Check for Updates…*.

Choose how often it checks (every hour, 6 hours, day or week) and whether to include beta
versions. Every download is checked against the release's published checksums before it is
installed, and the previous version goes to the Trash.

## Orbit on your iPhone

1. On the Mac: Settings → Phone → turn on access. Choose **Tailscale** (works anywhere) or
   **Local network** (same Wi-Fi only).
2. Scan the QR code with the iPhone app. Each phone gets its own key; you can see and remove
   devices in the same place, and limit a device to chats only.

The phone shows the same chats live, with the model picker, the queue, goals, files and the
home page. Answer approvals from the Lock Screen without unlocking; reply to a finished answer
from its notification. If the phone loses the connection mid-answer, the Mac carries on and the
app rejoins.

## Privacy and safety

- Everything lives on your Mac: chats, files, memory and settings, in Orbit's folder. Nothing is
  sent anywhere except to the model you choose.
- Actions that matter, like deleting files, publishing, or pushing, always ask first unless you
  chose a mode that allows them.
- What a model reads from the web or a file is treated as untrusted data and checked for
  attempts to give it instructions; anything suspicious raises a banner and is logged.
- A **temporary chat** (the *temp* button or ⋯ menu) is never written to disk.
- Terminals are only for you at the Mac unless you allow paired devices in Settings → Phone.

## Keyboard shortcuts

| Keys | What they do |
| --- | --- |
| Enter / Shift+Enter | send / new line |
| ⌘Enter | send into the running answer |
| Esc / Esc Esc | stop / rewind |
| Shift+Tab | cycle the permission mode |
| Ctrl+O / Ctrl+T | every tool call in full / the todo list |
| ⌘K (⌘N in the Mac app) | new chat |
| ⌘⇧K (⌘⇧N in the Mac app) | new chat with a chosen model and folder |
| ⌘P | search everything |
| ⌘F / ⌘G | find in this chat / jump to a message |
| ⌘J | files |
| Ctrl+\` | terminal |
| ⌘1–9 (Alt+1–9 in a browser) | go to a tab |
| ⌘, | settings |
| ? | the shortcut list |

## When something goes wrong

- **"Orbit isn't answering":** check the model picker. A local model may still be loading; a
  hosted one may be out of credit. Settings → Status runs a health check of every part.
- **A model keeps failing:** Orbit can retry on a fallback model; set it under Settings →
  Models & keys → *When a model keeps failing*.
- **The phone shows "No chats yet":** the phone and the Mac disagree on how to connect. Re-pair
  from Settings → Phone with the mode the Mac uses.
- **The Mac app says Orbit is not running:** it tries to start Orbit's server itself; if it
  cannot find it, choose your Orbit folder when it asks.
- **Something else:** Settings → Status shows logs and what is running. Orbit's source and
  issues are at [github.com/Micropeptide/Orbit](https://github.com/Micropeptide/Orbit).

---

Orbit is made by **Runtian Wu** — [runtianwu.com](https://runtianwu.com) ·
[github.com/Micropeptide](https://github.com/Micropeptide). MIT licensed.
