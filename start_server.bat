@echo off
title ProductSpeaker AI Brain Server
echo ========================================================
echo       AI VOICE SMART SPEAKER - SERVER STARTING
echo ========================================================
echo.

:: Kill any old python server on port 8000 first
echo [*] Killing any old server on port 8000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1
timeout /t 2 /nobreak >nul

cd /d C:\ProductSpeaker

echo [*] Starting server on 0.0.0.0:8000 ...
echo [*] ESP32 connects to: http://192.168.31.15:8000
echo.

python -m uvicorn backend.main:app ^
    --host 0.0.0.0 ^
    --port 8000 ^
    --timeout-keep-alive 75 ^
    --timeout-graceful-shutdown 10 ^
    --log-level info

pause
