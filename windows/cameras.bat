@echo off
rem Which cameras can this machine see? Run this first when the wrong one
rem opens, or the right one will not.
setlocal
call "%~dp0_env.bat" || goto :stop
%PY% -m poolarena cameras %*
echo.
pause
exit /b 0

:stop
pause
exit /b 1
