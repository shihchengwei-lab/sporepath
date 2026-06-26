@echo off
setlocal
cd /d "%~dp0"

set "ARCRIFT_DIR=%~dp0..\ArcRift"
set "ARCRIFT_BACKEND=%ARCRIFT_DIR%\backend"
set "ARCRIFT_DB=%ARCRIFT_BACKEND%\ArcRift.db"

if not exist "%ARCRIFT_BACKEND%\dist\index.js" (
  echo ArcRift backend build not found: %ARCRIFT_BACKEND%\dist\index.js
  echo Run npm install and npm run build in ArcRift first.
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$existing = Get-NetTCPConnection -LocalPort 3001 -ErrorAction SilentlyContinue; " ^
  "if (-not $existing) { " ^
  "  $env:ARCRIFT_STORAGE_MODE='sqlite'; " ^
  "  $env:SQLITE_DB_PATH='%ARCRIFT_DB%'; " ^
  "  $env:OLLAMA_URL='http://localhost:11434'; " ^
  "  $env:PORT='3001'; " ^
  "  Start-Process -FilePath 'node' -ArgumentList 'dist/index.js' -WorkingDirectory '%ARCRIFT_BACKEND%' -WindowStyle Hidden; " ^
  "  Start-Sleep -Seconds 3; " ^
  "} "

echo ArcRift backend should be available at http://localhost:3001
echo ArcRift DB: %ARCRIFT_DB%
