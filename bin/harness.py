"""Models for Orbit's Claude Code harness mode.

Claude Code speaks the Anthropic Messages API. Anything that serves that API can
run under the harness directly (DeepSeek, Qwen on DashScope, GLM, MiniMax, Kimi,
Anthropic, the local MTPLX server). Many good models are only served with
OpenAI's chat-completions API (on OpenCode Go: DeepSeek, Kimi, GLM, MiMo…);
those go through Orbit's gateway (bin/harness_gateway.py), which translates.
OpenCode traffic goes through the gateway for every model, so its key never
enters the Claude process.

Model ids: "harness:<provider>/<model>". Keys are the user's, kept in Orbit's
secrets (Settings), never in this module's config file.
"""
import json, os, re

# format: "messages" = Anthropic Messages API, "chat" = OpenAI chat completions,
#         "responses" = OpenAI Responses API
# auth:   "api_key" = give Claude Code the key (ANTHROPIC_API_KEY) and the base URL
#         "gateway" = Claude Code talks to Orbit's gateway, which adds the key
#         "local"   = the MTPLX server on this Mac, no key
#         "subscription" = plain Claude Code on your own Claude login, no API at all
#
# accounts: a provider can have several keys ("accounts"), say two OpenCode Go
# subscriptions. The active one is used first; when a provider says an account's
# quota is used up, the gateway marks it and moves on to the next. A provider
# with more than one account always goes through the gateway so that can happen.


def _m(mid, fmt, context=128000, label=None, **kw):
    return {"id": mid, "format": fmt, "context": context, "label": label or _label(mid), **kw}


def _label(mid):
    s = mid.replace("-", " ").replace("_", " ")
    s = re.sub(r"\bv(\d)", r"V\1", s)
    words = []
    for w in s.split():
        low = w.lower()
        if low in ("glm", "gpt", "mimo", "hy3", "hy4"): words.append(w.upper())
        elif low.startswith("qwen"): words.append("Qwen" + w[4:])
        elif low in ("deepseek",): words.append("DeepSeek")
        elif low in ("minimax",): words.append("MiniMax")
        elif w[:1].isalpha(): words.append(w[:1].upper() + w[1:])
        else: words.append(w)
    return " ".join(words)


_GO_CHAT = ["deepseek-v4-pro", "deepseek-v4-flash", "deepseek-v4.1-flash", "deepseek-v4-flash-vision-exp",
            "kimi-k3", "kimi-k2.7-code", "kimi-k2.6", "glm-5.3", "glm-5.3-flash", "glm-5.2", "glm-5.1",
            "mimo-v2.5-pro", "mimo-v2.5", "longcat-2.0", "hy4-preview", "hy3"]
_GO_MESSAGES = ["qwen3.8-max", "qwen3.8-flash", "qwen3.7-max", "qwen3.7-plus", "qwen3.6-plus",
                "minimax-m3", "minimax-m2.7", "minimax-m2.5", "union-alpha"]
_GO_RESPONSES = ["gpt-5.6-luna", "grok-4.6", "muse-spark-1.3-contributor", "muse-spark-1.2-contributor"]

_ZEN_CHAT = ["deepseek-v4-pro", "deepseek-v4-flash", "deepseek-v4-flash-vision-exp", "kimi-k3", "kimi-k2.7-code",
             "kimi-k2.6", "kimi-k2.5", "glm-5.3", "glm-5.3-flash", "glm-5.2", "glm-5.1", "glm-5",
             "minimax-m3", "minimax-m2.7", "minimax-m2.5", "big-pickle"]
_ZEN_MESSAGES = ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5", "claude-fable-5-1", "claude-opus-4-8",
                 "claude-sonnet-4-6", "qwen3.7-max", "qwen3.7-plus", "qwen3.6-plus", "qwen3.5-plus"]
_ZEN_RESPONSES = ["gpt-6-astra", "gpt-5.6-sol", "gpt-5.5", "gpt-5.4", "gpt-5.3-codex", "grok-4.6"]

