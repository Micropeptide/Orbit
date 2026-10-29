# Shared projects: design (round 0)

Status: decided 2026-10-27, implementation starts with the policy engine and the event log. Spec: `docs/collaboration-prompt.md`. Threat model: `THREAT_MODEL.md`. Wire format: `PROTOCOL.md`.

## 1. What this is

Several people work in one Orbit project: a group chat with one or more shared models, every message labelled with its author, every model action labelled with the person who caused it, where it ran and with what permission. Everything a model does for a member is limited by what that member may do, and by the project's rules, and is checked before it runs.

Not in scope now: co-editing one document live (no CRDT), running a model on a member's own computer for the project, federation between hosts.

## 2. The central decision: hybrid, host first

| | A. Host | B. Relay/sync | C. Hybrid (chosen) |
|---|---|---|---|
| Where models and files act | the host's Mac (or a server the host reaches, e.g. HPC) | each member's own Orbit | the host, always |
| Who needs a VPN / open port | members need to reach the host | nobody | nobody (relay) or members (direct) |
| Safety | one place to guard; nobody else's computer is reachable | each member's computer runs actions caused by others: the hard rule "no one reaches another computer" is only as good as every client | one place to guard |
| Privacy | content stays on the host | the relay holds content | the relay holds only ciphertext |
| Host offline | project unreachable | works | messages queue at the relay (encrypted) and are delivered when the host is back |

**Choice: C, built in this order.** (1) Host mode over the path Orbit already has (Tailscale Serve HTTPS, the same device-token machinery as the phone), clients are the browser, Orbit for Mac and the phone. (2) The relay on runtianwu.com (a Cloudflare Worker with a Durable Object per project) that carries end-to-end encrypted events, queues messages while the host is offline, and keeps an encrypted backup of the event log. Members never run actions for the project; their Orbit is only a client. The host may point the project's working directory at a server (HPC over its own ssh), which stays the host's credential, never a member's.

## 3. Parts

