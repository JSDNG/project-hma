# project-hma

A small **FastAPI** service that wraps the local **HideMyAcc (HMA)** REST
API as an authenticated HTTP layer.

The service is **stateless** — it does not persist anything. It is a thin
HTTP layer in front of the local HideMyAcc REST API
(`http://127.0.0.1:2268` by default), with an `x-api-key` gate so the
endpoints can be exposed beyond localhost.

All HMA helpers live in `app/hma_sync.py`; the route layer in `app/routes.py`
is a thin translation between HTTP and those pure functions.

---

## Features

- `GET /healthz` — liveness check
- `GET /config` — effective runtime configuration
- `GET /profiles` — fetch profiles from local HMA and return the mapped rows
  (proxy passwords included in the response)
- `DELETE /profiles/{profile_id}` — delete one profile from the local HMA API
- `DELETE /profiles` — batch-delete (best-effort) for a JSON array of IDs;
  returns per-ID success/failure
- Auto-generated **OpenAPI docs** at `/docs` (Swagger UI) and `/redoc`
- Pydantic-validated request/response models with explicit status codes
- Configuration via environment variables (`.env` supported through
  `pydantic-settings`)

---

## Requirements

- **Python 3.11+** (the project was developed and tested against 3.13)
- macOS / Linux / Windows
- A running HideMyAcc desktop client exposing the local API on
  `http://127.0.0.1:2268` (configurable via env var)

---

## Install

### macOS / Linux

```bash
cd path/to/project-hma
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Windows (PowerShell)

```powershell
cd C:\path\to\project-hma
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> If PowerShell blocks the activation script, run once (as your user):
> `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

### Windows (Command Prompt)

```bat
cd C:\path\to\project-hma
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
```

> The `playwright` / `undetected-playwright` packages in `requirements.txt`
> are kept for compatibility with other automation in this repo and are **not
> required** by the FastAPI service itself. If you only need the API, you can
> safely omit them.

---

## Configure

The service reads its configuration from environment variables. The easiest
approach is a local `.env` file at the project root — `pydantic-settings`
picks it up automatically on every OS.

### macOS / Linux

```bash
cp .env.example .env
# then edit .env in your editor of choice
```

### Windows (PowerShell)

```powershell
Copy-Item .env.example .env
notepad .env
```

### Windows (Command Prompt)

```bat
copy .env.example .env
notepad .env
```

### Variables

All variables are **required** in `.env` (no hardcoded defaults in code). See `.env.example` for the full list.

| Variable | Purpose |
|---|---|
| `HMA_LOCAL_API_BASE` | Local HideMyAcc REST API base URL. |
| `HMA_PROFILES_PATH` | HMA profiles API path (e.g. `/profiles`). |
| `HMA_HTTP_TIMEOUT` | HTTP client timeout (seconds). |
| `HMA_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `HMA_START_SUCCESS_CODE` | HMA body `code` value for successful start. |
| `HMA_DELETE_SUCCESS_CODE` | HMA body `code` value for successful delete. |
| `HMA_MIN_TCP_PORT` / `HMA_MAX_TCP_PORT` | Valid TCP port range for proxy validation. |
| `SUPOVER_API_KEY` | Shared secret for inbound `x-api-key` gate and outbound Supover calls. |
| `SUPOVER_API_KEY_HEADER` | Header name for API key (e.g. `x-api-key`). |
| `SUPOVER_SYNC_URL` | Endpoint for scheduled HMA profiles sync. |
| `SUPOVER_DEAD_STORES_URL` | Endpoint to fetch dead-with-balance stores. |
| `SUPOVER_STORES_SYNC_URL` | Endpoint to push store status data. |
| `TIKTOK_SELLER_BILLS_URL` | TikTok Seller bills page URL. |
| `TIKTOK_HEALTH_CENTER_URL` | TikTok health center page URL. |
| `TIKTOK_ACCOUNT_DEACTIVATED_TEXT` | Text to match for deactivated accounts. |
| `TIKTOK_ELEMENT_TIMEOUT` | Playwright element wait timeout (ms). |
| `TIKTOK_STEP_DELAY` | Delay between extraction steps (seconds). |
| `TIKTOK_DWELL_SECONDS` | Browser dwell time before stopping profile. |
| `XPATH_PENDING_BALANCE` | XPath for pending balance element. |
| `XPATH_ON_HOLD` | XPath for on-hold element. |
| `XPATH_BANK_ACCOUNT` | XPath for bank account element. |
| `XPATH_ACCOUNT_STATUS` | XPath for account status element. |

Setting variables directly (without a `.env`) — for one-off runs:

- **macOS / Linux (bash/zsh):** `export SUPOVER_API_KEY=...`
- **Windows PowerShell:** `$env:SUPOVER_API_KEY = "..."`
- **Windows Command Prompt:** `set SUPOVER_API_KEY=...`

---

## Run the API

The launch command is identical on every OS — only the venv activation
syntax differs.

```bash
# venv must be active (see Install)
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Then open:

- Swagger UI: <http://127.0.0.1:8000/docs>
- ReDoc:      <http://127.0.0.1:8000/redoc>

> `--reload` is for development. Drop it for production runs.

### Authentication

Every endpoint requires the caller to send an `x-api-key` header whose
value equals the server's `SUPOVER_API_KEY`. Missing or wrong
keys return `401`; if the server itself has no key configured it
fail-closes with `500`.

```
x-api-key: <SUPOVER_API_KEY>
```

### Quick test (cross-platform)

`curl` works on macOS, Linux, and modern Windows. `jq` is optional. The
examples below pull the key from your shell — `export
SUPOVER_API_KEY=...` first, or substitute the value inline.

```bash
# Health check
curl -s -H "x-api-key: $SUPOVER_API_KEY" http://127.0.0.1:8000/healthz

