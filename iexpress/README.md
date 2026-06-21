# Wrapping the builder into an .exe with IExpress

This folder uses **IExpress**, a tool built into every copy of Windows, to
turn `build_windows.bat` into a single double-clickable
`BuildModMigrator.exe`.

> **Is this the EXE of the app?** Not quite — read this first.
>
> There are two different "exe" ideas in this project:
> 1. **`ModMigrator.exe`** — the actual GUI application. You get this from
>    the GitHub Actions workflow, or by running `build_windows.bat` /
>    `build_macos.command` / `build_linux.sh`. **This is the one most
>    people want.**
> 2. **`BuildModMigrator.exe`** (what this folder makes) — a clickable
>    wrapper around the *builder* `.bat`. Running it unpacks the build
>    script and runs it, which then produces `ModMigrator.exe`. This
>    exists specifically because you asked for the `.bat` itself to become
>    an `.exe` via IExpress.

## How to build it

1. Make sure these four files are together in this folder:
   `make_exe_with_iexpress.bat`, `BuildModMigrator.sed`,
   `build_windows.bat`, and `mod_migrator_gui.py` (the latter two are
   copied here for you).
2. Double-click **`make_exe_with_iexpress.bat`**.
3. `BuildModMigrator.exe` appears in this folder.

Or do it by hand: press <kbd>Win</kbd>+<kbd>R</kbd>, type `iexpress`, and
walk through the wizard — choosing "Create new Self Extraction Directive
file" → "Extract files and run an installation command" → add
`build_windows.bat` and `mod_migrator_gui.py` → set the install command to
`cmd /c build_windows.bat`. The `.sed` here just automates exactly that.

## Two important caveats

**1. IExpress can't launch a `.bat` directly.** If you set the install
command to just `build_windows.bat`, IExpress fails at runtime with
`Error creating process Command.com /c ...`. That's why the directive uses
`cmd /c build_windows.bat` instead — this is the correct, working form.

**2. Antivirus false positives.** Self-extracting packages that run batch
files are a classic trigger for Windows SmartScreen and Defender (and
several engines on VirusTotal), because malware authors abuse the same
IExpress mechanism. The output here is harmless, but the flag is common and
outside our control.

If a clean, unflagged executable of the actual app matters to you, prefer
the **PyInstaller** route — the GitHub Actions workflow or the
`build_windows.bat` script — which produces `ModMigrator.exe` directly
without an IExpress wrapper. That's why those remain the recommended paths
in the main README, with IExpress offered here as the specifically-requested
alternative.