- **Host Orbit** (`bin/orbit-ui` + new modules): the project store, the event log, the turn engine, the policy engine, the guard, the execution jail. New code lives in `bin/collab_*.py`; routes under `/api/collab/`. The whole feature is off until the owner turns "Shared projects" on, and a project with one member behaves exactly as Orbit does today.
- **Clients**: the existing web page (Mac, browser, phone's web view is not used: the phone app talks to the same routes natively). A client holds a member token for one host.
- **Account service** (`orbit.runtianwu.com`, Cloudflare Worker + D1, built and tested locally, deployed by the person): sign-in with Google, Microsoft, GitHub, Apple, email link, passkeys; issues short-lived signed account tokens. It knows who a person is, never what they do. See section 7.
- **Relay** (same Worker, Durable Object per project): opaque encrypted events in, opaque encrypted events out, an outbox for the offline host. No plaintext, no keys.
- **Fake identity provider** for tests (`tests/fake_idp.py`): speaks OIDC locally.

## 4. The project on disk (host)

`collab/<project id>/` under Orbit's data folder:
- `project.json`: id, name, created, working directory, project instructions, turn mode, default guard settings, protocol version, "private mode" flag.
- `members.json`: member id, display name ("appear as"), role template, account link (provider, subject) or invite-only, device list (token hashes only), state (active, muted, removed), joined.
- `grants.json`: the explicit grants (section 5), each with who set it and when; the audit trail is the event log.
- `events.jsonl`: the append-only log (section 6).
- `chats/`: one session file per shared chat, the same format Orbit uses today, so models, rewind, queue and search keep working. A chat is shared by default; `visibility: {mode: all|members, members: [...]}` makes it private to some members, and a private chat is not listed, searched, counted or streamed to anyone else.
- `files-index.json` (later): who changed which file in which message.

Secrets (account refresh tokens, relay keys) go to the Keychain or `secrets.json` that Orbit already protects; never into `collab/`.

## 5. Permissions

**Roles** (templates only): owner, admin, editor, commenter, viewer, guest. A role expands to a **grant**; the real thing is the grant, explicit and revocable, optionally time-boxed, per member, and optionally narrowed per chat.

A grant has: `read_paths`, `write_paths` (path allowlists, absolute, resolved through symlinks), `deny_paths` (win over allows), `tools` (read, edit, shell, network, git, cluster, browser, delegate, schedule, crew, models), `shell` (none, read, build, all), switches `delete`, `move_out_of_scope`, `git_push`, `install`, `network`, `secrets` (all off for everyone but the owner), `models` (allowed model ids and whose account pays), `budget` (tokens, calls, cluster minutes, per day), `approver`, `can_start_crew`, `can_touch_cluster`, `can_add_members`, `can_change_grants`, `expires_at`.

**Whose authority.** An action caused by a message from member B runs with `effective = grant(B) ∩ project policy ∩ NEVER`. A turn that carries messages from several authors runs with the intersection of all of them (or the owner picks one-turn-per-author). A scheduled message or crew round runs with the grant of whoever created it, evaluated again at run time, so a revoked grant stops it. Text from files, pages and tool output never changes `effective`.

**NEVER list** (hard, not configurable by anyone through chat): Orbit's own settings and secrets, pairing and remote access, the shell profiles and login items, keys and tokens, `~/.claude`, `~/.codex`, the whole of `collab/` except through the project's own API, other people's folders, the home directory root. It reuses `qqcore.sensitive_write` and `sensitive_read`.

**Three layers, in this order, before any tool call:**
1. **Policy engine** (`collab_policy.py`, plain code): path jail with real-path resolution, capability check, shell classification, rate limits, NEVER list. Decides alone when the answer is clear.
2. **Guard model** (`collab_guard.py`): a separate model, chosen by the owner, with the owner's own instructions; sees only the action, who, the role, the working directory, the recent chat (marked untrusted) and the policy; answers allow, deny with a reason, or ask a human; fails closed.
3. **Human approval**: for what the guard or the policy marks risky; approver sees the exact command or diff, who asked and why; approve once / for this chat / deny with a reason the model reads; approvals expire; the most dangerous class can need two people.

Every decision is an event.

**Containment.** Commands run with a scrubbed environment (no host secrets, no personal tokens), in the project working directory, under a macOS sandbox profile where available, with limits and timeouts; per-member checkpoints for one-click undo; no member's computer is ever a target: the only machine an action can run on is the host (or the server the host chose).

## 6. The event log

One per project. Each event has `seq` (assigned by the host, gapless), `id`, `ts`, `type`, `author` (member id, or `model:<id>`, or `system`), `device`, `payload`, `prev` and `hash` (SHA-256 over the canonical form with `prev`): tamper-evident, exportable, replayable. Clients render the log; they reconnect and resume from `seq` over server-sent events (polling fallback for the phone). The host is the only writer: a client posts an intent, the host validates (token, role, grant, size, rate), appends and broadcasts. Types: `msg`, `edit`, `delete` (a tombstone; the original stays in the log under the retention rule; a message the model has already read cannot be deleted), `react`, `thread`, `model_turn_start`, `model_turn_end`, `tool_request`, `guard_decision`, `approval`, `tool_result`, `queue_add`, `queue_withdraw`, `join`, `leave`, `grant`, `revoke`, `role`, `member_state`, `decision_pin`, `task`, `note`, `panic`, `config`.

Chat text is untrusted data everywhere: stored raw, escaped on render, and fenced in prompts.

## 7. Accounts

Identity is optional: a host can run an invite-only project with signed invite links and no account service at all.

With accounts: the person signs in on `orbit.runtianwu.com` (OIDC authorization code + PKCE, strict `state` and `nonce`; passkeys; email link) and gets an **account token**: EdDSA-signed JWT, 15 minutes, claims `sub` (stable id), `name`, optional `avatar`, `iat`, `exp`, `aud: "orbit"`; refresh tokens rotate and are revocable per device; the public keys are published at `/.well-known/jwks.json` and cached by hosts so a host can verify a token offline. The host maps `sub` to a member and issues its own **member token** per device (random, stored hashed), so a leaked account token never grants project access by itself and a removed member's tokens die on the host immediately.

The service stores: account id, display name, optional avatar URL, linked sign-in methods (provider + subject), device list, hashed optional email. Never chat, file names or project data. No analytics, no cookies beyond the session, short log retention, delete-account and export in one action. Cloudflare Turnstile for bot protection (no tracking). Details and the service's own threat model: `docs/collab/ACCOUNTS.md` (written with the Worker).

## 8. Offline, queue, backup

The host appends in order; if the model server is loading or down, a message is still an event and the turn waits in the queue with its author (reusing the model-wait gate). If the host is offline, clients (through the relay) put encrypted message intents in the project's outbox; the host drains it on return, validates each against the grants *as of now*, and appends. The relay also keeps a periodically refreshed encrypted copy of the log (key held by the owner) as the cloud backup; restoring is an owner action. "Private mode": nothing leaves the host, no relay, no backup.

## 9. What changes for existing Orbit

Nothing, unless a project is shared. `risk_check` stays the base: the collab policy only adds checks for turns that belong to a shared project, and never relaxes it. The crew, goals, queue, rewind, scheduler and Cluster page get a `member` argument in later slices; until then they are owner-only inside a shared project.

## 10. Slices (each tested, small, behind the switch)

1. `collab_policy.py` (roles, grants, intersection, path jail, shell classification, `decide`) + red-team tests. **First.**
2. `collab_store.py`: project, members, invites, the event log with hash chain, resume cursors, tombstones, retention; red-team tests for forging, replay, tampering.
3. Routes + host auth (member tokens, invites) + SSE; two simulated members in the sandbox.
4. Web UI: Shared projects section, authorship on messages, "who is the model working for", presence, queue with authors, grants screen.
5. Turn engine: modes, queue fairness, effective grant per turn, model labels; guard model; approval flow; audit view; kill switches.
6. Execution jail; checkpoints per member; file view with blame.
7. Accounts: Worker + fake IdP + sign-in on Mac and phone; invites and guests.
8. Crew/cluster/goals/schedule in projects with permissions; notifications; search; export, replay; budgets.
9. Relay, encrypted outbox, backup.
10. Phone parity; the shareable build and installer; update path.
