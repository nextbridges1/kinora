@echo off
rem Uploads (pushes) the Kinora code to GitHub. A sign-in window may open the first time.
cd /d "%~dp0"
set GIT="C:\Program Files\Git\cmd\git.exe"
%GIT% add -A
%GIT% commit -q -m "Update Kinora" 2>nul
%GIT% push -u origin main
echo.
if errorlevel 1 (
  echo Upload FAILED. Read the message above, or send a screenshot to Claude.
) else (
  echo Upload finished. Render will pick up the changes automatically.
)
pause
