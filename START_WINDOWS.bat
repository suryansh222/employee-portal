@echo off
setlocal
cd /d "%~dp0"
title Colleague Workspace - Employee Portal
set "RUN_PORT=8000"
if defined PORTAL_PORT set "RUN_PORT=%PORTAL_PORT%"
if not "%~1"=="" set "RUN_PORT=%~1"
echo ============================================================
echo   COLLEAGUE WORKSPACE - NIGHT EDITION
echo   Employee accounts, attendance and document management
echo ============================================================
echo.

if exist ".venv\Scripts\python.exe" goto check_env
set "PY_CMD="
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
    if not errorlevel 1 set "PY_CMD=py -3"
)
if defined PY_CMD goto create_env
where python >nul 2>nul
if not errorlevel 1 (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
    if not errorlevel 1 set "PY_CMD=python"
)
if not defined PY_CMD (
    echo Python 3.10 or newer was not found.
    echo Install Python from https://www.python.org/downloads/windows/
    echo Enable the installer's PATH option, then run this file again.
    goto failed
)

:create_env
echo Creating this application's private Python environment...
%PY_CMD% -m venv .venv
if errorlevel 1 goto failed

:check_env
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if errorlevel 1 (
    echo The private Python environment is unavailable or too old.
    echo Stop the application. Rename ONLY the .venv folder to .venv_old.
    echo Do not rename or delete the data folder. Then run this file again.
    goto failed
)
".venv\Scripts\python.exe" -c "import importlib.metadata as m; assert m.version('fastapi') == '0.128.2'; assert m.version('uvicorn') == '0.48.0'; assert m.version('python-multipart') == '0.0.29'" >nul 2>nul
if not errorlevel 1 goto launch
echo Installing required packages. Internet is needed on first setup...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed

:launch
echo.
echo Starting http://127.0.0.1:%RUN_PORT%
echo Keep this window open. Press Ctrl+C here to stop the server.
echo On the first run, a ONE-TIME SETUP KEY will appear below.
echo Copy that key into the browser to create your administrator.
echo There are no pre-created accounts or default passwords.
echo.
".venv\Scripts\python.exe" server.py --port %RUN_PORT%
if errorlevel 1 goto failed
echo.
echo Server stopped. Your records remain in the data folder.
pause
exit /b 0

:failed
echo.
echo Setup or startup did not finish. Read the error above.
echo For a port conflict, open PowerShell in this folder and run:
echo   .\START_WINDOWS.bat 8001
echo Then open http://127.0.0.1:8001
echo See QUICK_START.md and README.md for help.
pause
exit /b 1
