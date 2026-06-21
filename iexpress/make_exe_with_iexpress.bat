@echo off
REM ===================================================================
REM  make_exe_with_iexpress.bat
REM
REM  Wraps build_windows.bat into a single double-clickable
REM  BuildModMigrator.exe using Windows' built-in IExpress tool.
REM
REM  HOW TO USE:
REM    1. Put this file, BuildModMigrator.sed, build_windows.bat and
REM       mod_migrator_gui.py all together in one folder.
REM    2. Double-click this file.
REM    3. BuildModMigrator.exe appears in the same folder.
REM
REM  WHAT THE RESULTING EXE DOES:
REM    When run, it unpacks build_windows.bat + mod_migrator_gui.py to a
REM    temp folder and runs the build, producing ModMigrator.exe (the
REM    actual GUI app). In other words this is an EXE that builds the
REM    app's EXE - handy if you specifically want a clickable builder
REM    rather than a .bat.
REM
REM  HEADS UP (please read):
REM    IExpress-wrapped batch files are a well-known trigger for
REM    antivirus false positives (SmartScreen / Defender may flag the
REM    output). This is inherent to how IExpress self-extractors work,
REM    not something this script is doing wrong. If you just want a
REM    clean EXE of the app itself, the GitHub Actions workflow or
REM    running build_windows.bat directly is the smoother path - those
REM    produce ModMigrator.exe via PyInstaller without the IExpress
REM    wrapper.
REM ===================================================================
setlocal

REM IExpress needs the source files next to the .sed. Confirm they exist.
if not exist build_windows.bat (
    echo Missing build_windows.bat in this folder.
    pause
    exit /b 1
)
if not exist mod_migrator_gui.py (
    echo Missing mod_migrator_gui.py in this folder.
    pause
    exit /b 1
)
if not exist BuildModMigrator.sed (
    echo Missing BuildModMigrator.sed in this folder.
    pause
    exit /b 1
)

echo Building BuildModMigrator.exe with IExpress...
echo.

REM /N = build now using the named SED file.
iexpress /N BuildModMigrator.sed

echo.
if exist BuildModMigrator.exe (
    echo =================================================================
    echo  Done! Created: BuildModMigrator.exe
    echo  Double-clicking it will build ModMigrator.exe (the GUI app).
    echo.
    echo  If Windows SmartScreen/Defender flags it, that's the known
    echo  IExpress false-positive issue - see the notes at the top of
    echo  this script for cleaner alternatives.
    echo =================================================================
) else (
    echo IExpress didn't produce BuildModMigrator.exe - scroll up for any
    echo error it printed. Make sure you're on Windows (IExpress is a
    echo built-in Windows tool and isn't available on macOS/Linux).
)

pause
