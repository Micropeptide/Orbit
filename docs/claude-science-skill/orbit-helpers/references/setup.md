# Connecting an agent to Orbit

The `orbit_*` tools come from an MCP connector that Orbit offers on the person's Mac. If they are missing, tell the person:

1. In Orbit: **Settings > Helpers**, turn on "Turn it on", and add this app by name (Claude Science is there by default; add another for Claude Code, Codex and so on). Each app gets its own token, folders and limits.
2. In the agent, add Orbit as a connector. Most sandboxed agents (Claude Science included) cannot reach this Mac's local addresses and may not run programs from a home folder, so use **Remote** with the address on the Orbit service: in Orbit's Settings > Helpers click "Allow access through the Orbit service" (needs the person signed in to their Orbit account), then "Copy the remote address for <the app>" and paste it as the connector's address (Claude Science: Customize, Connectors, add, **Remote**, name `orbit`, other boxes empty). The address contains the app's own token: keep it private. Calls through the service wait at most about 85 seconds, so a long `wait_s` returns early; just call again.
   - Agents that can use a local command instead: `/usr/bin/python3 /usr/local/bin/orbit-helpers-mcp` (Orbit's "Install the launcher" puts that file there), with the environment variables `ORBIT_HELPERS_URL=http://127.0.0.1:8455/mcp` and `ORBIT_HELPERS_TOKEN=<the token>` if it cannot read Orbit's settings. Claude Code: `claude mcp add orbit -- /usr/bin/python3 /usr/local/bin/orbit-helpers-mcp --app "Claude Code"`.
   - Agents that can reach local addresses can use `http://127.0.0.1:8455/mcp` with the header `Authorization: Bearer <the token>`.
3. Start a new session so the agent loads the tools, then call `orbit_models`.

Orbit answers only on that Mac and only with a valid token. If a call says the token was refused, the app was removed or its token replaced: ask the person to check Settings > Helpers. If it says Orbit is not running, Orbit is closed or Helpers is off. The agent cannot test the connection from inside its own sandbox (it cannot reach the Mac's local addresses); the connector itself can.
