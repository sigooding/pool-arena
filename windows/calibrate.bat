@echo off
rem Teaches it where the table is in the camera picture. Do this once after
rem the camera is mounted, and again if it ever moves.
setlocal
call "%~dp0_env.bat" || goto :stop

echo.
echo   Camera calibration.
echo.
echo   The accurate way is the four printed markers: print them from the
echo   scoreboard (Setup, then Camera, then "Print the markers"), tape them
echo   inside the cushions, and use "Calibrate from markers" there instead.
echo   They land under a millimetre; clicking corners by eye is nearer ten.
echo.
echo   This window does the clicking version.
echo.
%PY% -m poolarena calibrate %* || goto :failed
echo.
pause
exit /b 0

:failed
echo.
echo   It stopped with an error - the message is above.
echo   "cannot open camera" usually means another program has it open.
echo.
:stop
pause
exit /b 1
