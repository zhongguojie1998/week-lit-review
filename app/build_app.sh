#!/bin/bash
# Build (and optionally install) LitReview.app — a double-clickable wrapper around
# run_app.sh, so the menu-bar app launches without typing `bash app/run_app.sh`.
#
# Usage:
#   bash app/build_app.sh            # build app/LitReview.app
#   bash app/build_app.sh --install  # build + copy to /Applications + Login Item
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${APP_DIR}/.." && pwd)"
BUNDLE="${APP_DIR}/LitReview.app"
CONTENTS="${BUNDLE}/Contents"
APP_NAME="LitReview"
BUNDLE_ID="com.zhongguojie.litreview-app"
INSTALL_DEST="/Applications/${APP_NAME}.app"
LAUNCH_AGENT="$HOME/Library/LaunchAgents/${BUNDLE_ID}.plist"

INSTALL=0
[[ "${1:-}" == "--install" ]] && INSTALL=1

# --- build the bundle -------------------------------------------------------
rm -rf "${BUNDLE}"
mkdir -p "${CONTENTS}/MacOS" "${CONTENTS}/Resources"

cat > "${CONTENTS}/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>${APP_NAME}</string>
    <key>CFBundleDisplayName</key>
    <string>Lit Review</string>
    <key>CFBundleIdentifier</key>
    <string>${BUNDLE_ID}</string>
    <key>CFBundleExecutable</key>
    <string>${APP_NAME}</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>LSUIElement</key>
    <true/>
</dict>
</plist>
PLIST

printf 'APPL????' > "${CONTENTS}/PkgInfo"

# Launcher: the bundle's main executable. Repo path baked in at build time.
cat > "${CONTENTS}/MacOS/${APP_NAME}" <<LAUNCHER
#!/bin/bash
exec /bin/bash "${REPO_ROOT}/app/run_app.sh"
LAUNCHER
chmod +x "${CONTENTS}/MacOS/${APP_NAME}"

plutil -lint "${CONTENTS}/Info.plist" >/dev/null
echo "Built ${BUNDLE}"

[[ ${INSTALL} -eq 0 ]] && { echo "Run with --install to copy to /Applications and add a Login Item."; exit 0; }

# --- install ----------------------------------------------------------------
echo "Installing to ${INSTALL_DEST}…"
rm -rf "${INSTALL_DEST}"
cp -R "${BUNDLE}" "${INSTALL_DEST}"

# Retire the old auto-start LaunchAgent so it doesn't double-launch the app.
if [[ -f "${LAUNCH_AGENT}" ]]; then
  launchctl unload "${LAUNCH_AGENT}" 2>/dev/null || true
  mv "${LAUNCH_AGENT}" "${LAUNCH_AGENT}.retired"
  echo "Retired old LaunchAgent → ${LAUNCH_AGENT}.retired"
fi

# Register a hidden Login Item (de-dupe first).
osascript <<OSA
tell application "System Events"
    if exists login item "${APP_NAME}" then delete login item "${APP_NAME}"
    make login item at end with properties {path:"${INSTALL_DEST}", hidden:true}
end tell
OSA
echo "Added Login Item: ${APP_NAME}"
echo "Done. Launch now with: open -a ${APP_NAME}"
