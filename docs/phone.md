# Orbit on your phone

The Mac keeps everything; the app is a window onto it. There is no second copy
to reconcile and no cloud account — the phone talks to your Mac directly.

## Turning it on

**Settings → Phone** on the Mac. It is off by default, because Orbit has no
login and anything that can reach it can run code on your machine.

| Mode | What it does | Use it when |
|---|---|---|
| **Off** | Only the Mac itself can reach Orbit | the default |
| **Tailscale** | Fronted by **Tailscale Serve**: HTTPS with a real certificate at your Mac's MagicDNS name (`https://<mac>.<tailnet>.ts.net:8443`), the same door other tailnet apps use. The plain port is bound to the tailnet address only, never to whatever Wi-Fi you are on | you want it to work from anywhere |
| **Local network** | Binds every interface | you are at home on a network you trust |

Pick one, restart, and a QR code appears. Scan it with the app.

## What the QR carries

The address and a 32-byte pairing token. The token is generated on your Mac,
stored `chmod 600`, and lands in the iPhone's Keychain — you never type it.

Every request from off the machine must carry that token, compared in constant
time. Loopback is exempt, so nothing about using Orbit at the Mac changes.

**Rotate token** in the same panel invalidates every paired device at once. Use
it if a phone goes missing.

Requests arriving through Tailscale Serve reach Orbit over loopback with
forwarding headers; Orbit treats those as remote, so the token still applies.
The QR also lists fallback addresses (the tailnet IP, the `.local` name on a
LAN) and the app tries them by itself, then keeps learning new ones from the
Mac — you scan once.

The phone needs the Tailscale app connected to the same tailnet. If Orbit says
it can't reach the Mac, that is the first thing to check.

How this path was arrived at, and every way it failed first, is written up
for anyone building something similar in [tailnet-playbook.md](tailnet-playbook.md).

## What the app does

| | |
|---|---|
| **Chats** | live list grouped by day, pin, archive, rename, bin, share as Markdown; filter by project |
| **Search** | titles *and* the text of every message; tapping a hit jumps to that line and flashes it |
| **Conversation** | streaming answers, Markdown with fenced code and a copy button, collapsible thinking, tool chips, approval prompts |
| **Message actions** | long-press: copy, share, *edit and resend* (cuts the conversation back to that point on the Mac), *ask again* on the last answer |
| **Compact history** | summarises the older turns of a long chat on the Mac, from the ⋯ menu |
| **Attachments** | photos from the library, a picture from the camera, or any file from the Files app — uploaded to the Mac and sent with the next message. Photos are downscaled to 1600 px before upload |
| **Plots and images** | matplotlib output and attached pictures render inline; tap to zoom and pan |
| **Models** | per-conversation picker above the message box; each answer names the model that wrote it. Settings sets the default for new chats |
| **Local model server** | Settings shows whether the model server on the Mac is running and how much memory it holds; start, stop, restart, or switch to another installed model folder |
| **Files** | everything Orbit made or you attached, grouped by origin, with thumbnails; QuickLook preview, share sheet, *Add to Knowledge*, swipe to bin |
| **Offline** | last chat list and recent conversations cached on the phone; a banner says when the copy is stale |
| **Both sides stay in step** | a message sent from the phone appears in the Mac's browser within a few seconds, and the other way round; an answer started on one device is joined mid-stream on the other |
| **Answers survive a dropped connection** | if the phone loses the stream mid-answer the Mac carries on; the app rejoins the running answer rather than showing an error |
| **Notifications** | if an answer finishes while you are in another app it tells you; tapping the notification opens that chat |
| **iPad and landscape** | list beside conversation; ⌘N new chat, ⌘K model, ⌘F find, ⌘↩ send on a keyboard |
| **Find in chat** | ⋯ → Find (or type `/find`): steps through matches and flashes each |
| **Slash commands** | type `/` — `/new`, `/model`, `/compact`, `/find` |
| **Quote** | long-press any message → Quote puts it in the composer as a `>` block |
| **Tables and code** | Markdown pipe tables render as real grids; fenced code gets a copy button |
| **Share** | a chat as Markdown, plain text or a one-page PDF; an answer as text or as an image card; a plot straight to Photos |
| **Drafts** | what you were typing in each chat is still there when you come back |
| **Autonomy** | Settings shows and sets the same three-way autonomy mode as the Mac (Ask every time / Auto-approve safe actions / Full computer access) — a full-access confirmation from either device applies everywhere, and a chat on the Mac follows a mode changed from the phone |
| **Backup** | Settings shows the Mac's automatic backup (see below); back up now, list archives, put back what is missing |
| **Bin** | what you binned on the Mac, with Restore |
| **Appearance** | light/dark, larger answer text, haptics on/off |
| **Face ID** | optional lock whenever Orbit comes to the front |
| **Diagnostics** | one tap copies a short report (versions, address, model server, last error — no chat content, no token) |

### What it deliberately does not do

- It never stores a conversation the Mac has not accepted. The cache is for
  reading when the Mac is asleep; it is not a second database.
- Deleting a chat or a file moves it to the bin on the Mac, never past it.
- "Edit and resend" sends the Mac the text of the message it is about to cut
  back to. If the conversation changed elsewhere in the meantime the Mac
  refuses rather than cutting the wrong turn.

## Automatic backup

Once a day the Mac archives what cannot be re-downloaded — chats, memory,
skills, knowledge and settings — into **iCloud Drive › Orbit Backups** when the
Mac has iCloud Drive, otherwise into Orbit's own `backups/auto` folder. It skips
days when nothing changed, keeps the most recent fourteen archives, and leaves
API keys and the pairing token out unless you tick them in.

Turn it on or off, change the folder, or back up now under **Settings → Backup**
on the Mac; the phone shows the same status and can trigger a backup.

Restoring is deliberately one-directional: **Put back what is missing** adds
chats, memory, skills and knowledge the archive has and the Mac no longer does.
It never overwrites what is on disk now.

There is a long list of what it could do next in [roadmap.md](roadmap.md).

## Building it

Requires Xcode 16+ and [XcodeGen](https://github.com/yonaskolb/XcodeGen).

```bash
cd ios
xcodegen generate
open Orbit.xcodeproj
```

Select your team under Signing & Capabilities and run. A free Apple ID works for
personal use; the build lasts seven days before it needs re-signing.

### Installing from the terminal, and keeping it installed

`bin/orbit-phone-install` builds a Release copy signed for your paired iPhone
and installs it over USB or Wi-Fi. It finds the phone and your Apple
Development certificate on its own (override in `config/phone.json` with
`{"device": "...", "team": "..."}`), and installs *over* the existing app, so
the pairing and the offline copy survive.

- **Free Apple ID** — the signature lasts seven days, then iOS refuses to open
  the app. Load [docs/phone-refresh.plist](phone-refresh.plist) as a LaunchAgent
  (edit the two paths) and the Mac re-signs and reinstalls every night the phone
  is reachable; the script does nothing while the last build is under four days
  old. Also limited to three sideloaded apps per phone.
- **Apple Developer Program** (paid) — the same command signs for a year, and
  TestFlight builds last 90 days. Nothing else changes.

The first time, the phone asks you to trust the developer: **Settings → General
→ VPN & Device Management → your Apple ID → Trust**. Then open Orbit and scan
the QR from the Mac.

## Reaching it from a phone browser instead

If you would rather not build the app, the QR panel also shows a web link. Open
it once on the phone and the token is stored as a cookie; add the page to your
Home Screen and the PWA behaves much like the app.
