# Architecture

## Goals

1. **Single source of truth for sync logic.** All fetch / map / forward code
   lives in one pure module (`app/hma_sync.py`); the HTTP layer is just
   translation. No duplication across files.
2. **Stateless.** No database, no queue, no on-disk cache. Each request is
   self-contained.
3. **Simple to run.** A single `uvicorn` command should start the service. No
   Docker required. Runs identically on macOS, Linux, and Windows.
4. **Explicit configuration.** All tunables come from environment variables
   (or a local `.env`), with safe defaults. Secrets are masked in logs and in
   the `/config` response.
5. **Production-ready basics.** Typed Pydantic models, structured logging,
   proper HTTP status codes for upstream failures, OpenAPI documentation.

## Non-goals

- Persistence, authentication, rate limiting, background jobs, multi-tenant
  config — explicitly out of scope for this iteration.

---

## Directory layout

```
project-hma/
├── app/                              # FastAPI application package
│   ├── __init__.py
│   ├── main.py                       # FastAPI() instance, router wiring, OpenAPI metadata
│   ├── config.py                     # Settings (pydantic-settings) + cached get_settings()
│   ├── schemas.py                    # Pydantic request/response models
│   ├── routes.py                     # APIRouter with /healthz, /config, /profiles (GET/DELETE),
│                                     # /profiles/{id} (DELETE), /sync
│   ├── auth.py                       # require_api_key dependency (x-api-key gate)
│   └── hma_sync.py                   # Pure service module: fetch_profiles, profile_to_sync_row,
│                                     # post_sync, delete_profile, resolve_sync_post_url,
│                                     # mask_secrets, setup_logging
│
├── tests/                            # pytest suite
│   ├── conftest.py                   # Shared fixtures: TestClient, settings override
│   ├── test_hma_sync.py              # Unit tests for the pure helpers
│   └── test_routes.py                # Endpoint tests with upstream HTTP mocked
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
- `post_sync(session, sync_url, api_key, rows, timeout) -> requests.Response`
- `resolve_sync_post_url(url: str) -> str`
- `mask_secrets(row: dict) -> dict`
- `setup_logging(log_file=None, level="INFO") -> None`

Module constants: `DEFAULT_HMA_BASE`, `DEFAULT_PROFILES_PATH`,
`DEFAULT_TIMEOUT`, `DEFAULT_HMA_PROFILES_SYNC_URL`, `SYNC_POST_SUFFIX`.

### `app/config.py`

```python
class Settings(BaseSettings):
    hma_local_api_base: str = "http://127.0.0.1:2268"
    hma_profiles_sync_url: str = "https://n8n.supover.com/webhook"
    hma_api_key: str = ""              # required for non-dry-run /sync
    hma_http_timeout: int = 30
    hma_log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", env_prefix="")
```

Exposed via a `@lru_cache`-wrapped `get_settings()` so each request gets the
same instance and tests can override the dependency cleanly.

### `app/schemas.py`

Pydantic models that mirror what the service returns. Notable types:

- `ProfileRow` — one mapped row (`profile_id`, `profile_name`, `proxy`, `port`,
  `username`, `password`, `user_agent`). `password` is `str` but the route
  layer masks it before returning.
- `SyncSummary` — `{ rows_fetched, rows_forwarded, downstream_status,
  downstream_body, dry_run, sync_url }`.
- `ConfigView` — masked settings snapshot. Exposes only the **resolved**
  `sync_post_url` (the raw `hma_profiles_sync_url` base is omitted). `api_key`
  is shown as `"***"` if set, empty string otherwise.
- `HealthResponse` — `{ status: "ok" }`.

### `app/routes.py`

A single `APIRouter()` with tags grouped by purpose (`system`, `profiles`,
`sync`). Endpoints are **synchronous** (`def`, not `async def`) because the
service uses the blocking `requests` library; FastAPI runs sync handlers in a
threadpool automatically. Going async would force a parallel `httpx` codebase
or `run_in_threadpool` wrapping for zero benefit at this scale.

Endpoints map to `hma_sync.*` plus light error translation:

| Endpoint                     | Calls                                                       |
|------------------------------|-------------------------------------------------------------|
| `GET    /healthz`            | —                                                           |
| `GET    /config`             | `get_settings()` → masked view                              |
| `GET    /profiles`           | `fetch_profiles` → list[`profile_to_sync_row`]              |
| `DELETE /profiles/{id}`      | `delete_profile` (one upstream call)                        |
| `DELETE /profiles`           | `delete_profile` per ID (best-effort, deduplicated)         |
| `POST   /sync`               | `fetch_profiles` → map → `post_sync` (unless `dry_run`)     |

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
| Downstream webhook unreachable                     | `502`  | `{ "detail": "Sync webhook error: ..." }`         |
| Downstream webhook returns non-2xx                 | `502`  | `{ "detail": "Sync webhook responded HTTP N" }`   |
| `/sync` without `dry_run=true` and missing API key | `400`  | `{ "detail": "HMA_API_KEY is not configured" }`   |
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
relies on the presence of `data: [...]` rather than a code value, and the
downstream `POST /sync` targets an external n8n webhook that follows
standard HTTP codes.

---

## Security

- **Inbound authentication.** Every request must carry an `x-api-key` header
  matching `HMA_PROFILE_SYNC_API_KEY`. The check lives in `app/auth.py` as
  the `require_api_key` dependency and is attached at the `APIRouter` level
  so it applies uniformly to every endpoint, including `/healthz`. Header
  comparison uses `secrets.compare_digest` to avoid timing leaks. The gate
  is **fail-closed**: if the server has no key configured, all requests are
  rejected with `500` rather than silently letting traffic through.
- **Two keys, two directions.** `HMA_PROFILE_SYNC_API_KEY` authenticates
  inbound callers of this service. `HMA_API_KEY` is the outbound credential
  the service sends to the downstream n8n webhook on `/sync`. They are not
  interchangeable.
- **Secrets are never returned in responses.** Passwords in profile rows and
  the API key in `/config` are masked. A `?reveal=true` flag on `/profiles`
  unmasks passwords, intended for local debugging — not for production
  exposure.
- No hardcoded API key defaults anywhere in source. Both `HMA_API_KEY` and
  `HMA_PROFILE_SYNC_API_KEY` come only from the environment (or `.env`).

---

## Testing strategy

- **Pure-logic unit tests** (`test_hma_sync.py`): exercise `profile_to_sync_row`
  with multiple profile shapes (proxy dict present, fallback to `autoProxy*`,
  missing fields, non-string port). Also `resolve_sync_post_url` against all
  three URL shapes from its docstring, plus `mask_secrets` edge cases.
- **Route tests** (`test_routes.py`): use FastAPI `TestClient` with a `with`
  block (so lifespan runs). Upstream HTTP is patched at the
  `requests.Session.get/post` boundary using `unittest.mock`. Override
  `get_settings` via `app.dependency_overrides` to inject test config.
- No live HTTP. CI-safe.

Run with `pytest -q` from the project root (any OS).

---

## Logging

`app/main.py` configures the root logger on startup via the lifespan context
manager, using `setup_logging` from `app/hma_sync.py`. Uvicorn's own loggers
are left alone. By default logs go to stdout; pass a `log_file=Path(...)` to
`setup_logging` to also tee them to disk.

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
