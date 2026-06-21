@echo off
REM ---------------------------------------------------------------
REM  Builds mod_migrator_gui.py into a standalone ModMigrator.exe
REM  Just double-click this file. Keep it in the same folder as
REM  mod_migrator_gui.py.
REM ---------------------------------------------------------------
setlocal

set PYCMD=
where py >nul 2>nul
if not errorlevel 1 set PYCMD=py
if "%PYCMD%"=="" (
    where python >nul 2>nul
    if not errorlevel 1 set PYCMD=python
)

if "%PYCMD%"=="" (
    echo.
    echo Python wasn't found on this PC.
    echo Install it from https://www.python.org/downloads/
    echo IMPORTANT: tick "Add python.exe to PATH" during setup.
    echo Then double-click this file again.
    echo.
    pause
    exit /b 1
)

if not exist mod_migrator_gui.py (
    echo.
    echo Couldn't find mod_migrator_gui.py in this folder.
    echo Make sure build_windows.bat sits right next to mod_migrator_gui.py.
    echo.
    pause
    exit /b 1
)

echo Using "%PYCMD%" to build ModMigrator.exe ...
echo.

%PYCMD% -m pip install --upgrade pyinstaller
if errorlevel 1 (
    echo.
    echo Failed to install PyInstaller. Check your internet connection and try again.
    pause
    exit /b 1
)

REM --windowed = no console window pops up behind the GUI
%PYCMD% -m PyInstaller --onefile --windowed --name ModMigrator mod_migrator_gui.py

echo.
if exist dist\ModMigrator.exe (
    echo =========================================================
    echo  Success! Your program is at: dist\ModMigrator.exe
    echo  You can move/copy that single file anywhere you like and
    echo  double-click it to run it - Python is no longer needed.
    echo.
    echo  Note: since this isn't signed by a paid code-signing
    echo  certificate, Windows SmartScreen may warn about an
    echo  "unrecognized app" the first time it's run. Click
    echo  "More info" -^> "Run anyway" if that happens.
    echo =========================================================
) else (
    echo Something went wrong - scroll up to see the error from PyInstaller.
)

pause
