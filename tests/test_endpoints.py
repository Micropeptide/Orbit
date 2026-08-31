"""Hit every read-only endpoint of a running Orbit app and fail on any error.

    venv/bin/python tests/test_endpoints.py
"""
import json, urllib.request, urllib.error, sys
BASE = "http://127.0.0.1:8899"
GETS = ["/api/about","/api/agents","/api/code","/api/context","/api/default_prompt",
        "/api/files","/api/health","/api/info","/api/instructions","/api/knowledge",
        "/api/ledger","/api/mcp","/api/memory","/api/projects","/api/prompts",
        "/api/running","/api/schedule","/api/searchchats?q=test","/api/secrets",
        "/api/sessions?limit=5","/api/skills","/api/state","/api/status",
        "/api/tags","/api/trash"]   # settings and system_preview are POST-only
bad = []
for p in GETS:
    try:
        r = urllib.request.urlopen(BASE + p, timeout=25)
        body = r.read().decode("utf-8", "replace")
        code = r.status
        try:
            obj = json.loads(body); kind = type(obj).__name__
            n = len(obj) if isinstance(obj,(list,dict)) else "-"
        except ValueError:
            kind, n, obj = "NOT-JSON", "-", None
            bad.append((p, code, "response is not JSON"))
        err = obj.get("error") if isinstance(obj, dict) else None
        if err: bad.append((p, code, f"error: {err}"))
        print(f"  {code}  {p:34} {kind}[{n}]" + (f"  <-- {err}" if err else ""))
    except urllib.error.HTTPError as e:
        print(f"  {e.code}  {p:34} HTTPError"); bad.append((p, e.code, e.reason))
    except Exception as e:
        print(f"  ---  {p:34} {type(e).__name__}: {e}"); bad.append((p, "-", str(e)))
print("\nproblems:", len(bad))
for b in bad: print("   ", b)
sys.exit(1 if bad else 0)
