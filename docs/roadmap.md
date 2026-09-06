# Roadmap — two hundred things the phone app could do

Ticked items are built. The rest are ordered roughly by how much they would
matter to someone who uses Orbit every day, within each group. Nothing here
changes the rule the app is built on: the Mac holds everything, the phone is a
window onto it.

## Conversation

- [x] Streaming answers with Markdown, fenced code blocks and a copy button
- [x] Collapsible thinking, tool chips, approval prompts mid-answer
- [x] Each answer names the model that wrote it
- [x] Long-press: copy, share, edit-and-resend, ask again
- [x] Compact a long chat's history from the ⋯ menu
- [x] Rejoin an answer already running on the Mac; survive a dropped connection
- [x] Type the next message while the current answer streams
- [x] Reply-to quoting: long-press → Quote, so a follow-up points at one paragraph
- [ ] Tap a citation or DOI in an answer to open the paper in the Files tab
- [x] Tables rendered as tables (Markdown pipes → a scrolling grid)
- [ ] LaTeX rendered inline for equations
- [ ] Syntax colouring in code blocks
- [ ] "Continue" button when an answer stops at the token limit
- [ ] Branch a conversation from any message into a new chat
- [ ] Per-message token and time cost, shown on long-press
- [ ] Read aloud (AVSpeechSynthesizer) for an answer, with play/pause
- [ ] Message reactions as lightweight notes-to-self (⭐ to bookmark a message)
- [ ] Bookmarked messages list across chats

## Composer and input

- [x] Model capsule above the message box, per chat
- [x] Attach from library, camera or Files; thumbnails in the strip
- [ ] Dictation button that transcribes on-device (SFSpeechRecognizer) before sending
- [ ] Hold-to-talk voice message: transcribe, show the text, send on release
- [x] Slash commands: `/new`, `/model`, `/compact`, `/find`
- [ ] Prompt library: saved prompts from the Mac, inserted with `/`
- [x] Draft persistence per chat — leave and come back to what you were typing
- [ ] Paste an image straight into the composer
- [ ] Paste a URL and get a chip offering "fetch and attach the page"
- [ ] Multi-line editor sheet for long messages
- [x] Send with ⌘↩ on an external keyboard
- [ ] Text scanning from the camera (Live Text) into the composer

## Attachments and media

- [x] Photos downscaled to 1600 px JPEG before upload
- [x] Plots and pictures inline; tap to zoom and pan
- [ ] Attach a PDF and have it go straight into Knowledge, not just the message
- [ ] Attach several photos as one batch with a caption
- [ ] Image annotation before sending (arrow, circle, crop)
- [ ] Attach a screen recording or short video and send key frames
- [ ] Audio file attachment, transcribed on the Mac
- [ ] Attachment upload progress per file, with cancel
- [ ] Retry a failed upload without re-picking it
- [x] Save an inline plot to the Photos app
- [ ] Share an inline plot directly from its zoom view

## Files

- [x] Grouped by origin with thumbnails; QuickLook preview; share sheet
- [x] Add to Knowledge; swipe to bin
- [ ] Folders view mirroring the workspace tree, not only the flat list
- [x] Sort by name, size, date; filter by type
- [ ] Recently opened on this phone, at the top
- [ ] Open a CSV as a scrolling table rather than a PDF-ish preview
- [ ] Markdown files rendered, not raw
- [ ] Edit a text or Markdown file on the phone and save it back to the Mac
- [ ] Rename and move files
- [ ] Multi-select for bulk share or bin
- [x] "Ask about this file" — opens a new chat with the file attached
- [ ] Storage summary: how much the workspace holds, biggest files
- [x] Bin view with restore

## Search and organisation

- [x] Search titles and message text; jump to the exact line and flash it
- [x] Pinned / Today / Yesterday / This week / Earlier grouping
- [x] Archive, filter by project
- [x] Tags shown on chat rows
- [x] Search inside one conversation, with next/previous
- [ ] Search files by content, not only name
- [ ] Search scoped to a project or a date range
- [ ] Recent searches remembered
- [ ] Unread marker for chats that finished while you were away
- [ ] Swipe to mark read/unread
- [ ] Sort chats by title or by size
- [ ] Merge two chats
- [ ] Duplicate a chat as a starting point