PRESETS = {
    "local": {
        "label": "Local (this Mac)", "base": "", "key": "", "auth": "local", "models": [],
        "docs": "The model MTPLX serves on this Mac.",
    },
    "bionic": {
        "label": "Bionic", "base": "", "key": "", "auth": "gateway", "keyless": True,
        "docs": "The models Bionic runs on this Mac. They speak OpenAI's API, so the harness "
                "reaches them through Orbit's gateway; there is no key and nothing leaves the Mac. "
                "Orbit switches Bionic's local server on when you pick one.",
        "models": [],
    },
    "claude": {
        "label": "Claude · your subscription", "base": "", "key": "", "auth": "subscription",
        "docs": "Claude Code as you use it in a terminal: your own Claude login (Pro, Max, Team), no API key. "
                "Nothing goes through Orbit's gateway.",
        "models": [_m("opus", "messages", 200000, "Claude Opus (latest)"),
                   _m("sonnet", "messages", 200000, "Claude Sonnet (latest)"),
                   _m("haiku", "messages", 200000, "Claude Haiku (latest)"),
                   _m("opus[1m]", "messages", 1000000, "Claude Opus · 1M context"),
                   _m("sonnet[1m]", "messages", 1000000, "Claude Sonnet · 1M context")],
    },
    "opencode-go": {
        "label": "OpenCode Go", "base": "https://opencode.ai/zen/go/v1", "key": "OPENCODE_API_KEY",
        "auth": "gateway", "small": "deepseek-v4-flash", "keys_url": "https://opencode.ai/auth",
        "docs": "OpenCode's low-cost subscription for open coding models.",
        "models": [_m(x, "chat") for x in _GO_CHAT] + [_m(x, "messages") for x in _GO_MESSAGES]
                  + [_m(x, "responses") for x in _GO_RESPONSES],
    },
    "opencode-zen": {
        "label": "OpenCode Zen", "base": "https://opencode.ai/zen/v1", "key": "OPENCODE_API_KEY",
        "auth": "gateway", "small": "deepseek-v4-flash", "keys_url": "https://opencode.ai/auth",
        "docs": "OpenCode's pay-as-you-go catalogue.",
        "models": [_m(x, "chat") for x in _ZEN_CHAT] + [_m(x, "messages", 200000) for x in _ZEN_MESSAGES]
                  + [_m(x, "responses") for x in _ZEN_RESPONSES],
    },
    "deepseek": {
        "label": "DeepSeek", "base": "https://api.deepseek.com/anthropic", "key": "DEEPSEEK_API_KEY",
        "auth": "api_key", "small": "deepseek-v4-flash", "keys_url": "https://platform.deepseek.com/api_keys",
        "docs": "Unknown model names silently fall back to deepseek-v4-flash, so pick one explicitly.",
        "models": [_m("deepseek-v4-pro", "messages"), _m("deepseek-v4-flash", "messages")],
    },
    "qwen": {
        "label": "Qwen · Alibaba Model Studio", "base": "https://dashscope-intl.aliyuncs.com/apps/anthropic",
        "alt_bases": ["https://dashscope.aliyuncs.com/apps/anthropic"], "key": "DASHSCOPE_API_KEY",
        "auth": "api_key", "small": "qwen3-coder-plus", "keys_url": "https://modelstudio.console.alibabacloud.com",
        "docs": "The key's region must match the base URL (international ↔ -intl, mainland ↔ dashscope).",
        "models": [_m("qwen3-coder-plus", "messages"), _m("qwen3-max", "messages")],
    },
    "glm": {
        "label": "GLM · Z.ai", "base": "https://api.z.ai/api/anthropic",
        "alt_bases": ["https://open.bigmodel.cn/api/anthropic"], "key": "ZAI_API_KEY",
        "auth": "api_key", "small": "glm-4.5-air", "keys_url": "https://z.ai",
        "docs": "The base URL must end in /api/anthropic.",
        "models": [_m("glm-4.6", "messages"), _m("glm-4.5-air", "messages")],
    },
    "minimax": {
        "label": "MiniMax", "base": "https://api.minimax.io/anthropic",
        "alt_bases": ["https://api.minimaxi.com/anthropic"], "key": "MINIMAX_API_KEY",
        "auth": "api_key", "keys_url": "https://platform.minimax.io",
        "env": {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "512000"},
        "docs": "The /anthropic endpoint reports a small context window, so auto-compact is widened.",
        "models": [_m("MiniMax-M3", "messages", 512000)],
    },
    "kimi": {
        "label": "Kimi · Moonshot", "base": "https://api.moonshot.ai/anthropic",
        "alt_bases": ["https://api.moonshot.cn/anthropic"], "key": "MOONSHOT_API_KEY",
        "auth": "api_key", "keys_url": "https://platform.kimi.ai",
        "docs": ".ai and .cn keys are not interchangeable.",
        "models": [_m("kimi-k2.7-code", "messages")],
    },
    "anthropic": {
        "label": "Anthropic", "base": "https://api.anthropic.com", "key": "ANTHROPIC_API_KEY",
        "auth": "api_key", "small": "claude-haiku-4-5", "keys_url": "https://console.anthropic.com/settings/keys",
        "models": [_m("claude-opus-5", "messages", 1000000), _m("claude-sonnet-5", "messages", 1000000),
                   _m("claude-haiku-4-5", "messages", 200000)],
    },
}


