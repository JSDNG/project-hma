# Architecture

## Goals

1. **Single source of truth for HMA logic.** All fetch / start / stop code
   lives in one pure module (`app/hma_sync.py`); scripts are thin orchestrators.
2. **Stateless.** No database, no queue, no on-disk cache.
3. **Simple to run.** Two scripts, scheduled via Windows Task Scheduler.
4. **Explicit configuration.** All tunables come from environment variables
   (or a local `.env`), with no hardcoded defaults in code.

## Non-goals

- API server, persistence, rate limiting — explicitly out of scope.
- In-process background jobs. Scripts run as external, OS-scheduled jobs.

---

## Directory layout

```
project-hma/
├── app/                              # Core application package
│   ├── config.py                     # Settings (pydantic-settings) + cached get_settings()
│   ├── hma_sync.py                   # Pure helpers: fetch_profiles, start/stop/delete profile
│   ├── profile_actions.py            # Playwright browser actions (check_seller_status)
│   ├── supover_sync.py               # Pure helper: push_to_supover
│   ├── supover_stores.py             # Pure helpers: fetch/push store data, extract IDs
│   └── helpers/
│       ├── http.py                   # validate_api_credentials(), build_api_headers()
│       ├── logging.py                # setup_logging()
│       └── telegram.py              # send_telegram_message()
│
├── scripts/                          # OS-scheduled jobs
│   ├── sync_to_supover.py            # Job 1: HMA -> Supover profiles sync
│   ├── check_tiktok_store_status.py  # Job 2: TikTok store status check
│   ├── run_sync.bat                  # Windows launcher for sync_to_supover
│   ├── run_tiktok_store_status.bat   # Windows launcher for check_tiktok_store_status
│   ├── setup_sync_task.ps1           # Register the HMA-Supover-Sync scheduled task
│   ├── unregister_sync_task.ps1      # Remove the HMA-Supover-Sync scheduled task
│   ├── setup_tiktok_store_status_task.ps1    # Register HMA-TikTok-Store-Status task
│   └── unregister_tiktok_store_status_task.ps1
│
├── tests/
│   ├── conftest.py                   # Shared fixtures: settings override
│   ├── test_hma_sync.py              # Unit tests for pure helpers
│   ├── test_supover_stores.py        # Store fetch/ID extraction tests
│   └── test_supover_sync.py          # Push-to-Supover tests
│
├── docs/
│   ├── ARCHITECTURE.md               # This file
│   └── CHECK_SELLER_STATUS.md        # TikTok store status check flow
│
├── logs/                             # Log destination (gitignored)
├── pyproject.toml
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## Module responsibilities

### `app/helpers/http.py`

- `validate_api_credentials(api_key, url, url_env_name)` — strips and validates, raises `ValueError` if empty
- `build_api_headers(api_key_header, key, include_content_type)` — builds standard API headers

Used by: `supover_sync.py`, `supover_stores.py`.

### `app/helpers/telegram.py`

- `send_telegram_message(bot_token, chat_id, text)` — sends via Telegram Bot API; returns `False` on failure (never raises)

Used by: `scripts/check_tiktok_store_status.py`.

### `app/helpers/logging.py`

- `setup_logging(log_file, level)` — configures root logger (stdout + optional file)

Used by: both scripts.

### `app/hma_sync.py`

Pure functions, no global state:

- `fetch_profiles(session, base_url, timeout, profiles_path)`
- `fetch_profiles_response(session, base_url, timeout, profiles_path)`
- `profile_to_sync_row(profile, min_port, max_port)`
- `delete_profile(session, base_url, profile_id, timeout, profiles_path)`
- `start_profile(session, base_url, profile_id, timeout, profiles_path)`
- `stop_profile(session, base_url, profile_id, timeout, profiles_path)`
- `interpret_start_response(resp, start_success_code)`
- `parse_hma_body(resp)`

### `app/profile_actions.py`

- `SellerStatus` — frozen dataclass: `pending_settlement`, `payout_on_hold`, `bank_account_number`, `shop_status`, `all_elements_missing`
- `_read_xpath(page, xpath, timeout, log, field_name)` — shared DOM helper; returns `(text_content | None, found: bool)`
- `check_seller_status(ws_url, log, settings, region) -> SellerStatus` — navigates TikTok login page (`wait_for_url` homepage detection), then scrapes bills page for 3 DOM fields + 1 API field

Uses Playwright over CDP. All URLs, XPaths, timeouts come from `settings`.

### `app/supover_stores.py`

- `EligibleStore` — NamedTuple: `store_id`, `store_name`, `shop_code`, `region`, `profile_id`, `profile_name`, `proxy_host`, `proxy_port`, `proxy_username`, `proxy_password`, `seller`, `telegram`
- `fetch_dead_stores_with_balance(...)` — GET dead stores with balance
- `all_store_and_profile_ids(stores) -> list[EligibleStore]` — filter và normalise rows có HMA profile
- `push_store_status(...)` — POST store status (hoặc error) về Supover

### `app/supover_sync.py`

- `push_to_supover(session, url, api_key, payload, timeout, api_key_header)` — POSTs raw HMA response to Supover

### `app/config.py`

All configuration from `.env` via `pydantic-settings`. Exposed via `@lru_cache`-wrapped `get_settings()`.

---

## Scheduled jobs

### Supover profiles sync (`scripts/sync_to_supover.py`)

Forwards the raw HMA `/profiles` response to Supover verbatim. Runs twice
daily via Windows Task Scheduler.

### TikTok store status check (`scripts/check_tiktok_store_status.py`)

Key helpers: `_notify_supover_error` (push error về Supover cho mọi error path), `_process_store` (xử lý 1 store).

For each dead-with-balance store from Supover:
1. Test proxy via `api.ipify.org` → if dead, push Supover error + skip *(no Telegram)*
2. Start HMA profile → get `wsUrl` (failure → push Supover error + Telegram "Profile In Use" + skip)
3. `check_seller_status`: navigate TikTok login (region `GB` auto-remapped to `uk`); sleep `TIKTOK_LOGIN_WAIT_SECONDS`; detect homepage via `page.wait_for_url`
4. If `check_seller_status` raises → push Supover error + Telegram "Playwright Error" + skip
5. If `all_elements_missing` (not logged in) → push Supover error + skip *(no Telegram)*
6. Validate `SellerStatus` — if read error (`pending+hold == "0"` or `shop_status is None`) → push Supover error + Telegram "Element Read Error" + **abort all remaining stores**
7. If OK → POST `SellerStatus` data to Supover
8. Dwell `TIKTOK_DWELL_SECONDS` (only on success) → stop profile (always, in `finally`)

Runs every 2 days via Windows Task Scheduler.

---

## Testing strategy

- **Pure-logic unit tests** (`test_hma_sync.py`): exercise profile mapping,
  start/stop/delete helpers.
- **Supover tests** (`test_supover_sync.py`, `test_supover_stores.py`): validation,
  header construction, error propagation.
- No live HTTP. CI-safe.

Run with `pytest -q` from the project root.

---

## Logging

Both scripts configure the root logger on startup via `setup_logging` from
`app/helpers/logging.py`. Logs go to stdout and a dedicated file under `logs/`.
