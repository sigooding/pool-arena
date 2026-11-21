@echo off
rem The real thing: live camera, real table.
setlocal
call "%~dp0_env.bat" || goto :stop

echo.
echo   Starting Pool Arena.
echo.
echo     http://localhost:8777/                 the projector view
echo     http://localhost:8777/scoreboard.html  the tablet
echo.
echo   Close this window, or press Ctrl+C, to stop it.
echo.

rem Anything typed after the script name is passed straight through, so
rem start.bat --source kinect works without editing anything.
%PY% -m poolarena run %* || goto :failed
exit /b 0

:failed
echo.
echo   It stopped with an error - the message is above.
echo.
echo   "no calibration"          run calibrate.bat first
echo   "no camera at index N"    run cameras.bat to see what is
echo                             actually there
echo   "No module named numpy"   run setup.bat first
echo.
:stop
pause
exit /b 1
