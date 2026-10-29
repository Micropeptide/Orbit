"""Shared projects: who may do what. Plain code, no model, nothing here can be argued with.

A grant says what one member may do (folders to read and write, tools, how much shell, switches for delete / push / install /
network, models, budget, an end date). A turn caused by several people runs with the intersection of their grants. `Policy.decide`
answers allow, deny or ask for one tool call, and fails closed: a tool it does not know, an argument it cannot read, a command it
cannot parse, an error of its own -- all deny.

The layers that sit around it (the guard model, a person's approval, the execution jail) are in other modules; this is the first one
and the only one that is certain. See docs/collab/DESIGN.md section 5 and THREAT_MODEL.md.
"""
import glob, itertools, os, re, shlex, time, unicodedata

ROLES = ("owner", "admin", "editor", "commenter", "viewer", "guest")
TOOLS = ("read", "edit", "shell", "network", "git", "cluster", "browser", "delegate", "schedule", "crew", "models")
SHELL_LEVELS = ("none", "read", "build", "all")
LEVEL = {k: i for i, k in enumerate(SHELL_LEVELS)}
SWITCHES = ("delete", "move_out_of_scope", "git_push", "install", "network", "run_code")       # False < "ask" < True
FILE_FLAGS = ("files_download", "files_browse", "files_edit", "files_upload_chat", "files_upload_dir")        # what a member may do with files themselves, not through a model
BOOLS = ("approver", "can_post", "can_start_crew", "can_touch_cluster", "can_add_members", "can_change_grants") + FILE_FLAGS
MAX_COMMAND = 50_000
MAX_PATH = 4096

# What a tool is, as a kind of power. A tool not named here is refused.
TOOL_CAP = {
    "read_file": "read", "list_dir": "read", "glob": "read", "grep_files": "read",
    "write_file": "edit", "edit_file": "edit", "multi_edit": "edit",
    "run_shell": "shell", "python": "shell",
    "web_search": "network", "fetch_url": "network", "http_json": "network", "fetch_paper_pdf": "network", "pubmed_search": "network",
    "ncbi": "network", "uniprot": "network", "arabidopsis_gene": "network", "alphafold": "network",
    "cluster_ls": "cluster", "cluster_read": "cluster", "cluster_status": "cluster",
    "cluster_run": "cluster", "cluster_submit": "cluster", "cluster_qdel": "cluster",
    "task": "delegate",
}
CLUSTER_CHANGES = {"cluster_run", "cluster_submit", "cluster_qdel"}
ALWAYS_OK = {"plan", "ask_user", "list_skills", "goal_status", "use_skill", "self_check"}
# Tools that are the person's own: Orbit's code, its other chats and memory, the screen. Never reachable from a shared project.
NEVER_TOOLS = {"self_patch", "self_rollback", "self_source", "orbit", "orbit_improve", "screen_click", "screen_move", "screen_drag",
               "screen_type", "screen_key", "screen_scroll", "screen_look", "remember", "search_chats", "read_chat", "chat_send", "chat_create",
               "chat_list", "chat_wait", "save_skill", "search_knowledge", "search_agent_memory", "claude_usage", "goal_set",
               # these outlive the turn or start work that runs later, or in a chat of its own, with the host's rights: not until they are made aware of shared projects
               "delegate", "schedule_task", "cancel_scheduled_task", "list_scheduled_tasks", "run_shell_background", "stop_background", "check_background", "list_background"}
REQUIRE_PATH = {"read_file", "write_file", "edit_file", "multi_edit"}
PATH_KEYS = ("path", "file_path", "notebook_path", "directory", "dir", "dest", "destination", "src", "source", "target")


# ---------------------------------------------------------------------------------------------------------- grants

def template(role, project=None):
    """The grant a role starts from. `project` is the project's working directory."""
    paths = [project] if project else []
    base = {"read_paths": list(paths), "write_paths": [], "deny_paths": [], "tools": [], "shell": "none", "delete": False,
            "move_out_of_scope": False, "git_push": False, "install": False, "network": False, "run_code": False, "models": [], "budget": {},
            "approver": False, "can_post": False, "can_start_crew": False, "can_touch_cluster": False, "can_add_members": False,
            "can_change_grants": False, "expires_at": None, "role": role, **{f: False for f in FILE_FLAGS}}
    if role == "owner":
        base.update(write_paths=list(paths), tools=list(TOOLS), shell="all", delete=True, move_out_of_scope=True, git_push=True,
                    install=True, network=True, run_code=True, models=["*"], approver=True, can_post=True, can_start_crew=True, can_touch_cluster=True,
                    can_add_members=True, can_change_grants=True, **{f: True for f in FILE_FLAGS})
    elif role == "admin":
        base.update(write_paths=list(paths), tools=list(TOOLS), shell="all", delete="ask", git_push="ask", install="ask", network=True, run_code="ask",
                    models=["*"], approver=True, can_post=True, can_start_crew=True, can_touch_cluster=True, can_add_members=True, can_change_grants=True, **{f: True for f in FILE_FLAGS})
    elif role == "editor":
        base.update(write_paths=list(paths), tools=["read", "edit", "shell", "git", "delegate", "models"], shell="build", models=["*"], can_post=True, **{f: True for f in FILE_FLAGS})
    elif role == "commenter":
        base.update(tools=["read"], can_post=True, files_download=True, files_upload_chat=True)
    elif role in ("viewer", "guest"):
        base.update(read_paths=[], files_download=role == "viewer")
    else:
        raise ValueError(f"unknown role {role!r}")
    return base


