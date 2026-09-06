# Orbit on your phone

The Mac keeps everything; the app is a window onto it. There is no second copy
to reconcile and no cloud account — the phone talks to your Mac directly.

## Turning it on

**Settings → Phone** on the Mac. It is off by default, because Orbit has no
login and anything that can reach it can run code on your machine.

| Mode | What it does | Use it when |
|---|---|---|
| **Off** | Only the Mac itself can reach Orbit | the default |
| **Tailscale** | Binds the tailnet address *only* — the port is not on whatever Wi-Fi you are on | you want it to work from anywhere |
| **Local network** | Binds every interface | you are at home on a network you trust |

Pick one, restart, and a QR code appears. Scan it with the app.

## What the QR carries

The address and a 32-byte pairing token. The token is generated on your Mac,
stored `chmod 600`, and lands in the iPhone's Keychain — you never type it.

Every request from off the machine must carry that token, compared in constant
time. Loopback is exempt, so nothing about using Orbit at the Mac changes.

**Rotate token** in the same panel invalidates every paired device at once. Use
it if a phone goes missing.

## The app

- **Chats** — the same conversations, live. Search titles *and* the text of
  every message. Swipe to pin or bin. Pull to refresh.
- **Files** — everything Orbit made or you attached, previewed with QuickLook,
  grouped by where it came from.
- **Model picker** — per conversation, exactly as on the Mac. Each answer is
  labelled with the model that wrote it.
- **Attachments** — a photo or a file from the Files app, uploaded to the Mac
  and sent with your next message.
- **Offline** — the last copy of your chat list and recent conversations is
  cached, so the app opens to something when the Mac is asleep. A banner says
  so rather than pretending.

## Building it

Requires Xcode 16+ and [XcodeGen](https://github.com/yonaskolb/XcodeGen).

```bash
cd ios
xcodegen generate
open Orbit.xcodeproj
```

Select your team under Signing & Capabilities and run. A free Apple ID works for
personal use; the build lasts seven days before it needs re-signing.

## Reaching it from a phone browser instead

If you would rather not build the app, the QR panel also shows a web link. Open
it once on the phone and the token is stored as a cookie; add the page to your
Home Screen and the PWA behaves much like the app.
