@echo off
REM ======================================================================
REM  Windows Task Scheduler launcher for the check-seller-status job.
REM
REM  Behavior:
REM    - cd to the project root (one level above this scripts\ folder),
REM      so the .env file is discovered by pydantic-settings.
REM    - Activate the local virtual environment at .venv\Scripts\.
REM    - Run scripts\open_first_dead_store_tiktok.py.
REM    - Append stdout + stderr to logs\check_seller.bat.log
REM      (the Python script also writes structured logs to
REM       logs\open_first_dead_store_tiktok.log via the application logger).
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

echo. >> "logs\check_seller.bat.log"
echo [%DATE% %TIME%] Starting check-seller-status >> "logs\check_seller.bat.log"
"%PY_EXE%" -m scripts.open_first_dead_store_tiktok >> "logs\check_seller.bat.log" 2>&1
set "RC=%ERRORLEVEL%"
echo [%DATE% %TIME%] Finished with exit code %RC% >> "logs\check_seller.bat.log"

endlocal & exit /b %RC%
