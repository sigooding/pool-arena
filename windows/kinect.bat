@echo off
rem Optional: adds Kinect v2 support. Needs the Kinect for Windows SDK 2.0
rem installed first, from Microsoft.
setlocal
call "%~dp0_env.bat" || goto :stop
echo.
echo   Installing Kinect v2 support ...
echo.
%PY% -m pip install pykinect2 comtypes || goto :failed
echo.
echo   Done. Use it with:  start.bat --source kinect
echo   Or both cameras:    start.bat --source cam:0,kinect --depth-balls
echo.
pause
exit /b 0

:failed
echo.
echo   That did not work. The error is above. Kinect v2 also needs the
echo   "Kinect for Windows SDK 2.0" from Microsoft, installed separately.
echo.
:stop
pause
exit /b 1
