@echo off
rem No camera, no table. Everything runs against a simulator.
setlocal
call "%~dp0_env.bat" || goto :stop

echo.
echo   Starting the demo. Two things to open:
echo.
echo     http://localhost:8777/                 the projector view
echo     http://localhost:8777/scoreboard.html  the tablet
echo.
echo   Close this window, or press Ctrl+C, to stop it.
echo.
%PY% -m poolarena demo %* || goto :failed
exit /b 0

:failed
echo.
echo   It stopped with an error - the message is above.
echo   If it says "No module named numpy", run setup.bat first.
echo.
:stop
pause
exit /b 1
