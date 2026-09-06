"""Reaching Orbit from your phone, without opening it to the world.

The server has always been localhost-only, which is the right default: it has no
login, and anything that can talk to it can run code on your Mac. Remote access
is therefore off until you turn it on, and when it is on it holds to three rules:

  1. **Loopback stays free.** A request from 127.0.0.1 is you, at the machine, and
     is treated exactly as before. Nothing about the desktop experience changes.
  2. **Everything else needs the token.** Any request arriving over the network
     must carry the pairing token, compared in constant time. No token, no answer
     — not even a 404 that would confirm the path exists.
  3. **You choose the surface.** `tailscale` binds only to the tailnet address, so
     the port is not on your café Wi-Fi at all. `lan` binds everywhere and is
     meant for a trusted home network.

Pairing is a QR code: the phone scans a URL carrying host, port and token, and
never asks you to type a secret on a phone keyboard.
"""
import hmac, json, os, secrets, socket, subprocess, urllib.request

TOKEN_BYTES = 32
TAILSCALE_BINS = ["/usr/local/bin/tailscale", "/opt/homebrew/bin/tailscale",
                  "/Applications/Tailscale.app/Contents/MacOS/Tailscale"]


# ------------------------------------------------------------------ the token

def token_path(root):
    return os.path.join(root, "config", "remote-token")


def load_token(root, create=False):
    """The pairing secret. Written 0600, never logged, never in a URL we print."""
    p = token_path(root)
    try:
        tok = open(p).read().strip()
        if tok: return tok
    except OSError:
        pass
    if not create: return ""
    tok = secrets.token_urlsafe(TOKEN_BYTES)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(tok)
    try: os.chmod(p, 0o600)
    except OSError: pass
    return tok


def rotate_token(root):
    """New secret; every paired device must scan again. That is the point."""
    try: os.remove(token_path(root))
    except OSError: pass
    return load_token(root, create=True)


def token_matches(root, given):
    tok = load_token(root)
    if not tok or not given: return False
    return hmac.compare_digest(tok, given)


# ------------------------------------------------------------------ addresses

def address_is_local(ip):
    """Is this address actually assigned to an interface right now?

    `tailscale ip` happily reports the last address it was given even when the
    daemon is logged out, and binding it then fails with EADDRNOTAVAIL. Ask the
    kernel instead of taking the CLI's word for it.
    """
    if not ip: return False
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind((ip, 0))
        return True
    except OSError:
        return False
    finally:
        s.close()


def tailscale_ip():
    """This Mac's tailnet address, or "" when Tailscale is not actually up."""
    for b in TAILSCALE_BINS:
        if not os.path.exists(b): continue
        try:
            out = subprocess.run([b, "ip", "-4"], capture_output=True, text=True,
                                 timeout=5).stdout.strip().splitlines()
        except Exception:
            continue
        for line in out:
            ip = line.strip()
            if ip.startswith("100.") and address_is_local(ip):
                return ip
    return ""


def tailscale_name():
    """The MagicDNS name, which survives an address change."""
    for b in TAILSCALE_BINS:
        if not os.path.exists(b): continue
        try:
            st = json.loads(subprocess.run([b, "status", "--json"],
                            capture_output=True, text=True, timeout=5).stdout)
        except Exception:
            continue
        dns = ((st.get("Self") or {}).get("DNSName") or "").rstrip(".")
        if dns: return dns
    return ""


def lan_ip():
    """This Mac's address on the real local network.

    Asking the routing table picks whatever holds the default route, which with
    Tailscale up is a utun interface — not the Wi-Fi address a phone on the same
    network needs. Ask the physical interfaces first.
    """
    for iface in ("en0", "en1", "en2"):
        try:
            ip = subprocess.run(["/usr/sbin/ipconfig", "getifaddr", iface],
                                capture_output=True, text=True, timeout=3).stdout.strip()
        except Exception:
            continue
        if ip and not ip.startswith("100."):
            return ip
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 9))          # TEST-NET-1: no packet is sent
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return ""


