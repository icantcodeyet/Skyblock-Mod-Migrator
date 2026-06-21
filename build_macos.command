#!/bin/bash
# -----------------------------------------------------------------
#  Builds mod_migrator_gui.py into a standalone ModMigrator.app
#  Double-click this file in Finder (it will open in Terminal).
#  Keep it in the same folder as mod_migrator_gui.py.
# -----------------------------------------------------------------
cd "$(dirname "$0")"
set -e

if ! command -v python3 >/dev/null 2>&1; then
    echo
    echo "python3 wasn't found on this Mac."
    echo "Install it from https://www.python.org/downloads/ then run this again."
    echo
    read -p "Press Enter to close..."
    exit 1
fi

if [ ! -f mod_migrator_gui.py ]; then
    echo
    echo "Couldn't find mod_migrator_gui.py in this folder."
    echo "Make sure build_macos.command sits right next to mod_migrator_gui.py."
    echo
    read -p "Press Enter to close..."
    exit 1
fi

echo "Using $(python3 --version) to build ModMigrator.app ..."
echo

python3 -m pip install --upgrade pyinstaller --break-system-packages 2>/dev/null \
    || python3 -m pip install --upgrade pyinstaller

# --windowed produces a proper .app bundle instead of a bare terminal binary
python3 -m PyInstaller --onefile --windowed --name ModMigrator mod_migrator_gui.py

echo
if [ -d "dist/ModMigrator.app" ]; then
    echo "========================================================="
    echo " Success! Your app is at: dist/ModMigrator.app"
    echo " You can move it to /Applications or anywhere you like."
    echo
    echo " Note: since this isn't signed with a paid Apple Developer"
    echo " certificate, Gatekeeper will likely block it the first"
    echo " time with 'cannot be opened because the developer cannot"
    echo " be verified'. To run it anyway: right-click (or"
    echo " Control-click) the app -> Open -> Open, just once."
    echo "========================================================="
else
    echo "Something went wrong - scroll up to see the error from PyInstaller."
fi

read -p "Press Enter to close..."
