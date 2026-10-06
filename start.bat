@echo off
rem Starts Kinora on http://127.0.0.1:8000 (only reachable from this computer).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First run: setting up Python packages...
  python -m venv .venv || goto :fail
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail
)
echo.
echo Kinora is starting. Open http://127.0.0.1:8000 in your browser.
echo Press Ctrl+C in this window to stop it.
echo.
".venv\Scripts\python.exe" -m uvicorn server.main:app --host 127.0.0.1 --port 8000
goto :eof
:fail
echo Setup failed. See README.md, section "Troubleshooting".
pause
