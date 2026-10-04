@echo off
setlocal enabledelayedexpansion
title CreatorAI Launcher

:: Navigate to project root directory
cd /d "%~dp0"

echo ========================================================
echo               GenZCreators / CreatorAI
echo              Application Startup Script
echo ========================================================
echo.

:: 1. Check Python
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python was not found in PATH.
    echo Please install Python 3.11+ and ensure "Add Python to PATH" is checked.
    echo.
    pause
    exit /b 1
)

:: 2. Check Virtual Environment
set "ACTIVATE_CMD="
if exist "%~dp0backend\.venv\Scripts\activate.bat" (
    echo [INFO] Detected virtual environment in backend\.venv
    set "ACTIVATE_CMD=call "%~dp0backend\.venv\Scripts\activate.bat" ^&^&"
) else if exist "%~dp0.venv\Scripts\activate.bat" (
    echo [INFO] Detected virtual environment in .venv
    set "ACTIVATE_CMD=call "%~dp0.venv\Scripts\activate.bat" ^&^&"
)

:: 3. Check Node/npm
set "NPM_AVAILABLE=1"
where npm >nul 2>nul
if %ERRORLEVEL% neq 0 (
    set "NPM_AVAILABLE=0"
)

echo Select launch option:
echo   [1] Start Full Stack (Backend + Frontend Web App) -- Default
echo   [2] Start Backend and Master Suite Only (Port 8000)
echo   [3] Start Frontend Web App Only (Port 3000)
echo   [4] Run Backend Test Suite (pytest)
echo   [5] Exit
echo.

:: Default to option 1 after 5 seconds if no key is pressed
choice /c 12345 /d 1 /t 5 /m "Select option (1-5)"
set "CHOICE_VAL=%ERRORLEVEL%"

if "%CHOICE_VAL%"=="1" goto start_all
if "%CHOICE_VAL%"=="2" goto start_backend
if "%CHOICE_VAL%"=="3" goto start_frontend
if "%CHOICE_VAL%"=="4" goto run_tests
if "%CHOICE_VAL%"=="5" goto exit_script

:start_all
echo.
echo ========================================================
echo Starting Backend (FastAPI on http://127.0.0.1:8000)...
echo ========================================================
if defined ACTIVATE_CMD (
    start "CreatorAI - Backend (Port 8000)" cmd /k "cd /d "%~dp0backend" && %ACTIVATE_CMD% python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"
) else (
    start "CreatorAI - Backend (Port 8000)" cmd /k "cd /d "%~dp0backend" && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"
)

if "%NPM_AVAILABLE%"=="1" (
    echo Starting Frontend (Vite on http://localhost:3000)...
    start "CreatorAI - Frontend (Port 3000)" cmd /k "cd /d "%~dp0apps\web" && npm run dev"
) else (
    echo [WARNING] npm was not found. Skipping frontend startup.
)

:: Wait 2 seconds and open browser
timeout /t 2 /nobreak >nul
echo.
echo Opening browser...
start http://127.0.0.1:8000/demo
if "%NPM_AVAILABLE%"=="1" (
    start http://localhost:3000/
)

goto show_summary

:start_backend
echo.
echo ========================================================
echo Starting Backend (FastAPI on http://127.0.0.1:8000)...
echo ========================================================
if defined ACTIVATE_CMD (
    start "CreatorAI - Backend (Port 8000)" cmd /k "cd /d "%~dp0backend" && %ACTIVATE_CMD% python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"
) else (
    start "CreatorAI - Backend (Port 8000)" cmd /k "cd /d "%~dp0backend" && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"
)

timeout /t 2 /nobreak >nul
echo Opening backend demo in browser...
start http://127.0.0.1:8000/demo

goto show_summary

:start_frontend
echo.
if "%NPM_AVAILABLE%"=="0" (
    echo [ERROR] Node.js and npm are required to run the frontend.
    pause
    exit /b 1
)
echo ========================================================
echo Starting Frontend (Vite on http://localhost:3000)...
echo ========================================================
start "CreatorAI - Frontend (Port 3000)" cmd /k "cd /d "%~dp0apps\web" && npm run dev"

timeout /t 2 /nobreak >nul
echo Opening frontend in browser...
start http://localhost:3000/

goto show_summary

:run_tests
echo.
echo ========================================================
echo Running pytest test suite...
echo ========================================================
cd /d "%~dp0backend"
if defined ACTIVATE_CMD (
    %ACTIVATE_CMD% python -m pytest
) else (
    python -m pytest
)
echo.
pause
exit /b 0

:show_summary
echo.
echo ========================================================
echo             Services launched successfully!
echo ========================================================
echo - Backend Demo Suite : http://127.0.0.1:8000/demo
echo - API Documentation   : http://127.0.0.1:8000/api/docs
echo - API Health Check    : http://127.0.0.1:8000/api/health
if "%NPM_AVAILABLE%"=="1" (
echo - Frontend Web App    : http://localhost:3000/
)
echo.
echo Tip: Close the opened terminal windows to stop the servers.
echo ========================================================
echo.
pause
exit /b 0

:exit_script
echo Exiting.
exit /b 0
