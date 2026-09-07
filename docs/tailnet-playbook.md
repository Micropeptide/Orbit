# Reaching a Mac-hosted service from an iPhone app over Tailscale

What we learned making Orbit's phone app talk to the Orbit server on a Mac.
Written for whoever — or whatever — builds the next one. Nothing here is
specific to Orbit; swap the port numbers.

## The shape that works

```
iPhone app ──HTTPS──▶ https://<mac>.<tailnet>.ts.net:8443   (Tailscale Serve, real certificate)
                                   │  terminates TLS, forwards to loopback
                                   ▼
                         http://127.0.0.1:8899                (your server, bound to loopback + tailnet IP)
```

One command on the Mac sets up the front door and it survives reboots:

```bash
tailscale serve --bg --https=8443 http://127.0.0.1:8899
tailscale serve status --json          # inspect; pick another port if 443/8443 are taken
```

The app then speaks plain HTTPS to a name that resolves on the tailnet and a
certificate iOS already trusts (Let's Encrypt, provisioned by Tailscale). No
ATS exceptions, no plaintext on the wire, no port opened on whatever Wi-Fi the
Mac happens to be on.

## The problems, in the order they bit

### 1. "App Transport Security policy requires the use of a secure connection"
iOS refuses plain `http://` to anything it does not consider *local*. Local
means `.local` names and RFC 1918 addresses — `NSAllowsLocalNetworking` covers
those. A tailnet address (`100.x.y.z`, CGNAT range) or `*.ts.net` name is
**not** local to ATS, so `http://<mac>.<tailnet>.ts.net:8899` is blocked
outright, before any packet is sent.

Stopgap: `NSAllowsArbitraryLoads = true` in Info.plist. Real fix: HTTPS via
Serve, above. (We kept the exception for LAN mode, where the address is a
private IP and the traffic never leaves the home network.)

### 2. The phone was not on the tailnet
Nothing in the app can fix this, and the app's error ("can't reach your Mac")
looks the same as every other failure. Diagnose from the Mac:

```bash
tailscale status                      # is the phone listed, and online?
tailscale ping 100.x.y.z              # "pong via DERP" or direct = tunnel is up
```

Ours said `iphone  offline, last seen 9d ago`. The user had to open the
Tailscale app on the phone and connect. Put this first in any troubleshooting
text; it is the most likely cause and the one the developer cannot see.

### 3. The direct port still did not connect; Serve did
With the phone online, plain `http://<mac>.ts.net:8899` still failed while
another app on the same Mac worked through Serve on 443. We did not pin down
why (tailnet ACLs restricting ports, and MagicDNS quirks on iOS are the usual
suspects). Serve sidestepped all of it: it is the path Tailscale itself
expects tailnet apps to use. Do this first rather than last.

### 4. Serve makes every request look local — a security hole if you trust loopback
Serve terminates TLS and connects to your server from **127.0.0.1**. If your
server has a shortcut like "loopback peer ⇒ the user at the keyboard, no auth
needed" (ours did — it is how the desktop UI works without a token), every
tailnet device now gets that shortcut.

What Serve actually sends (observed with a throwaway HTTP server):

```
Host: <mac>.<tailnet>.ts.net:8443
X-Forwarded-For: 100.x.y.z              ← the caller's tailnet address
X-Forwarded-Host: <mac>.<tailnet>.ts.net:8443
X-Forwarded-Proto: https
Tailscale-User-Login: user@example.com  ← identity of the tailnet user
Tailscale-User-Name: …
Tailscale-User-Profile-Pic: …
Tailscale-Headers-Info: https://tailscale.com/s/serve-headers
```

Fix: a request from loopback **with** `X-Forwarded-For` or
`Tailscale-User-Login` is remote — apply the token check. Verify with three
curls from the Mac itself (Serve is reachable from its own host):

```bash
curl -o /dev/null -w '%{http_code}\n' https://<mac>.<tailnet>.ts.net:8443/api/health            # expect 401
curl -H "Authorization: Bearer $TOKEN" … https://<mac>.<tailnet>.ts.net:8443/api/health       # expect 200
curl -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8899/api/health                        # expect 200 (desktop unchanged)
```

### 5. Host/Origin allow-lists must include the Serve name
If you guard against DNS rebinding by checking `Host`, add
`<mac>.<tailnet>.ts.net:8443` (and the bare name for port 443). If you check
`Origin`, allow `https://` forms too. Otherwise Serve requests get a 403 that
looks like an auth failure.

### 6. Bind the right interfaces
- **Tailnet mode:** loopback + the tailnet IP (`tailscale ip -4`), as two
  sockets. Not `0.0.0.0` — that puts the port on the café Wi-Fi.
- **LAN mode:** `0.0.0.0` is fine; that is the point.
- Listeners are chosen at startup. Changing the mode without restarting left
  ours on `*:8899` while the host allow-list had already switched — confusing
  403s. Say "restart to apply" in the UI.

### 7. Names change; carry fallbacks in the pairing
- MagicDNS may be off on a phone; the tailnet **IP** always works (it is stable
  per node).
- On a LAN, the DHCP address changes; `<hostname>.local` does not.

Our QR carries `url` (the best address) plus `alts` (the rest, same mode
only — tailnet mode never lists a LAN address). The app tries `url`, then each
alt, with a **6-second** timeout per attempt (the default 30 s with
`waitsForConnectivity` makes fallback feel broken), keeps whichever answers,
and — once connected — refreshes the list from the server so a phone paired
long ago still learns a new address without rescanning.

### 8. Pairing and the token
QR = `orbit://pair?url=…&token=…&name=…&alts=…`. The token is generated on the
Mac (32 random bytes, file mode 0600), compared in constant time, stored in
the iPhone Keychain (`ThisDeviceOnly`), sent as `Authorization: Bearer`.
"Rotate token" invalidates every phone at once. Loopback without forwarding
headers stays exempt so the desktop experience is unchanged.

## Things adjacent to the tailnet that also cost an evening

- **XcodeGen + a custom Info.plist ignores `INFOPLIST_KEY_*` build settings.**
  Put `UILaunchScreen: {}` and every `NS*UsageDescription` under
  `info.properties`. Without a launch screen the app runs letterboxed at
  compatibility size; without `NSCameraUsageDescription` iOS kills the app the
  moment the QR scanner touches the camera — it looks like "the app exits".
- **Free Apple ID signing lasts 7 days.** `xcodebuild … -allowProvisioningUpdates
  -allowProvisioningDeviceRegistration DEVELOPMENT_TEAM=<id>` then
  `xcrun devicectl device install app --device <id> Orbit.app`. Read the
  expiry from `embedded.mobileprovision`. A nightly LaunchAgent that re-signs
  and reinstalls (install over the same bundle id keeps app data) makes it
  effectively permanent while the phone is reachable.
- `devicectl … launch` fails with **"Locked"** when the phone is locked and
  with "profile has not been explicitly trusted" until the user taps Trust in
  Settings → General → VPN & Device Management. Neither is a build problem.
- Serve ports are shared across every app on the Mac: read
  `tailscale serve status --json` and take the first free HTTPS port.

## Checklist for the next app

1. `tailscale serve --bg --https=<port> http://127.0.0.1:<app>` — verify with curl from the Mac.
2. Treat loopback + forwarding headers as remote; add the Serve name to the Host allow-list.
3. Pair with a QR carrying the https URL, the token, and the tailnet IP as a fallback.
4. In the app: short timeouts, try alternates, learn addresses after connecting.
5. Tell the user, in the failure banner, that the phone's Tailscale must be connected.
6. Launch screen and usage strings in the plist proper.
