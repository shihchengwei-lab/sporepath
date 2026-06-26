@echo off
setlocal
cd /d "%~dp0"

call "%~dp0Start-ArcRift.bat"

set "ARCRIFT_DIR=%~dp0..\ArcRift"
for %%I in ("%ARCRIFT_DIR%\extension\dist\chrome") do set "ARCRIFT_EXTENSION=%%~fI"
set "CHROME_USER_DATA=%LOCALAPPDATA%\Google\Chrome\User Data"
set "CHROME_PROFILE=Default"
set "CHROME_EXE="

if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined CHROME_EXE if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not defined CHROME_EXE (
  echo Google Chrome was not found.
  exit /b 1
)

if not exist "%ARCRIFT_EXTENSION%\manifest.json" (
  echo ArcRift extension build not found: %ARCRIFT_EXTENSION%
  echo Run npm install and npm run build in ArcRift\extension first.
  exit /b 1
)

if not exist "%CHROME_USER_DATA%\Local State" (
  echo Chrome user data was not found: %CHROME_USER_DATA%
  exit /b 1
)

echo Closing Chrome so the ArcRift extension can load into the logged-in profile...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$windows = Get-Process chrome -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 }; foreach ($window in $windows) { [void]$window.CloseMainWindow() }; Start-Sleep -Seconds 8; Get-Process chrome -ErrorAction SilentlyContinue | Stop-Process -Force"

start "ArcRift Logged-In Chrome" "%CHROME_EXE%" ^
  --user-data-dir="%CHROME_USER_DATA%" ^
  --profile-directory="%CHROME_PROFILE%" ^
  --load-extension="%ARCRIFT_EXTENSION%" ^
  --no-first-run ^
  --disable-default-apps ^
  https://chatgpt.com/ ^
  https://claude.ai/
