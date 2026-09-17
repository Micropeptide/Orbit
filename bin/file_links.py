"""Files a chat mentions: finding them, and doing things with them on this Mac.

Models name files in every style -- `/abs/path.png`, `~/x.csv`, `./out/fig.html`,
a bare `report.md`, `src/app.py:42`, `file:///...`, a markdown link, a line in a
shell block (`open figure.html`). A relative name means the folder the chat works
in (a Claude Code chat's folder, the project's folder, Orbit's workspace), so each
name is looked up there, the way the model meant it.

Opening follows the Mac's own choices (`open`), except that anything that would
run -- an app, a script, an installer -- is only shown in Finder. Previews in Orbit
are served from a per-folder capability link, in a sandbox, so a page a model wrote
can load its own images and scripts but can never reach Orbit's API.
"""
import mimetypes, os, re, secrets, shutil, subprocess, threading, time, urllib.parse

HOME = os.path.expanduser("~")

# files that could run when opened: shown in Finder instead
RUNNABLE = {".app", ".command", ".tool", ".terminal", ".scpt", ".applescript", ".workflow", ".pkg", ".mpkg",
            ".jar", ".webloc", ".inetloc", ".fileloc", ".action", ".prefpane", ".shortcut", ".dmg", ".sh",
            ".bash", ".zsh", ".scptd", ".osax", ".kext", ".mobileconfig"}

# never previewed or copied into a page, whatever a chat says
_SECRET_PARTS = (os.sep + ".ssh" + os.sep, os.sep + ".gnupg" + os.sep, os.sep + "Keychains" + os.sep,
                 os.sep + ".aws" + os.sep, os.sep + ".kube" + os.sep, os.sep + ".docker" + os.sep)
_SECRET_NAMES = re.compile(r"^(id_[a-z0-9_]+(\.pub)?|.*\.(pem|key|p12|pfx|keychain-db|kdbx)|\.env(\..*)?|"
                           r"secrets\.json|remote-token|credentials(\.json)?|\.netrc|\.pgpass|auth\.json|"
                           r"\.credentials\.json|token\.json)$", re.I)

