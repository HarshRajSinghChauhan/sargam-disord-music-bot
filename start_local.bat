@echo off
title Sargam Discord Music Bot (Local Mode)
cls
echo ========================================================
echo        Sargam Discord Bot - Local Mode
echo   Running directly on your Laptop (Home Wi-Fi)
echo   - 0 Proxies used (Unlimited, Free, Direct Connection)
echo   - Cloud (Render) bot will automatically enter Standby
echo ========================================================
echo.

:: Mark this node as the local laptop
set BOT_NODE=laptop

:: Ensure local ffmpeg is in PATH
set PATH=%~dp0;C:\Users\harsh\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin;%PATH%

:: Clear YTDL_PROXY so local machine uses direct home internet (no proxy blocks/limits)
set YTDL_PROXY=

:: Check virtual environment
if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe bot.py
) else (
    python bot.py
)

echo.
echo ========================================================
echo   Local bot stopped. Cloud (Render) bot will resume!
echo ========================================================
pause
