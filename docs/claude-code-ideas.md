# Claude Code in Orbit: 200 ideas, and what became of them

Orbit can run chats through the real Claude Code harness on the local model
(`bin/claude_engine.py`). Before building it, we listed 200 adaptations and
improvements. The good ones that were practical now are done (✅); a few are
partly there (◐); the rest are noted with why they wait (·).

Tally: **145 done, 3 partial, 52 not yet.**

## Update: Claude Code mode is claude-qwen in a window

After the first round, the direction changed: Orbit should be a desktop window onto
`claude-qwen`, conveying everything and adding nothing of its own. So:

- Orbit's additions are off by default and grouped as "Orbit extras": skill
  routing (61–68), skill hints (68), Orbit's skills (69), project tools (87),
  Orbit's safety rules (33), time stamps on messages (17).
- One command line for the terminal and Orbit; Orbit adds only the stream
  transport, the session and a chat's permission mode. Claude's own default mode
  applies unless a chat picks one.
- Skills, plugins, MCP servers and permission settings are read from Claude and
  changed in Claude (`~/.claude`, `claude plugin`, `claude mcp`). "Save as skill"
  in a Claude Code chat writes a Claude skill.
- A new chat's working folder can be chosen, with extra folders (`--add-dir`).
- Hooks, background tasks, model fallback, denied permissions and Claude's own
  command output (`/context`, `/cost`, `/compact`) all show in the chat.
- The `/` menu lists every Claude command and skill before a chat's first answer.
- Scheduled runs honour a job's own model (they used whichever model was last active).
- Fans: MTPLX's fan mode ("default" lets macOS manage them); quiet mode now uses it
  for a few hours instead of keeping the model off.

## A. The engine

1. ✅ Run the real harness per chat over Claude Code's stream-json protocol, not a one-shot `claude -p` with the chat pasted in.
2. ✅ Resume the same Claude session every turn (`--resume`): Claude keeps its own history, compaction, todo list and file state.
3. ✅ New chats get their session id up front (`--session-id`), recorded in the chat.
4. ✅ Thinking streams into Orbit's thinking view, with a time for each paragraph.
5. ✅ Answer text streams as it is written.
6. ✅ Each Claude step is its own Orbit step: what it said, then the tools that step called.
7. ✅ Every tool call and result is an Orbit tool row with timing and success.
8. ✅ Write and Edit show diff cards, built from Claude's own structured patch.
9. ✅ Subagent activity shows as helper status lines.
10. ✅ Claude's compaction shows as a notice.
11. ✅ Claude's API retries show as Orbit's retry note.
12. ✅ An MCP server that fails to connect is reported in the chat.
13. ✅ Tokens and time are recorded on the answer; the context meter follows the prompt size.
14. ✅ Stop sends an interrupt, and ends the process if it does not stop within 8 s.
15. ✅ Notes sent mid-answer go in as queued messages, and show as read.
16. ✅ Attached images reach Claude as image blocks.
17. ✅ Each message carries when it was sent, so the model knows the date and time.
18. ✅ A chat that began on another model gives Claude the earlier conversation on its first turn.
19. ✅ Editing or regenerating in Orbit resumes Claude at the last message Orbit kept (`--resume-session-at`).
20. ✅ Forking a chat branches the Claude session (`--fork-session`); the fork follows its new id.
21. ✅ Scheduled runs work, including their time limit.
22. ✅ Claude Code chats share Orbit's one-answer-at-a-time slot.
23. ✅ Long runs get the periodic progress line, with open todo items.
24. ✅ A model server that is not answering is explained, with what to do.
25. ✅ The harness never inherits another Claude session's variables or a real Anthropic key.
26. ✅ A sleeping model server is started, with progress.
27. ✅ Titles, memory notes and summaries go straight to the local model, not through a whole Claude session.
28. ✅ Progress is saved during long runs.
29. · Keep one Claude process warm between messages. Saves about a second a turn; makes stopping and permissions harder.
30. · `--replay-user-messages` to confirm each note was delivered. Notes are already confirmed by the stream.