CATEGORIES = {
    "image": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif", ".ico", ".avif", ".svg"},
    "pdf": {".pdf"},
    "html": {".html", ".htm", ".xhtml"},
    "markdown": {".md", ".markdown", ".mdx", ".rmd", ".qmd"},
    "table": {".csv", ".tsv", ".tab"},
    "sheet": {".xlsx", ".xls", ".xlsm", ".numbers", ".ods"},
    "doc": {".docx", ".doc", ".pages", ".rtf", ".odt", ".pptx", ".ppt", ".key", ".odp", ".epub"},
    "notebook": {".ipynb"},
    "data": {".json", ".jsonl", ".ndjson", ".yaml", ".yml", ".toml", ".xml", ".parquet", ".feather", ".h5", ".hdf5",
             ".npy", ".npz", ".pkl", ".rds", ".rdata", ".sqlite", ".db", ".bed", ".bam", ".sam", ".vcf", ".fa",
             ".fasta", ".fq", ".fastq", ".gff", ".gff3", ".gtf", ".bw", ".bigwig", ".pdb", ".cif", ".mmcif", ".nwk",
             ".newick", ".aln", ".sto", ".phy", ".log", ".ini", ".cfg", ".conf", ".env.example"},
    "audio": {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".aiff"},
    "video": {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"},
    "archive": {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".zst"},
    "code": {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".swift", ".m", ".mm", ".c", ".h", ".cc", ".cpp",
             ".hpp", ".rs", ".go", ".java", ".kt", ".rb", ".php", ".pl", ".r", ".jl", ".lua", ".sql", ".css",
             ".scss", ".less", ".vue", ".svelte", ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".tex", ".bib",
             ".sty", ".cls", ".f90", ".f", ".scala", ".hs", ".ex", ".exs", ".dart", ".cs", ".vb", ".smk", ".nf",
             ".wdl", ".cwl", ".dockerfile", ".makefile", ".cmake", ".gradle", ".proto", ".graphql", ".ipy"},
    "text": {".txt", ".text", ".rst", ".org", ".adoc", ".csv.txt", ".diff", ".patch", ".srt", ".vtt"},
}
EXT_CATEGORY = {e: c for c, es in CATEGORIES.items() for e in es}
_NAMED_TEXT = {"makefile", "dockerfile", "readme", "license", "snakefile", "gemfile", "procfile", "justfile",
               "claude.md", "agents.md", "orbit.md"}
KNOWN_EXTS = set(EXT_CATEGORY) | RUNNABLE

mimetypes.add_type("text/markdown", ".md")
mimetypes.add_type("application/json", ".ipynb")
mimetypes.add_type("text/tab-separated-values", ".tsv")
mimetypes.add_type("application/x-ndjson", ".jsonl")
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("image/avif", ".avif")
mimetypes.add_type("image/heic", ".heic")


def category(path, is_dir=False):
    if is_dir: return "folder"
    base = os.path.basename(path).lower()
    ext = os.path.splitext(base)[1]
    if ext in EXT_CATEGORY: return EXT_CATEGORY[ext]
    if ext in RUNNABLE: return "app"
    if base in _NAMED_TEXT: return "text"
    return "other"


def mime_for(path):
    cat = category(path)
    mt = mimetypes.guess_type(path)[0]
    if cat in ("code", "text", "markdown", "table", "notebook") or (cat == "data" and not mt):
        return "text/plain; charset=utf-8" if cat != "table" or not mt else mt + "; charset=utf-8"
    return mt or "application/octet-stream"


_LINE = re.compile(r"^(.*?)(?::(\d+)(?::(\d+))?|#L(\d+)(?:-L?\d+)?)$")


def clean(raw):
    """A name as a model wrote it -> (path text, line or None). Strips quotes,
    backticks, `file://`, angle brackets, trailing punctuation, `:12:3` and `#L12`."""
    s = str(raw or "").strip()
    prev = None
    while prev != s:                      # **`name`**, and the like
        prev = s
        s = s.strip("`'\"“”‘’<>*").rstrip(".,;:!?)]}")
    if s.startswith("file://"):
        s = urllib.parse.unquote(s[7:])
        if s.startswith("localhost/"): s = s[9:]
    line = None
    m = _LINE.match(s)
    if m and m.group(1) and (m.group(2) or m.group(4)):
        line = int(m.group(2) or m.group(4))
        s = m.group(1)
    return s, line


def looks_like_file(text):
    """Is this (a bare word in code or prose) a file name worth looking up?"""
    s, _ = clean(text)
    if not s or len(s) > 1024 or "\n" in s: return False
    if re.match(r"^[a-z][a-z0-9+.-]*://", s) and not s.startswith("file://"): return False   # a URL
    if s.startswith(("/", "~/", "./", "../")): return True
    base = os.path.basename(s.rstrip("/"))
    if " " in s and not re.search(r"\.[A-Za-z0-9]{1,6}$", s): return False
    ext = os.path.splitext(base)[1].lower()
    if ext in KNOWN_EXTS: return not re.fullmatch(r"\d+(\.\d+)+", base)          # not a version like 1.2.3
    return base.lower() in _NAMED_TEXT or ("/" in s and bool(re.fullmatch(r"[\w.@+-]+(/[\w.@ +-]+)+/?", s)))


def roots_for(cwd=None, add_dirs=(), project_dir=None, workspace=None):
    """The folders a chat's relative names mean, most likely first."""
    out = []
    for d in (cwd, *(add_dirs or ()), project_dir, workspace):
        if not d: continue
        d = os.path.abspath(os.path.expanduser(str(d)))
        if d not in out: out.append(d)
    return out


def _stat(path):
    try: return os.stat(path)
    except OSError: return None


def resolve(raw, roots, changed=()):
    """Where a name a chat used points, and what is there."""
    text, line = clean(raw)
    info = {"input": str(raw), "path": "", "exists": False, "line": line}
    if not text: return info
    exp = os.path.expanduser(text)
    cands = []
    if os.path.isabs(exp):
        cands.append(exp)
    else:
        rel = text[2:] if text.startswith("./") else text
        for r in roots: cands.append(os.path.join(r, rel))
        # a bare name the answer wrote or changed somewhere else
        base = os.path.basename(rel.rstrip("/"))
        for c in changed or ():
            if c and (c == rel or c.endswith(os.sep + rel) or os.path.basename(c) == base):
                cands.append(c)
    for c in cands:
        c = os.path.normpath(c)
        st = _stat(c)
        if st is None: continue
        return describe(c, st, info)
    info["path"] = os.path.normpath(cands[0]) if cands else text
    return info


def describe(path, st=None, info=None):
    st = st or _stat(path)
    info = dict(info or {})
    is_dir = bool(st) and os.path.isdir(path)
    info.update(path=path, exists=bool(st), name=os.path.basename(path.rstrip("/")) or path,
                dir=os.path.dirname(path.rstrip("/")), kind="folder" if is_dir else "file",
                category=category(path, is_dir), ext=os.path.splitext(path)[1].lower())
    if st:
        info.update(size=st.st_size, mtime=st.st_mtime,
                    runs=not is_dir and (info["ext"] in RUNNABLE or (os.access(path, os.X_OK) and not info["ext"])),
                    servable=servable(path) and not is_dir,
                    home=path.replace(HOME, "~", 1) if path.startswith(HOME + os.sep) else path)
    return info


def servable(path, max_bytes=200 * 1024 * 1024):
    """May Orbit show this file's contents in a page? Your own files, not secrets."""
    p = os.path.realpath(path)
    if not os.path.isfile(p): return False
    if any(part in p + os.sep for part in _SECRET_PARTS) or _SECRET_NAMES.match(os.path.basename(p)): return False
    if not (p.startswith(os.path.realpath(HOME) + os.sep) or p.startswith(("/tmp/", "/private/tmp/", "/private/var/folders/",
                                                                          "/var/folders/", "/Volumes/"))):
        return False
    try: return os.path.getsize(p) <= max_bytes
    except OSError: return False


# ---------------------------------------------------------------- previews
# A preview link opens one folder, read-only, for a while: /fs/<token>/<path in it>.
_GRANTS = {}
_GLOCK = threading.Lock()
GRANT_SECS = 12 * 3600


def grant(path):
    """A link a page can load this file from, along with the files beside it."""
    path = os.path.realpath(path)
    folder = os.path.dirname(path)
    now = time.time()
    with _GLOCK:
        for k in [k for k, g in _GRANTS.items() if g["until"] < now]: _GRANTS.pop(k, None)
        tok = next((k for k, g in _GRANTS.items() if g["dir"] == folder), None)
        if tok: _GRANTS[tok]["until"] = now + GRANT_SECS
        else:
            tok = secrets.token_urlsafe(18)
            _GRANTS[tok] = {"dir": folder, "until": now + GRANT_SECS}
    rel = os.path.relpath(path, folder)
    return f"/fs/{tok}/" + urllib.parse.quote(rel)


def granted_file(url_path):
    """The file a /fs/ link names, if its grant covers it; else None."""
    m = re.match(r"^/fs/([A-Za-z0-9_-]{16,64})/(.*)$", url_path or "")
    if not m: return None
    with _GLOCK:
        g = _GRANTS.get(m.group(1))
    if not g or g["until"] < time.time(): return None
    rel = urllib.parse.unquote(m.group(2)) or "index.html"
    p = os.path.realpath(os.path.join(g["dir"], rel))
    if not (p == g["dir"] or p.startswith(g["dir"] + os.sep)): return None
    if os.path.isdir(p): p = os.path.join(p, "index.html")
    return p if servable(p) else None


# the headers a previewed file is sent with: a page runs as a sandboxed stranger
def preview_headers(path):
    h = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
    if category(path) in ("html", "image") or path.lower().endswith((".svg", ".xml", ".xhtml")):
        h["Content-Security-Policy"] = "sandbox allow-scripts allow-popups allow-forms allow-modals allow-downloads"
    return h


# ---------------------------------------------------------------- acting on files
def _run(argv, timeout=15):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


APP_CANDIDATES = [
    # (name, bundle locations, categories it suits; "*" = any file)
    ("Preview", ["/System/Applications/Preview.app", "/Applications/Preview.app"], {"image", "pdf"}),
    ("Safari", ["/Applications/Safari.app"], {"html", "pdf", "image"}),
    ("Google Chrome", ["/Applications/Google Chrome.app"], {"html", "pdf", "image"}),
    ("Firefox", ["/Applications/Firefox.app"], {"html"}),
    ("Visual Studio Code", ["/Applications/Visual Studio Code.app"], {"*"}),
    ("Cursor", ["/Applications/Cursor.app"], {"*"}),
    ("Zed", ["/Applications/Zed.app"], {"*"}),
    ("Sublime Text", ["/Applications/Sublime Text.app"], {"*"}),
    ("BBEdit", ["/Applications/BBEdit.app"], {"*"}),
    ("Xcode", ["/Applications/Xcode.app"], {"code", "text", "data"}),
    ("TextEdit", ["/System/Applications/TextEdit.app", "/Applications/TextEdit.app"],
     {"text", "code", "markdown", "table", "data", "html", "notebook", "other"}),
    ("Microsoft Excel", ["/Applications/Microsoft Excel.app"], {"table", "sheet"}),
    ("Numbers", ["/Applications/Numbers.app"], {"table", "sheet"}),
    ("Microsoft Word", ["/Applications/Microsoft Word.app"], {"doc", "text", "markdown"}),
    ("Pages", ["/Applications/Pages.app"], {"doc", "text"}),
    ("Microsoft PowerPoint", ["/Applications/Microsoft PowerPoint.app"], {"doc"}),
    ("Keynote", ["/Applications/Keynote.app"], {"doc"}),
    ("Adobe Illustrator", [], {"image", "pdf"}),
    ("Affinity Designer 2", ["/Applications/Affinity Designer 2.app"], {"image", "pdf"}),
    ("Pixelmator Pro", ["/Applications/Pixelmator Pro.app"], {"image"}),
    ("Typora", ["/Applications/Typora.app"], {"markdown"}),
    ("Obsidian", ["/Applications/Obsidian.app"], {"markdown"}),
    ("RStudio", ["/Applications/RStudio.app"], {"code", "markdown", "table"}),
    ("Jupyter Notebook", [], {"notebook"}),
    ("QuickTime Player", ["/System/Applications/QuickTime Player.app", "/Applications/QuickTime Player.app"], {"audio", "video"}),
    ("IINA", ["/Applications/IINA.app"], {"audio", "video"}),
    ("VLC", ["/Applications/VLC.app"], {"audio", "video"}),
    ("PyMOL", ["/Applications/PyMOL.app"], {"data"}),
    ("ChimeraX", ["/Applications/ChimeraX.app"], {"data"}),
    ("Archive Utility", ["/System/Library/CoreServices/Applications/Archive Utility.app"], {"archive"}),
    ("Terminal", ["/System/Applications/Utilities/Terminal.app"], {"folder"}),
    ("iTerm", ["/Applications/iTerm.app"], {"folder"}),
]


def open_with_apps(path):
    info = describe(path)
    cat = info.get("category")
    out = []
    for name, locs, cats in APP_CANDIDATES:
        if cat == "folder" and "folder" not in cats and name not in ("Visual Studio Code", "Cursor", "Zed"): continue
        if "*" not in cats and cat not in cats: continue
        loc = next((l for l in locs if os.path.isdir(l)), None)
        if loc: out.append({"name": name, "app": loc})
    return out


def editor_cli():
    for c in ("code", "cursor", "zed"):
        p = shutil.which(c) or next((x for x in (f"/usr/local/bin/{c}", f"/opt/homebrew/bin/{c}") if os.path.exists(x)), None)
        if p: return p
    vs = "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"
    return vs if os.path.exists(vs) else None


def open_path(path, reveal=False, app=None, line=None):
    """Open on this Mac. Returns (ok, what happened)."""
    info = describe(path)
    if not info["exists"]: return False, "not found"
    runs = bool(info.get("runs"))
    if app:
        known = {a["app"] for a in open_with_apps(path)}
        if app not in known: return False, "not an app Orbit offers for this file"
        if runs and not reveal and not app.endswith(("Terminal.app", "iTerm.app")) and info["kind"] != "folder":
            pass                     # opening a script *in an editor* runs nothing
        r = _run(["open", "-a", app, path])
        return r.returncode == 0, "opened in " + os.path.basename(app)[:-4] if r.returncode == 0 else (r.stderr.strip() or "failed")
    if line and not reveal and info["kind"] == "file":
        ed = editor_cli()
        if ed:
            r = _run([ed, "-g", f"{path}:{line}"])
            if r.returncode == 0: return True, f"opened at line {line}"
    if reveal or runs:
        r = _run(["open", "-R", path])
        return r.returncode == 0, ("shown in Finder rather than run" if runs and not reveal else "shown in Finder")
    r = _run(["open", path])
    if r.returncode != 0 and info["kind"] == "file":
        # nothing is set to open this kind of file: show it instead of failing
        r = _run(["open", "-R", path])
        return r.returncode == 0, "no app opens this kind of file; shown in Finder"
    return r.returncode == 0, "opened"


def quick_look(path):
    if not os.path.exists(path): return False
    subprocess.Popen(["qlmanage", "-p", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    # bring the preview panel forward: qlmanage opens behind the browser
    threading.Timer(0.6, lambda: subprocess.run(["osascript", "-e", 'tell application "System Events" to set frontmost of '
                                                 'process "qlmanage" to true'], capture_output=True, timeout=5)).start()
    return True


def _as(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def copy_file(path):
    """Put the file itself on the clipboard, to paste into Finder, Mail, Slack…
    An image also goes as a picture, so it pastes into a document."""
    if not os.path.exists(path): return False, "not found"
    cat = category(path, os.path.isdir(path))
    if cat == "image" and path.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff")):
        cls = "PNGf" if path.lower().endswith(".png") else "JPEG" if path.lower().endswith((".jpg", ".jpeg")) else \
              "GIFf" if path.lower().endswith(".gif") else "TIFF"
        script = f"set the clipboard to (read (POSIX file {_as(path)}) as «class {cls}»)"
        r = _run(["osascript", "-e", script])
        if r.returncode == 0: return True, "image copied"
    r = _run(["osascript", "-e", f"set the clipboard to (POSIX file {_as(path)})"])
    return r.returncode == 0, ("file copied — paste it in Finder, Mail or a chat" if r.returncode == 0 else r.stderr.strip()[:200])


def copy_text(text):
    r = subprocess.run(["pbcopy"], input=str(text), text=True, capture_output=True, timeout=10)
    return r.returncode == 0


def run_in_terminal(command, cwd=None):
    """Open Terminal in the chat's folder and run a command you chose to run."""
    cmd = str(command or "").strip()
    if not cmd: return False, "no command"
    cd = f"cd {sh_quote(cwd)} && " if cwd and os.path.isdir(cwd) else ""
    script = f'tell application "Terminal"\nactivate\ndo script {_as(cd + cmd)}\nend tell'
    r = _run(["osascript", "-e", script], timeout=20)
    return r.returncode == 0, ("running in Terminal" if r.returncode == 0 else r.stderr.strip()[:200])


def open_terminal_at(folder):
    if not os.path.isdir(folder): folder = os.path.dirname(folder)
    r = _run(["open", "-a", "Terminal", folder])
    return r.returncode == 0


def sh_quote(s):
    import shlex
    return shlex.quote(str(s))


# ---------------------------------------------------------------- shell blocks
_OPEN_CMD = re.compile(r"^\s*(?:\$\s*)?(open|xdg-open|start|code|cursor|subl|zed|qlmanage\s+-p)\s+(?:-[a-zA-Z]\s+(?:\"[^\"]+\"|'[^']+'|\S+)\s+)*(.+?)\s*$")


def open_targets(block):
    """`open fig.html`, `code src/app.py` … in a shell block: the files it opens."""
    import shlex
    out = []
    for line in str(block or "").splitlines():
        m = _OPEN_CMD.match(line)
        if not m: continue
        try: words = shlex.split(m.group(2))
        except ValueError: words = m.group(2).split()
        for w in words:
            if w.startswith("-") or re.match(r"^[a-z]+://", w): continue
            out.append(w)
    return out[:8]


# ---------------------------------------------------------------- previews of other kinds
# Word and RTF documents become HTML (macOS textutil), spreadsheets tables, HEIC and
# TIFF pictures PNG (sips), a zip or tar its list of contents, and anything else Quick
# Look can draw (Keynote, Pages, Numbers, PowerPoint…) a picture of its first page.
def _cache_name(path, cache_dir, suffix):
    import hashlib
    st = os.stat(path)
    h = hashlib.sha1(f"{path}|{st.st_mtime}|{st.st_size}".encode()).hexdigest()[:20]
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, h + suffix)


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_PREVIEW_CSS = ("<style>body{font:14px -apple-system,Helvetica,sans-serif;margin:18px;color:#1c1b19;background:#fff}"
                "table{border-collapse:collapse;margin:0 0 20px}td,th{border:1px solid #ddd;padding:3px 7px;font-size:12.5px;"
                "white-space:nowrap}th{background:#f3f3f3;position:sticky;top:0}h3{font-size:14px;margin:18px 0 6px}"
                "pre{font:12px ui-monospace,Menlo,monospace}</style>")


def render_preview(path, cache_dir, max_rows=3000):
    """(kind, file) for showing this file in Orbit: kind is "html" or "image"; or
    (None, why) when there is no way to show it."""
    info = describe(path)
    if not info["exists"] or info["kind"] != "file": return None, "not a file"
    ext, cat = info["ext"], info["category"]
    try:
        if ext in (".docx", ".doc", ".rtf", ".rtfd", ".odt", ".wordml", ".webarchive"):
            out = _cache_name(path, cache_dir, ".html")
            if not os.path.exists(out):
                r = _run(["textutil", "-convert", "html", "-output", out, path], timeout=60)
                if r.returncode != 0 or not os.path.exists(out): raise RuntimeError(r.stderr.strip() or "textutil failed")
            return "html", out
        if ext in (".xlsx", ".xlsm"):
            try:
                import openpyxl
            except ImportError:
                openpyxl = None
            if openpyxl:
                out = _cache_name(path, cache_dir, ".html")
                if not os.path.exists(out):
                    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
                    parts = ["<!doctype html><meta charset=utf-8>", _PREVIEW_CSS]
                    for ws in wb.worksheets[:12]:
                        parts.append(f"<h3>{_esc(ws.title)}</h3><table>")
                        for i, row in enumerate(ws.iter_rows(values_only=True)):
                            if i >= max_rows:
                                parts.append(f"<tr><td colspan=99>… first {max_rows} rows</td></tr>"); break
                            tag = "th" if i == 0 else "td"
                            parts.append("<tr>" + "".join(f"<{tag}>{'' if v is None else _esc(v)}</{tag}>" for v in row) + "</tr>")
                        parts.append("</table>")
                    open(out, "w", encoding="utf-8").write("".join(parts))
                return "html", out
        if ext in (".heic", ".heif", ".tif", ".tiff", ".bmp", ".psd", ".dng", ".cr2", ".nef", ".arw"):
            out = _cache_name(path, cache_dir, ".png")
            if not os.path.exists(out):
                r = _run(["sips", "-s", "format", "png", "-Z", "2400", path, "--out", out], timeout=60)
                if r.returncode != 0: raise RuntimeError(r.stderr.strip() or "sips failed")
            return "image", out
        if cat == "archive" and ext in (".zip", ".tar", ".tgz", ".gz", ".bz2", ".xz"):
            out = _cache_name(path, cache_dir, ".html")
            if not os.path.exists(out):
                rows = []
                if ext == ".zip":
                    import zipfile
                    with zipfile.ZipFile(path) as z:
                        rows = [(i.filename, i.file_size) for i in z.infolist()[:5000]]
                else:
                    import tarfile
                    with tarfile.open(path) as t:
                        for m in t:
                            rows.append((m.name + ("/" if m.isdir() else ""), m.size))
                            if len(rows) >= 5000: break
                body = "".join(f"<tr><td>{_esc(n)}</td><td style='text-align:right'>{s:,}</td></tr>" for n, s in rows)
                open(out, "w", encoding="utf-8").write(f"<!doctype html><meta charset=utf-8>{_PREVIEW_CSS}<h3>{len(rows)} entries</h3>"
                                                       f"<table><tr><th>name</th><th>bytes</th></tr>{body}</table>")
            return "html", out
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
    else:
        err = None
    # anything else Quick Look can picture
    outdir = _cache_name(path, cache_dir, ".ql")
    os.makedirs(outdir, exist_ok=True)
    png = os.path.join(outdir, os.path.basename(path) + ".png")
    if not os.path.exists(png):
        _run(["qlmanage", "-t", "-s", "1600", "-o", outdir, path], timeout=60)
    if os.path.exists(png): return "image", png
    return None, err or "no preview for this kind of file"


def find_by_name(name, roots=(), limit=12):
    """A file a chat named at the wrong path: files with that name, in the chat's
    folders first, then anywhere in your home folder (Spotlight)."""
    base = os.path.basename(str(name or "").rstrip("/"))
    if not base or len(base) > 255: return []
    out = []
    for r in roots or ():
        for dp, dns, fns in os.walk(r):
            dns[:] = [d for d in dns if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".git")][:200]
            if base in fns or base in dns:
                out.append(os.path.join(dp, base))
                if len(out) >= limit: return out
            if dp.count(os.sep) - r.count(os.sep) > 6: dns[:] = []
    try:
        r = subprocess.run(["mdfind", "-onlyin", HOME, "-name", base], capture_output=True, text=True, timeout=15)
        for line in r.stdout.splitlines():
            if os.path.basename(line) == base and line not in out and "/Library/" not in line and "/." not in line:
                out.append(line)
                if len(out) >= limit: break
    except Exception:
        pass
    return out
