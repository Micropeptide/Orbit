# Shared projects: protocol, version 1

A client that sees a higher `proto` than it knows must stop with "update Orbit"; a host refuses a client that sends a version it does not support, with a message naming both versions.

## Auth

`Authorization: Bearer <member token>`. A member token is 32 random bytes, base64url, issued by the host per device at join; the host keeps only `sha256(token)`. An account token (JWT) is accepted only at `POST /api/collab/join`, once, to bind an account to a member and receive a member token. Every state-changing route also requires `Origin` to be the host's own origin or absent (native apps), and a JSON body.

## Routes (host)

All under `/api/collab/`. Errors: `{"error": "...", "code": "..."}` with 400 bad input, 401 no/invalid token, 403 not allowed (the message says which grant is missing), 404, 409 conflict, 413 too large, 429 rate limit, 426 protocol version.

| Method | Path | Who | What |
|---|---|---|---|
| GET | `/projects` | member | projects this token belongs to |
| POST | `/projects` | local owner only | create (name, working directory, turn mode) |
| GET | `/p/<pid>` | member | project, members (public fields), my grant, protocol |
| GET | `/p/<pid>/events?tail=1&limit=` / `?before=<seq>&limit=` | member | the newest events this member may see (or the page before a seq), oldest first, as `{events, head, next, more_before}`; `head` is the cursor to stream or poll from |
| GET | `/p/<pid>/events?after=<seq>&limit=` | member | events after a cursor, only those the member may see; `Accept: text/event-stream` streams them, with `id: <seq>` so a browser resumes by itself |
| POST | `/p/<pid>/intent` | member | `{id, nonce, type, chat, payload}`: a message, edit, delete, react, queue withdraw, approval, task...; host validates and appends; answers `{seq}` |
| POST | `/p/<pid>/invite` | `can_add_members` | `{role|grant, expires_in, uses}` -> `{link, id}` |
| POST | `/join` | anyone with a link | `{link, name, account_token?}` -> `{member, token}` |
| POST | `/p/<pid>/grants` | `can_change_grants` | set or revoke a member's grant |
| POST | `/p/<pid>/members/<mid>` | admin | mute, remove, block |
| POST | `/p/<pid>/panic` | owner/admin | stop answers, pause crews, freeze grants |
| GET | `/p/<pid>/verify` | owner | verify the hash chain |
| GET | `/p/<pid>/export?format=md|json` | member | their visible view |

## Event

```
{ "seq": 41, "id": "e_9f2c...", "ts": 1793150000.123, "type": "msg",
  "author": "m_ab12" | "model:harness:claude/sonnet" | "system",
  "device": "d_77", "chat": "c_main", "payload": {...},
  "prev": "<hash of seq 40>", "hash": "<sha256 of canonical(event without hash)>" }
```

`canonical` = JSON with sorted keys, no spaces, UTF-8, floats as written by the host. The first event has `prev = "0"*64`.

Payloads (selected):
- `msg`: `{text, to: ["model:..."]|[], reply_to?, thread?}` (text <= 100 kB)
- `model_turn_start`: `{turn, initiated_by: [member...], model, payer, cwd, effective: <grant summary>, queue_pos}`
- `tool_request`: `{turn, tool, args_summary, touches: [paths], requested_by}` -> `guard_decision`: `{verdict, layer: policy|guard|human, reason}` -> `approval`: `{request, approver, mode: once|chat, expires}` -> `tool_result`: `{ok, summary}`
- `grant`: `{member, grant, set_by}`; `revoke`: `{member, what, set_by}`
- `delete`: `{target, tombstone: true}`; the text is removed from client views; the original is kept in the log encrypted under the retention rule, and a message with `seen_by_model` cannot be deleted.

## Invites and joins

Invite link: `orbit://join?host=<url>&p=<pid>&i=<invite id>&s=<secret>` (and the same as an https page for browsers). The secret is random and stored hashed; an invite has `role|grant`, `expires`, `uses`, and the owner can list and revoke it. A host without the account service signs the link (HMAC with a host key) instead of storing it.

## Relay (later, host mode first)

The relay stores only `{project, seq?, box, nonce, ciphertext}` blobs (AES-256-GCM, key held by members and host, wrapped to each device key). Client -> relay -> host outbox for an offline host; host -> relay for encrypted backup. The relay authenticates members by account token and never sees keys.

## Account service API (summary)

`GET /.well-known/jwks.json`; `GET /auth/<provider>/start`, `/callback` (PKCE, state, nonce); `POST /auth/email`, `/auth/passkey/*`; `POST /token/refresh` (rotating); `GET /me`, `DELETE /me`, `GET /me/export`; `GET /devices`, `DELETE /devices/<id>`. Detailed in `ACCOUNTS.md` when the Worker is written.
