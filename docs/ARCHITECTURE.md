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
   (or a local `.env`), with no hardcoded defaults in code. Secrets are never echoed back.
5. **Production-ready basics.** Typed Pydantic models, structured logging,
   proper HTTP status codes for upstream failures, `x-api-key` gate on every
   route, OpenAPI documentation.

## Non-goals

- Persistence, rate limiting, multi-tenant config — explicitly out of
  scope for this iteration.
- In-process background jobs. Scripts run as external, OS-scheduled jobs,
  not as in-app scheduler threads.

---

## Directory layout

```
project-hma/
├── app/                              # FastAPI application package
│   ├── __init__.py
│   ├── main.py                       # FastAPI() instance, router wiring, OpenAPI metadata
│   ├── config.py                     # Settings (pydantic-settings) + cached get_settings()
│   ├── schemas.py                    # Pydantic request/response models
│   ├── routes.py                     # APIRouter with /healthz, /config, /profiles endpoints
│   ├── auth.py                       # require_api_key dependency (x-api-key gate)
│   ├── hma_sync.py                   # Pure service module: fetch_profiles, delete_profile,
│   │                                 # start_profile, stop_profile, interpret_start_response
│   ├── profile_actions.py            # Playwright browser actions (check_seller_status)
│   ├── supover_sync.py               # Pure helper: push_to_supover
│   ├── supover_stores.py             # Pure helpers: fetch/push store data, extract IDs
│   └── helpers/                      # Shared utilities
│       ├── __init__.py
│       ├── http.py                   # validate_api_credentials(), build_api_headers()
│       ├── logging.py                # setup_logging()
│       └── telegram.py              # send_telegram_message()
│
├── scripts/                          # OS-scheduled jobs (run outside the FastAPI process)
│   ├── sync_to_supover.py            # CLI entry point: HMA -> Supover profiles sync
│   ├── check_tiktok_store_status.py  # CLI entry point: check TikTok store status, push to Supover
│   ├── run_sync.bat                  # Windows launcher for sync_to_supover
│   ├── setup_sync_task.ps1           # Register the HMA-Supover-Sync scheduled task
│   ├── unregister_sync_task.ps1      # Remove the HMA-Supover-Sync scheduled task
│   ├── run_tiktok_store_status.bat   # Windows launcher for check_tiktok_store_status
│   ├── setup_tiktok_store_status_task.ps1    # Register the HMA-TikTok-Store-Status task (every 2 days)
│   └── unregister_tiktok_store_status_task.ps1
│
├── tests/                            # pytest suite
│   ├── conftest.py                   # Shared fixtures: TestClient, settings override
│   ├── test_hma_sync.py              # Unit tests for the pure helpers
│   ├── test_routes.py                # Endpoint tests with upstream HTTP mocked
│   ├── test_supover_stores.py        # Unit tests for store fetch/ID extraction
│   └── test_supover_sync.py          # Unit tests for push_to_supover
│
├── docs/
│   ├── ARCHITECTURE.md               # This file
│   ├── API.md                        # Endpoint reference
│   └── CHECK_SELLER_STATUS.md        # TikTok store status check flow
│
├── logs/                             # Log destination (gitignored)
│
├── pyproject.toml                    # pytest config (pythonpath, testpaths)
├── requirements.txt
├── .env.example                      # Documented environment variables
├── .gitignore
└── README.md
```

### Why this shape

- **`app/` as a single package** keeps imports flat (`from app.hma_sync import …`)
  and matches FastAPI's "Bigger Applications" convention.
- **`app/helpers/`** holds shared utilities (HTTP header construction,
  credential validation, logging setup) used across multiple modules.
- **No `app/services/` subdirectory.** The service is small enough that
  flat modules are clearer than nested packages.

---

## Module responsibilities

### `app/helpers/http.py`  (shared HTTP utilities)

- `validate_api_credentials(api_key, url, url_env_name) -> (key, target)` — strips and validates, raises `ValueError` if empty
- `build_api_headers(api_key_header, key, include_content_type=True) -> dict` — builds standard API headers

Used by: `supover_sync.py`, `supover_stores.py`.

### `app/helpers/telegram.py`  (Telegram notifications)

- `send_telegram_message(bot_token, chat_id, text, *, timeout=10) -> bool` — sends a message via Telegram Bot API; returns `False` on failure (never raises)

Used by: `scripts/check_tiktok_store_status.py`.

### `app/helpers/logging.py`  (shared logging)

- `setup_logging(log_file=None, level="INFO")` — configures root logger (stdout + optional file)

Used by: `main.py`, both scripts.

### `app/hma_sync.py`  (pure logic — no FastAPI imports)

Pure functions, no global state. Public surface:

