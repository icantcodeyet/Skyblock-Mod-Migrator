#!/bin/bash
# -----------------------------------------------------------------
#  Builds mod_migrator_gui.py into a standalone ModMigrator binary.
#  Run with:  bash build_linux.sh
#  Keep it in the same folder as mod_migrator_gui.py.
# -----------------------------------------------------------------
cd "$(dirname "$0")"
set -e

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 wasn't found. Install it with your distro's package manager"
    echo "(e.g. 'sudo apt install python3 python3-pip python3-tk') and try again."
    exit 1
fi

if [ ! -f mod_migrator_gui.py ]; then
    echo "Couldn't find mod_migrator_gui.py in this folder."
    echo "Make sure build_linux.sh sits right next to mod_migrator_gui.py."
    exit 1
fi

if ! python3 -c "import tkinter" >/dev/null 2>&1; then
    echo "Tkinter isn't installed for this Python. Install it first, e.g.:"
    echo "  Debian/Ubuntu:  sudo apt install python3-tk"
    echo "  Fedora:         sudo dnf install python3-tkinter"
    echo "  Arch:           sudo pacman -S tk"
    exit 1
fi

echo "Using $(python3 --version) to build the ModMigrator binary ..."
echo

python3 -m pip install --upgrade pyinstaller --break-system-packages 2>/dev/null \
    || python3 -m pip install --upgrade pyinstaller

python3 -m PyInstaller --onefile --windowed --name ModMigrator mod_migrator_gui.py

echo
if [ -f "dist/ModMigrator" ]; then
    chmod +x dist/ModMigrator
    echo "========================================================="
    echo " Success! Your program is at: dist/ModMigrator"
    echo " Run it with: ./dist/ModMigrator"
    echo
    echo " Note: this binary is tied to roughly the glibc version on"
    echo " this machine (forward-compatible only) - it'll run fine on"
    echo " equal-or-newer distro releases, but maybe not much older"
    echo " ones. For wide distribution, prefer the Linux build from"
    echo " the project's GitHub Actions workflow, which targets an"
    echo " older base for broader compatibility."
    echo "========================================================="
else
    echo "Something went wrong - scroll up to see the error from PyInstaller."
fi