def bind_addresses(mode):
    """Every address to listen on.

    Loopback is always one of them — binding only the tailnet address would take
    the desktop app away from you. The remote address is a *second* socket rather
    than 0.0.0.0, so in tailscale mode the port genuinely is not on the café
    Wi-Fi: it is bound to the tailnet interface and nowhere else.
    """
    addrs = ["127.0.0.1"]
    if mode == "tailscale":
        ip = tailscale_ip()
        if ip: addrs.append(ip)
    elif mode == "lan":
        addrs = ["0.0.0.0"]                  # one socket already covers loopback
    return addrs


def reachable_hosts(mode, port):
    """Host: values that are legitimately ours, for the rebinding guard."""
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
    if mode == "tailscale":
        for h in (tailscale_ip(), tailscale_name()):
            if h: hosts.add(f"{h}:{port}")
    elif mode == "lan":
        ip = lan_ip()
        if ip: hosts.add(f"{ip}:{port}")
        hosts.add(f"{socket.gethostname()}:{port}")
        hosts.add(f"{socket.gethostname()}.local:{port}")
    return hosts


def best_url(mode, port):
    """The address to hand a phone. MagicDNS first — it outlives a DHCP lease."""
    if mode == "tailscale":
        host = tailscale_name() or tailscale_ip()
        if host: return f"http://{host}:{port}"
        return ""
    if mode == "lan":
        ip = lan_ip()
        return f"http://{ip}:{port}" if ip else ""
    return ""


def status(root, mode, port):
    """Everything the settings panel needs to explain the current state."""
    ts_ip, ts_name = tailscale_ip(), tailscale_name()
    ts_installed = any(os.path.exists(b) for b in TAILSCALE_BINS)
    hint = ""
    if mode == "tailscale" and not ts_ip:
        hint = ("Tailscale is installed but not connected — open it and sign in, "
                "then restart Orbit." if ts_installed else
                "Tailscale is not installed. Use LAN mode, or install Tailscale "
                "to reach this Mac from anywhere.")
    return {
        "mode": mode,
        "enabled": mode != "off",
        "url": best_url(mode, port),
        "token_set": bool(load_token(root)),
        "tailscale": {"running": bool(ts_ip), "ip": ts_ip, "name": ts_name,
                      "installed": ts_installed},
        "lan_ip": lan_ip(),
        "port": port,
        "hint": hint,
    }


# ------------------------------------------------------------------ pairing

def pair_payload(root, mode, port):
    """What the QR code carries. Scanned once, stored in the Keychain."""
    url = best_url(mode, port)
    if not url: return {}
    tok = load_token(root, create=True)
    return {"v": 1, "url": url, "token": tok,
            "web": f"{url}/?t={tok}",     # for a phone browser or the PWA
            "name": socket.gethostname().replace(".local", "")}


def pair_uri(root, mode, port):
    p = pair_payload(root, mode, port)
    if not p: return ""
    from urllib.parse import quote
    return (f"orbit://pair?url={quote(p['url'])}&token={quote(p['token'])}"
            f"&name={quote(p['name'])}")


def pair_qr_png(root, mode, port, box=8):
    """QR as PNG bytes, rendered locally — the token never leaves this Mac."""
    uri = pair_uri(root, mode, port)
    if not uri: return b""
    import io
    import qrcode
    img = qrcode.make(uri, box_size=box, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ------------------------------------------------------------------ discovery

_BONJOUR = {"proc": None}

def advertise(port, name=None):
    """Announce _orbit._tcp so the app finds this Mac on the same network.

    dns-sd is part of macOS; there is no third-party dependency and nothing is
    published beyond the local link.
    """
    stop_advertising()
    if not os.path.exists("/usr/bin/dns-sd"): return False
    label = name or socket.gethostname().replace(".local", "")
    try:
        _BONJOUR["proc"] = subprocess.Popen(
            ["/usr/bin/dns-sd", "-R", f"Orbit on {label}", "_orbit._tcp", "local",
             str(port), "path=/"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, start_new_session=True)
        return True
    except Exception:
        return False


def stop_advertising():
    p = _BONJOUR.get("proc")
    if p and p.poll() is None:
        try: p.terminate()
        except Exception: pass
    _BONJOUR["proc"] = None
