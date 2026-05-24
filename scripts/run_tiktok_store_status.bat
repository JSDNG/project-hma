@echo off
REM ======================================================================
REM  Windows Task Scheduler launcher for the TikTok store status job.
REM
REM  Behavior:
REM    - cd to the project root (one level above this scripts\ folder),
REM      so the .env file is discovered by pydantic-settings.
REM    - Activate the local virtual environment at .venv\Scripts\.
REM    - Run scripts\check_tiktok_store_status.py.
REM    - Append stdout + stderr to logs\tiktok_store_status.bat.log
REM      (the Python script also writes structured logs to
REM       logs\check_tiktok_store_status.log via the application logger).
REM
REM  Exit code from the Python script is preserved, so Task Scheduler's
REM  "Last Run Result" column reflects the real outcome:
REM      0x0  success
REM      0x1  configuration error
REM      0x2  Supover unreachable / bad response / no eligible profile
REM      0x3  local HMA /profiles/start failed or returned a bad response
REM      0x4  Playwright connect or navigation error
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

echo. >> "logs\tiktok_store_status.bat.log"
echo [%DATE% %TIME%] Starting tiktok-store-status >> "logs\tiktok_store_status.bat.log"
"%PY_EXE%" -m scripts.check_tiktok_store_status >> "logs\tiktok_store_status.bat.log" 2>&1
set "RC=%ERRORLEVEL%"
echo [%DATE% %TIME%] Finished with exit code %RC% >> "logs\tiktok_store_status.bat.log"

endlocal & exit /b %RC%
