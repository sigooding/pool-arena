@echo off
rem Pre-flight. Read-only: it starts no game and changes nothing, so it is
rem safe to run at any point, including twice to compare two cameras.
setlocal
call "%~dp0_env.bat" || goto :stop

echo.
echo   Rack up first - all the balls on the table, nobody leaning over it.
echo   This reads the table for a few seconds and reports what it found.
echo.
pause

%PY% -m poolarena doctor %*
echo.
pause
exit /b 0

:stop
pause
exit /b 1
