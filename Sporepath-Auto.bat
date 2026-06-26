@echo off
cd /d "%~dp0"

start "Sporepath" powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0Run-Sporepath-Auto.ps1"