## Models and providers

- [x] Per-chat model picker; default model for new chats
- [x] Models grouped by provider; "needs an API key" shown for unready ones
- [ ] Add or remove an API key from the phone (stored on the Mac, never on the phone)
- [ ] Fetch a provider's model list from the phone
- [ ] Per-model context meter in the picker
- [ ] Favourite models pinned to the top of the picker
- [ ] Temperature and max-tokens per chat under an "Advanced" disclosure
- [ ] Show which models are reachable right now (CLI signed in, key valid)
- [ ] One-tap "sign in" instructions when a CLI provider is logged out
- [ ] Compare: send one prompt to two models and show answers side by side

## Local model server

- [x] Running/stopped, model and memory; start, stop, restart
- [x] Switch between installed model folders
- [ ] Tokens per second and last request latency
- [ ] Memory pressure warning before a start would swap
- [ ] Idle-stop timer setting (what the watchdog uses), editable from the phone
- [ ] Download a new model through MTPLX from the phone, with progress
- [ ] Delete an unused model folder (to the bin)
- [ ] Log tail for the server, for when a start fails
- [ ] Scheduled start (e.g. warm the model at 8:55 every weekday)

## Knowledge and papers

- [ ] Knowledge tab: what the Mac has indexed, searchable
- [ ] Add a paper by DOI or title from the phone
- [ ] Open a paper's PDF with QuickLook; highlights saved as notes
- [ ] "Cite this" — copy a formatted reference
- [ ] Citation check results shown as a list with links
- [ ] Reading list: papers to read, synced with the Mac
- [ ] Share-sheet extension: send a PDF or URL from Safari straight into Knowledge
- [ ] Memory browser: what Orbit remembers about you, edit or forget items

## Tools and agents

- [ ] Tool timeline in a chat: what ran, how long, what it returned (expandable)
- [ ] Re-run a tool call with edited arguments
- [ ] Approve-with-conditions ("allow this shell command for the rest of this chat")
- [ ] Per-chat tool toggles (web off, shell off) under the ⋯ menu
- [ ] Cluster job status from the phone (queued, running, done) when the Mac has SSH set up
- [ ] Browser-use sessions shown as screenshots as they happen
- [ ] MCP servers listed with on/off, mirroring the Mac panel
- [ ] Skills list: read a skill, enable or disable it

## Scheduling and automation

- [ ] Jobs tab: scheduled tasks with next run, last result, enable/disable
- [ ] Create a job from the phone ("every Monday 8:00, search PubMed for …")
- [ ] Job results delivered as notifications, opening the resulting chat
- [ ] Run a job now
- [ ] Shortcuts app actions: "Ask Orbit", "New chat with clipboard", "Send photo to Orbit"
- [ ] Siri: "Ask Orbit …" via App Intents
- [ ] Home Screen widget: last answer, or a tappable "Ask" box
- [ ] Lock Screen widget showing whether the model server is running

## Sync and offline

- [x] Automatic daily backup of the Mac's chats, memory, skills, knowledge and settings into iCloud Drive; restore adds only what is missing
- [x] Last chat list and recent conversations cached; stale banner
- [x] Cache excluded from iCloud backup
- [ ] Queue a message while offline and send it when the Mac is back
- [ ] Background refresh (BGAppRefreshTask) so the list is fresh when opened
- [ ] Delta sync: fetch only chats changed since the last look
- [x] Prefetch the last N conversations for the plane
- [ ] Cache size setting and "clear" with the size shown
- [ ] Conflict notice if a chat was edited on the Mac while the phone showed a stale copy

## Notifications

