@echo off
setlocal
cd /d "%~dp0"

call "%~dp0Start-ArcRift.bat"

set "ARCRIFT_DIR=%~dp0..\ArcRift"
for %%I in ("%ARCRIFT_DIR%\extension\dist\chrome") do set "ARCRIFT_EXTENSION=%%~fI"
set "ARCRIFT_PROFILE=%LOCALAPPDATA%\Sporepath\ArcRift Chrome Profile"
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

mkdir "%ARCRIFT_PROFILE%" >nul 2>&1

start "ArcRift Chrome" "%CHROME_EXE%" ^
  --user-data-dir="%ARCRIFT_PROFILE%" ^
  --load-extension="%ARCRIFT_EXTENSION%" ^
  --no-first-run ^
  --disable-default-apps ^
  https://chatgpt.com/
