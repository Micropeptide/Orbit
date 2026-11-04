# Claude Code features Orbit does not fully support yet

Audited 2026-10-30 against Claude Code 2.1.300 (`claude --help`, its subcommands, the binary's strings) and Orbit's `CMDS` list
(`web/app.js`), `CONTROLS` (`bin/claude_engine.py`) and its system-event renderer. Most valuable first. Size: S small, M medium, L large.

Already covered: all six permission modes, `/rewind` (with files), `/fork`, `/resume`, `/compact`, `/context`, `/usage`, `/tasks`,
`/worktree`, `/export`, `/diff`, `/add-dir`, `/goal`, "Ran N hooks" summaries, elicitation, prompt suggestions, MCP list/add/remove,
plugins, skills. Unknown slash commands in a Claude chat go through to Claude, so `/init`, `/review`, `/security-review`, `/loop` and skills work.
Done since the audit: the cost chip, MCP server list with sign-in and a reload-plugins button (`/mcp-servers`), the status line, your own shortcuts and keybindings.json (`/keys`), cloud sessions / `--from-pr` / remote control typed into the terminal (`/cloud`), subagent definitions with a model each (`/subagents`), the hooks list (`/hooks`), `/claude-options` (subagent model, spending limit, subagent text, autocompact), the plan card for `ExitPlanMode`, background sessions (`/background`, `/bg <task>`), `/init` `/review` `/security-review` shortcuts, answers Claude starts by itself shown as answering, thinking summaries (`showThinkingSummaries`), Claude Code's own model fallback (card + the model that really answered).

| # | Gap | Where it would plug in | Size |
|---|-----|------------------------|------|
| 1 | Hooks editor/viewer (26 events; `get_hooks_listing`); today only the on/off `disableAllHooks` | `CONTROLS`, Claude settings panel in `web/app2.js` (`#cc_hooks`), per-hook detail in the "Ran N hooks" block | M |
| 2 | Output styles (`/output-style`, `outputStyle`); init already reports `available_output_styles` | picker in `claudePanel` (`web/app.js`), `outputStyle` in the per-run settings (`launcher_files`) | S |
| 3 | Cost per chat (`/cost`, `get_session_cost`, `--max-budget-usd`) | cost chip, a "stop at $N" setting in the argv builder | S–M |
| 4 | "Always allow" on the approval card (`permission_suggestions` -> `updatedPermissions`) | `can_use_tool` reply in the engine; approval card in `web/app.js` | M |
| 5 | `statusLine` command | footer, `drawModeHint` area | M |
| 6 | Subagent definitions (`.claude/agents/*.md`, `--agent`, `--agents`) | Library > agents tab, argv builder | M |
| 7 | Reload plugins/skills button (`reload_plugins` is in `CONTROLS`) | plugins panel | S |
| 8 | MCP OAuth + resources (`mcp_authenticate`, `mcp_read_resource`); `mcp_status` is only a JSON dump | Claude MCP list in `web/app2.js` | M–L |
| 9 | `/btw` side question (`side_question`) | `CONTROLS`, `CMDS`, popover | S |
| 10 | Plan card for `ExitPlanMode` (Approve / Keep planning / open plan file) | tool card renderer | M |
| 11 | `/fast` and live `list_models` for the Claude picker | `apply_flag_settings`, picker | S–M |
| 12 | `--autocompact N` window slider | argv builder, Claude panel | S |
| 13 | `--json-schema` for Crew/delegate reviewer scores; `--max-turns` | argv builder | S |
| 14 | `--forward-subagent-text`: subagent text and thinking under their Task card | argv + renderer (`parent_tool_use_id` is already parsed) | M |
| 15 | Background sessions (`--bg`, `claude agents`, attach/logs/respawn) | "Run in background" send option, sessions list | L |
| 16 | `--from-pr`, `--teleport`, `--cloud`, `/remote-control` | New chat dialog | M |
| 17 | `/init`, `/review`, `/security-review` as buttons | empty-chat state, Memory panel | S |
| 18 | `/recap` ("catch me up"), `away_summary` | button | S |
| 19 | Memory: `memory_recall`/`memory_saved` events, `autoMemoryEnabled`, `/pause-memory`, `claudeMdExcludes` | under each answer; Memory panel | M |
| 20 | Settings keys without UI: `alwaysThinkingEnabled`, `cleanupPeriodDays`, `attribution`, `includeGitInstructions`, `apiKeyHelper`, `availableModels`, `modelOverrides`, `enabledPlugins`, `autoMode`, `worktree`, `plansDirectory`... | a generic "Advanced" JSON editor for `~/.claude/settings.json` | M |
| 21 | `set_max_thinking_tokens` slider, `sandbox` toggle, `--safe-mode` troubleshoot button | Claude panel | S–M |
| 22 | Keybindings / vim mode | low value in a web UI | S |
| 23 | `api_retry` status chip, reset countdown (`/rate-limit-options`) | status line | S |
| 24 | `file_suggestions` control for `@` completion from Claude's own index | composer | S |
| 25 | `rename_session` (`/rename` also renames the Claude transcript), `get_task_output` for long background tasks, `get_workspace_diff` | commands, task rows | S–M |

Suggested next order: 2, 3, 4, 9, 17 (visible, small), then 6, 8, 14 (largest functional gaps).
