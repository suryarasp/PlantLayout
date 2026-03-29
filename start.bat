@echo off
title EPC Structural Design Software
echo ============================================
echo  EPC Structural Design Software
echo  Pipe Rack Analyzer  ^|  AISC 360 + ACI 318
echo ============================================
cd /d "%~dp0"

REM ── Check if already running on port 5000 ──────────────────────
netstat -ano | findstr ":5000 " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo.
    echo  Server is already running on port 5000.
    echo  Opening browser...
    timeout /t 1 /nobreak >nul
    start "" "http://localhost:5000"
    echo.
    echo  Browser opened. Close this window to leave server running.
    pause
    exit /b 0
)

REM ── Check dependencies (import test — no network needed if installed) ──
echo.
echo  Checking dependencies...
py -c "import flask, flask_cors, numpy, pandas" >nul 2>&1
if %errorlevel%==0 (
    echo  Dependencies OK.
) else (
    echo  Some packages missing. Installing...
    py -m pip install flask flask-cors numpy pandas reportlab openpyxl --no-warn-script-location
    if %errorlevel% neq 0 (
        echo  ERROR: pip install failed.
        echo  Make sure Python 3.9+ is installed and in PATH.
        pause
        exit /b 1
    )
    echo  Dependencies installed.
)

REM ── Start Flask server in background ───────────────────────────
echo.
echo  Starting server on http://localhost:5000 ...
start "EPC-Server" /min py app.py

REM ── Wait for server to become ready (poll up to 15 seconds) ────
set /a tries=0
:WAIT_LOOP
set /a tries+=1
if %tries% gtr 15 (
    echo  WARNING: Server did not respond after 15 seconds.
    echo  Try opening http://localhost:5000 manually.
    pause
    exit /b 1
)
timeout /t 1 /nobreak >nul
REM Use PowerShell to test TCP connection (no curl dependency needed)
py -c "import socket; s=socket.socket(); s.settimeout(0.5); r=s.connect_ex(('127.0.0.1',5000)); s.close(); exit(r)" >nul 2>&1
if %errorlevel% neq 0 goto WAIT_LOOP

REM ── Open browser ───────────────────────────────────────────────
echo  Server ready. Opening browser...
start "" "http://localhost:5000"
echo.
echo  ============================================
echo   EPC Software running at http://localhost:5000
echo   Close the "EPC-Server" window to stop.
echo  ============================================
echo.
pause
