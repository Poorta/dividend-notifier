#!/bin/bash
# Build a local macOS .app and .dmg installer.
#
# Run from the repository root:
#   bash packaging/build_mac.sh

set -euo pipefail

cd "$(dirname "$0")/.."

ROOT_DIR="$(pwd)"
APP_NAME="Dividend Notifier"
DIST_DIR="$ROOT_DIR/packaging/dist"
TMP_ROOT="$(mktemp -d /tmp/dividend-notifier-build-XXXXXX)"
RELEASE_STAGE="$TMP_ROOT/release-stage"
DMG_STAGE="$TMP_ROOT/dmg-stage"
trap 'rm -rf "$TMP_ROOT"' EXIT

export PIP_CACHE_DIR="$(pwd)/.cache-build/pip"
export PYINSTALLER_CONFIG_DIR="$(pwd)/.cache-build/pyinstaller"
mkdir -p "$PIP_CACHE_DIR" "$PYINSTALLER_CONFIG_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found"
  exit 1
fi

if [ ! -d ".venv-build" ]; then
  python3 -m venv .venv-build
fi

PYTHON="$(pwd)/.venv-build/bin/python"
"$PYTHON" -m pip install --disable-pip-version-check -r requirements.txt pyinstaller

cd packaging
"$PYTHON" -m PyInstaller --clean --noconfirm DividendNotifier.spec

rm -rf "$RELEASE_STAGE" "$DMG_STAGE"
mkdir -p "$RELEASE_STAGE" "$DMG_STAGE"

# Copy the app out of Desktop/iCloud-managed folders before signing/archiving.
# Those folders can attach FinderInfo xattrs that break ad-hoc signing.
ditto --norsrc "dist/$APP_NAME.app" "$RELEASE_STAGE/$APP_NAME.app"
xattr -cr "$RELEASE_STAGE/$APP_NAME.app" 2>/dev/null || true
codesign --force --deep --sign - "$RELEASE_STAGE/$APP_NAME.app" >/dev/null 2>&1 || true

rm -f "$DIST_DIR/DividendNotifier-mac-arm64.zip"
(
  cd "$RELEASE_STAGE"
  ditto -c -k --norsrc --keepParent "$APP_NAME.app" "$DIST_DIR/DividendNotifier-mac-arm64.zip"
)

ditto --norsrc "$RELEASE_STAGE/$APP_NAME.app" "$DMG_STAGE/$APP_NAME.app"
ln -s /Applications "$DMG_STAGE/Applications"
xattr -cr "$DMG_STAGE" 2>/dev/null || true
rm -f "$DIST_DIR/DividendNotifier-mac-arm64.dmg"
if hdiutil create \
  -volname "$APP_NAME" \
  -srcfolder "$DMG_STAGE" \
  -ov \
  -format UDZO \
  "$DIST_DIR/DividendNotifier-mac-arm64.dmg"; then
  DMG_STATUS="created"
else
  DMG_STATUS="not created (hdiutil failed in this environment)"
fi

echo ""
echo "Build finished:"
echo "  packaging/dist/$APP_NAME.app"
echo "  packaging/dist/DividendNotifier-mac-arm64.dmg - $DMG_STATUS"
echo "  packaging/dist/DividendNotifier-mac-arm64.zip"