def _path(root):
    return os.path.join(root, "config", "harness.json")


# ------------------------------------------------------------------ live model lists
#
# models.dev (the catalogue OpenCode itself uses) lists each provider's models
# with their context window, output limit and API. A provider's own /models
# endpoint, asked with your key, says what your account can use right now.

MODELS_DEV_URL = "https://models.dev/api.json"
MODELS_DEV_ID = {"opencode-go": "opencode-go", "opencode-zen": "opencode", "deepseek": "deepseek",
                 "qwen": "alibaba", "glm": "zai", "minimax": "minimax", "kimi": "moonshotai",
                 "anthropic": "anthropic"}


def _fetched_path(root):
    return os.path.join(root, "config", "harness-models.json")


def fetched(root):
    try:
        return json.load(open(_fetched_path(root)))
    except (OSError, ValueError):
        return {}


def _http_json(url, headers=None, timeout=20):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "orbit", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def models_dev(root, max_age=86400, timeout=30):
    """The models.dev catalogue, kept for a day in config/models-dev.json."""
    import time
    path = os.path.join(root, "config", "models-dev.json")
    try:
        if time.time() - os.path.getmtime(path) < max_age:
            return json.load(open(path))
    except (OSError, ValueError):
        pass
    try:
        d = _http_json(MODELS_DEV_URL, timeout=timeout)
        tmp = path + ".tmp"
        with open(tmp, "w") as fh: json.dump(d, fh)
        os.replace(tmp, path)
        return d
    except Exception:
        try: return json.load(open(path))
        except (OSError, ValueError): return {}


def _format_from_npm(npm):
    npm = npm or ""
    if "anthropic" in npm: return "messages"
    if npm.endswith("/openai"): return "responses"
    if "google" in npm: return None                  # Gemini's own API: not supported
    return "chat"


def refresh_models(root, pid, secrets=None, timeout=20):
    """Bring a provider's model list up to date. Returns (count, note)."""
    import time
    base_p = providers(root).get(pid)
    if not base_p or base_p.get("auth") in ("local", "subscription"): return 0, "not a remote provider"
    dev = (models_dev(root).get(MODELS_DEV_ID.get(pid, pid)) or {}).get("models") or {}
    live, note = None, ""
    key = _key_value(base_p, secrets)
    if key and base_p.get("base"):
        try:
            base = base_p["base"].rstrip("/")
            url = base + ("/v1/models" if base.endswith("/anthropic") else "/models")
            d = _http_json(url, {"Authorization": "Bearer " + key, "x-api-key": key,
                                 "anthropic-version": "2023-06-01"}, timeout)
            live = [m.get("id") for m in (d.get("data") or d.get("models") or []) if isinstance(m, dict) and m.get("id")]
        except Exception as e:
            note = f"live list unavailable ({type(e).__name__})"
    ids = live if live else list(dev.keys())
    if not ids: return 0, note or "no models found"
    preset = {m["id"]: m for m in PRESETS.get(pid, {}).get("models") or []}
    out = []
    for mid in ids:
        info = dev.get(mid) or {}
        lim = info.get("limit") or {}
        if base_p.get("auth") == "api_key":
            fmt = "messages"                              # these endpoints are Anthropic-compatible
        elif mid in preset:
            fmt = preset[mid]["format"]
        else:
            fmt = _format_from_npm((info.get("provider") or {}).get("npm") if isinstance(info.get("provider"), dict)
                                   else None)
        if fmt is None: continue
        out.append({"id": mid, "format": fmt, "label": info.get("name") or _label(mid),
                    "context": int(lim.get("context") or (preset.get(mid) or {}).get("context") or 128000),
                    "output": int(lim.get("output") or 0) or None,
                    "reasoning": bool(info.get("reasoning")), "free": "free" in mid})
    out.sort(key=lambda m: (m["free"], m["id"]))
    cache = fetched(root)
    cache[pid] = {"at": time.time(), "source": ("live+models.dev" if live else "models.dev"), "models": out, "note": note}
    tmp = _fetched_path(root) + ".tmp"
    with open(tmp, "w") as fh: json.dump(cache, fh, indent=1)
    os.replace(tmp, _fetched_path(root))
    return len(out), note


