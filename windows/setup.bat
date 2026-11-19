@echo off
rem Run this once, before anything else.
setlocal
call "%~dp0_env.bat" || goto :stop

echo.
echo   Setting up Pool Arena. A few minutes, and about 60 MB downloaded.
echo.

rem Checked here rather than left to fail later: pip's message for "no
rem version of this package works on your Python" is long and does not say
rem the thing that would help, which is which Python to install.
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>nul
if errorlevel 1 (
  echo   The Python on this machine is too old. Checking which one...
  %PY% -c "import sys; print('   found Python ' + sys.version.split()[0])"
  echo.
  echo   Pool Arena needs 3.10 or newer. Install the current version from
  echo   https://www.python.org/downloads/ - tick "Add python.exe to PATH"
  echo   on the installer's first screen - then run this again.
  echo.
  goto :stop
)

rem Its own folder, so installing here cannot break anything else on the PC
rem and deleting .venv undoes all of it.
if not exist ".venv\Scripts\python.exe" (
  echo   Making a private Python environment in .venv ...
  %PY% -m venv .venv || goto :novenv
)
set "PY=.venv\Scripts\python.exe"

echo   Installing numpy and OpenCV ...
"%PY%" -m pip install --upgrade pip --quiet
"%PY%" -m pip install numpy "opencv-python>=4.8" || goto :failed

rem Installed is not the same as working: a half-finished download leaves a
rem package that imports and then falls over. Better to find out now than
rem with a table racked and people waiting.
echo   Checking they actually load ...
"%PY%" -c "import numpy, cv2; print('   numpy ' + numpy.__version__ + ', OpenCV ' + cv2.__version__)" || goto :broken

echo.
echo   Ready. What to run next:
echo.
echo     demo.bat        no camera needed - try the games and the projector
echo     calibrate.bat   teach it where your table is
echo     check.bat       is the camera good enough? run this before a game
echo     start.bat       the real thing
echo.
echo   Only if you are using them:
echo     kinect.bat      adds Kinect v2 support (needs Microsoft's
echo                     "Kinect for Windows SDK 2.0" installed first)
echo     yolo.bat        adds the YOLO ball detector (large download)
echo.
pause
exit /b 0

:novenv
echo.
echo   Could not make the .venv folder. The error is above.
echo   If this is a work PC, the usual cause is a policy blocking it.
echo.
goto :stop

:broken
echo.
echo   They installed but will not load. The error is above.
echo   Deleting the .venv folder and running this again fixes most of these.
echo.
goto :stop

:failed
echo.
echo   The download did not finish. The error is above.
echo   The usual causes are no internet, or a company network blocking pip.
echo.
:stop
pause
exit /b 1