## B. Permissions

31. ✅ Claude's permission prompts come to Orbit's approval box (`--permission-prompt-tool stdio`).
32. ✅ Claude Code decides what needs asking, from its permission mode and your Claude allow/deny rules; Orbit adds nothing by default.
33. ✅ Optionally, Orbit's own safety rules, autonomy mode and folder limit apply on top (off by default).
34. ✅ "Don't ask again" saves a Claude permission rule, such as `Bash(git diff:*)`, which you can edit first.
35. ✅ Claude's own suggested rules are offered as one-click choices.
36. ✅ Choose where rules are saved: where Claude suggests, the folder, the project, everywhere, or this session.
37. ✅ `mode:acceptEdits` as an answer switches the session's mode instead of adding a rule.
38. ✅ Each chat has a permission-mode switch next to its title.
39. ✅ Changing the mode applies to an answer already running.
40. ✅ Orbit's plan mode and Claude's plan mode are the same switch, live.
41. ✅ While plan mode is on in Orbit, Claude cannot leave it by itself.
42. ✅ Runs nobody is watching refuse what needs asking, and say so to the model.
43. ✅ "Deny with reason" passes your reason to Claude.
44. ✅ A prompt is always answered, even if deciding fails, so a run never hangs.
45. ✅ Approvals can be answered from any window showing the chat.
46. · Edit Claude's allow/deny rule lists inside Orbit. For now they are in Claude's settings files.
47. ✅ A separate permission mode for unattended (scheduled) runs.
48. ✅ Write and Edit approvals show the proposed diff before anything changes.
49. ✅ Choosing Bypass asks for confirmation first.
50. ✅ Permission decisions go to Orbit's safety log.

## C. Questions and plans

51. ✅ AskUserQuestion becomes Orbit's question box: options, several choices, or your own words.
52. ✅ "Should I continue?" is answered yes without waiting for you.
53. ✅ Claude's todo list (TodoWrite, TaskCreate, TaskUpdate) is Orbit's plan dock.
54. ✅ The plan is saved with the chat.
55. ✅ The progress line lists open todo items.
56. · Show Claude's ExitPlanMode plan as a card with "Approve and build".
57. · MCP elicitation requests as question boxes.
58. · Ask about a running answer without interrupting it (`side_question`).
59. · Configurable time to wait for an answer.
60. ✅ Questions and approvals raise a notification.

## D. Skills

61. ✅ Each chat is offered the skills that match it, chosen from `~/.claude/skills` by name and description.
62. ✅ Unrelated skills are hidden with `skillOverrides`, so the listing no longer takes about 10,000 tokens of bare names.
63. ✅ Offered skills keep their full descriptions.
64. ✅ Some skills are always offered (configurable).
65. ✅ A cap on skills per chat.
66. ✅ A chat's set only grows when a new message needs more, so the prompt stays cacheable.
67. ✅ Typing `/skill-name` makes that skill available to the chat.
68. ✅ The best matches are named in the message as a hint.
69. ✅ Orbit's saved skills are packaged as a Claude plugin and can be loaded too.
70. ✅ That plugin is rebuilt only when the skills change.
71. ✅ Claude's commands and skills appear in Orbit's `/` menu in Claude Code chats.
72. ✅ Commands Orbit does not have (`/compact`, `/context`, skills) go straight to Claude.
73. · Skill usage statistics.
74. · Routing by embeddings. Keyword matching works, and embeddings would spin up the GPU.
75. · Routing plugin skills too; overrides do not hide them, so it needs plugin toggling.
76. · "Save as skill" from a Claude Code chat, as a Claude skill folder.
77. ✅ The Claude panel lists the skills offered to the chat.
78. · Different always-offered skills per Orbit project.
79. · A switch for Claude's bundled skills.
80. · A description-length setting for the skill listing.

