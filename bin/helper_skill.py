"""The Orbit helpers skill, packaged for agents that read skills (Claude Science, Claude Code, Codex, and any folder-of-skills agent).

The skill is a folder (docs/claude-science-skill/orbit-helpers: SKILL.md plus a few reference files) with no token and nothing personal in it: the connection is made
separately in Settings > Helpers. This module installs it into an agent's skills folder at the person's request, or zips it to hand to another agent.
"""
import os, re, shutil, zipfile

NAME = "orbit-helpers"
MARKER = ".installed-by-orbit"
SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "claude-science-skill", NAME)


class SkillError(Exception):
    pass


def source():
    src = os.path.realpath(SRC)
    if not os.path.isfile(os.path.join(src, "SKILL.md")): raise SkillError("the skill files are missing from this copy of Orbit")
    return src


def version():
    try: text = open(os.path.join(source(), "SKILL.md"), encoding="utf-8").read()
    except (OSError, SkillError): return ""
    m = re.search(r'^\s*version:\s*"?([\w.\-]+)"?\s*$', text, re.M)
    return m.group(1) if m else ""


def files():
    """The skill's files as relative paths (nothing hidden, nothing outside the folder)."""
    src, out = source(), []
    for root, dirs, names in os.walk(src):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for n in sorted(names):
            if n.startswith(".") or os.path.islink(os.path.join(root, n)): continue
            out.append(os.path.relpath(os.path.join(root, n), src))
    return out


def targets(csci_data_dir="", home=None):
    """Where an agent keeps its skills on this Mac, for the agents that are installed: [{id, name, dir, installed, version}]."""
    home = home or os.path.expanduser("~")
    cands = [("claude-science", "Claude Science", os.path.join(csci_data_dir, "skills") if csci_data_dir else ""),
             ("claude-code", "Claude Code", os.path.join(home, ".claude", "skills")), ("codex", "Codex", os.path.join(home, ".codex", "skills"))]
    out = []
    for tid, name, d in cands:
        if not d or not os.path.isdir(d): continue
        dest = os.path.join(d, NAME); mark = os.path.join(dest, MARKER)
        have = os.path.isdir(dest)
        theirs = ""
        if os.path.isfile(mark):
            try: theirs = open(mark).read().strip()
            except OSError: pass
        out.append({"id": tid, "name": name, "dir": d, "installed": have, "ours": have and os.path.isfile(mark), "version": theirs})
    return out


def install(target_dir):
    """Copy the skill into an agent's skills folder. Replaces an earlier copy that Orbit installed; refuses to touch a folder of the same name that Orbit did not make."""
    if not isinstance(target_dir, str) or not os.path.isdir(target_dir): raise SkillError("that agent's skills folder does not exist")
    src, dest = source(), os.path.join(target_dir, NAME)
    if os.path.islink(dest) or (os.path.exists(dest) and not os.path.isdir(dest)): raise SkillError(f"{dest} is not a plain folder; it was not touched")
    if os.path.exists(dest) and not os.path.isfile(os.path.join(dest, MARKER)):
        raise SkillError(f"a folder named {NAME} is already there and was not installed by Orbit; it was not touched")
    tmp = os.path.join(target_dir, f".{NAME}.new")
    shutil.rmtree(tmp, True)
    try:
        for rel in files():
            to = os.path.join(tmp, rel); os.makedirs(os.path.dirname(to), exist_ok=True); shutil.copyfile(os.path.join(src, rel), to)
        with open(os.path.join(tmp, MARKER), "w") as f: f.write(version() + "\n")
        if os.path.isdir(dest): shutil.rmtree(dest)
        os.rename(tmp, dest)
    except BaseException:
        shutil.rmtree(tmp, True); raise
    return {"path": dest, "version": version(), "files": len(files()) + 1}


def make_zip(out_dir):
    os.makedirs(out_dir, mode=0o700, exist_ok=True)
    out = os.path.join(out_dir, f"{NAME}-{version() or 'skill'}.zip"); tmp = out + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in files(): z.write(os.path.join(source(), rel), f"{NAME}/{rel}")
    os.replace(tmp, out)
    return {"path": out, "version": version(), "files": len(files())}