# List mapped profile rows (proxy passwords included)
curl -s -H "x-api-key: $SUPOVER_API_KEY" http://127.0.0.1:8000/profiles

# Delete a single profile
curl -s -X DELETE -H "x-api-key: $SUPOVER_API_KEY" \
  http://127.0.0.1:8000/profiles/abc123

# Batch-delete profiles
curl -s -X DELETE http://127.0.0.1:8000/profiles \
  -H "x-api-key: $SUPOVER_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"profile_ids": ["abc123", "def456"]}'
```

On **PowerShell** you can also use `Invoke-RestMethod`:

```powershell
$h = @{ "x-api-key" = $env:SUPOVER_API_KEY }
Invoke-RestMethod -Headers $h http://127.0.0.1:8000/healthz
Invoke-RestMethod -Headers $h http://127.0.0.1:8000/profiles
```

---

## Running on startup / in the background

This is optional — the service runs fine in a foreground terminal during
development.

### macOS

- For a quick "leave it running" session: `nohup uvicorn app.main:app
  --host 127.0.0.1 --port 8000 > logs/uvicorn.log 2>&1 &`
- For a managed background service, create a `~/Library/LaunchAgents/*.plist`
  launchd entry that invokes `.venv/bin/uvicorn app.main:app ...`.

### Linux

- A `systemd` unit running `.venv/bin/uvicorn app.main:app ...` is the usual
  approach.

### Windows

- For a one-off persistent run, launch from a terminal and minimize it.
- For a managed service, register the uvicorn command with
  [NSSM](https://nssm.cc/) or Task Scheduler ("At log on" / "At startup"
  trigger, pointing at `.venv\Scripts\uvicorn.exe app.main:app
  --host 127.0.0.1 --port 8000`).

---

## Scheduled Supover sync (Windows Task Scheduler)

A standalone runner at `scripts/sync_to_supover.py` calls the local HMA
`/profiles` endpoint and POSTs its **raw response body** — exactly what HMA
returned, no mapping or re-shaping — to `SUPOVER_SYNC_URL` with the
`x-api-key: SUPOVER_API_KEY` header. It does **not** require the FastAPI
service to be running.

### One-time setup on Windows 10 Pro

1. Confirm the project venv exists and the deps are installed (see
   [Install](#install)). The launcher prefers `.venv\Scripts\python.exe`
   and falls back to `python` on `PATH` if the venv is missing.
2. Fill in `SUPOVER_API_KEY` in your local `.env`.
3. Smoke-test the runner once by hand (from the project root):

   ```powershell
   .\.venv\Scripts\python.exe -m scripts.sync_to_supover
   ```

   You should see `Supover accepted payload (HTTP 200).` in the console and
   in `logs\supover_sync.log`.
4. Register the scheduled task (open PowerShell **as your normal user** —
   admin is not required for a user-scoped task):

   ```powershell
   .\scripts\setup_sync_task.ps1
   ```

   Pass `-RunWhetherLoggedOn` if you want the sync to fire even when you
   are signed out (uses S4U; no password is stored):

   ```powershell
   .\scripts\setup_sync_task.ps1 -RunWhetherLoggedOn
   ```

5. Verify the task fires:

   ```powershell
   Start-ScheduledTask -TaskName HMA-Supover-Sync
   Get-ScheduledTaskInfo -TaskName HMA-Supover-Sync | Select-Object LastRunTime, LastTaskResult
   Get-Content .\logs\supover_sync.log -Tail 20
   ```

   `LastTaskResult` of `0` is success. Other exit codes:
   `1` = config error, `2` = local HMA unreachable / bad body,
   `3` = Supover unreachable or returned non-2xx.

6. To remove the task later:

   ```powershell
   .\scripts\unregister_sync_task.ps1
   ```

### Files involved

| Path                            | Purpose                                                            |
|---------------------------------|--------------------------------------------------------------------|
| `scripts/sync_to_supover.py`    | Python entry point; reads `.env`, calls HMA, posts to Supover.     |
| `scripts/run_sync.bat`          | Launcher Task Scheduler executes — activates the venv, sets cwd.   |
| `scripts/setup_sync_task.ps1`   | Registers the `HMA-Supover-Sync` task (00:00 + 12:00 daily).       |
| `scripts/unregister_sync_task.ps1` | Removes the scheduled task.                                     |
| `logs/supover_sync.log`         | Structured logs from the Python script.                            |
| `logs/supover_sync.bat.log`     | Wrapper-level log (start/finish timestamps + exit code).           |

### Manual GUI alternative (optional)

If you prefer the Task Scheduler GUI over the PowerShell setup script:

1. Open **Task Scheduler** → **Create Task…** (not "Create Basic Task").
2. **General** — name it `HMA-Supover-Sync`. Pick a logon mode
   ("Run only when user is logged on" is fine for the simple case).
3. **Triggers** — add two **Daily** triggers, one at `00:00:00` and one at
   `12:00:00`.
4. **Actions** — **Start a program**, browse to
   `<project root>\scripts\run_sync.bat`. In **Start in (optional)** put
   the project root (the folder that contains `.env`).
5. **Settings** — leave defaults; optionally tick "Run task as soon as
   possible after a scheduled start is missed".

## Tests

```bash
# venv active
pytest -q
```

Tests cover the pure mapping helpers and every endpoint (upstream HTTP is
mocked, so no network access is required).

---

## Project layout

See [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md).

## API reference

See [`docs/API.md`](./docs/API.md), or open `/docs` (Swagger UI) once the
server is running.
