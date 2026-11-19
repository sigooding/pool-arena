@echo off
rem Optional: adds the YOLO ball detector, which finds balls by shape rather
rem than colour and copes better with a tight rack and poor light. It is a
rem large download.
setlocal
call "%~dp0_env.bat" || goto :stop
echo.
echo   Installing YOLO support. This is a big download (about 2 GB).
echo.
%PY% -m pip install ultralytics || goto :failed
echo.
echo   Done. Add a model from the scoreboard: Setup, then Detector.
echo.
echo   A .pt model file is a pickled Python object and loading one RUNS CODE
echo   from that file. Only use a model from somewhere you actually trust.
echo.
pause
exit /b 0

:failed
echo.
echo   That did not work. The error is above.
echo.
:stop
pause
exit /b 1
