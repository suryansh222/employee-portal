@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run START_WINDOWS.bat once to create the Python environment.
    pause
    exit /b 1
)
echo Stop the running server before continuing.
".venv\Scripts\python.exe" manage.py reset-password
pause
