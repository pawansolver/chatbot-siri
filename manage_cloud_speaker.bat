@echo off
title Aether Smart Speaker - AWS Cloud Manager
color 0b
:MENU
cls
echo ================================================================
echo       AETHER AI SMART SPEAKER - CLOUD MANAGEMENT CONSOLE
echo                   Server IP: 15.135.138.107
echo ================================================================
echo.
echo  [1] Check Status of All 3 Containers (Speaker, Diffy, WebUI)
echo  [2] View LIVE Real-time Speaker Voice Logs (Speech & Answers)
echo  [3] View Diffy MCP Skills Server Logs
echo  [4] View Open WebUI (fluAi) Logs
echo  [5] Restart ProductSpeaker Container
echo  [6] Open Web Dashboards in Browser
echo  [7] Test Cloud Health via curl
echo  [8] Exit
echo.
echo ================================================================
set /p opt="Enter your choice (1-8): "

if "%opt%"=="1" goto STATUS
if "%opt%"=="2" goto LOGS_SPEAKER
if "%opt%"=="3" goto LOGS_DIFFY
if "%opt%"=="4" goto LOGS_WEBUI
if "%opt%"=="5" goto RESTART_SPEAKER
if "%opt%"=="6" goto OPEN_WEB
if "%opt%"=="7" goto TEST_CURL
if "%opt%"=="8" exit
goto MENU

:STATUS
cls
echo [*] Checking container status on AWS...
ssh -i "%USERPROFILE%\Downloads\my-server-key.pem" -o StrictHostKeyChecking=no ubuntu@15.135.138.107 "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"
echo.
pause
goto MENU

:LOGS_SPEAKER
cls
echo [*] Streaming ProductSpeaker live logs (Press Ctrl+C to stop)...
echo.
ssh -i "%USERPROFILE%\Downloads\my-server-key.pem" -o StrictHostKeyChecking=no ubuntu@15.135.138.107 "docker logs -f --tail 40 product-speaker"
pause
goto MENU

:LOGS_DIFFY
cls
echo [*] Streaming Diffy MCP logs (Press Ctrl+C to stop)...
echo.
ssh -i "%USERPROFILE%\Downloads\my-server-key.pem" -o StrictHostKeyChecking=no ubuntu@15.135.138.107 "docker logs -f --tail 40 diffy-mcp"
pause
goto MENU

:LOGS_WEBUI
cls
echo [*] Streaming Open WebUI logs (Press Ctrl+C to stop)...
echo.
ssh -i "%USERPROFILE%\Downloads\my-server-key.pem" -o StrictHostKeyChecking=no ubuntu@15.135.138.107 "docker logs -f --tail 40 open-webui"
pause
goto MENU

:RESTART_SPEAKER
cls
echo [*] Restarting ProductSpeaker container on AWS...
ssh -i "%USERPROFILE%\Downloads\my-server-key.pem" -o StrictHostKeyChecking=no ubuntu@15.135.138.107 "docker restart product-speaker"
echo [OK] ProductSpeaker restarted successfully!
pause
goto MENU

:OPEN_WEB
cls
echo [*] Opening dashboards in your default browser...
start http://15.135.138.107:8000
start http://15.135.138.107:8080
start http://15.135.138.107:7860/health
pause
goto MENU

:TEST_CURL
cls
echo [*] Pinging ProductSpeaker Health endpoint...
curl -s http://15.135.138.107:8000/health/ready
echo.
echo.
pause
goto MENU
