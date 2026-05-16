@echo off
REM ======================================================================
REM  Windows Task Scheduler launcher for the Supover sync job.
REM
REM  Behavior:
REM    - cd to the project root (one level above this scripts\ folder),
REM      so the .env file is discovered by pydantic-settings.
REM    - Activate the local virtual environment at .venv\Scripts\.
REM    - Run scripts\sync_to_supover.py.
REM    - Append stdout + stderr to logs\supover_sync.bat.log
REM      (the Python script also writes structured logs to
REM       logs\supover_sync.log via the application logger).
REM
REM  Exit code from the Python script is preserved, so Task Scheduler's
REM  "Last Run Result" column reflects the real outcome:
REM      0x0  success
REM      0x1  configuration error
REM      0x2  local HMA unreachable / bad body
REM      0x3  Supover unreachable / non-2xx
REM ======================================================================

setlocal

REM Resolve project root = parent of this script's directory.
set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."

cd /d "%PROJECT_ROOT%" || exit /b 1

if not exist "logs" mkdir "logs"

REM Prefer the local venv if present; fall back to the system "python" on PATH.
set "PY_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe"
if not exist "%PY_EXE%" set "PY_EXE=python"

echo. >> "logs\supover_sync.bat.log"
echo [%DATE% %TIME%] Starting supover sync >> "logs\supover_sync.bat.log"
"%PY_EXE%" -m scripts.sync_to_supover >> "logs\supover_sync.bat.log" 2>&1
set "RC=%ERRORLEVEL%"
echo [%DATE% %TIME%] Finished with exit code %RC% >> "logs\supover_sync.bat.log"

endlocal & exit /b %RC%
