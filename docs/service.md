# Running Orbit as a background service

Two optional LaunchAgents: one keeps the web app running, one stops the local
model when you are not using it.

## The web app

```bash
cp docs/launchagent.plist ~/Library/LaunchAgents/com.orbit.ui.plist
```

Edit the two paths inside to your install, then:

```bash
launchctl load ~/Library/LaunchAgents/com.orbit.ui.plist
```

`KeepAlive` restarts it if it exits, so the app is there whenever you open the
browser, and *Restart interface* in the UI works by exiting and letting launchd
bring it back.

## The idle watchdog

The local model holds ~20 GB of RAM. `bin/orbit-idle-watchdog` stops it after
`idle_min` minutes of no traffic; the next message reloads it (~15s, and the UI
says so while it happens).

```bash
cp docs/watchdog.plist ~/Library/LaunchAgents/com.orbit.watchdog.plist
launchctl load ~/Library/LaunchAgents/com.orbit.watchdog.plist
```

It only stops the server when the metrics fingerprint is stale *and* there are no
open connections, so it cannot interrupt work in progress.

## Scheduled prompts

Inside the app, Tasks → New task runs a prompt on a schedule and drops the result
into its own chat. That needs no launchd of its own — the running app does it.
