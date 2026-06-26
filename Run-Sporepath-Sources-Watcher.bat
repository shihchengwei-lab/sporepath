@echo off
cd /d "%~dp0"

set "PYTHONPATH=src"
set "SPOREPATH_DB=real_memory.sqlite"
set "SPOREPATH_VAULT=%USERPROFILE%\Documents\Sporepath Vault"
set "SPOREPATH_GRAPH=real_graph.html"

python -m sporepath --db "%SPOREPATH_DB%" watch-sources --source all --vault "%SPOREPATH_VAULT%" --graph "%SPOREPATH_GRAPH%" --interval-s 20
