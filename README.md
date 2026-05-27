# project-hma

Scheduled jobs that integrate the local **HideMyAcc (HMA)** desktop client
with **Supover** and **TikTok Seller Center**.

The project is **stateless** — no database, no API server. Two scripts run
on a schedule via Windows Task Scheduler.

---

## Features

1. **Supover Profile Sync** — pulls HMA profiles and pushes them to Supover
   (daily at 00:00 & 12:00).
2. **TikTok Store Status Check** — opens HMA browser profiles, scrapes
   TikTok Seller billing data, and pushes results to Supover (every 2 days
   at 04:00). Sends Telegram alerts on failures.

---

## Requirements

- **Python 3.11+** (developed against 3.13)
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
python -m playwright install chromium
```

### Windows (PowerShell)

```powershell
cd C:\path\to\project-hma
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
```

---

## Configure

Copy `.env.example` to `.env` and fill in all values:

```bash
cp .env.example .env
```

See `.env.example` for the full list of variables.

| Variable | Purpose |
|---|---|
| `HMA_LOCAL_API_BASE` | Local HMA REST API base URL |
| `HMA_PROFILES_PATH` | HMA profiles API path |
| `HMA_HTTP_TIMEOUT` | HTTP client timeout (seconds) |
| `HMA_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `HMA_START_SUCCESS_CODE` | HMA body `code` value for successful start |
| `HMA_MIN_TCP_PORT` / `HMA_MAX_TCP_PORT` | Valid TCP port range for proxy validation |
| `SUPOVER_API_KEY` | Shared secret for Supover API calls |
| `SUPOVER_API_KEY_HEADER` | Header name for API key |
| `SUPOVER_SYNC_URL` | Endpoint for profiles sync |
| `SUPOVER_DEAD_STORES_URL` | Endpoint to fetch dead-with-balance stores |
| `SUPOVER_STORES_SYNC_URL` | Endpoint to push store status data |
| `TIKTOK_SELLER_LOGIN_URL` | TikTok login page URL (with `{region}` placeholder) |
| `TIKTOK_SELLER_BILLS_URL` | TikTok bills page URL (with `{region}` placeholder) |
| `TIKTOK_SHOP_INFO_API_URL` | TikTok shop info API URL (with `{region}` placeholder) |
| `TIKTOK_ELEMENT_TIMEOUT` | Playwright element wait timeout (ms) |
| `TIKTOK_STEP_DELAY` | Delay between extraction steps (seconds) |
| `TIKTOK_DWELL_SECONDS` | Browser dwell time before stopping profile |
| `XPATH_PENDING_BALANCE` | XPath for pending balance element |
| `XPATH_ON_HOLD` | XPath for on-hold element |
| `XPATH_BANK_ACCOUNT` | XPath for bank account element |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token for error notifications |
| `TELEGRAM_CHAT_ID` | Telegram chat ID for error notifications |

---

## Scheduled Jobs

### 1. Supover Profile Sync

Pulls HMA `/profiles` and POSTs the raw response to Supover.

```bash
python -m scripts.sync_to_supover
```

**Schedule:** Daily at 00:00 and 12:00.

**Setup (Windows Task Scheduler):**

```powershell
.\scripts\setup_sync_task.ps1
```

**Exit codes:** `0` success, `1` config error, `2` HMA unreachable, `3` Supover error.

### 2. TikTok Store Status Check

For each dead-with-balance store: starts HMA profile, checks TikTok login
status, scrapes billing data, pushes to Supover.

```bash
python -m scripts.check_tiktok_store_status
```

**Schedule:** Every 2 days at 04:00.

**Setup (Windows Task Scheduler):**

```powershell
.\scripts\setup_tiktok_store_status_task.ps1
```

**Exit codes:** `0` success, `1` config error, `2` Supover error, `3` HMA
start failed, `4` Playwright error, `5` element read failure, `6` not logged in.

See [`docs/CHECK_SELLER_STATUS.md`](./docs/CHECK_SELLER_STATUS.md) for the
detailed flow.

---

## Tests

```bash
pytest -q
```

---

## Project layout

See [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md).