## E. Tools and MCP

81. ✅ WebSearch, which needs Anthropic's servers, is off and the model is told to use WebFetch.
82. ✅ Heavy tools a local chat has no use for (Workflow, Cron, worktrees, ReportFindings, SendMessage…) are off, saving about 15,000 tokens.
83. ✅ Which tools are off is editable.
84. ✅ Pick the MCP servers from your Claude configuration (paper-fetch by default); only those load.
85. ✅ Or load them all.
86. ✅ Optionally, Orbit's own tools (memory, chat search, scheduling, web search) through an MCP bridge. Off by default.
87. ✅ A project's own trusted tools stay available in that project's chats, so project pipelines keep working.
88. ✅ Bridge calls run inside the chat, with Orbit's checks, on loopback with a per-run token.
89. ✅ MCP timeouts allow for a long wait on your approval.
90. ✅ Shell commands may run up to 10 minutes.
91. ✅ Context usage and MCP status from the Claude panel, while it runs.
92. · Buttons to toggle or reconnect an MCP server.
93. · Stop a background shell task from Orbit.
94. · `rewind_files`. Orbit's undo covers it.
95. · Orbit's web search in place of WebSearch without turning on Orbit's tools.
96. · Crawling helpers as a default MCP server.
97. · Images produced by tools shown inline.
98. · Diffs for notebook edits.
99. ◐ Browser automation servers: available when all MCP servers are loaded.
100. · MCP servers chosen per project.

## F. History

101. ✅ Claude sessions run on the local model in a terminal appear in the sidebar.
102. ✅ Optionally, sessions on any model too.
103. ✅ Scanning is fast: a byte search, cached by size and time, in the background.
104. ✅ Titles come from Claude's own titles, or the first message.
105. ✅ Opening one brings it into Orbit with its tool rows, thinking and images.
106. ✅ Harness wrappers are removed: system reminders, command output, caveats, time stamps.
107. ✅ Slash commands read as typed.
108. ✅ Compacted history is marked.
109. ✅ Continuing an imported chat continues the same Claude session.
110. ✅ Continuing an Orbit chat in a terminal brings the new part back when you open it.
111. ✅ Sessions are placed in the Orbit project whose folder they ran in.
112. ✅ A "CC" badge and a Claude filter in the sidebar; terminal-only sessions in italics.
113. ✅ Deleting one hides it; Claude's transcript is left alone.
114. ✅ Each chat has a copyable `claude-qwen --resume` command.
115. ✅ They sort in by time, and your manual order is kept.
116. · Search inside transcripts not yet opened.
117. · Read subagent transcripts.
118. · Import every session at once.
119. · Turn an Orbit chat from another model into a Claude session file.
120. · Follow a session live while it runs in a terminal.
121. ◐ Session names: Claude's are read; renaming in Orbit does not write back.
122. · Sessions from remote (SSH) projects.
123. · A badge for these chats in the iPhone app.
124. · Pin or archive a terminal session before opening it.
125. ✅ Claude Code runs count in Orbit's usage statistics.

## G. The `claude-qwen` command

126. ✅ The full harness (24 tools) instead of `--bare` (Bash, Read, Edit: not even Write).
127. ✅ The same setup as Orbit: profile, MCP servers, hooks, tools off, Orbit's skills.
128. ✅ `CLAUDE_QWEN_PROFILE` picks a profile for one run.
129. ✅ `CLAUDE_QWEN_BARE=1` brings back the old minimal mode.
130. ✅ `CLAUDE_QWEN_DRY_RUN=1` prints the command.
131. ✅ `ORBIT_MODEL_URL` / `ORBIT_MODEL_PORT` point it at another server.
132. ✅ It starts the local model when needed.
133. ✅ Dynamic system-prompt sections are left out, so the prompt stays cacheable across sessions.
134. ✅ The old launcher is kept as a backup.
135. · `claude-qwen --orbit` to open the session in Orbit.
136. · Shell completion.
137. · A status line with the local model's speed.
138. · A warning when Orbit is using the model.
139. ✅ A separate Claude configuration folder can be used (`ORBIT_CLAUDE_CONFIG_DIR`).
140. ✅ Documentation.