def load(root):
    """The user's choices: custom providers, base URL per provider, extra env,
    per-model context, models hidden from the picker."""
    try:
        d = json.load(open(_path(root)))
    except (OSError, ValueError):
        d = {}
    return {"custom": d.get("custom") or {}, "providers": d.get("providers") or {},
            "hidden": d.get("hidden") or [], "contexts": d.get("contexts") or {},
            "gateway_port": d.get("gateway_port") or 8897, "proxy": d.get("proxy") or ""}


def save(root, cfg):
    keep = {k: cfg.get(k) for k in ("custom", "providers", "hidden", "contexts", "gateway_port", "proxy")}
    for c in (keep.get("custom") or {}).values():          # a key value never goes in this file
        c.pop("api_key", None)
    p = _path(root)
    tmp = p + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(keep, fh, indent=1)
    os.replace(tmp, p)
    return keep


def providers(root, local_name=None):
    """Presets merged with the user's choices, plus custom providers."""
    cfg = load(root)
    fetched_all = fetched(root)
    out = {}
    for pid, p in list(PRESETS.items()) + [(k, {**v, "custom": True}) for k, v in cfg["custom"].items()]:
        p = json.loads(json.dumps(p))
        over = cfg["providers"].get(pid) or {}
        if over.get("base"): p["base"] = over["base"]
        if over.get("env"): p["env"] = {**(p.get("env") or {}), **over["env"]}
        if over.get("small"): p["small"] = over["small"]
        if over.get("accounts"): p["accounts"] = over["accounts"]
        if over.get("active"): p["active"] = over["active"]
        for m in over.get("extra_models") or []:
            if not any(x["id"] == m.get("id") for x in p["models"]):
                p["models"].append(_m(m["id"], m.get("format") or "messages", m.get("context") or 128000))
        got = (fetched_all.get(pid) or {}).get("models")
        if got and pid not in ("local", "claude"):
            p["models"] = [dict(m) for m in got]
            p["fetched_at"] = fetched_all[pid].get("at")
        if pid == "local" and local_name:
            p["models"] = [_m(local_name, "messages", 131072, label=f"{local_name}")]
        if pid == "bionic":
            # Bionic is asked what it has, every time: models come and go there
            b = _bionic()
            if b is None or not b.installed():
                continue                        # not on this Mac: not in the picker
            if not p.get("base"): p["base"] = b.base_url(b.port())
            if not over.get("extra_models"):
                p["models"] = [_m(m["model"], "chat", m["context"], label=m["label"])
                               for m in b.models()]
        for m in p["models"]:
            m.setdefault("format", "messages"); m.setdefault("context", 128000)
            m.setdefault("label", _label(m["id"]))
            ctx = cfg["contexts"].get(f"{pid}/{m['id']}")
            if ctx: m["context"] = int(ctx)
        out[pid] = p
    return out


def _secret(name, secrets):
    return ((secrets or {}).get(name) or os.environ.get(name) or "") if name else ""


def accounts(p):
    """A provider's accounts, the active one first: [{id, label, key}]."""
    rows = [a for a in (p.get("accounts") or []) if isinstance(a, dict) and a.get("key")]
    if not rows and p.get("key"):
        rows = [{"id": "main", "label": "Main", "key": p["key"]}]
    active = p.get("active")
    rows.sort(key=lambda a: a.get("id") != active)
    return [{"id": str(a.get("id") or a["key"]), "label": a.get("label") or a["key"], "key": a["key"]} for a in rows]


