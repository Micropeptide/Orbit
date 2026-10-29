"""Who changed what: a quick snapshot of a project folder (path -> size and modification time), and the difference between two of them.

The turn engine takes one before and one after each model turn and writes the difference into the project's record, so "this file was created by
Qwen, asked by Mei" is true whatever made the change (a file tool, a shell command, a script). Version control folders and dependency folders are
left out, links are not followed, and a folder too large to walk is reported as such instead of being walked for ever.
"""
import os

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache", ".DS_Store", ".idea", ".orbit-attachments"}
MAX_FILES = 20_000


class Snapshot(dict):
    truncated = False


def snapshot(root, max_files=MAX_FILES):
    snap, stack = Snapshot(), [root]
    while stack:
        d = stack.pop()
        try: entries = list(os.scandir(d))
        except OSError: continue
        for e in entries:
            try:
                if e.is_symlink(): continue
                if e.is_dir(follow_symlinks=False):
                    if e.name not in SKIP_DIRS: stack.append(e.path)
                elif e.is_file(follow_symlinks=False):
                    if len(snap) >= max_files: snap.truncated = True; return snap
                    st = e.stat(follow_symlinks=False); snap[os.path.relpath(e.path, root)] = (st.st_size, st.st_mtime_ns)
            except OSError: continue
    return snap


def diff(before, after, limit=200):
    created = sorted(set(after) - set(before)); deleted = sorted(set(before) - set(after))
    modified = sorted(p for p in set(before) & set(after) if before[p] != after[p])
    more = max(0, len(created) - limit) + max(0, len(modified) - limit) + max(0, len(deleted) - limit)
    return {"created": created[:limit], "modified": modified[:limit], "deleted": deleted[:limit], "more": more,
            "truncated": bool(getattr(before, "truncated", False) or getattr(after, "truncated", False))}
