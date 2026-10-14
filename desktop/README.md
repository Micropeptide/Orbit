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
npm run dist   # dist/mac-arm64/Orbit.app
npm run dmg    # a .dmg installer
```

Builds are unsigned. The first time you open one, right-click Orbit.app and
choose **Open**. To redraw the menu-bar icon: `npm run tray-icon`.

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

Commands: `settings`, `new-chat`, `new-chat-with`, `close-tab`, `reopen-tab`,
`find`, `palette`, `toggle-sidebar`, `toggle-terminal`, `files`, `stop`,
`next-tab`, `prev-tab`, `tab {n}`, `jump`, `open-chat {sid}`,
`new-chat-send {text, background?, draft?}`.
Commands that arrive before the page calls `onCommand` are queued (for chat
opening and sending) or handled natively (`close-tab` closes the window).
