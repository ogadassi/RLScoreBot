@echo off
title RLScoreBot Launcher
cd /d "%~dp0"

:: Start the bot in a separate, visible command window
echo Starting RLScoreBot...
start "RLScoreBot" start_bot.bat

:: Launch Rocket League with Steam parameters
echo Launching Rocket League...
%*
