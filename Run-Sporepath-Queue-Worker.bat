@echo off
cd /d "%~dp0"

set "PYTHONPATH=src"
set "SPOREPATH_DB=real_memory.sqlite"
set "SPOREPATH_VAULT=%USERPROFILE%\Documents\Sporepath Vault"
set "SPOREPATH_GRAPH=real_graph.html"
set "SPOREPATH_QUEUE_MODEL=qwen3:1.7b"
set "SPOREPATH_QUEUE_OFF_PEAK=00:00-07:00"
set "SPOREPATH_QUEUE_BATCH=5"
set "SPOREPATH_QUEUE_INTERVAL=300"
set "SPOREPATH_QUEUE_MIN_CHARS=80"
set "SPOREPATH_QUEUE_DEDUPE_THRESHOLD=0.92"
set "SPOREPATH_OLLAMA_TIMEOUT=120"
set "SPOREPATH_OLLAMA_NUM_PREDICT=260"

where ollama >nul 2>nul
if errorlevel 1 (
  echo Ollama was not found on PATH. Queue worker will not start.
  exit /b 2
)

ollama show "%SPOREPATH_QUEUE_MODEL%" >nul 2>nul
if errorlevel 1 (
  echo Model %SPOREPATH_QUEUE_MODEL% was not found.
  echo Install it first: ollama pull %SPOREPATH_QUEUE_MODEL%
  exit /b 2
)

python -m sporepath --db "%SPOREPATH_DB%" queue-worker ^
  --source all ^
  --min-chars "%SPOREPATH_QUEUE_MIN_CHARS%" ^
  --dedupe-threshold "%SPOREPATH_QUEUE_DEDUPE_THRESHOLD%" ^
  --off-peak "%SPOREPATH_QUEUE_OFF_PEAK%" ^
  --batch-size "%SPOREPATH_QUEUE_BATCH%" ^
  --interval-s "%SPOREPATH_QUEUE_INTERVAL%" ^
  --vault "%SPOREPATH_VAULT%" ^
  --graph "%SPOREPATH_GRAPH%" ^
  --extractor ollama ^
  --model "%SPOREPATH_QUEUE_MODEL%" ^
  --ollama-timeout-s "%SPOREPATH_OLLAMA_TIMEOUT%" ^
  --ollama-num-predict "%SPOREPATH_OLLAMA_NUM_PREDICT%"
