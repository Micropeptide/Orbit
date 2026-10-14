"""A chat working in a copy of its own: a git worktree on a branch of its own, so it can
change files freely while your checkout stays as it is -- and you can run two chats on
one repository without them treading on each other. When it is done you merge the branch
back, or throw the copy away. (OpenCode v2 calls these workspaces.)

The copy lives under Orbit's own folder (worktrees/<repo>/<name>), not beside your
repository, so nothing new appears in folders you look at. Only what is committed in
your checkout goes into the copy; uncommitted changes stay where they are.
"""
import os, re, subprocess, time


def _git(cwd, *args, timeout=60):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    p = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=timeout, env=env)
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()


def _ok(cwd, *args, timeout=60):
    rc, out, err = _git(cwd, *args, timeout=timeout)
    if rc != 0:
        raise RuntimeError(err or out or f"git {' '.join(args)} failed")
    return out


def slug(text, fallback="chat"):
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:40].strip("-")
    return s or fallback


def toplevel(folder):
    rc, out, _ = _git(folder, "rev-parse", "--show-toplevel")
    return out if rc == 0 and out else None


def create(folder, home, name, title=""):
    """A new worktree of the repository `folder` is in, on a new branch orbit/<name>, made
    from what that checkout has committed now. Returns what the chat keeps about it."""
    if not folder or not os.path.isdir(folder):
        raise RuntimeError("this chat has no folder on this Mac")
    top = toplevel(folder)
    if not top:
        raise RuntimeError(f"{folder} is not in a git repository")
    rc, base, _ = _git(top, "symbolic-ref", "--quiet", "--short", "HEAD")
    if rc != 0:
        raise RuntimeError("the repository is not on a branch (a detached HEAD) — check one out first")
    sha = _ok(top, "rev-parse", "HEAD")
    want = slug(name or title)
    branch, path, n = f"orbit/{want}", os.path.join(home, "worktrees", slug(os.path.basename(top), "repo"), want), 1
    # a name already taken, as a branch or a folder, gets a number
    while _git(top, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")[0] == 0 or os.path.exists(path):
        n += 1
        branch, path = f"orbit/{want}-{n}", os.path.join(os.path.dirname(path), f"{want}-{n}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _ok(top, "worktree", "add", "-b", branch, path, sha, timeout=300)
    # the part of the repository the chat was in, inside the copy
    rel = os.path.relpath(os.path.realpath(folder), os.path.realpath(top))
    inner = os.path.normpath(os.path.join(path, rel)) if rel != "." else path
    dirty = bool(_git(top, "status", "--porcelain", "--untracked-files=no")[1])
    return {"path": path, "cwd": inner if os.path.isdir(inner) else path, "branch": branch, "repo": top,
            "origin": folder, "base": base, "base_sha": sha, "created": time.time(),
            "left_behind": dirty}


def status(wt):
    """How the copy stands: commits on its branch the base has not got, and what is not
    committed yet."""
    path = wt.get("path") or ""
    if not os.path.isdir(path):
        return {"exists": False, **wt}
    _, ahead, _ = _git(path, "rev-list", "--count", f"{wt.get('base_sha')}..HEAD")
    _, behind, _ = _git(wt["repo"], "rev-list", "--count", f"{wt.get('branch')}..{wt.get('base')}")
    _, porcelain, _ = _git(path, "status", "--porcelain")
    files = [l[3:] for l in porcelain.splitlines() if l.strip()]
    _, log, _ = _git(path, "log", "--format=%h %s", f"{wt.get('base_sha')}..HEAD", "-n", "20")
    return {**wt, "exists": True, "ahead": int(ahead or 0), "behind": int(behind or 0),
            "dirty": len(files), "files": files[:50], "commits": log.splitlines()}


def commit_all(wt, message):
    path = wt["path"]
    if _git(path, "status", "--porcelain")[1]:
        _ok(path, "add", "-A")
        _ok(path, "commit", "-q", "-m", message)
        return True
    return False


def merge(wt, message):
    """Bring the copy's work into the branch it came from, in your checkout. Anything not
    committed in the copy is committed first. Your checkout must be on that branch with
    nothing uncommitted that the merge would touch; a merge that conflicts is undone and
    says where. The copy and its branch go once the merge is in."""
    st = status(wt)
    if not st.get("exists"):
        raise RuntimeError("the copy is gone (deleted outside Orbit?) — discard it instead")
    commit_all(wt, message)
    repo, base, branch = wt["repo"], wt["base"], wt["branch"]
    rc, cur, _ = _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD")
    if rc != 0 or cur != base:
        raise RuntimeError(f"your checkout is on {cur or 'a detached HEAD'}, not {base} — switch it back to merge")
    _, ahead, _ = _git(repo, "rev-list", "--count", f"{base}..{branch}")
    if int(ahead or 0) == 0:
        remove(wt)
        return {"merged": False, "why": "nothing to bring back — the copy had no changes"}
    rc, out, err = _git(repo, "merge", "--no-ff", "--no-edit", "-m", f"Merge {branch}: {message}", branch, timeout=300)
    if rc != 0:
        _, conflicts, _ = _git(repo, "diff", "--name-only", "--diff-filter=U")
        _git(repo, "merge", "--abort")
        if conflicts:
            raise RuntimeError("the merge conflicts in " + ", ".join(conflicts.splitlines()[:8])
                               + " — nothing was changed; resolve it in the copy (merge "
                               + base + " into it there) and try again")
        raise RuntimeError(err or out or "the merge failed; nothing was changed")
    remove(wt, force=True)                 # merged: what is left in it is ignored files
    return {"merged": True, "commits": int(ahead)}


def remove(wt, force=False):
    """Throw the copy away, and its branch with it."""
    repo, path, branch = wt.get("repo"), wt.get("path"), wt.get("branch")
    if repo and os.path.isdir(repo):
        if path and os.path.exists(path):
            args = ["worktree", "remove"] + (["--force"] if force else []) + [path]
            rc, out, err = _git(repo, *args, timeout=120)
            if rc != 0:
                raise RuntimeError(err or out or "could not remove the copy")
        _git(repo, "worktree", "prune")
        if branch:
            _git(repo, "branch", "-D" if force else "-d", branch)
    return True
