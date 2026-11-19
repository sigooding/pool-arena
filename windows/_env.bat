@echo off
rem Shared by every other script here: finds a Python and points PY at it.
rem Not meant to be run on its own.

rem Everything runs from the repo root, whatever folder the shortcut was
rem launched from. Without this, double-clicking from the desktop starts in
rem C:\Windows\System32 and nothing is found.
cd /d "%~dp0.."

rem A virtual environment made by setup.bat wins, so the system Python is
rem never what gets used by accident.
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if defined PY goto :found

rem The py launcher is the one thing reliably on PATH on Windows. Plain
rem `python` on a machine without it opens the Microsoft Store instead of
rem reporting an error, which is a confusing way to fail, so it is tried
rem second.
where py >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto :found

where python >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto :found

echo.
echo   No Python found.
echo.
echo   Install it from https://www.python.org/downloads/ and tick
echo   "Add python.exe to PATH" on the first screen of the installer.
echo   Then run setup.bat in this folder.
echo.
exit /b 1

:found
exit /b 0
