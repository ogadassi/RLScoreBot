@echo off
title RLScoreBot
cd /d "%~dp0"

:loop
echo.
echo ===============================
echo   Starting RLScoreBot...
echo ===============================
echo.

python RLScoreBot.py
set EXIT_CODE=%errorlevel%

if %EXIT_CODE%==0 (
    echo.
    echo Bot exited cleanly. Restarting in 3 seconds... (Close window to stop)
    timeout /t 3 /nobreak >nul
    goto loop
)

if %EXIT_CODE%==1 (
    echo.
    echo Bot crashed (exit code 1). Restarting in 5 seconds... (Close window to stop)
    timeout /t 5 /nobreak >nul
    goto loop
)

if %EXIT_CODE%==2 (
    exit
)

echo.
echo Bot stopped with exit code %EXIT_CODE%. Press any key to exit.
pause >nul
