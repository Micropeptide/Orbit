# Parity: what the phone has, and what it doesn't

One row per user-visible Mac feature and its state on the iPhone app. The phone is a live
window onto the same server, so a feature is **Full** only when the phone has a working UI
for it end to end (not just the API), **Partial** when it does some of it, and **Missing**
when the phone has no UI for it yet. This is a living table: it is re-checked every round
the phone changes.

The **Missing** rows are the phone's backlog. The Cluster screen, Cluster models, Helpers and
Crew were added on 2026-10-28; what is left is the Terminal, the worktree, Tabs and the
Mac-only rows (menu bar, Dock, Quick Ask, launch at login, updates).

Last re-checked 2026-10-28: the Cluster screens, Cluster models, Helpers (and Crew, by its decoded
data only) were checked on an iPhone 17 simulator paired with the live Mac, read-only; every write
(start, stop, cancel, measure, save) was checked against the Mac's handlers and decoded fixtures, not run.

| Mac feature | Where on the Mac | Phone state | Where on the phone |
| --- | --- | --- | --- |
| Open Orbit (Mac app or any browser on the Mac) | Applications → Orbit for Mac, or http://127.0.0.1:8899 | Full | Orbit iPhone app after pairing (Pairing screen → Chats) |
| Pick who answers: model picker plus the Claude Code / Codex engine chips and colour band | chat top bar | Partial | model label above the message box (opens the model sheet); the engine is only chosen when a chat is made (New chat with…, Settings → How chats run), not switched on an existing chat |
| General instructions ("tell it who you are") | Settings → Memory → General instructions | Full | Library → Memory & instructions → Standing instructions |
| Add a model or key and press test | Settings → Models & keys | Full | Settings → Settings on the Mac → Models & keys → provider → Test |
| New chat | sidebar → + New chat (⌘N) | Full | Chats tab → pencil |
| New chat with… (model, machine, folder, permission mode, save as preset) | sidebar ▾, or ⌘⇧N | Full | Chats → pencil menu → New chat with… |
| Tabs (⌘1–9, close, reopen, reorder, per-tab state dots) | tab strip along the top | Missing | — |
| Chat list state marks (answering, waiting, new, queued, scheduled) | sidebar → Chats | Full | Chats tab → row marks and the status chips |
| Chat row actions (rename, pin, tag, archive, project, export, delete) | right-click a row or its ⋯ | Full | Chats tab → row context menu and swipe actions |
| Search everything, find in chat, jump to a message | ⌘P, ⌘F, ⌘G | Partial | Chats tab search (chat titles, message text, files); /find and /jump inside a chat; commands are not searched |
| Projects (own instructions, folder, filing chats) | sidebar → Projects | Full | Chats → filter menu → Projects…, or row menu → Project |
| Sessions from Claude Code, Codex and OpenCode | bottom of the sidebar chat list | Full | Chats tab → "From Claude Code / From Codex / From OpenCode" sections |
| Home page under a new chat (what wants you, running, coming up, usage, allowances) | home page of a new chat | Full | new chat's home page in the Chats tab |
| Sending: Enter, Shift+Enter, queue while answering, ⌘Enter to steer | message box | Full | message box: Send queues while it answers; hold Send or ⌘⇧↩ to steer |
| / commands and saved prompts | message box → "/" | Full | message box → "/" menu |
| @ mention a file or another chat | message box → "@" | Full | message box → "@" menu (files, knowledge, chats) |
| ! shell mode | message box → "!" | Full | message box: a leading "!" |
| # save a line to memory | message box → "#" | Full | message box: a leading "#" |
| Sent-message history (↑/↓) and Ctrl+R search | message box | Full | message box → ↑/↓ history, Ctrl+R on a hardware keyboard |
| Attach files and images (+, drag, paste) | message box | Full | message box → ＋ (Photos, Camera, Files) |
| Send later (once, or every day) | ⏱ beside the message box | Full | message box → Send later; Scheduled tab |
| Long pastes folded into an expandable chip | message box | Full | message box (pasted-text chip) |
| Live steps and tool calls (Ctrl+O), todo list (Ctrl+T) | transcript | Full | chat transcript; /verbose, /todos |
| Stop | Esc, Stop, or ⌘. | Full | Stop under the running answer (also Esc and the Send button) |
| Rewind to an earlier message, chat only or chat + files | Esc Esc | Full | chat ⋯ → Rewind… (or /rewind) |
| Approvals, answered from the chat, a notification or the Lock Screen | in-chat card and macOS notification | Full | chat approval card; Lock Screen notification with Allow / Deny |
| Permission mode (ask, accept edits, plan, auto) | Shift+Tab; written under the message box | Full | chat → work chip → Where this chat works; Shift+Tab on a hardware keyboard |
| Answer footer: time and tokens, files changed with diff and undo, copy / retry / fork / quote | under each answer | Full | chat → message actions and answer extras |
| Goals (keep going until done, with history, pause, edit, clear) | goal bar above the message box; /goal | Full | chat → goal strip above the message box; /goal |
| Chats that talk to each other (dock, waiting line, from-marked messages) | dock above the message box | Full | chat → "Talks with N chats" dock above the message box |
| Several Claude accounts, the main account, automatic switching when one is used up | Settings → Models & keys → Claude accounts / When an account runs out | Full | Settings on the Mac → Models & keys → Claude accounts and When an account runs out |
| Adding a Claude account (browser sign-in plus claude setup-token) | Settings → Models & keys → Add a Claude account | Partial | Settings on the Mac → Models & keys → Add a Claude account (name and pasted token; the sign-in itself runs on the Mac) |
| One chat pinned to one account (Auto account) | model picker → Auto account | Full | model sheet → Claude account picker |
| Seeing what it builds: browser, iOS Simulator, Mac app windows | Settings → Tools → Seeing what it builds | Partial | no such setting on the phone; inside a chat the agent can still use it and shows the screenshots |
| Gemini with an API key | Settings → Models & keys → Gemini · Google AI | Full | Settings on the Mac → Models & keys → Gemini |
| Sign in with Google, install the Antigravity or Gemini CLI | Settings → Models & keys → Sign in with Google / Install in the terminal | Missing | — |
| Files (everything Orbit made or you attached) | sidebar → Files (⌘J) | Full | Files tab |
| Library: Knowledge documents | sidebar → Library → Knowledge | Full | Library → Knowledge |
| Library: Skills | Library → Skills | Full | Library → Skills |
| Library: Agents | Library → Agents | Full | Library → Agents |
| Library: Saved prompts | Library → Prompts | Full | Library → Saved prompts |
| Orbit memory and standing instructions | Settings → Memory | Full | Library → Memory & instructions |
| Claude Code memory (CLAUDE.md and notes) | Settings → Memory (Claude Code mode) | Full | Library → Claude Code memory |
| System prompt | Settings → General → system prompt | Full | Library → System prompt |
| Scheduled messages and tasks | sidebar → Scheduled | Full | Scheduled tab |
| Running now and background tasks | home page and Scheduled | Full | Scheduled tab → Running now; /tasks |
| Trash | sidebar → Trash | Full | Settings → Bin |
| Folder chip, git branch, uncommitted files and diffs | chat title → folder chip, git line beneath | Full | chat → work chip; git dock above the message box (branch, files, diffs, line comments) |
| Terminal (several shells in the chat's folder, kept across reloads) | Ctrl+` or /terminal in a chat | Missing | — |
| Work in a separate copy (worktree), merge back or throw it away | /worktree, or chat ⋯ → Work in a separate copy | Missing | — |
| Menu bar icon listing chats that answer or wait | menu bar | Missing | — |
| Dock badge counting chats that need you | Dock | Missing | — |
| Notifications when an answer is ready or a chat needs approval | macOS notifications | Full | iOS notification; approval and reply straight from the notification |
| Quick Ask (⌥Space from anywhere) | any app on the Mac | Missing | — |
| Export a chat as PDF | ⌘⇧E in the Mac app | Full | chat ⋯ → Share as PDF |
| orbit:// links (chat, new text, tabs) | macOS URL scheme | Full | opens from notifications and orbit:// links (chat, new, tabs) |
| Launch at login / keep running in the menu bar | Orbit menu | Missing | — |
| Menu and keyboard shortcuts, and the "?" shortcut list | Mac app menus; ? | Partial | hardware-keyboard commands; /help and ⌘/ for the shortcut list |
| Updates (install automatically, tell me, check manually; frequency; betas) | Settings → General → Orbit for Mac; Orbit → Updates | Missing | — (updates via the App Store) |
| Phone access: Tailscale or local network, pairing QR, paired devices, chats-only limit | Settings → Phone | Full | Settings on the Mac → Phone access |
| A pairing link so another computer's browser opens Orbit | Settings → Phone → Show a pairing link | Missing | — |
| Temporary chat that is never written to disk | temp button, or chat ⋯ | Full | Chats → pencil → New temporary chat; "temporary · burn" chip |
| Untrusted web and file content checked, with a banner and a log entry | warnings in the transcript | Full | chat → answer warnings |
| Actions that matter ask first (autonomy modes, permission mode) | Settings → Tools; Shift+Tab | Full | Settings → Autonomy; Settings on the Mac → Tools & rules |
| Settings → Status: health check, restart, logs | Settings → Status | Full | Settings on the Mac → Status & health |
| Fallback model when a model keeps failing | Settings → Models & keys → When a model keeps failing | Full | Settings on the Mac → When a model keeps failing |
| Stay on the chosen model (no fallback): wait and retry when its connection drops | the **stay** button above the chat, `/stay on\|off\|auto`, Settings → Fallback → Stay on the model | Full | model picker → Fallback (per chat); Settings on the Mac → When a model keeps failing → Stay on the model (with how long to wait); Settings on the Mac → Cluster models → When a model drops |
| Phone access over the internet with no Tailscale (Cloudflare Tunnel + Access) | Settings → Phone → Internet (no Tailscale); `bin/orbit-tunnel` | Full | Pairing by QR sets the address and the Access key; the Phone screen lists the mode (docs/INTERNET_DOOR.md) |
| Shared projects: open one, chat in it | Settings → Shared projects; the project page | Full | Shared tab → project → Open (the Mac's own page in a web view; works through the internet door) |
| Shared projects: start one, invite people, change roles, mute or remove, cancel invitations, pause, rename, export switch | Settings → Shared projects | Partial | Shared tab → "+", then a project → People / Invite someone / Project. Joining someone else's project by link, publishing through the service and per-person file rules are Mac-only |
| Helper apps acting on Orbit itself (Claude Code and others may ask to read or write your chats, start Crew runs, invite to shared projects, start cluster models; each change waits for your yes) | Settings → Helpers → Orbit actions, and the inbox | Full | Settings on the Mac → Helpers → an app → Orbit actions; requests wait in the same inbox with Allow and Don't allow |
| Re-pairing a phone that disagrees with the Mac | Settings → Phone | Full | Pairing screen; Settings → Unpair this phone |
| Crew mode (builder and reviewer improving a folder until stopped) | sidebar → Crew (/crew) | Partial | Scheduled tab → Crew: the runs with state, round and best score (kept current every 8 s), a run's status, limits, the reviewer's score and summary per round, what is still to do, notes to the builder, pause, resume and stop (resume and stop ask first), open the builder's or reviewer's chat, delete; + starts a crew (brief, builder and reviewer model, folder, hour and round limits) after a confirmation. Not on the phone: several builders or reviewers, designating an existing chat, the reference folder, success criteria, editing the brief, pinned orders |
| Cluster page: jobs, queue, disk, GPUs, errors, history, settings | sidebar → Cluster (/cluster) | Full | Scheduled tab → Cluster (a screen; it also links to Cluster models). Opens on the Mac's last reading (no SSH) with Refresh to read again: needs a look (put away / show again), your jobs (why it waits, output, efficiency, copy for a chat, cancel with confirmation, swipe to cancel), last three days (what went wrong, efficiency), GPUs (kinds, per node, "where would my job start now?"), limits and the queue (fair-share, partitions, login node, your processes with Stop), usage history (1 / 7 / 30 days), disk bars with Read again, biggest folders / who uses the lab disk / my folder (measuring starts a small batch job after a confirmation; follows a running measurement), what happened (events with cause and fix, errors in running jobs), watching and settings (watch, notify kinds, explain failures, read-again schedule, project folder). Not on the phone: "Ask Orbit" opens a chat (Copy for a chat instead), the 30-second auto refresh |
| Cluster models (models running on the cluster's GPUs) | Settings → Cluster models | Partial | Settings on the Mac → Cluster models (and Scheduled → Cluster → Cluster models): each model's state (waiting for a GPU, loading, ready, stopping, failed), node and job, time left, placement, health, speed and load, start / stop / restart (each asks first), speed test, server messages, which chats use it ("New chats start in Orbit / Claude Code / Codex": sets the default model), all its settings, schedule and notices, Stay on the model, logins to the cluster. Not on the phone: adding or removing a model server |
| Helpers: other agents hand Orbit work (inbox, apps, limits, approval) | Settings → Helpers | Partial | Settings on the Mac → Helpers: turn it on, the inbox (jobs waiting for your yes with Allow / Don't allow, running jobs with Stop, finished jobs with the answer, conversations with Open the chat / Allow 30 more / End, last-7-days totals), each app's approval, notices, folders and limits, and removing an app. Not on the phone (stays on the Mac): an app's token and address, the remote address through the Orbit service, installing the skill |
| Usage stats (turns, tokens and time per model, tool and day) | ⋯ → Usage stats; /stats | Full | chat ⋯ → Usage stats; Chats filter menu → Usage stats; new chat's home page |
| Claude plan usage (5-hour and weekly windows) | /usage in Claude Code mode | Full | Settings on the Mac → Models & keys → an account's live usage; model sheet allowance line |
| Settings → General (thinking, side work, review, quiet mode, sampling) | Settings → General | Full | Settings on the Mac → General |
| Settings → Local server (KV cache, fan mode, restart server) | Settings → Local server | Full | Settings → Model server; Settings on the Mac → Local server |
| Settings → Tools (permissions, allow/deny rules, tool list) | Settings → Tools | Full | Settings on the Mac → Tools & rules |
| Settings → Easy mode | Settings → Easy mode | Full | Settings on the Mac → Easy mode |
| Settings → MCP servers | Settings → MCP | Full | Settings on the Mac → MCP servers |
| Settings → Claude Code (defaults, permissions, SSH hosts, skills, plugins, MCP) | Settings → Claude Code | Full | Settings on the Mac → Claude Code |
| Settings → Codex (defaults, AGENTS.md, SSH hosts, skills, plugins, MCP) | Settings → Codex | Full | Settings on the Mac → Codex |
| Settings → Backup (automatic, back up now, export, restore) | Settings → Backup | Full | Settings → Backup |