def account_keys(p, secrets, root=None, pid=None):
    """Accounts with a key, in the order to try them: the active one, then the rest;
    accounts marked used up go last (a mark may be stale, so they are still tried)."""
    out = [{"id": a["id"], "label": a["label"], "key_name": a["key"], "api_key": _secret(a["key"], secrets)}
           for a in accounts(p)]
    out = [a for a in out if a["api_key"]]
    if root and pid:
        try:
            import harness_usage
            for a in out: a["exhausted"] = harness_usage.exhausted(root, pid, a["id"])
            out.sort(key=lambda a: bool(a.get("exhausted")))
        except Exception:
            pass
    return out


def _key_value(p, secrets):
    got = account_keys(p, secrets)
    return got[0]["api_key"] if got else ""


def claude_installed():
    import shutil
    for d in ("", "~/.local/bin", "/opt/homebrew/bin", "/usr/local/bin", "~/.claude/local"):
        if (shutil.which("claude") if not d else os.path.exists(os.path.join(os.path.expanduser(d), "claude"))):
            return True
    return False


_LOGIN = {"at": 0.0, "state": None, "token": None}
TOKEN_KEY = "CLAUDE_CODE_OAUTH_TOKEN"      # from `claude setup-token`, saved in Orbit's secrets


def claude_login(max_age=120, token=None):
    """Whether the `claude` command is signed in to a Claude account: "yes", "no" or
    "missing". Signed in means its own login (`claude auth login`, kept in the macOS
    Keychain) or a long-lived token from `claude setup-token` saved in Orbit."""
    import subprocess, time
    if _LOGIN["state"] and _LOGIN["token"] == bool(token) and time.time() - _LOGIN["at"] < max_age:
        return _LOGIN["state"]
    if not claude_installed():
        state = "missing"
    else:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "ANTHROPIC"))}
        if token: env[TOKEN_KEY] = token
        env["PATH"] = ":".join([env.get("PATH", "")] + [os.path.expanduser(d) for d in
                                                        ("~/.local/bin", "/opt/homebrew/bin", "/usr/local/bin")])
        try:
            r = subprocess.run(["claude", "auth", "status"], env=env, capture_output=True, text=True, timeout=20)
            state = "yes" if json.loads(r.stdout or "{}").get("loggedIn") else "no"
        except Exception:
            state = "yes"                     # cannot tell: let Claude Code itself say
    _LOGIN.update(at=time.time(), state=state, token=bool(token))
    return state


def _bionic():
    try:
        import bionic
        return bionic
    except Exception:
        return None


def _ready(pid, p, secrets):
    if p.get("auth") == "local" or p.get("keyless"): return True
    if p.get("auth") == "subscription": return claude_login(token=_secret(TOKEN_KEY, secrets)) == "yes"
    return bool(_key_value(p, secrets))


def catalogue(root, secrets=None, local_name=None, include_unready=False):
    """Harness models for the picker: providers you can use now (a key set, or local)."""
    cfg = load(root)
    out = []
    for pid, p in providers(root, local_name).items():
        ready = _ready(pid, p, secrets)
        if not ready and not include_unready: continue
        # the local model is already in the picker as "Claude Code · local Qwen"
        if pid == "local" and not include_unready: continue
        for m in p["models"]:
            mid = f"harness:{pid}/{m['id']}"
            if mid in cfg["hidden"] and not include_unready: continue
            out.append({"id": mid, "provider": "harness", "model": f"{pid}/{m['id']}",
                        "label": f"{m['label']} · {p['label']}", "context": m["context"],
                        "thinking": True, "kind": "harness", "format": m["format"],
                        "provider_label": "Claude Code · " + p["label"], "ready": ready,
                        "hidden": mid in cfg["hidden"],
                        "note": "through Orbit's translating gateway" if m["format"] != "messages" else ""})
    return out


