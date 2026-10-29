# The internet door: reach Orbit from your phone on any network

A Cloudflare Tunnel plus Cloudflare Access, instead of (or beside) Tailscale. The phone needs no VPN app, and the QR works on
any network. Orbit stays closed to everyone but you.

## What stands between the internet and Orbit

1. **No open port.** `cloudflared` on the Mac dials *out* to Cloudflare. Nothing listens on the router or the Wi-Fi.
2. **Cloudflare Access** in front of the name. Exactly two things pass: your email (a one-time code is mailed to it, for a
   browser) and one service token (for the phone app). Anything else is stopped at Cloudflare's edge and never reaches the Mac.
3. **Orbit checks Access too.** Every request that names the tunnel's host must carry Cloudflare's signed Access token for this
   application (signature, audience, issuer, expiry). A request that somehow skipped Access is refused by Orbit itself.
4. **Orbit's own pairing.** After both, each device still needs the token it got by scanning the QR; a chats-only device cannot
   reach settings.
5. **Never mistaken for local.** A request that arrives through the tunnel is not treated as "you at the Mac", whatever headers a
   proxy adds or strips: its Host and the proxy headers are checked, not one header.
6. **Turn Phone access to Off** and the door is shut again (Orbit refuses everything that is not from this Mac).

## Setting it up

Needs a Cloudflare API token (Keychain item `orbit-cloudflare-token`) that may edit **Cloudflare Tunnel**, **Access: Apps and
Policies**, **Access: Service Tokens**, **Access: Organizations, Identity Providers, and Groups** (account) and **DNS** (zone).

```bash
brew install cloudflared
bin/orbit-tunnel setup --host phone.example.com --email you@example.com
```

Then choose **Internet (no Tailscale)** in Settings, Phone, press Save & restart server, and show the QR. (The tunnel also works in
Tailscale and Local-network modes, but Internet mode is the tightest: Orbit listens on this Mac's loopback only, announces nothing
on the Wi-Fi and never touches Tailscale.) `bin/orbit-tunnel status` checks it; `bin/orbit-tunnel remove` undoes it.

## Secrets

- The service token's secret is in the Keychain (`orbit-tunnel-access`) and in the QR you scan (it is how the phone app proves
  itself to Cloudflare). It expires after a year; `bin/orbit-tunnel rotate` replaces it, then scan the QR again.
- The tunnel's run token is in `~/.config/orbit/tunnel-token` (mode 0600); the settings in `~/.config/orbit/tunnel.json`.
- Lost phone: Settings, Phone, Devices, revoke it; to be thorough run `rotate` too.

## How the phone's web views get through Access

The phone's API calls carry the service token on every request. A web view (a shared project's page, a file preview) makes calls
the app cannot sign, and Cloudflare sets no cookie for a service token. But Cloudflare does accept its own signed token as the
`CF_Authorization` cookie, and Orbit receives that token with every request that came through the tunnel. So before a page loads,
the app asks `GET /api/access/cookie` (paired devices only, and only through the tunnel) and puts the answer in the web view as a
cookie. It lasts as long as the Access session (12 hours); the app fetches a fresh one each time a page is opened.
