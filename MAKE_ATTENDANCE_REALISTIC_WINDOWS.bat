@echo off
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe MAKE_ATTENDANCE_REALISTIC.py
) else (
  python MAKE_ATTENDANCE_REALISTIC.py
)
pause