def resolve(root, mid, secrets=None, local_name=None):
    if not mid or not str(mid).startswith("harness:"): return None
    pid, _, model = str(mid)[len("harness:"):].partition("/")
    p = providers(root, local_name).get(pid)
    if not p: return None
    m = next((x for x in p["models"] if x["id"] == model), None)
    if m is None and pid == "local" and model:
        m = _m(model, "messages", 131072)
    if m is None: return None
    cfg = load(root)
    keys = account_keys(p, secrets, root, pid)
    auth = p.get("auth") or "api_key"
    if auth == "api_key" and len(keys) > 1:
        auth = "gateway"               # several accounts: the gateway can move to the next
    return {"id": mid, "provider": "harness", "model": f"{pid}/{model}",
            "label": f"{m['label']} · {p['label']}", "context": m["context"], "kind": "harness",
            "provider_label": "Claude Code · " + p["label"], "ready": _ready(pid, p, secrets),
            "provider_cfg": {"kind": "harness", "provider": pid, "model": model, "base": p.get("base") or "",
                             "format": m["format"], "auth": auth,
                             "key_name": (keys[0]["key_name"] if keys else p.get("key") or ""),
                             "api_key": keys[0]["api_key"] if keys else "",
                             "accounts": [{"id": a["id"], "api_key": a["api_key"]} for a in keys],
                             "account": keys[0]["id"] if keys else "",
                             "env": dict(p.get("env") or {}), "small": p.get("small") or model,
                             "context": m["context"], "max_output": m.get("output"),
                             "label": p["label"], "proxy": cfg["proxy"],
                             "local": p.get("auth") == "local",
                             "keyless": bool(p.get("keyless")),
                             "subscription": p.get("auth") == "subscription"}}


_WORD = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")


def find(root, text, secrets=None, local_name=None):
    """A model named in words ("deepseek v4 pro on opencode go", "local qwen")."""
    text = (text or "").strip()
    if not text: return None
    if text.startswith("harness:"):
        return resolve(root, text, secrets, local_name)
    want = set(_WORD.findall(text.lower()))
    best, best_s = None, 0.0
    for m in catalogue(root, secrets, local_name, include_unready=True):
        pid = m["model"].split("/")[0]
        hay = set(_WORD.findall((m["model"] + " " + m["label"] + " " + pid).lower().replace("-", " ")))
        if pid == "local": hay |= {"local", "mac", "mtplx", "qwen"}
        if pid == "opencode-go": hay |= {"opencode", "go"}
        if pid == "opencode-zen": hay |= {"opencode", "zen"}
        if pid == "claude": hay |= {"claude", "subscription", "login", "anthropic"}
        if pid not in ("opencode-go", "opencode-zen", "local", "claude"): hay |= {"direct", "official"}
        hit = want & hay
        if not hit: continue
        score = len(hit) - 0.1 * len(hay - want) / max(1, len(hay))
        score -= 0.01 * len(want - hay)
        if not m["ready"]: score -= 0.5
        if pid == "claude" and "claude" in want: score += 0.2      # "claude opus": your own Claude first
        if score > best_s:
            best, best_s = m, score
    if best is None or best_s < 1: return None
    # every distinctive word must match something
    return resolve(root, best["id"], secrets, local_name)


def _exhausted(root, pid, account):
    try:
        import harness_usage
        return harness_usage.exhausted(root, pid, account)
    except Exception:
        return None


def public_view(root, secrets=None, local_name=None):
    """For the settings page: everything but key values."""
    cfg = load(root)
    out = []
    for pid, p in providers(root, local_name).items():
        out.append({"id": pid, "label": p["label"], "base": p.get("base"), "alt_bases": p.get("alt_bases") or [],
                    "key": p.get("key"), "key_set": bool(_key_value(p, secrets)), "auth": p.get("auth"),
                    "keyless": bool(p.get("keyless")), "ready": _ready(pid, p, secrets),
                    "login": claude_login(token=_secret(TOKEN_KEY, secrets)) if p.get("auth") == "subscription" else None,
                    "token_set": bool(_secret(TOKEN_KEY, secrets)) if p.get("auth") == "subscription" else None,
                    "accounts": [{"id": a["id"], "label": a["label"], "key": a["key"],
                                  "key_set": bool(_secret(a["key"], secrets)),
                                  "active": i == 0, "exhausted": _exhausted(root, pid, a["id"])}
                                 for i, a in enumerate(accounts(p))],
                    "docs": p.get("docs") or "", "keys_url": p.get("keys_url") or "", "custom": bool(p.get("custom")),
                    "env": p.get("env") or {}, "small": p.get("small") or "", "fetched_at": p.get("fetched_at"),
                    "models": [{**m, "hidden": f"harness:{pid}/{m['id']}" in cfg["hidden"]} for m in p["models"]]})
    return {"providers": out, "gateway_port": cfg["gateway_port"], "proxy": cfg["proxy"]}
