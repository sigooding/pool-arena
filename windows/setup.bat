@echo off
rem Run this once, before anything else.
setlocal
call "%~dp0_env.bat" || goto :stop

echo.
echo   Setting up Pool Arena. This takes a few minutes the first time.
echo.

rem Its own folder, so installing here cannot break anything else on the PC
rem and deleting .venv undoes all of it.
if not exist ".venv\Scripts\python.exe" (
  echo   Making a private Python environment in .venv ...
  %PY% -m venv .venv || goto :failed
)
set "PY=.venv\Scripts\python.exe"

echo   Installing the things it needs ...
"%PY%" -m pip install --upgrade pip --quiet
"%PY%" -m pip install numpy "opencv-python>=4.8" || goto :failed

echo.
echo   Done. What to run next:
echo.
echo     demo.bat        no camera needed - try the games and the projector
echo     calibrate.bat   teach it where your table is
echo     check.bat       is the camera good enough? run this before a game
echo     start.bat       the real thing
echo.
echo   Optional, only if you are using them:
echo     kinect.bat      adds Kinect v2 support
echo     yolo.bat        adds the YOLO ball detector
echo.
pause
exit /b 0

:failed
echo.
echo   That did not work. The error is above.
echo   The usual cause is no internet, or a company network blocking pip.
echo.
:stop
pause
exit /b 1
