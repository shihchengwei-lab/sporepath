@echo off
cd /d "%~dp0"

set "TASK_NAME=Sporepath Queue Worker"
set "WORKER=%~dp0Run-Sporepath-Queue-Worker.bat"

schtasks /Create /TN "%TASK_NAME%" /TR "\"%WORKER%\"" /SC ONLOGON /RL LIMITED /F
if errorlevel 1 (
  echo Failed to install %TASK_NAME%.
  exit /b 1
)

echo Installed %TASK_NAME%.
echo It starts at Windows logon; the worker itself only digests during its off-peak window.
