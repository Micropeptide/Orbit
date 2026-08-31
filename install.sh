#!/bin/sh
# Orbit installer. Safe to re-run: it never overwrites your data or settings.
set -e

ROOT=$(cd "$(dirname "$0")" && pwd)
PY=${ORBIT_PYTHON:-python3}
BIN_DIR=${ORBIT_BIN_DIR:-$HOME/bin}

say()  { printf '  %s\n' "$1"; }
step() { printf '\n\033[1m%s\033[0m\n' "$1"; }

step "Orbit — installing into $ROOT"

# ---------------------------------------------------------------- python
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "python3 not found. Install it (brew install python) and re-run." >&2; exit 1
fi
VER=$("$PY" -c 'import sys;print("%d.%d"%sys.version_info[:2])')
case "$VER" in
  3.1[0-9]|3.9) ;;
  *) echo "Python $VER found; Orbit needs 3.9 or newer." >&2; exit 1 ;;
esac
say "python $VER"

# ---------------------------------------------------------------- venv
step "Dependencies"
if [ ! -x "$ROOT/venv/bin/python" ]; then
  "$PY" -m venv "$ROOT/venv"
  say "created venv/"
fi
"$ROOT/venv/bin/python" -m pip install -q --upgrade pip
"$ROOT/venv/bin/python" -m pip install -q -r "$ROOT/requirements.txt"
say "installed $(grep -vc '^#' "$ROOT/requirements.txt" 2>/dev/null || echo several) packages"

# ---------------------------------------------------------------- folders
step "Your data lives here"
for d in config memory skills knowledge sessions workspace uploads trash logs backups; do
  mkdir -p "$ROOT/$d"
done
say "$ROOT/{config,memory,knowledge,sessions,workspace,…}"

# defaults are copied once; your edits are never overwritten
for f in settings agents projects schedule mcp; do
  if [ -f "$ROOT/config/$f.default.json" ] && [ ! -f "$ROOT/config/$f.json" ]; then
    cp "$ROOT/config/$f.default.json" "$ROOT/config/$f.json"
    say "config/$f.json (from defaults)"
  fi
done
[ -f "$ROOT/config/instructions.md" ] || cat > "$ROOT/config/instructions.md" <<'EOF'
Anything you write here is prepended to every conversation — the equivalent of a
standing brief. Say who you are, what you are working on, and how you want
answers written. Delete this text once you have replaced it.
EOF

# ---------------------------------------------------------------- commands
step "Commands"
mkdir -p "$BIN_DIR"
for c in orbit ob; do
  ln -sf "$ROOT/bin/$c" "$BIN_DIR/$c"
done
say "$BIN_DIR/orbit  and  $BIN_DIR/ob"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) say "note: $BIN_DIR is not on your PATH — add it to ~/.zshrc:"
     say "      export PATH=\"\$HOME/bin:\$PATH\"" ;;
esac

# ---------------------------------------------------------------- local model
step "Local model (optional)"
MTPLX="$HOME/Library/Application Support/MTPLX/runtime-venv/bin/mtplx"
MODELS="$HOME/.mtplx/models"
if [ -x "$MTPLX" ] && [ -d "$MODELS" ]; then
  FIRST=$(ls "$MODELS" 2>/dev/null | head -1)
  if [ -n "$FIRST" ] && [ ! -f "$ROOT/config/mtplx-launch.json" ]; then
    "$ROOT/venv/bin/python" - "$ROOT" "$MTPLX" "$MODELS/$FIRST" <<'EOF'
import json, sys
root, mtplx, model = sys.argv[1:4]
json.dump({"command": mtplx, "args": [
    "serve", "--host", "127.0.0.1", "--port", "8000", "--model", model,
    "--context-window", "32768", "--paged-kv-quantization", "q8",
    "--ssd-session-cache", "on", "--fan-mode", "smart", "--yes"]},
    open(root + "/config/mtplx-launch.json", "w"), indent=1)
EOF
    say "configured MTPLX with $FIRST"
  else
    say "MTPLX found; launch config already present"
  fi
else
  say "MTPLX not installed — that is fine."
  say "Orbit also runs on the CLIs you are signed into (claude, codex, …)"
  say "or any API key you add in Settings. Local model: see docs/models.md"
fi

# ---------------------------------------------------------------- done
step "Done"
say "orbit          chat in the terminal"
say "orbit --ui     open the web app on http://127.0.0.1:8899"
say "ob             same as orbit, fewer keystrokes"
printf '\nRun `orbit --ui` to start.\n\n'
