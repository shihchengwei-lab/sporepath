@echo off
cd /d "%~dp0"

set "TASK_NAME=Sporepath Queue Worker"

schtasks /Delete /TN "%TASK_NAME%" /F
if errorlevel 1 (
  echo Failed to remove %TASK_NAME%, or the task was not installed.
  exit /b 1
)

echo Removed %TASK_NAME%.