## H. Fitting a local model

141. ✅ The prompt went from about 46,000 tokens to about 14,000 (focused profile).
142. ✅ Resuming keeps the prompt's start unchanged, so the model's cache is reused.
143. ✅ Claude hooks are off unless you turn them on.
144. ✅ Subagents and the "small fast model" run on the local model too.
145. ✅ Telemetry, error reporting, auto-update and non-essential traffic are off.
146. ✅ Quiet mode: for a few hours the model server runs with MTPLX's "default" fan mode (macOS manages the fans).
147. ✅ Quiet mode in Settings (3 h, or off).
148. · A low-power profile (smaller context) for quiet hours.
149. · Run the model server at background priority.
150. ✅ Compaction is sized to the local model's context window.
151. ✅ Orbit's reasoning effort, and "retry deeper", reach Claude as `--effort`.
152. · A thinking-token budget control.
153. · A warm-up request after the model starts.
154. · Tokens per second per run in the statistics.
155. ✅ Large tool output is trimmed (by Claude).
156. ✅ Nothing starts a Claude session just to make a title.
157. ✅ History is not scanned when it is turned off.
158. ✅ The skill index is cached.
159. ✅ Which chats are linked to which sessions is cached.
160. ✅ The skills plugin is rebuilt only when needed.

## I. Interface

161. ✅ A Claude Code tab in Settings with every engine option.
162. ✅ A Claude panel: session, folder, mode, profile, skills, version, MCP.
163. ✅ Context usage and MCP status buttons.
164. ✅ A permission-mode switch in the title bar.
165. ✅ The model is listed as "Claude Code · local Qwen".
166. ✅ Engine notices appear as chat lines.
167. ✅ Approval boxes edit Claude rules, with Claude's suggestions.
168. ✅ Bypass needs confirming.
169. ✅ Skills Claude loads show as tool rows.
170. · Friendlier tool-row labels (the command for Bash, the file for Read).
171. · Subagent steps nested under their task.
172. ✅ Token and time stats under each answer.
173. ✅ Shift+Tab cycles the permission mode, as in Claude Code.
174. · A line saying a session was resumed or forked.
175. · The permission-mode switch in the iPhone app.
176. · Dropped files become `@file` mentions.
177. · `@` file autocomplete in Claude Code chats.
178. · Output style picker.
179. · Agent picker (`--agent`).
180. · A notice when Claude falls back to another model.
181. · A hint when Claude Code has an update.
182. · A first-run explanation of the profiles.
183. · Engine details in `/status`.
184. ✅ Undo works for files Claude changed (snapshots before each edit).
185. ✅ Stop interrupts cleanly.

## J. Safety, testing and docs

186. ✅ No real Anthropic key ever reaches the local harness.
187. ✅ The tools bridge answers loopback only, with a per-run token.
188. ✅ Tests write nothing into `~/.claude`.
189. ✅ A scripted stand-in for the Messages API makes the tests fast and exact.
190. ✅ End-to-end tests with the real `claude` binary, and offline tests.
191. ✅ Orbit's own engine tests stay on Orbit's engine.
192. ✅ Claude session markers are never sent to any other model.
193. ✅ Experiment transcripts were removed from `~/.claude`.
194. ✅ This document and `docs/claude-code-engine.md`.
195. ✅ Personal details checked before publishing.
196. ✅ Published.
197. · Rate limits on bridge calls.
198. ✅ `logs/claude.log`: one line per run (chat, session, mode, profile).
199. ◐ An answer cut off by an Orbit restart is picked up through the engine; Claude's side resumes from its transcript.
200. ✅ The Claude panel shows whether Claude Code is installed and its version.
