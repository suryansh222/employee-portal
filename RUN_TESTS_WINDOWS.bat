@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run START_WINDOWS.bat once to create the Python environment.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements-test.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 goto failed
echo All tests passed. Test databases were isolated from your data.
pause
exit /b 0
:failed
echo Tests could not complete successfully. Read the error above.
pause
exit /b 1
