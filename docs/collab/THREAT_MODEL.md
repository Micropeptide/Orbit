# Shared projects: threat model

Assets: the host's computer and files; the host's keys, accounts and cluster login; other members' data and privacy; the integrity of the project's record; the account service's data.

Trust: the owner/host is trusted with their own machine. Everyone else is not. Every member's text, every file, web page and tool result a model reads is untrusted data. Models are not a security boundary: the policy engine and the jail are.

| # | Attacker | Wants | Controls | Test (red-team suite `tests/test_collab_redteam.py`) |
|---|---|---|---|---|
| 1 | Malicious member | delete or change files outside their scope | path jail on real paths (symlinks, `..`, case, unicode normalisation), write allowlist, deny list wins, delete switch off by default | escape attempts: `../`, absolute, symlink out, NFD/NFC and case variants, `~`, trailing dots, null byte |
| 2 | Malicious member | run dangerous commands (`rm -rf`, `curl | sh`, `git push`, `ssh`, `scp`, `osascript`, `launchctl`, write `~/.zshrc`) | shell classification into read/build/other; `shell` level must cover it; NEVER list; base `risk_check` still applies | each command, with quoting, `;`, `&&`, `$()`, backticks, `env`, `sudo` prefixes |
| 3 | Malicious member | read or change Orbit's settings, keys, pairing, remote access | NEVER list through real paths; the collab API is the only way into `collab/` | read/write `settings.json`, `remote-token`, `secrets.json`, `collab/` |
| 4 | Malicious member | use the host's model account, cluster or keys | grants name allowed models and payers; env scrubbed in the jail; cluster only with grant | model not in grant; env dump shows no secrets |
| 5 | Malicious member | raise own role, forge another's authorship | every intent is authenticated to a member token; the host sets `author` itself; role/grant changes need `can_change_grants` and are events | forged `author` field ignored; self-promotion refused |
| 6 | Malicious member | confused deputy: make the model act with the owner's power | `effective = grant(author) ∩ project ∩ NEVER`; turns with several authors use the intersection; schedules re-evaluate at run time | owner-and-guest messages in one turn; schedule then revoke |
| 7 | Malicious member | prompt injection in a message | text fenced and labelled untrusted; the guard cannot be changed by chat; policy is code | "ignore previous instructions" in message, file, web page; guard asked to approve forbidden action |
| 8 | Poisoned file or page | same, via content | content never raises permissions; instruction-like text in a tool result is flagged to the members | file with injected orders; flagged |
| 9 | Malicious member | stored XSS / markdown abuse | all text escaped on render; links get `rel=noopener`; no raw HTML | `<script>`, `<img onerror>`, `javascript:` links, huge nested markdown |
| 10 | Malicious member | flood: queue, huge messages, many connections | size and rate limits per member; queue caps; SSE connection caps | 1 MB message, 10k messages, 500 connections |
| 11 | Stolen or leaked invite link | join as someone | random, single-use or limited, expiring, role-capped, owner sees and revokes; join is an event | expired, used, revoked, wrong project |
| 12 | Stolen device / token | act as the member | tokens hashed on the host, per device, revocable; removing a member kills all tokens at once; short account tokens | revoked token refused immediately |
| 13 | Replay | reuse an approval or an intent | approvals bound to action hash, approver, chat, expiry, single use; intents carry a nonce and are idempotent by id | replay approval for another action; resend intent |
| 14 | Tamper | rewrite history | hash chain; the host is the only writer; export verifies; tombstones keep originals under retention | edit a line in the file: verification fails |
| 15 | CSRF / cross-origin | cause actions from another site | origin check and token required on every state-changing route; no ambient cookie authority | cross-origin POST without token |
| 16 | Compromised provider account | sign in as a person | account service links by `(provider, subject)` only after consent; new-device notice; passkeys; the host still requires a grant the owner gave that person | provider subject change; unlink |
| 17 | Curious operator of the account service / relay | read chats | the service never receives content; the relay sees only ciphertext and sizes/timing; keys never leave members and host | the code path never sends plaintext (asserted in tests) |
| 18 | Careless member | does something harmful by accident | defaults off, approvals, checkpoints per member, dry-run mode, "what would this touch" preview | delete requires approval; undo restores |
| 19 | Host mistake | shares too much | grants screen shows everything; project working directory is shown on every model action; panic button | UI test: grants screen lists all |
| 20 | Removed member | keep access or data | tokens revoked, sessions closed, project secrets rotated on request, private chats stay private | removed member's SSE closes; API 401 |

Residual risks (accepted, stated to the user): a model with write access inside a member's scope can write harmful content there (checkpoints and review limit it); the host can read everything on their own machine; the relay operator can drop or delay messages (not read or forge them); timing and size metadata at the relay.
