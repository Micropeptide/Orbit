"""Muse Glimmer: Meta's open-weight 30B multimodal model, run on this Mac.

Nothing here downloads or starts anything. It looks for a Glimmer that is already being
served (Ollama, LM Studio or llama.cpp's `llama serve`, all OpenAI-compatible), so the model
appears in Orbit's pickers when it is up, and it says how to get it when it is not.

  https://dev.meta.ai/docs/muse-glimmer         (Apache 2.0, 128K context, text + image in)
  https://dev.meta.ai/docs/muse-glimmer/deploy  (the runtimes)
"""
import json, os, shutil, subprocess, time, urllib.request

# (runtime, where it listens by default, how to ask it what it serves)
RUNTIMES = (
    ("ollama", "http://127.0.0.1:11434", "ollama"),
    ("lmstudio", "http://127.0.0.1:1234", "lmstudio"),
    ("llama.cpp", "http://127.0.0.1:8080", "llama"),
)
CONTEXT = 131072
HF_REPO = "meta-models/Muse-Glimmer-30B-GGUF"
HF_FILE = "Muse-Glimmer-30B-KQuant-17GB-Q4_K_M.gguf"
GGUF_GB = 17
SERVE_PORT = 8080

# the commands from the docs; the settings page types them into Orbit's terminal for you to run
COMMANDS = {
    "ollama": "ollama run muse-glimmer",
    "llama.cpp": ("llama serve -hf %s --hf-file %s -a muse-glimmer -ngl 99 -c %d -np 1 --host 127.0.0.1 --port %d "
                  "--chat-template-kwargs '{\"reasoning_strength\":\"low\"}'" % (HF_REPO, HF_FILE, CONTEXT, SERVE_PORT)),
    "lmstudio": "lms server start",
}

_CACHE = {"at": 0.0, "rows": []}


def _get(url, timeout=1.5):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "orbit"}), timeout=timeout) as r:
        return json.load(r)


def _ids(runtime, base):
    """The model ids a running server lists, or None when nothing answers there."""
    try:
        if runtime == "ollama":
            d = _get(base + "/api/tags")
            return [m.get("name") or m.get("model") for m in d.get("models") or [] if isinstance(m, dict)]
        d = _get(base + "/v1/models")
        return [m.get("id") for m in d.get("data") or [] if isinstance(m, dict)]
    except Exception:
        return None


def served(max_age=45, force=False):
    """Glimmer models being served right now: [{"id", "runtime", "base", "label", "context"}]; `base`
    is the OpenAI-compatible root (.../v1). Looked up at most every `max_age` seconds."""
    if not force and time.time() - _CACHE["at"] < max_age: return list(_CACHE["rows"])
    rows = []
    for runtime, root, _ in RUNTIMES:
        for mid in _ids(runtime, root) or []:
            if mid and "glimmer" in str(mid).lower():
                rows.append({"id": str(mid), "runtime": runtime, "base": root + "/v1",
                             "label": "Muse Glimmer 30B · " + ("llama.cpp" if runtime == "llama.cpp" else
                                                               "Ollama" if runtime == "ollama" else "LM Studio"),
                             "context": CONTEXT})
    _CACHE.update(at=time.time(), rows=rows)
    return list(rows)


def memory_gb():
    try: return round(int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5).stdout) / 2**30)
    except Exception: return None


def installed():
    """Which runtimes are on this Mac (a binary or an app), without starting any."""
    found = {}
    for name, binary in (("ollama", "ollama"), ("llama.cpp", "llama"), ("lmstudio", "lms")):
        for d in ("", "/opt/homebrew/bin", "/usr/local/bin", os.path.expanduser("~/.local/bin"),
                  os.path.expanduser("~/.lmstudio/bin")):
            p = shutil.which(binary) if not d else (os.path.join(d, binary) if os.access(os.path.join(d, binary), os.X_OK) else None)
            if p: found[name] = p; break
    if "lmstudio" not in found and os.path.isdir("/Applications/LM Studio.app"): found["lmstudio"] = "/Applications/LM Studio.app"
    if "llama.cpp" not in found and os.path.isdir("/Applications/Llama.app"): found["llama.cpp"] = "/Applications/Llama.app"
    return found


def status(fresh=False):
    """For Settings: what is serving, what is installed, whether this Mac can hold it, and the commands."""
    mem, free = memory_gb(), None
    try: free = round(shutil.disk_usage(os.path.expanduser("~")).free / 2**30)
    except Exception: pass
    have = installed()
    rows = served(max_age=0 if fresh else 45, force=fresh)
    fits = (mem or 0) >= 32
    advice = ("" if rows else
              ("The 4-bit build is about %d GB: it fits this Mac's %s GB, but Orbit's local model and Glimmer would not "
               "both stay loaded." % (GGUF_GB, mem) if fits else
               "The 4-bit build is about %d GB and wants 32 GB of memory or more; this Mac has %s GB." % (GGUF_GB, mem)))
    return {"serving": rows, "installed": have, "memory_gb": mem, "disk_free_gb": free, "fits": fits,
            "advice": advice, "commands": COMMANDS, "size_gb": GGUF_GB, "license": "Apache 2.0",
            "docs": "https://dev.meta.ai/docs/muse-glimmer"}


def models_for_picker():
    """Served Glimmer models as local models the pickers can offer: [{"model", "label", "base", "context"}]."""
    return [{"model": r["id"], "label": r["label"], "base": r["base"], "context": r["context"]} for r in served()]
