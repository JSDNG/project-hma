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

| Variable                  | Default                              | Purpose                                                                 |
|---------------------------|--------------------------------------|-------------------------------------------------------------------------|
| `HMA_LOCAL_API_BASE`      | `http://127.0.0.1:2268`              | Local HideMyAcc REST API base.                                          |
| `HMA_PROFILE_SYNC_API_KEY`| *(empty)*                            | **Required.** Shared secret that incoming clients must send as `x-api-key` on every request to this service. If unset, the server rejects all requests with HTTP 500 (fail-closed). |
| `HMA_HTTP_TIMEOUT`        | `30`                                 | HTTP client timeout (seconds).                                          |
| `HMA_LOG_LEVEL`           | `INFO`                               | `DEBUG`, `INFO`, `WARNING`, `ERROR`.                                    |

Setting variables directly (without a `.env`) — for one-off runs:

- **macOS / Linux (bash/zsh):** `export HMA_PROFILE_SYNC_API_KEY=...`
- **Windows PowerShell:** `$env:HMA_PROFILE_SYNC_API_KEY = "..."`
- **Windows Command Prompt:** `set HMA_PROFILE_SYNC_API_KEY=...`

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
value equals the server's `HMA_PROFILE_SYNC_API_KEY`. Missing or wrong
keys return `401`; if the server itself has no key configured it
fail-closes with `500`.

```
x-api-key: <HMA_PROFILE_SYNC_API_KEY>
```

### Quick test (cross-platform)

`curl` works on macOS, Linux, and modern Windows. `jq` is optional. The
examples below pull the key from your shell — `export
HMA_PROFILE_SYNC_API_KEY=...` first, or substitute the value inline.

```bash
# Health check
curl -s -H "x-api-key: $HMA_PROFILE_SYNC_API_KEY" http://127.0.0.1:8000/healthz

# List mapped profile rows (proxy passwords included)
curl -s -H "x-api-key: $HMA_PROFILE_SYNC_API_KEY" http://127.0.0.1:8000/profiles

# Delete a single profile
curl -s -X DELETE -H "x-api-key: $HMA_PROFILE_SYNC_API_KEY" \
  http://127.0.0.1:8000/profiles/abc123

# Batch-delete profiles
curl -s -X DELETE http://127.0.0.1:8000/profiles \
  -H "x-api-key: $HMA_PROFILE_SYNC_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"profile_ids": ["abc123", "def456"]}'
```

On **PowerShell** you can also use `Invoke-RestMethod`:

```powershell
$h = @{ "x-api-key" = $env:HMA_PROFILE_SYNC_API_KEY }
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