def _clean_paths(v, home, field):
    if not isinstance(v, (list, tuple)): raise ValueError(f"{field} must be a list")
    out = []
    for p in v:
        if not isinstance(p, str) or not p or "\x00" in p: raise ValueError(f"{field}: not a path")
        p = os.path.expanduser(p)
        if not os.path.isabs(p): raise ValueError(f"{field}: {p!r} is not an absolute path")
        p = os.path.realpath(p)
        if p == os.sep or len([x for x in p.split(os.sep) if x]) < 1 or (home and p == home):
            if field != "deny_paths": raise ValueError(f"{field}: {p!r} is too broad (the filesystem root and the home folder cannot be granted)")
        if p not in out: out.append(p)
    return out


def normalize(g, policy=None):
    """A grant as plain data with everything checked; unknown fields are dropped, bad values raise ValueError, a missing field is no access."""
    policy = policy or Policy()
    g = g if isinstance(g, dict) else {}
    out = template("guest")
    out["role"] = str(g.get("role") or "custom")[:20]
    for f in ("read_paths", "write_paths", "deny_paths"):
        if f in g: out[f] = _clean_paths(g[f], policy.home, f)
    if "tools" in g:
        if not isinstance(g["tools"], (list, tuple)): raise ValueError("tools must be a list")
        out["tools"] = [t for t in TOOLS if t in g["tools"]]
    if "shell" in g:
        if g["shell"] not in SHELL_LEVELS: raise ValueError("shell must be one of " + ", ".join(SHELL_LEVELS))
        out["shell"] = g["shell"]
    for f in SWITCHES:
        if f in g:
            if g[f] not in (True, False, "ask"): raise ValueError(f"{f} must be true, false or \"ask\"")
            out[f] = g[f]
    for f in BOOLS:
        if f in g:
            if not isinstance(g[f], bool): raise ValueError(f"{f} must be true or false")
            out[f] = g[f]
    if "models" in g:
        if not isinstance(g["models"], (list, tuple)) or not all(isinstance(m, str) for m in g["models"]): raise ValueError("models must be a list of ids")
        out["models"] = sorted(set(g["models"]))
    if "budget" in g:
        b = g["budget"]
        if not isinstance(b, dict) or any(not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0 for v in b.values()):
            raise ValueError("budget must map names to numbers >= 0")
        out["budget"] = {str(k)[:30]: v for k, v in b.items()}
    if g.get("expires_at") is not None:
        if not isinstance(g["expires_at"], (int, float)) or isinstance(g["expires_at"], bool): raise ValueError("expires_at must be a time")
        out["expires_at"] = float(g["expires_at"])
    return out


def _fold(p):
    return unicodedata.normalize("NFC", p).casefold()


