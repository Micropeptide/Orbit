"""Round-trip every object the UI can create, against a running Orbit app.

    venv/bin/python tests/test_api.py

Creates and removes its own data; leaves nothing behind.
"""
import json, os, urllib.request, time
BASE="http://127.0.0.1:8899"
def post(p, d=None):
    r=urllib.request.Request(BASE+p, data=json.dumps(d or {}).encode(),
        headers={"Content-Type":"application/json","Origin":BASE})
    return json.load(urllib.request.urlopen(r, timeout=30))
def get(p): return json.load(urllib.request.urlopen(BASE+p, timeout=30))

fails=[]
def check(label, cond, extra=""):
    print(("  ok   " if cond else "  FAIL ")+label+("  "+str(extra) if extra and not cond else ""))
    if not cond: fails.append(label)

# --- memory
post("/api/memory/save", {"name":"smoke-mem","title":"Smoke test","text":"delete me"})
check("memory saved", any(m["name"]=="smoke-mem" for m in get("/api/memory")))
post("/api/memory/delete", {"name":"smoke-mem"})
check("memory deleted", not any(m["name"]=="smoke-mem" for m in get("/api/memory")))

# --- saved prompt
post("/api/prompts/save", {"name":"smoke-prompt","text":"say hi"})
check("prompt saved", "smoke-prompt" in get("/api/prompts"))
post("/api/prompts/delete", {"name":"smoke-prompt"})
check("prompt deleted", "smoke-prompt" not in get("/api/prompts"))

# --- agent
post("/api/agents/save", {"name":"smoke-agent","instructions":"you are a test",
                          "tools":["read_file"],"desc":"test"})
check("agent saved", "smoke-agent" in get("/api/agents")["agents"])
post("/api/agents/delete", {"name":"smoke-agent"})
check("agent deleted", "smoke-agent" not in get("/api/agents")["agents"])

# --- skill
post("/api/skills/save", {"name":"smoke-skill","text":"# smoke\nsteps"})
check("skill saved", any(s.get("name")=="smoke-skill" for s in get("/api/skills")))
post("/api/skills/delete", {"name":"smoke-skill"})
check("skill deleted", not any(s.get("name")=="smoke-skill" for s in get("/api/skills")))

# --- project
p=post("/api/projects/save", {"name":"smoke-project","instructions":"none"})
pid=[k for k,v in get("/api/projects").items() if v["name"]=="smoke-project"]
check("project saved", bool(pid), p)
if pid:
    post("/api/projects/delete", {"id":pid[0]})
    check("project deleted", not any(v["name"]=="smoke-project" for v in get("/api/projects").values()))

# --- scheduled task
j=post("/api/schedule/save", {"job":{"name":"smoke-task","prompt":"noop","every":"daily","at":"23:59"}})
try:
    post("/api/schedule/save", {"job":{"name":"empty"}}); check("empty task refused", False)
except Exception as e: check("empty task refused", "400" in str(e), e)
jid=[x["id"] for x in get("/api/schedule")["jobs"] if x.get("name")=="smoke-task"]
check("task saved", bool(jid), j)
if jid:
    post("/api/schedule/delete", {"id":jid[0]})
    check("task deleted", not any(x.get("name")=="smoke-task" for x in get("/api/schedule")["jobs"]))

# --- chat lifecycle on a real saved chat: rename -> tag -> pin -> archive -> bin -> restore -> purge
import sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
import qqcore as qc
sid = "smoke-" + time.strftime("%Y%m%d-%H%M%S")
qc.session_save(sid, [{"role":"system","content":"s"},
                      {"role":"user","content":"hello"},
                      {"role":"assistant","content":"hi"}], "smoke chat")
qc._SESS_CACHE["key"] = None
def row():
    return next((s for s in get("/api/sessions?limit=80")["items"] if s["id"] == sid), None)
check("chat listed", row() is not None)
post("/api/session/rename", {"id":sid,"title":"smoke renamed"})
post("/api/tag", {"id":sid,"tags":["smoke"]})
post("/api/session/flag", {"id":sid,"pinned":True})
r = row()
check("rename+tag+pin", bool(r) and r["title"]=="smoke renamed"
      and "smoke" in (r.get("tags") or []) and r.get("pinned"), r)
post("/api/session/flag", {"id":sid,"archived":True,"pinned":False})
r = row(); check("archived", bool(r) and r.get("archived") and not r.get("pinned"), r)
ex = urllib.request.urlopen(BASE+"/api/export?id="+sid, timeout=20).read().decode()
check("export markdown exports the chat you asked for", "smoke renamed" in ex and "hello" in ex, ex[:120])
post("/api/delete", {"id":sid})
check("binned", row() is None and any(sid in t["name"] for t in get("/api/trash")))
post("/api/trash/restore", {"name":next(t["name"] for t in get("/api/trash") if sid in t["name"])})
check("restored", row() is not None)
post("/api/delete", {"id":sid})
post("/api/trash/purge", {"name":next(t["name"] for t in get("/api/trash") if sid in t["name"])})
check("purged", not any(sid in t["name"] for t in get("/api/trash")) and row() is None)

# --- flags set before a chat has a file must survive its first save
fresh = post("/api/new")["sid"]                 # /api/new makes it the current chat
post("/api/session/flag", {"id":fresh,"pinned":True})
post("/api/tag", {"id":fresh,"tags":["pending"]})
post("/api/project/select", {"id":None})        # any action that writes the chat out
raw = json.load(open(qc.session_path(fresh)))
check("pending pin survives first save", raw.get("pinned") is True, raw)
check("pending tag survives first save", "pending" in (raw.get("tags") or []), raw)
os.remove(qc.session_path(fresh))          # leave nothing behind
qc._SESS_CACHE["key"] = None

print("\nfailures:", fails or "none")
