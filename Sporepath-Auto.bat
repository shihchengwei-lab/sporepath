@echo off
cd /d "%~dp0"

call "%~dp0Start-ArcRift.bat"

set "PYTHONPATH=src"
set "ARCRIFT_DB=%~dp0..\ArcRift\backend\ArcRift.db"
set "SPOREPATH_DB=real_memory.sqlite"
set "SPOREPATH_VAULT=%USERPROFILE%\Documents\Sporepath Vault"
set "SPOREPATH_GRAPH=real_graph.html"

rem ArcRift saved web chats are queued by Run-Sporepath-Queue-Worker.bat.
rem Run-Sporepath-Watcher.bat remains available for manual immediate sync.
start "Sporepath Sources Watcher" /min "%~dp0Run-Sporepath-Sources-Watcher.bat"
start "Sporepath Queue Worker" /min "%~dp0Run-Sporepath-Queue-Worker.bat"

python -m sporepath --db "%SPOREPATH_DB%" app
