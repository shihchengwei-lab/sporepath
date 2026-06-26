@echo off
cd /d "%~dp0"
set PYTHONPATH=src
python -m sporepath --db real_memory.sqlite app