def under(path, root, fold=False):
    if fold: path, root = _fold(path), _fold(root)
    else: path, root = unicodedata.normalize("NFC", path), unicodedata.normalize("NFC", root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _meet_paths(a, b):
    """Folders both lists allow: where one list's folder holds the other's, the deeper one."""
    out = []
    for x in a:
        for y in b:
            z = y if under(y, x) else x if under(x, y) else None
            if z and z not in out: out.append(z)
    return sorted(out)


def _strict(a, b):
    order = {False: 0, "ask": 1, True: 2}
    return a if order[a] <= order[b] else b


def intersect(a, b):
    """What both grants allow: the stricter of each field."""
    out = template("guest")
    out["role"] = "mixed"
    out["read_paths"] = _meet_paths(a["read_paths"], b["read_paths"])
    out["write_paths"] = _meet_paths(a["write_paths"], b["write_paths"])
    out["deny_paths"] = sorted(set(a["deny_paths"]) | set(b["deny_paths"]))
    out["tools"] = [t for t in a["tools"] if t in b["tools"]]
    out["shell"] = a["shell"] if LEVEL[a["shell"]] <= LEVEL[b["shell"]] else b["shell"]
    for f in SWITCHES: out[f] = _strict(a[f], b[f])
    for f in BOOLS: out[f] = bool(a[f] and b[f])
    ma, mb = a["models"], b["models"]
    out["models"] = mb if "*" in ma else ma if "*" in mb else sorted(set(ma) & set(mb))
    bud = {}
    for k in set(a["budget"]) | set(b["budget"]):
        vals = [x[k] for x in (a["budget"], b["budget"]) if k in x]
        bud[k] = min(vals)
    out["budget"] = bud
    ex = [x for x in (a["expires_at"], b["expires_at"]) if x is not None]
    out["expires_at"] = min(ex) if ex else None
    return out


def effective(grants, policy=None, now=None):
    """The grant a turn runs with: the intersection of every author's, nothing at all when there is nobody."""
    gs = list(grants)
    if not gs: return normalize({}, policy=policy)
    out = gs[0]
    for g in gs[1:]: out = intersect(out, g)
    return out


def summary(g):
    """What a grant lets a person do, in plain sentences (the 'what can each person do here' screen reads these)."""
    s = []
    s.append("read files in " + ", ".join(g["read_paths"]) if g["read_paths"] else "read no files")
    s.append("edit files in " + ", ".join(g["write_paths"]) if g["write_paths"] else "cannot edit files")
    if g["deny_paths"]: s.append("never touch " + ", ".join(g["deny_paths"]))
    s.append({"none": "cannot run commands", "read": "run read-only commands", "build": "run build and test commands", "all": "run any command"}[g["shell"]])
    for f, label in (("delete", "delete"), ("git_push", "push to git"), ("install", "install software"), ("network", "use the network"), ("run_code", "run programs and scripts")):
        s.append(f"can {label}" if g[f] is True else f"must ask first to {label}" if g[f] == "ask" else f"cannot {label}")
    for t in ("cluster", "schedule", "crew", "delegate"):
        if t in g["tools"]: s.append(f"can use {t}")
    s.append("download files the models make in chats" if g["files_download"] else "cannot download files from chats")
    s.append("browse and download files in the project folder" if g["files_browse"] else "cannot browse the project folder")
    if g["files_edit"]: s.append("edit text files in the project folder (where allowed to write)")
    if g["files_upload_chat"]: s.append("attach files to the chat")
    if g["files_upload_dir"]: s.append("put files into the project folder (where allowed to write)")
    if g["expires_at"]: s.append("until " + time.strftime("%Y-%m-%d %H:%M", time.localtime(g["expires_at"])))
    return s


# ---------------------------------------------------------------------------------------------------------- shell

READ_PROGS = {"ls", "cat", "head", "tail", "wc", "grep", "egrep", "fgrep", "rg", "file", "stat", "pwd", "echo", "printf", "date", "which", "id",
              "whoami", "diff", "cmp", "sort", "uniq", "cut", "tr", "du", "df", "tree", "basename", "dirname", "realpath", "readlink", "jq",
              "md5", "shasum", "sha256sum", "true", "false", "test", "[", "nl", "fold", "column", "less", "more", "hexdump", "od", "strings",
              "comm", "paste", "join", "expand", "rev", "seq", "sleep", "uname", "tac", "nproc", "cd", "export", "unset", "alias"}
BUILD_PROGS = {"make", "cmake", "ninja", "pytest", "py.test", "mkdir", "touch", "cp", "mv", "tee", "rm", "rmdir", "unlink", "ln", "gcc", "clang",
               "cc", "c++", "g++", "tar", "zip", "unzip", "gzip", "gunzip", "tsc", "black", "ruff", "flake8", "mypy", "prettier", "eslint", "isort", "gradle", "mvn", "xcodebuild", "swift"}
INTERPRETERS = {"sh", "bash", "zsh", "fish", "dash", "ksh", "csh", "tcsh", "python", "python3", "python2", "node", "ruby", "perl", "php", "lua",
                "osascript", "awk", "gawk", "nawk", "xargs", "eval", "exec", "source", ".", "nohup_", "npx", "tclsh", "swift-repl"}
NETWORK_PROGS = {"curl", "wget", "ssh", "scp", "sftp", "rsync", "nc", "ncat", "netcat", "telnet", "ftp", "dig", "nslookup", "ping", "traceroute", "gh", "mosh"}
PRIVILEGED = {"sudo", "su", "doas", "launchctl", "osascript", "systemsetup", "defaults", "killall", "pkill", "kill", "shutdown", "reboot", "halt",
              "diskutil", "hdiutil", "security", "dscl", "networksetup", "pmset", "csrutil", "spctl", "tccutil", "sysadminctl", "dd", "mkfs", "fdisk"}
SECRET_PROGS = {"env", "printenv", "declare", "compgen", "typeset"}
DELETE_PROGS = {"rm", "rmdir", "unlink", "shred"}
WRAPPERS = {"env", "nohup", "time", "command", "nice", "exec", "builtin", "stdbuf", "caffeinate"}
GIT_READ = {"status", "log", "diff", "show", "blame", "ls-files", "rev-parse", "describe", "shortlog", "grep", "ls-tree", "cat-file", "reflog",
            "rev-list", "name-rev", "whatchanged", "show-ref", "count-objects", "check-ignore", "diff-tree", "for-each-ref", "var", "version", "help"}
GIT_BUILD = {"add", "commit", "checkout", "switch", "restore", "stash", "merge", "rebase", "cherry-pick", "mv", "init", "worktree", "apply",
             "revert", "tag", "branch", "notes", "am", "format-patch"}
GIT_NET = {"fetch", "pull", "clone", "push", "ls-remote", "submodule", "remote"}
SECRETISH = re.compile(r"\$\{?[A-Za-z_]*(KEY|SECRET|TOKEN|PASS|CRED|AWS|ANTHROPIC|OPENAI|API|AUTH|SESSION)[A-Za-z_0-9]*", re.I)
REDIRECT_W = re.compile(r"(?<![<&>\d])(?:\d*|&)(>>?|>\|)\s*([^\s;|&<>()]+)")
REDIRECT_R = re.compile(r"(?<![<\d])<(?![<(])\s*([^\s;|&<>()]+)")
ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
DANGEROUS_ENV = re.compile(r"^(PATH|LD_[A-Z_]*|DYLD_[A-Z_]*|PYTHON[A-Z_]*|NODE_OPTIONS|BASH_ENV|ENV|PS4|IFS|SHELLOPTS|GIT_[A-Z_]*|HOME)=")
MODE = re.compile(r"^[0-7]{3,4}$|^[ugoa]*[+\-=][rwxXst]+(,[ugoa]*[+\-=][rwxXst]+)*$")


def _blank_quotes(s):
    out, q = [], None
    for c in s:
        if q:
            out.append(" "); q = None if c == q else q
        elif c in "'\"": q = c; out.append(" ")
        else: out.append(c)
    return "".join(out)


def _segments(cmd):
    """Split a command line at ; && || | & and newlines outside quotes. -> ([(segment, separator before it)], flags)."""
    segs, cur, q, sep, flags, i, n = [], [], None, "", set(), 0, len(cmd)
    def flush(nsep):
        nonlocal cur, sep
        t = "".join(cur).strip()
        if t: segs.append((t, sep))
        cur, sep = [], nsep
    while i < n:
        c = cmd[i]
        if q == "'":
            cur.append(c)
            if c == "'": q = None
        elif q == '"':
            if c == "\\" and i + 1 < n: cur.append(cmd[i:i + 2]); i += 2; continue
            if c == '"': q = None
            elif c == "`" or (c == "$" and cmd[i + 1:i + 2] == "("): flags.add("substitution")
            cur.append(c)
        else:
            if c == "\\" and i + 1 < n: cur.append(cmd[i:i + 2]); i += 2; continue
            if c in "'\"": q = c; cur.append(c)
            elif c == "`" or (c == "$" and cmd[i + 1:i + 2] == "(") or (c in "<>" and cmd[i + 1:i + 2] == "("): flags.add("substitution"); cur.append(c)
            elif cmd.startswith("&&", i) or cmd.startswith("||", i): flush(cmd[i:i + 2]); i += 2; continue
            elif c in ";|\n": flush(c)
            elif c == "&":
                if (cur and cur[-1].endswith(">")) or cmd[i + 1:i + 2] == ">": cur.append(c)
                else: flush("&")
            elif c == "<" and cmd[i + 1:i + 2] == "<": flags.add("heredoc"); cur.append(c)
            else: cur.append(c)
        i += 1
    if q: flags.add("unbalanced")
    flush("")
    return segs, flags


def _is_pathy(tok, cwd):
    if not tok or tok.startswith("-"): return False
    if "/" in tok or tok.startswith(("~", ".")): return True
    return bool(cwd) and os.path.exists(os.path.join(cwd, tok))


def classify(cmd, cwd=None):
    """What a command line asks for. -> {level: read|build|all, flags: set, reads: [token], writes: [token], programs: [name]}.
    Anything it cannot read with certainty is level 'all'."""
    out = {"level": "read", "flags": set(), "reads": [], "writes": [], "programs": []}
    def need(l):
        if LEVEL[l] > LEVEL[out["level"]]: out["level"] = l
    if not isinstance(cmd, str) or not cmd.strip(): need("all"); out["flags"].add("empty"); return out
    segs, flags = _segments(cmd)
    out["flags"] |= flags
    if flags & {"substitution", "unbalanced", "heredoc"}: need("all")
    if "substitution" in flags: out["flags"].add("code")
    cur = cwd
    if SECRETISH.search(cmd): out["flags"].add("secrets")
    if re.search(r"(^|[;&|\s])[^\s()]+\s*\(\)\s*\{", cmd): out["flags"].add("function_def"); need("all")
    for seg, sep in segs:
        raw = _blank_quotes(seg)
        for m in REDIRECT_W.finditer(raw): out["writes"].append(_unquote(seg, raw, m.start(2), m.end(2)))
        for m in REDIRECT_R.finditer(raw): out["reads"].append(_unquote(seg, raw, m.start(1), m.end(1)))
        try: toks = shlex.split(seg)
        except ValueError: need("all"); out["flags"].add("unbalanced"); continue
        toks = _drop_redirects(toks)
        i = 0
        while i < len(toks) and ASSIGN.match(toks[i]):
            if DANGEROUS_ENV.match(toks[i]): need("all")
            i += 1
        while i < len(toks):
            w = os.path.basename(toks[i])
            if w in ("sudo", "su", "doas"): out["flags"].add("privileged"); need("all"); i += 1
            elif w in WRAPPERS:
                if w == "env" and not any(ASSIGN.match(t) or not t.startswith("-") for t in toks[i + 1:]): break      # bare `env`: prints it
                i += 1
                while i < len(toks) and (ASSIGN.match(toks[i]) or toks[i].startswith("-")): i += 1
            elif w == "timeout" or w == "gtimeout": i += 2
            else: break
        if i >= len(toks): continue
        prog, args = os.path.basename(toks[i]), toks[i + 1:]
        out["programs"].append(prog)
        if sep == "|" and prog in INTERPRETERS | {"sh", "bash", "zsh"}: out["flags"].add("pipe_to_shell")
        if prog in ("cd", "pushd", "popd", "chdir"):
            tgt = next((a for a in args if not a.startswith("-")), "~" if prog != "popd" else None)
            if tgt is None or tgt == "-" or "$" in tgt or "`" in tgt: out["flags"].add("cd_dynamic"); need("all"); continue
            out["reads"].append(_rel(tgt, cur))
            if cur: cur = os.path.normpath(os.path.join(cur, os.path.expanduser(tgt)))
            need("read"); continue
        n_r, n_w = len(out["reads"]), len(out["writes"])
        _classify_one(prog, args, cur, out, need)
        if cur and cur != cwd:                        # after a `cd`, relative paths mean something else: say where
            out["reads"][n_r:] = [_rel(t, cur) for t in out["reads"][n_r:]]
            out["writes"][n_w:] = [_rel(t, cur) for t in out["writes"][n_w:]]
    out["flags"] = set(out["flags"])
    return out


def _rel(tok, cur):
    if not cur or not isinstance(tok, str) or os.path.isabs(tok) or tok.startswith("~") or "$" in tok: return tok
    return os.path.join(cur, tok)


def _unquote(seg, raw, a, b):
    t = seg[a:b]
    return t.strip("'\"")


def _drop_redirects(toks):
    out, skip = [], False
    for t in toks:
        if skip: skip = False; continue
        if re.fullmatch(r"(\d*|&)>>?|>\||<|<<<?", t): skip = True; continue
        if re.fullmatch(r"\d*>&\d*-?|\d*<&\d*-?", t): continue
        if re.match(r"^(\d*|&)>>?[^>&]", t) or re.match(r"^<[^<(]", t): continue
        out.append(t)
    return out


def _operands(args):
    return [a for a in args if not a.startswith("-")]


def _flagvals(args):
    """Path-like values given to a flag as --opt=value (or of=value): reads or writes depending on the program."""
    return [a.split("=", 1)[1] for a in args if "=" in a and ("/" in a.split("=", 1)[1] or a.split("=", 1)[1].startswith(("~", ".")))]


def _classify_one(prog, args, cwd, out, need):
    reads, writes, flags = out["reads"], out["writes"], out["flags"]
    ops = _operands(args)
    if prog in PRIVILEGED: flags.add("privileged"); need("all")
    if prog in SECRET_PROGS or (prog in ("export", "set") and not args): flags.add("secrets"); need("all")
    if prog in NETWORK_PROGS: flags.add("network"); need("all")
    if prog in DELETE_PROGS: flags.add("delete")
    if prog in INTERPRETERS and not (prog.startswith("python") and _python_build(args)):
        need("all"); flags.add("code"); writes += [a for a in ops if _is_pathy(a, cwd)]; return
    if prog.startswith("python") and _python_build(args):
        need("build"); writes += [a for a in ops if _is_pathy(a, cwd)]
        if "pip" in args and any(a in ("install", "uninstall") for a in args): flags.add("install"); flags.add("network")
        return
    if prog == "git": return _git(args, cwd, out, need)
    if prog in ("npm", "yarn", "pnpm", "bun"):
        sub = ops[0] if ops else ""
        if sub in ("test", "run", "build", "t", "run-script", "lint", "start") or not sub: need("build")
        elif sub in ("install", "i", "add", "ci", "update", "upgrade", "remove", "uninstall", "rm"): need("build"); flags.add("install"); flags.add("network")
        else: need("all")
        return
    if prog in ("pip", "pip3"):
        sub = ops[0] if ops else ""
        if sub in ("list", "show", "freeze", "check"): need("read")
        elif sub in ("install", "uninstall", "download"): need("build"); flags.add("install"); flags.add("network")
        else: need("all")
        return
    if prog == "cargo":
        sub = ops[0] if ops else ""
        if sub in ("build", "test", "check", "clippy", "fmt", "doc", "bench", "clean"): need("build")
        elif sub in ("install", "add", "update", "fetch"): need("build"); flags.add("install"); flags.add("network")
        else: need("all")
        return
    if prog == "go":
        sub = ops[0] if ops else ""
        if sub in ("build", "test", "vet", "fmt", "mod", "list", "version", "env"): need("build")
        elif sub in ("install", "get"): need("build"); flags.add("install"); flags.add("network")
        else: need("all")
        return
    if prog == "brew": need("all"); flags.add("install"); flags.add("network"); return
    if prog == "find":
        paths = []
        for a in args:
            if a.startswith(("-", "(", "!")): break
            paths.append(a)
        reads += paths or ["."]
        if any(a in ("-exec", "-execdir", "-ok", "-okdir") for a in args): need("all")
        if "-delete" in args: flags.add("delete"); need("build"); writes += paths or ["."]
        return
    if prog == "sed":
        script_given = any(a in ("-e", "-f", "--expression", "--file") or a.startswith("--expression=") or a.startswith("--file=") for a in args)
        files = ops if script_given else ops[1:]
        script = " ".join(ops[:1] if not script_given else [a for a in args if not a.startswith("-")])
        if re.search(r"(^|[;{}\s])[we]\b", script) and not re.fullmatch(r"[^we]*", script): need("all")
        if any(a == "-i" or a.startswith(("-i", "--in-place")) for a in args): need("build"); writes += files
        else: need("read"); reads += files
        return
    if prog in ("grep", "egrep", "fgrep", "rg"):
        pat_given = any(a in ("-e", "-f", "--regexp") or a.startswith("--regexp=") for a in args)
        files = ops if pat_given else ops[1:]
        reads += files; need("read"); return
    if prog == "cp":
        need("build")
        if ops: writes.append(ops[-1]); reads += ops[:-1]
        return
    if prog in ("mv", "ln", "install", "rsync"):
        need("build"); writes += ops; return
    if prog in ("chmod", "chown", "chgrp"):
        need("all"); writes += [a for a in ops[1:]] if ops and (prog != "chmod" or MODE.match(ops[0]) or True) else ops; return
    if prog in ("touch", "mkdir", "tee", "truncate", "rm", "rmdir", "unlink", "shred"):
        need("build"); writes += [a for a in ops if not (prog == "truncate" and a.isdigit())]; return
    if prog in READ_PROGS:
        need("read"); reads += [a for a in ops if _is_pathy(a, cwd)]; reads += _flagvals(args); return
    if prog in BUILD_PROGS:
        need("build"); writes += [a for a in ops if _is_pathy(a, cwd)]; writes += _flagvals(args)
        for opt in ("-o", "-C", "--directory"):
            if opt in args:
                j = args.index(opt)
                if j + 1 < len(args): writes.append(args[j + 1])
        return
    need("all"); flags.add("code"); writes += [a for a in ops if _is_pathy(a, cwd)]; writes += _flagvals(args)


def _python_build(args):
    return "-m" in args and args[args.index("-m") + 1:args.index("-m") + 2] and args[args.index("-m") + 1] in ("pytest", "unittest", "pip", "compileall", "black", "ruff", "mypy", "flake8")


def _git(args, cwd, out, need):
    flags, reads = out["flags"], out["reads"]
    i, ops = 0, list(args)
    while i < len(ops) and ops[i].startswith("-"):
        o = ops[i]
        if o == "-c" or o.startswith("--exec-path") or o.startswith("--config-env"): need("all"); return
        if o == "-C" and i + 1 < len(ops): reads.append(ops[i + 1]); i += 2; continue
        if o.startswith(("--git-dir=", "--work-tree=")): reads.append(o.split("=", 1)[1]); i += 1; continue
        i += 1
    if i >= len(ops): need("read"); return
    sub, rest = ops[i], ops[i + 1:]
    if sub.startswith("!"): need("all"); return
    if "--no-index" in rest: need("all"); return                   # reads any two files, whatever the project
    vals, skip = [], False
    for a in rest:
        if skip: skip = False; continue
        if a in ("-m", "--message", "-F", "--file", "-t", "--template", "--author", "--date"): skip = True; continue
        if a.startswith(("--message=", "--author=", "--date=", "--cleanup=")): continue
        if not a.startswith("-") and _is_pathy(a, cwd): vals.append(a)
    if sub in GIT_READ: need("read"); reads.extend(vals)
    elif sub == "config":
        if any(a in ("--get", "--get-all", "--list", "-l", "--get-regexp") for a in rest): need("read")
        else: need("all")
    elif sub in GIT_BUILD:
        need("build"); out["writes"].extend(vals)
        if sub == "branch" and any(a in ("-d", "-D", "--delete", "-m", "-M") for a in rest): flags.add("delete")
        if sub == "tag" and any(a in ("-d", "--delete") for a in rest): flags.add("delete")
        if sub == "worktree": need("build")
    elif sub in ("rm",): need("build"); flags.add("delete")
    elif sub == "clean": need("build"); flags.add("delete")
    elif sub == "reset":
        need("build")
        if "--hard" in rest or "--merge" in rest: flags.add("delete")
    elif sub in GIT_NET:
        need("build"); flags.add("network")
        if sub == "push": flags.add("git_push")
        if sub == "submodule": need("all")
    else: need("all")


# ---------------------------------------------------------------------------------------------------------- decisions

class Policy:
    """The rules around the grants: the folders nobody may touch, the home folder, and how keys and login files are recognised."""

    def __init__(self, never=None, home=None, sensitive=None):
        self.home = os.path.realpath(os.path.expanduser(home)) if home else os.path.realpath(os.path.expanduser("~"))
        self.never = [os.path.realpath(p) for p in (never if never is not None else self.default_never())]
        self.sensitive = sensitive if sensitive is not None else self._qq_sensitive

    @staticmethod
    def default_never():
        try:
            import qqcore as q
            return [os.path.join(q.ROOT, d) for d in ("config", "collab", "sessions", "memory", "knowledge", "backups", "bin", "web", "desktop", "tools")]
        except Exception: return []

    @staticmethod
    def _qq_sensitive(path):
        try:
            import qqcore as q
            return q.sensitive_read(path) or q.sensitive_write(path)
        except Exception: return None

    # -- one path
    def resolve(self, p, cwd):
        if not isinstance(p, str) or not p or "\x00" in p or len(p) > MAX_PATH: return None
        p = os.path.expanduser(p)
        if not os.path.isabs(p):
            if not cwd or not os.path.isabs(cwd): return None
            p = os.path.join(cwd, p)
        return os.path.realpath(p)

    def check_path(self, g, p, mode, cwd):
        """-> (ok, reason, layer, resolved). Variables, brace expansion and patterns that could reach elsewhere are refused; a pattern is
        expanded and every file it matches is checked on its real path (a link inside the project that leads outside does not pass)."""
        if isinstance(p, str):
            if "$" in p or "`" in p: return False, f"{p[:60]!r} uses a variable that cannot be checked", "policy", None
            if "{" in p or "}" in p: return False, f"{p[:60]!r} uses brace expansion, which cannot be checked", "policy", None
        r = self.resolve(self._glob_root(p), cwd)
        if r is None: return False, f"not a usable path: {str(p)[:80]!r}", "policy", None
        ok, why, layer = self._check_resolved(g, r, mode)
        if not ok: return False, why, layer, r
        if isinstance(p, str) and re.search(r"[*?\[]", p):
            if ".." in p.replace("\\", "/").split("/"): return False, f"{p[:60]!r} is a pattern with '..' in it, which cannot be checked", "policy", r
            pat = os.path.expanduser(p)
            pat = pat if os.path.isabs(pat) else os.path.join(cwd, pat)
            matches = list(itertools.islice(glob.iglob(pat, recursive=True), 2001))
            if len(matches) > 2000: return False, f"{p[:60]!r} matches too many files to check", "policy", r
            for m in matches:
                ok, why, layer = self._check_resolved(g, os.path.realpath(m), mode)
                if not ok: return False, why, layer, os.path.realpath(m)
        return True, "", "policy", r

    def _check_resolved(self, g, r, mode):
        for n in self.never:
            if under(r, n, fold=True): return False, f"{r} is part of Orbit itself and is never available in a shared project", "never"
        hit = self.sensitive(r)
        if hit: return False, f"{r} holds keys, login files or services ({hit}) and is never available in a shared project", "never"
        if r == self.home: return False, "the home folder itself is not available", "never"
        for d in g["deny_paths"]:
            if under(r, d, fold=True): return False, f"{r} is in a folder this grant excludes", "grant"
        allowed = g["write_paths"] if mode == "write" else g["read_paths"] + g["write_paths"]
        if not any(under(r, a) for a in allowed):
            return False, f"{r} is outside the folders this grant allows for {'editing' if mode == 'write' else 'reading'}", "grant"
        return True, "", "policy"

    @staticmethod
    def _glob_root(p):
        if isinstance(p, str) and re.search(r"[*?\[{]", p):
            head = re.split(r"[*?\[{]", p, maxsplit=1)[0]
            return head.rsplit(os.sep, 1)[0] or "." if os.sep in head else "."
        return p

    # -- one action
    def decide(self, g, action, base=None, now=None):
        """allow, deny or ask, with the reason, the layer that decided, and what the action touches. Never raises."""
        try:
            return self._decide(g, action, base, now)
        except Exception as e:                                           # fail closed
            return {"verdict": "deny", "reason": f"the policy could not read this action ({type(e).__name__})", "layer": "policy", "touches": [], "tool": str((action or {}).get("tool"))[:60]}

    def _decide(self, g, action, base, now):
        tool = action.get("tool"); args = action.get("args"); cwd = action.get("cwd")
        args = args if isinstance(args, dict) else {}
        d = {"verdict": "allow", "reason": "", "layer": "policy", "touches": [], "tool": tool if isinstance(tool, str) else "", "flags": []}
        def deny(reason, layer="policy"): d.update(verdict="deny", reason=reason, layer=layer); return d
        if not isinstance(tool, str) or not tool: return deny("no tool named")
        if g.get("expires_at") is not None and g["expires_at"] <= (now or time.time()): return deny("this grant has expired")
        if tool in NEVER_TOOLS: return deny(f"{tool} is not available in a shared project")
        asks = []
        if tool in ALWAYS_OK: cap = None
        else:
            cap = TOOL_CAP.get(tool)
            if cap is None: return deny(f"{tool} is not a tool shared projects know, so it is not allowed")
            if cap not in g["tools"]: return deny(f"{tool} needs the '{cap}' permission, which this grant does not include")
        if cap in ("read", "edit"):
            mode = "write" if cap == "edit" else "read"
            paths = [args[k] for k in PATH_KEYS if k in args]
            if isinstance(args.get("paths"), list): paths += args["paths"]
            if tool in REQUIRE_PATH and not paths: return deny("which file? no path was given")
            if not paths: paths = [cwd] if tool != "glob" else [args.get("pattern") or cwd]
            if tool == "glob" and isinstance(args.get("pattern"), str) and ("path" not in args): paths = [args["pattern"]]
            for p in paths:
                ok, why, layer, r = self.check_path(g, p, mode, cwd)
                if r: d["touches"].append(r)
                if not ok: return deny(why, layer)
        elif cap == "shell":
            r = self._shell(g, tool, args, cwd, d, deny, asks)
            if r is not None: return r
        elif cap == "network":
            sw = g["network"]
            if sw is False: return deny("this grant cannot use the network")
            if sw == "ask": asks.append("uses the network"); d["flags"].append("network")
        elif cap == "cluster":
            if tool in CLUSTER_CHANGES and not g["can_touch_cluster"]: return deny("this grant cannot change anything on the cluster")
        if base is not None:
            lvl, why = base(tool, args)
            if lvl == "block": return deny(why or "blocked by Orbit's own safety rules", "base")
            if lvl == "confirm": asks.append(why or "Orbit's own rules ask first")
        d["flags"] = sorted(set(d["flags"]))
        if asks: d.update(verdict="ask", reason="; ".join(asks))
        return d

    def _shell(self, g, tool, args, cwd, d, deny, asks):
        if g["shell"] == "none": return deny("this grant cannot run commands")
        if not isinstance(cwd, str) or not os.path.isabs(cwd): return deny("no working folder for this command")
        ok, why, layer, r = self.check_path(g, cwd, "read", cwd)
        if not ok: return deny("the working folder " + why, layer)
        if tool == "python":
            code = args.get("code")
            if not isinstance(code, str): return deny("no code given")
            if g["shell"] != "all": return deny("running Python code needs the full-shell permission")
            if g["run_code"] is False: return deny("this grant cannot run programs or scripts")
            if g["run_code"] == "ask": asks.append("runs Python code that cannot be checked")
            return None
        if tool == "stop_background": need = "build"; c = {"flags": set(), "reads": [], "writes": []}
        else:
            cmd = args.get("command")
            if not isinstance(cmd, str) or not cmd.strip(): return deny("no command given")
            if len(cmd) > MAX_COMMAND: return deny("that command is too long to check")
            c = classify(cmd, cwd); need = c["level"]
        if LEVEL[need] > LEVEL[g["shell"]]:
            return deny(f"this command needs '{need}' shell access; this grant has '{g['shell']}'")
        for f, why in (("privileged", "changes how this Mac runs (administrator, services, scripting, processes)"), ("secrets", "reads secrets or the environment"),
                       ("pipe_to_shell", "feeds text straight into a shell"),
                       ("function_def", "defines a shell function, which cannot be checked"),
                       ("cd_dynamic", "changes folder to a place that cannot be checked")):
            if f in c["flags"]: return deny(f"this command {why}, which is not allowed in a shared project")
        for tok in sorted(set(c["writes"])):
            if tok == "/dev/null": continue
            ok, why, layer, r = self.check_path(g, tok, "write", cwd)
            if r: d["touches"].append(r)
            if not ok: return deny(why, layer)
        for tok in sorted(set(c["reads"])):
            if tok == "/dev/null": continue
            ok, why, layer, r = self.check_path(g, tok, "read", cwd)
            if r: d["touches"].append(r)
            if not ok: return deny(why, layer)
        for flag, label in (("delete", "deletes"), ("git_push", "pushes to a remote"), ("install", "installs software"), ("network", "uses the network"),
                            ("code", "runs a program or script whose effects cannot be checked")):
            if flag in c["flags"]:
                sw = g["run_code" if flag == "code" else flag]
                if sw is False: return deny(f"this command {label}, which this grant does not allow")
                if sw == "ask": asks.append(f"this command {label}"); d["flags"].append("run_code" if flag == "code" else flag)
        return None
