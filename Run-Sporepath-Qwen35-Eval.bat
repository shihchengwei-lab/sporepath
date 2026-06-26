@echo off
cd /d "%~dp0"

set "PYTHONPATH=src"
set "SPOREPATH_EVAL_MODEL=qwen3.5:4b"
set "SPOREPATH_EVAL_OUT=eval\qwen35_4b_eval.jsonl"
set "SPOREPATH_EVAL_REPORT=eval\qwen35_4b_eval.md"
set "SPOREPATH_EVAL_CLEAN_OUT=eval\qwen35_4b_eval.clean.jsonl"
set "SPOREPATH_EVAL_CLEAN_REPORT=eval\qwen35_4b_eval.clean.md"
set "SPOREPATH_EVAL_LIMIT=50"
set "SPOREPATH_EVAL_PER_FILE_LIMIT=1"
set "SPOREPATH_EVAL_CHECKPOINT_EVERY=1"
set "SPOREPATH_EVAL_DEDUPE_THRESHOLD=0.92"
set "SPOREPATH_EVAL_MIN_CHARS=80"
set "SPOREPATH_EVAL_MAX_CHARS=1400"
set "SPOREPATH_OLLAMA_TIMEOUT=180"
set "SPOREPATH_OLLAMA_NUM_PREDICT=320"

where ollama >nul 2>nul
if errorlevel 1 (
  echo Ollama was not found on PATH. Eval will not start.
  exit /b 2
)

ollama list | findstr /C:"%SPOREPATH_EVAL_MODEL%" >nul
if errorlevel 1 (
  echo Model %SPOREPATH_EVAL_MODEL% was not found.
  echo Install it first: ollama pull %SPOREPATH_EVAL_MODEL%
  exit /b 2
)

python -m sporepath eval-extract ^
  --source all ^
  --limit "%SPOREPATH_EVAL_LIMIT%" ^
  --per-file-limit "%SPOREPATH_EVAL_PER_FILE_LIMIT%" ^
  --checkpoint-every "%SPOREPATH_EVAL_CHECKPOINT_EVERY%" ^
  --dedupe-threshold "%SPOREPATH_EVAL_DEDUPE_THRESHOLD%" ^
  --min-chars "%SPOREPATH_EVAL_MIN_CHARS%" ^
  --max-chars "%SPOREPATH_EVAL_MAX_CHARS%" ^
  --extractor ollama ^
  --model "%SPOREPATH_EVAL_MODEL%" ^
  --ollama-timeout-s "%SPOREPATH_OLLAMA_TIMEOUT%" ^
  --ollama-num-predict "%SPOREPATH_OLLAMA_NUM_PREDICT%" ^
  --out "%SPOREPATH_EVAL_OUT%" ^
  --report "%SPOREPATH_EVAL_REPORT%"

if errorlevel 1 exit /b %errorlevel%

python -m sporepath eval-clean "%SPOREPATH_EVAL_OUT%" ^
  --out "%SPOREPATH_EVAL_CLEAN_OUT%" ^
  --report "%SPOREPATH_EVAL_CLEAN_REPORT%" ^
  --dedupe-threshold "%SPOREPATH_EVAL_DEDUPE_THRESHOLD%"
