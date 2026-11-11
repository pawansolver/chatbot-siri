@echo off
title ProductSpeaker + Diffy MCP Launcher
echo ========================================================
echo    AI VOICE SMART SPEAKER + DIFFY MCP - STARTING ALL
echo ========================================================
echo.

:: Kill any old listeners on ports 3001 (Diffy MCP) and 8000 (ProductSpeaker)
echo [*] Clearing old processes on ports 3001 and 8000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :3001 ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1
timeout /t 1 /nobreak >nul

:: 1. Start Diffy MCP Skills Server in its own window
echo [*] Starting Diffy MCP Skills Server on http://127.0.0.1:3001/mcp ...
start "Diffy MCP Backend (:3001)" cmd /k "cd /d C:\Users\pawan\Downloads\diffy-main\diffy-main && python main.py --http"

:: Wait up to 8 seconds for Diffy MCP /health
echo [*] Waiting for Diffy MCP server to become ready...
powershell -NoProfile -Command "for ($i=0; $i -lt 16; $i++) { try { $r = Invoke-RestMethod -Uri 'http://127.0.0.1:3001/health' -TimeoutSec 1; if ($r.status -eq 'ok') { Write-Host '[OK] Diffy MCP Server ready on port 3001.'; exit 0 } } catch {}; Start-Sleep -Milliseconds 500 }; Write-Host '[WARN] Diffy MCP still starting; ProductSpeaker will auto-connect shortly.'"

:: 2. Start ProductSpeaker AI Brain on port 8000
cd /d C:\ProductSpeaker
echo.
echo [*] Starting ProductSpeaker AI Brain on http://0.0.0.0:8000 ...
echo [*] ESP32 connects to: http://192.168.31.15:8000
echo [*] Mode: HYBRID (Diffy MCP + General Knowledge)
echo.

python -m uvicorn backend.main:app ^
    --host 0.0.0.0 ^
    --port 8000 ^
    --timeout-keep-alive 75 ^
    --timeout-graceful-shutdown 10 ^
    --log-level info

pause

