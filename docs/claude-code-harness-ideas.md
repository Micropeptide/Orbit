# Harness mode: 200 further ideas, and what became of them

Harness mode runs any model through Claude Code: the local Qwen, OpenCode Go and
Zen, DeepSeek, Qwen (Model Studio), GLM, MiniMax, Kimi, Anthropic and your own
endpoints. These are the ideas considered while building it (including what
[bunshin-desktop](https://github.com/frankkk96/bunshin-desktop) offers), marked
done (✅), partly done (◐) or not yet (·).

Tally: **107 done, 2 partial, 91 not yet.**

## A. Providers and models

1. ✅ A provider registry: base URL, key name, API format per model, context, small model.
2. ✅ OpenCode Go as the main preset, with each model's API (chat, Messages or Responses).
3. ✅ OpenCode Zen preset.
4. ✅ DeepSeek's Anthropic endpoint preset.
5. ✅ Qwen on Alibaba Model Studio, international and mainland endpoints.
6. ✅ GLM on Z.ai and BigModel.
7. ✅ MiniMax, with the wider auto-compact window its endpoint needs.
8. ✅ Kimi (Moonshot), .ai and .cn.
9. ✅ Anthropic itself.
10. ✅ The local MTPLX model as a harness model.
11. ✅ Your own providers: any base URL, any of the three APIs, your model list.
12. ✅ Region (base URL) choice per provider.
13. ✅ Hide models you do not want in the picker.
14. ✅ Models show only for providers with a key (and the local one).
15. ✅ Claude's opus/sonnet tiers map to the chosen model, the haiku tier to the provider's small model.
16. ✅ Subagents run on the same model.
17. ✅ Context window per model sets Claude's compaction point.
18. ✅ Model ids `harness:<provider>/<model>`; old `claude-qwen-cli:default` chats keep working.
19. ✅ Pick models by words: "deepseek v4 pro on opencode go", "kimi k3", "local qwen".
20. ✅ A test button per model: one short request through the same route a chat uses.
21. ✅ Model lists fetched live: models.dev (context, output limit, API per model) and the provider's own `/models` with your key; daily and on demand.
22. · Price per model and a running cost estimate.
23. · Per-model thinking/effort defaults.
24. · Automatic fallback to another provider when one is down.
25. · Model aliases you name yourself.
26. ✅ Each chat's context window follows its model (1M for DeepSeek V4…); the local Qwen keeps the server's.
27. · Edit a provider's extra environment in the page (the registry file supports it).
28. · Import providers from bunshin's database.
29. · Share a provider list between machines.
30. · Usage limits of OpenCode Go (5-hour / weekly / monthly) shown against your spend.

## B. The gateway

31. ✅ Translates Anthropic Messages requests to OpenAI chat completions.
32. ✅ Translates the streamed answer back: text, thinking, tool calls, stop reason, usage.
33. ✅ Cached tokens reported as cache reads.
34. ✅ Reasoning returned to reasoning models within a tool loop (DeepSeek needs it).
35. ✅ Images passed through as image parts.
36. ✅ Tool results placed right after the call that made them.
37. ✅ `tool_choice` any/tool/none mapped.
38. ✅ Non-streamed answers translated too.
39. ✅ OpenAI Responses API translation (GPT, Grok on OpenCode).
40. ✅ Anthropic-format models forwarded as is, with the key added.
41. ✅ Keys added by the gateway, never given to the Claude process (OpenCode).
42. ✅ Loopback only.
43. ✅ A private token: only Orbit's own Claude runs can use the keys behind it.
44. ✅ Upstream errors keep their status and meaning (429 → rate limit, 401 → authentication…), so Claude Code retries sensibly.
45. ✅ Token counting answered locally.
46. ✅ Proxy setting for model requests.
47. ✅ Request and error counts per provider, shown in Settings.
48. ✅ Starts with Orbit; its port is configurable.
49. ✅ Brief upstream failures (connection errors, 502/503/504) retried twice inside the gateway.
50. · Request log with timing per model.
51. ✅ Replies capped at each model's output limit.
52. · Documents (PDF blocks) converted to text for models that cannot read them.
53. · Prompt caching hints for providers that support them.
54. · Rate-limit awareness (wait and resume instead of failing).
55. · Keep-alive connections to providers.
56. · Streaming JSON repair for tool arguments some models malform.
57. · Gateway as its own service, usable when Orbit is closed.
58. · HTTPS for the gateway.
59. · Per-provider timeouts.
60. · Gemini's API format.

## C. The engine

61. ✅ One engine for every harness model; the local-only paths (waking the model, one answer at a time) apply to the local model only.
62. ✅ Remote models run alongside each other and alongside local chats.
63. ✅ A chat can switch model and keep its Claude session.
64. ✅ A missing key is explained before anything runs.
65. ✅ Titles, memory notes and summaries go to the chat's own provider, not the local model.
66. ✅ Resume commands name the right launcher and model.
67. ✅ Terminal sessions opened in Orbit keep the model they ran on.
68. ✅ History includes sessions on any harness model (not ordinary Claude sessions).
69. ✅ Each answer is labelled with its model and provider.
70. ✅ Usage from every provider feeds the context meter and statistics.
71. · Per-chat fallback model (`--fallback-model`).
72. · Warn when a model's context is smaller than the chat so far.
73. · Compare two models on the same message.
74. · Route subagents to a cheaper model.
75. · Record the provider's request id with each answer.
76. · Show cost per answer.
77. · Remember the last model used per folder.
78. · Offline detection before starting a remote run.
79. · Tool-use capability check per model.
80. · Effort levels mapped to each provider's reasoning settings.

## D. Scheduled tasks

81. ✅ A scheduled task names its model, in words or as an id.
82. ✅ The scheduling tool accepts a `model` and reports which model will run it.
83. ✅ Unknown model names are refused with a list of choices.
84. ✅ A model picker in the task form and on each task.
85. ✅ Scheduled runs honour the task's model (they used whichever model was last active).
86. ✅ Tasks whose tools belong to a project stay on the model those tools were built for.
87. · Fall back to another model when a scheduled run's provider fails.
88. · Budget per scheduled task.
89. · Run a task on several models and compare.
90. · Notify with the model that ran it.

## E. Starting chats (bunshin's agents)

91. ✅ "New chat with…": model, working folder and permission mode together.
92. ✅ Save that as a preset; start or delete presets.
93. ✅ Recent folders and project folders offered.
94. ✅ Folder chip and mode switch on every Claude Code chat.
95. · Preset avatars and descriptions.
96. · Presets with their own system prompt, disabled tools, allow/deny rules, MCP servers and extra settings (bunshin's per-agent config).
97. · Presets in the iPhone app.
98. · A preset per project.
99. · Duplicate a preset.
100. ✅ Cmd/Ctrl+Shift+K opens "New chat with…".

## F. Terminal

101. ✅ `claude-harness <model>`: the interactive harness on any harness model.
102. ✅ It explains a missing key or a stopped gateway.
103. ✅ Dry run shows the command without secrets.
104. ✅ Its sessions appear in Orbit's sidebar.
105. · Shell completion for model names.
106. ✅ `claude-harness --list`.
107. · Pick a model interactively.
108. · Use the gateway without Orbit running.
109. · A status line with the model and gateway state.
110. · `claude-harness --orbit` to open the session in Orbit.

## G. Settings page

111. ✅ Models section: providers, keys (entered by you, stored in Orbit's secrets), regions, models, tests.
112. ✅ Add your own provider.
113. ✅ Proxy.
114. ✅ Gateway status and counts.
115. ✅ "Get a key" links.
116. ✅ Key removal.
117. · Search models.
118. · Mark favourite models.
119. · Reorder providers.
120. · Show each model's price and limits.

## H. Bugs fixed along the way

121. ✅ Saving one provider's key erased every other saved key.
122. ✅ Saving one provider's region replaced other providers' settings.
123. ✅ Claude Code chats on the local model did not wait their turn with other local answers.
124. ✅ The local model appeared twice in the picker.
125. ✅ Scheduled runs used the last active model instead of their own.
126. ✅ The gateway could have been used by any program on the Mac.
127. ✅ The page kept polling running answers while hidden with nothing running.
128. ✅ History scanning re-read every transcript once per model name.
129. ✅ Ordinary Claude sessions would have been listed as harness sessions.
130. ✅ Imported sessions were always given the local model.

## I. From bunshin-desktop

131. ✅ Any Anthropic-compatible provider with base URL, key and model.
132. ✅ Provider guide values (DeepSeek, Qwen, GLM, MiniMax, Kimi) as presets.
133. ✅ The three tier variables set to the provider's model.
134. ✅ Working folder per conversation.
135. ✅ Permission modes, including dontAsk and bypass.
136. ✅ Environment of other Claude sessions never leaks into a run.
137. ✅ Resume by session id.
138. ✅ Permission request cards (allow once, don't ask again, deny).
139. ✅ Image attachments.
140. ✅ Proxy.
141. ◐ Per-agent configuration: effort, extra system prompt, disabled tools and MCP servers exist as launcher settings; per-preset versions do not.
142. · A private Claude configuration folder per app (bunshin isolates `CLAUDE_CONFIG_DIR`; Orbit uses yours on purpose, so the terminal and Orbit share skills and history).
143. · Bundling Claude Code inside the app.
144. · Auto-update.
145. · Crash reporting.
146. · Interface languages.
147. · Agent avatars.
148. · PDF attachments as documents.
149. · A local SQLite store for conversations.
150. · Windows build.

## J. Reliability and safety

151. ✅ Keys never written to the registry file.
152. ✅ Settings API never returns key values.
153. ✅ Tests use scripted stand-ins for both APIs; no network, no model, no keys.
154. ✅ End-to-end tests with the real `claude` binary through the gateway.
155. ✅ A provider's key goes only to that provider.
156. ✅ Gateway token file is private to your account.
157. ◐ Errors from providers are readable in the chat; a few formats may still show raw text.
158. · Key storage in the macOS Keychain.
159. · Rotate the gateway token from Settings.
160. · Warn before sending a chat to a remote provider for the first time.
161. · Mark chats that left the Mac.
162. · Redact keys from any log line.
163. · Spend limits per provider.
164. · Alert on unusual usage.
165. · Health check of all providers at once.
166. · Timeout and retry settings per provider.
167. · Detect a key for the wrong region.
168. · Detect a model that silently falls back to another (DeepSeek).
169. · Verify TLS certificates of custom providers explicitly.
170. · Audit log of which provider saw which chat.

## K. Interface

171. ✅ Models grouped by provider in every picker.
172. ✅ "needs a key" shown where it applies.
173. ✅ Claude Code chats recognised for every harness model.
174. · Model badge in the sidebar.
175. · Filter the sidebar by model.
176. ✅ Claude Code mode: provider and model pickers in the header, orange accent, new chats and Settings follow the harness.
177. · Model chosen per message.
178. · Show the provider's rate limits.
179. · Per-model colour.
180. · Onboarding for adding the first key.

## L. Documentation

181. ✅ Harness mode guide (`docs/claude-code-engine.md`).
182. ✅ This list.
183. ✅ README row for harness mode.
184. · A troubleshooting page per provider.
185. · Screenshots of the Models section.
186. · A short video.
187. · Examples of custom providers (vLLM, Ollama with an Anthropic shim, LM Studio).
188. · Notes on which models handle Claude Code's tools best.
189. · Migration notes from bunshin.
190. · Localised docs.

## M. Later

191. · Run the harness on a remote machine and stream it to Orbit.
192. · Several models collaborating in one task.
193. · Evaluate models on your own tasks.
194. · Choose a model automatically by task.
195. · Share presets as files.
196. · Import Claude Desktop sessions.
197. · Web search through a provider that offers it.
198. · MCP servers per model.
199. · Voice input for harness chats.
200. · The iPhone app choosing harness models.
