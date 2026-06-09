#!/bin/bash
# Launch the Lit-Review menu-bar app.
#
# IMPORTANT: macOS menu-bar (PyObjC/rumps) apps need a *framework* Python build,
# or no icon appears and the process just blocks. uv's bundled python and conda's
# base python are NOT framework builds, so we build a venv from a framework Python
# (Homebrew or the system python3) and run from it.
set -euo pipefail
# Include ~/.local/bin (claude CLI) on PATH; review_runner further augments the
# child env with node's location.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

APP_DIR="/Users/guojiezhong/Desktop.personal/Claude/week-lit-review/app"
VENV="$APP_DIR/.venv"
cd "$APP_DIR"

# Pick the first interpreter that is a framework build.
FW_PY=""
for c in /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3 /usr/bin/python3; do
  if [ -x "$c" ] && "$c" -c "import sysconfig,sys; sys.exit(0 if sysconfig.get_config_var('PYTHONFRAMEWORK') else 1)" 2>/dev/null; then
    FW_PY="$c"; break
  fi
done
if [ -z "$FW_PY" ]; then
  echo "No framework Python found (needed for the menu-bar GUI)." >&2
  exit 1
fi

# Build venv + deps on first run (fast on subsequent runs).
if [ ! -x "$VENV/bin/python" ]; then
  echo "First run: creating venv from $FW_PY and installing rumps + pywebview…"
  "$FW_PY" -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip
  # rumps/pywebview: GUI. playwright: bioRxiv PDF via Chrome (Cloudflare bypass).
  # requests/feedparser/pyyaml: so the skill's fetch_papers.py runs under this venv.
  "$VENV/bin/pip" install -q rumps pywebview playwright requests feedparser pyyaml
fi

exec "$VENV/bin/python" menubar_app.py