- [x] Answer finished while backgrounded → notification; tap opens the chat
- [ ] Notification shows the first line of the answer with the chat title
- [ ] Reply from the notification (inline text action)
- [ ] Approval prompts as actionable notifications: Allow / Refuse
- [ ] Job finished notifications
- [ ] Model server stopped/started notifications (optional)
- [ ] Do-not-disturb hours for Orbit notifications
- [ ] Badge count for answers you have not looked at

## Security and privacy

- [x] Token in the Keychain, this-device-only; constant-time compare on the Mac
- [x] Deletions go to the bin, never past it
- [x] Edit-and-resend refuses if the chat changed elsewhere
- [x] Face ID to open the app (optional)
- [ ] Face ID before approving a shell command
- [ ] Per-device tokens, so one phone can be revoked without the others
- [ ] Paired devices list on the Mac with last-seen time
- [ ] HTTPS over the tailnet with Tailscale certificates
- [ ] Private-relay warning: explain why iCloud Private Relay breaks LAN mode
- [ ] Screenshot protection for sensitive chats (blur in the app switcher)
- [ ] Audit log tab: what the phone asked the Mac to do

## Pairing and connectivity

- [x] QR pairing; Bonjour discovery; manual entry
- [x] Tailscale or LAN modes with dual listeners
- [ ] Automatic fallback: try LAN first, then the tailnet address, remembering both
- [ ] Wake-on-LAN packet from the phone when the Mac is asleep
- [x] Connection quality indicator (latency to the Mac)
- [ ] Pair a second Mac and switch between them
- [ ] Re-pair by tapping a link in Messages from the Mac (orbit:// URL)
- [ ] Handoff: continue on the Mac the chat you are reading on the phone

## iPad, Mac and Watch

- [x] Sidebar and detail side by side on iPad and landscape
- [x] Keyboard shortcuts on iPad (⌘N new chat, ⌘F find, ⌘K model, ⌘↩ send)
- [ ] Multiple windows on iPad
- [ ] Drag a file from the Files app onto a chat
- [ ] Mac Catalyst build for a second Mac that is not the one running Orbit
- [ ] Apple Watch: quick ask by dictation, answer read back
- [ ] CarPlay-style read-aloud of the last answer (Now Playing)

## Accessibility

- [x] Labels on the toolbar and composer controls
- [ ] Dynamic Type verified at the largest sizes
- [ ] VoiceOver rotor for messages, code blocks, tool chips
- [x] Reduce Motion respected for the flash and scroll animations
- [ ] High-contrast mode for bubbles
- [ ] Localisation: Chinese and Spanish first

## Settings

- [x] Local model server; default model; offline cache; unpair; about
- [x] Theme: system, light, dark
- [x] Font size for answers, independent of Dynamic Type
- [x] Haptics on/off
- [ ] Send-with-return toggle
- [ ] Default project for new chats
- [ ] Data usage: photo quality (1600 px / original) and thumbnail prefetch on cellular
- [x] Diagnostics: last errors, server version, a "copy report" button

## Sharing and export

- [x] Share a chat as Markdown; share a file; share an answer
- [x] Export a chat as PDF (words; plots are left out)
- [x] Copy a chat as plain text
- [x] Share an answer as an image card
- [ ] Open in… for any file (Pages, Numbers, GoodNotes)
- [ ] AirDrop a file to the Mac's workspace from the phone

## Performance

- [x] Live text coalesced to ~20 updates a second
- [x] Authenticated thumbnails cached in memory; the Mac caches the host list
- [ ] Disk cache for thumbnails across launches
- [ ] Lazy rendering of very long conversations (windowed list)
- [ ] Incremental Markdown parsing during streaming (only the last block re-parses)
- [ ] Image decoding off the main thread
- [ ] HTTP/2 keep-alive session reused across requests

## Developer and testing

- [x] DEBUG environment hooks for headless simulator runs (pair, open, send, tab)
- [ ] UI tests on the simulator covering pairing, send, search, files
- [ ] Snapshot tests for the bubble renderer
- [ ] A fake server in-process for tests without a Mac
- [ ] Crash and error reporting to the Mac's log, not to a third party
- [ ] TestFlight build recipe in the docs
