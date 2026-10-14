# Orbit for macOS

A native macOS app for Orbit. It opens Orbit's local web UI in its own window
and adds what a browser tab can't:

- **Menu-bar icon** showing how many chats are answering, with a menu of chats
  that need you and the ones still running.
- **Notifications** when an answer finishes or a chat needs your approval
  (click to jump to it), plus a **dock badge** for chats waiting on you and
  unread chats.
- **Quick Ask** — press **⌥Space** anywhere for a floating prompt.
  ⏎ sends and opens Orbit; ⌘⏎ sends in the background and notifies you when
  the answer is ready.
- A full **macOS menu** with keyboard shortcuts (new chat, tabs, command
  palette, find, stop answer, zoom, export chat as PDF…).
- **orbit:// links**: `orbit://chat/<id>` opens a chat; `orbit://new?text=…`
  opens a new chat with the text in the composer (it is never sent automatically).
- Starts Orbit's server if it isn't running (through its LaunchAgent when there
  is one), and leaves it running when you quit — it's a background service.
- Links to other sites open in your browser (Google Chrome when installed).
- **Updates** itself from GitHub Releases (see below).

## Install

1. Download `Orbit-<version>-arm64.dmg` from
   [GitHub Releases](https://github.com/Micropeptide/Orbit/releases)
   (desktop releases are tagged `desktop-v<version>`).
2. Open the dmg and drag **Orbit** to **Applications**.
3. Orbit isn't notarized by Apple, so the first time you open it, right-click
   Orbit.app in Applications and choose **Open** (then **Open** again). Or run:

   ```sh
   xattr -dr com.apple.quarantine /Applications/Orbit.app
   ```

Orbit for Mac needs an Apple silicon Mac.

## Updates

Orbit checks GitHub Releases for new versions. Choose how in
**Orbit › Updates**:

- **Install Automatically** — downloads and verifies the update in the
  background, then installs it when Orbit is idle (no chat answering and no
  Orbit window in front for 2 minutes) or the next time you quit Orbit.
  After a relaunch you get an "Orbit updated to …" notification.
- **Notify Me** (default) — a notification and an **Install Update…** item
  in the menu-bar menu when a new version is out. Nothing is downloaded until
  you choose **Install and Relaunch**.
- **Don't Check** — Orbit never checks by itself.

**Check Every Hour / 6 Hours / Day / Week** sets how often it checks (default:
once a day; restarting Orbit doesn't trigger an extra check).
**Include Beta Versions** also offers prereleases. **Orbit › Check for
Updates…** (also in the menu-bar menu) checks right away in any mode, and
**Skip This Version** in its dialog stops reminders for that version.

Every download is checked against the release's `SHA256SUMS.txt` before
anything is installed. The old app goes to the Trash as `Orbit-<old version>.app`.
If Orbit can't replace itself — for example when it is run from the dmg, or
it lives in a folder you can't write to — it opens the release page instead
so you can update by hand.

## Run from source

Requires Node.js and npm. From this folder:

```sh
npm install
npm start
```

When run from inside the Orbit folder (`<orbit>/desktop`), the app finds
Orbit automatically. Otherwise it looks in `~/Orbit`, `~/Applications/Orbit`
and `/Applications/Orbit`, or asks you to choose the folder.
Set `ORBIT_UI_PORT` to use a port other than 8899.

## Build the app

```sh
npm run dist      # dist/mac-arm64/Orbit.app
npm run dmg       # a .dmg installer
npm run release   # dmg + updater zip + SHA256SUMS.txt in dist/
npm test          # unit tests for the update logic
```

`npm run release` produces the three assets a desktop release needs:
`Orbit-<version>-arm64.dmg`, `Orbit-<version>-arm64-mac.zip` (used by the
updater) and `SHA256SUMS.txt`. Attach all three to a GitHub release tagged
`desktop-v<version>` (mark betas as prereleases).

Builds are ad-hoc signed (no Developer ID, not notarized). Orbit for Mac is
built with Electron and electron-builder. To redraw the menu-bar icon:
`npm run tray-icon`.

## For the web UI: the desktop bridge

Pages served by Orbit get `window.orbitDesktop`:

| Member | Purpose |
| --- | --- |
| `isDesktop`, `platform`, `version` | Detect the desktop app |
| `onCommand(cb)` | `cb(name, arg)` for menu, tray, shortcut and link commands; returns an unsubscribe function |
| `setActiveChat(sid, title)` | Which chat this window shows (`null` for none) — names exported PDFs and silences notifications for the chat you're looking at |
| `exportPDF()` | Same as File › Export Chat as PDF… |
| `openExternal(url)` | Open an http(s)/mailto link in the browser |
| `quickAsk()` | Show the Quick Ask panel |
| `setTitleBarDark(bool)` | Match the window background to the page theme |
| `updates.getState()` | Promise of the update state (below) |
| `updates.check()` | Check now (works in any mode); resolves to the state |
| `updates.install()` | Download, verify, install and relaunch; resolves to the state if it couldn't |
| `updates.setPrefs({autoUpdate, updateCheckEvery, updateChannel})` | `'auto'\|'notify'\|'off'`, `1\|6\|24\|168` hours, `'stable'\|'beta'`; any subset; rejects on bad values |
| `updates.onState(cb)` | `cb(state)` on every change; returns an unsubscribe function |

Update state: `{current, latest: {version, notes, url, publishedAt, prerelease} | null,
available, checking, downloading, progress (0–1 | null), staged (version | null),
error (string | null), lastCheck (epoch ms | null), prefs: {autoUpdate,
updateCheckEvery, updateChannel, skippedVersion}}`.

Commands: `settings`, `new-chat`, `new-chat-with`, `close-tab`, `reopen-tab`,
`find`, `palette`, `toggle-sidebar`, `toggle-terminal`, `files`, `stop`,
`next-tab`, `prev-tab`, `tab {n}`, `jump`, `open-chat {sid}`,
`new-chat-send {text, background?, draft?}`.
Commands that arrive before the page calls `onCommand` are queued (for chat
opening and sending) or handled natively (`close-tab` closes the window).