- `fetch_profiles(session, base_url, timeout, profiles_path) -> list[dict]`
- `fetch_profiles_response(session, base_url, timeout, profiles_path) -> Any`
- `profile_to_sync_row(profile, min_port, max_port) -> dict[str, str]`
- `delete_profile(session, base_url, profile_id, timeout, profiles_path) -> Response`
- `start_profile(session, base_url, profile_id, timeout, profiles_path) -> Response`
- `stop_profile(session, base_url, profile_id, timeout, profiles_path) -> Response`
- `interpret_start_response(resp, start_success_code) -> StartResult`
- `parse_hma_body(resp) -> dict | None`

All parameters (paths, timeouts, success codes) come from callers — no hardcoded defaults.

### `app/profile_actions.py`  (browser automation)

- `check_seller_status(ws_url, log, settings, region) -> dict[str, str | None]` — navigates TikTok Seller bills page, extracts 3 DOM fields (pending_settlement, payout_on_hold, bank_account_number) + 1 API field (shop_status)

Uses Playwright over CDP. All URLs, XPaths, timeouts, and delays come from `settings` (`.env`).

### `app/supover_stores.py`  (Supover stores API)

- `push_store_status(...)` — POST store status to Supover
- `fetch_dead_stores_with_balance(...)` — GET dead stores with balance
- `all_store_and_profile_ids(stores)` — extract all eligible (store_id, tt_shop_code, region, profile_id) tuples

### `app/config.py`

All configuration comes from `.env` via `pydantic-settings`. No hardcoded defaults for URLs, API keys, or XPaths.
Exposed via `@lru_cache`-wrapped `get_settings()`.

### `app/routes.py`

A single `APIRouter()` with tags grouped by purpose (`system`, `profiles`).
Endpoints are synchronous and map to `hma_sync.*` functions.

---

## Error handling

| Condition                                          | Status | Body                                              |
|----------------------------------------------------|--------|---------------------------------------------------|
| Local HMA unreachable / `requests.RequestException`| `502`  | `{ "detail": "HMA local API error: ..." }`        |
| Local HMA returns malformed JSON / missing `data`  | `502`  | `{ "detail": "Invalid HMA response: ..." }`       |
| `DELETE /profiles/{id}` — HMA 402 + `code: 0`      | `402`  | `{ "detail": "HMA local API requires a Team plan ..." }` |
| `DELETE /profiles/{id}` — HMA `code != 1` (other)  | `502`  | `{ "detail": "HMA local API signaled failure ..." }` |
| `DELETE /profiles` — per-ID errors                 | `200`  | Returned inside `failures[]`, not as an HTTP error |
| Missing / wrong `x-api-key` header                 | `401`  | `{ "detail": "Invalid or missing x-api-key" }`    |
| Server `SUPOVER_API_KEY` not configured             | `500`  | `{ "detail": "SUPOVER_API_KEY is not configured on the server" }` |

---

## Security

- **Inbound authentication.** Every request must carry an `x-api-key` header
  matching `SUPOVER_API_KEY`. The check lives in `app/auth.py` as
  the `require_api_key` dependency. Comparison uses `secrets.compare_digest`.
  Fail-closed: if the server has no key configured, all requests are rejected with `500`.
- **Proxy passwords are returned in clear text** on `GET /profiles`. Access
  control is provided by the `x-api-key` gate.
- No hardcoded API key defaults anywhere in source.
  `SUPOVER_API_KEY` comes only from the environment (or `.env`).

---

## Logging

`app/main.py` configures the root logger on startup via the lifespan context
manager, using `setup_logging` from `app/helpers/logging.py`. Uvicorn's own
loggers are left alone. By default logs go to stdout; pass a `log_file` to
also tee them to disk.

---

## Scheduled jobs

### Supover profiles sync (`scripts/sync_to_supover.py`)

Forwards the raw HMA `/profiles` response to Supover verbatim. Runs twice
daily via Windows Task Scheduler (`scripts/setup_sync_task.ps1`).

### TikTok store status check (`scripts/check_tiktok_store_status.py`)

For each dead-with-balance store from Supover:
1. Start HMA profile → get `wsUrl`
2. Navigate TikTok Seller bills page → extract 3 DOM fields + 1 API field
3. Validate results — if element read or API call failed, send Telegram notification and skip push
4. POST data back to Supover `/api/hma/stores/sync`
5. Dwell → stop profile

Runs every 2 days via Windows Task Scheduler (`scripts/setup_tiktok_store_status_task.ps1`).

---

## Testing strategy

- **Pure-logic unit tests** (`test_hma_sync.py`): exercise `profile_to_sync_row`,
  `delete_profile`, `start_profile`, `stop_profile`, `interpret_start_response`.
- **Route tests** (`test_routes.py`): FastAPI `TestClient` with mocked upstream HTTP.
- **Supover tests** (`test_supover_sync.py`, `test_supover_stores.py`): validation,
  header construction, error propagation.
- No live HTTP. CI-safe.

Run with `pytest -q` from the project root (any OS).
