# Architecture

## Goals

1. **Single source of truth for HMA logic.** All fetch / map / delete code
   lives in one pure module (`app/hma_sync.py`); the HTTP layer is just
   translation. No duplication across files.
2. **Stateless.** No database, no queue, no on-disk cache. Each request is
   self-contained.
3. **Simple to run.** A single `uvicorn` command should start the service. No
   Docker required. Runs identically on macOS, Linux, and Windows.
4. **Explicit configuration.** All tunables come from environment variables
   (or a local `.env`), with safe defaults. Secrets are never echoed back.
5. **Production-ready basics.** Typed Pydantic models, structured logging,
   proper HTTP status codes for upstream failures, `x-api-key` gate on every
   route, OpenAPI documentation.

## Non-goals

- Persistence, rate limiting, multi-tenant config — explicitly out of
  scope for this iteration.
- In-process background jobs. The Supover sync runs as an external,
  OS-scheduled script (`scripts/sync_to_supover.py`), not as an in-app
  scheduler thread. This keeps the FastAPI service stateless and
  request-driven; see [Scheduled Supover sync](#scheduled-supover-sync)
  below.

---

## Directory layout

```
project-hma/
├── app/                              # FastAPI application package
│   ├── __init__.py
│   ├── main.py                       # FastAPI() instance, router wiring, OpenAPI metadata
│   ├── config.py                     # Settings (pydantic-settings) + cached get_settings()
│   ├── schemas.py                    # Pydantic request/response models
│   ├── routes.py                     # APIRouter with /healthz, /config, /profiles (GET),
│                                     # /profiles (DELETE batch), /profiles/{id} (DELETE)
│   ├── auth.py                       # require_api_key dependency (x-api-key gate)
│   ├── hma_sync.py                   # Pure service module: fetch_profiles, profile_to_sync_row,
│   │                                 # delete_profile, parse_hma_body, setup_logging
│   └── supover_sync.py               # Pure helper: push_to_supover, build_supover_payload
│                                     # (used by the scheduled runner; not by the API)
│
├── scripts/                          # OS-scheduled jobs (run outside the FastAPI process)
│   ├── sync_to_supover.py            # CLI entry point: HMA -> Supover, twice daily
│   ├── run_sync.bat                  # Windows Task Scheduler launcher (sets cwd, activates venv)
│   ├── setup_task.ps1                # Register the HMA-Supover-Sync scheduled task
│   └── unregister_task.ps1           # Remove the scheduled task
│
├── tests/                            # pytest suite
│   ├── conftest.py                   # Shared fixtures: TestClient, settings override
│   ├── test_hma_sync.py              # Unit tests for the pure helpers
│   ├── test_routes.py                # Endpoint tests with upstream HTTP mocked
│   └── test_supover_sync.py          # Unit tests for push_to_supover / build_supover_payload
│
├── docs/
│   ├── ARCHITECTURE.md               # This file
│   └── API.md                        # Endpoint reference
│
├── logs/                             # Free-form log destination (optional)
│
├── pyproject.toml                    # pytest config (pythonpath, testpaths)
├── requirements.txt
├── .env.example                      # Documented environment variables
├── .gitignore
└── README.md
```

### Why this shape

- **`app/` as a single package** keeps imports flat (`from app.hma_sync import …`)
  and matches FastAPI's "Bigger Applications" convention without
  over-fragmenting a small service.
- **No `app/api/` subdirectory.** With four endpoints, splitting into multiple
  router files adds friction without benefit. If the surface grows past
  ~10 endpoints we'll split per resource.
- **No `app/services/` subdirectory.** There is exactly one service module
  (`hma_sync.py`). Adding a folder for one file is premature abstraction.

---

## Module responsibilities

### `app/hma_sync.py`  (pure logic — no FastAPI imports)

Pure functions, no global state, no I/O side effects beyond explicit HTTP
calls made through a `requests.Session` passed in by the caller. This is
where bug fixes and behavior changes belong.

Public surface:

- `fetch_profiles(session, base_url, timeout) -> list[dict]`
- `profile_to_sync_row(profile: dict) -> dict[str, str]`
- `delete_profile(session, base_url, profile_id, timeout) -> requests.Response`
- `parse_hma_body(resp) -> dict | None` — JSON-parses an HMA response into
  a dict if possible (callers interpret the `code` field themselves; see
  "HMA response convention" below)
- `setup_logging(log_file=None, level="INFO") -> None`

Module constants: `DEFAULT_HMA_BASE`, `DEFAULT_PROFILES_PATH`,
`DEFAULT_TIMEOUT`.

### `app/config.py`

```python
class Settings(BaseSettings):
    hma_local_api_base: str = "http://127.0.0.1:2268"
    hma_profile_sync_api_key: str = ""    # required: inbound x-api-key
    hma_http_timeout: int = 30
    hma_log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", env_prefix="")
```

Exposed via a `@lru_cache`-wrapped `get_settings()` so each request gets the
same instance and tests can override the dependency cleanly.

### `app/schemas.py`

Pydantic models that mirror what the service returns. Notable types:

- `ProfileRow` — one mapped row (`profile_id`, `profile_name`, `proxy`, `port`,
  `username`, `password`, `user_agent`). The proxy `password` is returned
  in clear text; access control is provided by the `x-api-key` gate.
- `ConfigView` — non-secret settings snapshot
  (`hma_local_api_base`, `hma_http_timeout`, `hma_log_level`). The inbound
  API key is never echoed back.
- `DeleteResponse` / `BatchDeleteRequest` / `BatchDeleteResponse` /
  `BatchDeleteFailure` — DELETE endpoint shapes.
- `HealthResponse` — `{ status: "ok" }`.

### `app/routes.py`

A single `APIRouter()` with tags grouped by purpose (`system`, `profiles`).
Endpoints are **synchronous** (`def`, not `async def`) because the service
uses the blocking `requests` library; FastAPI runs sync handlers in a
threadpool automatically. Going async would force a parallel `httpx` codebase
or `run_in_threadpool` wrapping for zero benefit at this scale.

Endpoints map to `hma_sync.*` plus light error translation:

| Endpoint                     | Calls                                                       |
|------------------------------|-------------------------------------------------------------|
| `GET    /healthz`            | —                                                           |
| `GET    /config`             | `get_settings()` → non-secret view                          |
| `GET    /profiles`           | `fetch_profiles` → list[`profile_to_sync_row`]              |
| `DELETE /profiles/{id}`      | `delete_profile` (one upstream call)                        |
| `DELETE /profiles`           | `delete_profile` per ID (best-effort, deduplicated)         |

### `app/main.py`

Builds the `FastAPI` instance, registers `openapi_tags`, configures logging
once on startup via the lifespan context manager, and includes the router.
Kept under ~30 lines.

---

## Error handling

The service translates upstream failures into appropriate HTTP status codes
instead of leaking 500s:

| Condition                                          | Status | Body                                              |
|----------------------------------------------------|--------|---------------------------------------------------|
| Local HMA unreachable / `requests.RequestException`| `502`  | `{ "detail": "HMA local API error: ..." }`        |
| Local HMA returns malformed JSON / missing `data`  | `502`  | `{ "detail": "Invalid HMA response: ..." }`       |
| `DELETE /profiles/{id}` — HMA 402 + `code: 0`      | `402`  | `{ "detail": "HMA local API requires a Team plan ..." }` |
| `DELETE /profiles/{id}` — HMA `code != 1` (other)  | `502`  | `{ "detail": "HMA local API signaled failure (HTTP N, code=K): ..." }` |
| `DELETE /profiles` — per-ID errors                 | `200`  | Returned inside `failures[]`, not as an HTTP error |
| Missing / wrong `x-api-key` header                 | `401`  | `{ "detail": "Invalid or missing x-api-key" }`    |
| Server `HMA_PROFILE_SYNC_API_KEY` not configured   | `500`  | `{ "detail": "HMA_PROFILE_SYNC_API_KEY is not configured on the server" }` |
| Unexpected exception                               | `500`  | FastAPI default                                   |

---

## HMA response convention

The HideMyAcc local API carries the meaningful status in the response
**body**'s `code` field, and the meaning of that field is endpoint-specific.
For `DELETE /profiles/{id}` ([official
docs](https://eng-hidemyacc.gitbook.io/hidemyacc-docs-vietnamese/hidemyacc-3.0-tinh-nang/hidemyacc-3.0-api/profile/xoa-profile)):

| HMA HTTP | HMA body         | Meaning                                            |
|----------|------------------|----------------------------------------------------|
| `200`    | `{"code": 1}`    | Success — profile deleted.                         |
| `402`    | `{"code": 0}`    | "API supported from Team plan" — subscription required. |

`parse_hma_body(resp)` returns the JSON body as a dict (or `None` if the
body wasn't JSON). The DELETE route's `_interpret_hma_delete` helper applies
the rules above:

1. `code == 1` → success.
2. HTTP `402` + `code == 0` → pass `402` through with a clear message.
3. Anything else → `502` with `(HTTP N, code=K, body...)` in `detail`.

This is applied **only** to the DELETE endpoints. `GET /profiles` already
relies on the presence of `data: [...]` rather than a code value.

---

## Security

- **Inbound authentication.** Every request must carry an `x-api-key` header
  matching `HMA_PROFILE_SYNC_API_KEY`. The check lives in `app/auth.py` as
  the `require_api_key` dependency and is attached at the `APIRouter` level
  so it applies uniformly to every endpoint, including `/healthz`. Header
  comparison uses `secrets.compare_digest` to avoid timing leaks. The gate
  is **fail-closed**: if the server has no key configured, all requests are
  rejected with `500` rather than silently letting traffic through.
- **Proxy passwords are returned in clear text** on `GET /profiles`. The
  endpoint is gated by `x-api-key`, so access control is the responsibility
  of whoever holds the key — treat `HMA_PROFILE_SYNC_API_KEY` as sensitive.
  The inbound API key itself is never echoed back from `/config`.
- No hardcoded API key defaults anywhere in source.
  `HMA_PROFILE_SYNC_API_KEY` comes only from the environment (or `.env`).

---

## Testing strategy

- **Pure-logic unit tests** (`test_hma_sync.py`): exercise `profile_to_sync_row`
  with multiple profile shapes (proxy dict present, fallback to `autoProxy*`,
  missing fields, non-string port) and the argument validation of
  `delete_profile`.
- **Route tests** (`test_routes.py`): use FastAPI `TestClient` with a `with`
  block (so lifespan runs). Upstream HTTP is patched at the
  `requests.Session.get/delete` boundary using `unittest.mock`. Override
  `get_settings` via `app.dependency_overrides` to inject test config. A
  separate `unauth_client` fixture (no default `x-api-key` header) covers
  the auth gate.
- No live HTTP. CI-safe.

Run with `pytest -q` from the project root (any OS).

---

## Logging

`app/main.py` configures the root logger on startup via the lifespan context
manager, using `setup_logging` from `app/hma_sync.py`. Uvicorn's own loggers
are left alone. By default logs go to stdout; pass a `log_file=Path(...)` to
`setup_logging` to also tee them to disk.

---

## Scheduled Supover sync

`scripts/sync_to_supover.py` is a standalone job that runs **outside** the
FastAPI process. It reuses the in-tree pure helpers so there is exactly one
mapping path:

1. `app.config.get_settings()` — same `.env`, same env vars.
2. `app.hma_sync.fetch_profiles` against `HMA_LOCAL_API_BASE` directly
   (the script does **not** call the FastAPI `/profiles` endpoint, so the
   service does not need to be running).
3. `app.hma_sync.profile_to_sync_row` for each item.
4. `app.supover_sync.push_to_supover` — POST `{count, data}` to
   `SUPOVER_SYNC_URL` with `x-api-key: SUPOVER_API_KEY`.

The runner exits with a meaningful code so Task Scheduler's "Last Run
Result" column is useful (`0` ok, `1` config, `2` HMA, `3` Supover) and
appends to `logs/supover_sync.log`. Scheduling itself is delegated to the
OS — on Windows that is Task Scheduler, registered via
`scripts/setup_task.ps1` with two daily triggers at `00:00` and `12:00`.

The FastAPI app does not import `supover_sync` and does not start any
background thread — keeping the runtime stateless and request-driven.

---

## Cross-platform notes

The application code is pure Python and uses no OS-specific APIs.
Platform differences exist only in operator-facing commands:

- **venv activation:** `source .venv/bin/activate` (POSIX) vs.
  `.\.venv\Scripts\Activate.ps1` (Windows PowerShell) /
  `.venv\Scripts\activate.bat` (Windows cmd).
- **Setting env vars:** `export X=...` vs. `$env:X = "..."` vs. `set X=...`.
- **Running on startup:** launchd / systemd / NSSM, respectively.

The actual `uvicorn app.main:app` invocation is identical on every OS. See
the README for copy-pasteable commands per platform.
