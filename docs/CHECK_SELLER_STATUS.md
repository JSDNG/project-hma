# check_seller_status

Browser action chạy trên HMA profile để lấy 4 thông tin từ TikTok Seller, sau đó validate và POST về Supover.

## Flow

```
Proxy alive check ──► HMA /profiles/start ──► Login page ──► Check redirect ──► Bills page ──► pending_balance ──delay──► on_hold ──delay──► bank_account ──delay──► shop_status (API) ──delay──► Validate ──► POST Supover ──► Dwell
```

### Bước 0 — Proxy alive check

- Trước khi gọi HMA `/profiles/start`, script GET `https://api.ipify.org?format=json` qua proxy `(host:port[, user:pass])` lấy từ `profile_hma`.
- Sống (HTTP 2xx) → log + sleep `PROXY_CHECK_DWELL_SECONDS` giây → tiếp tục mở profile.
- Chết (timeout / 4xx / 5xx / không kết nối được) → gửi Telegram **"Proxy Dead"** kèm `proxy host:port` và lý do raw → sleep `PROXY_CHECK_DWELL_SECONDS` → exit code `7`, skip store, tiếp tục store kế tiếp.
- Profile không có proxy → skip step này, đi thẳng tới `/profiles/start`.

### Bước 1 — HMA `/profiles/start`

- Nếu `/profiles/start` trả về lỗi (HTTP 400 hoặc `body.code != 1`) — thường là seller đang dùng profile — gửi Telegram **"Profile In Use"** → exit code `3`, skip store, tiếp tục.

### Bước 2 — Login Check

- URL: `TIKTOK_SELLER_LOGIN_URL` (có `{region}` placeholder)
- `region == "gb"` → đổi thẳng sang `"uk"` cho cả login + bills + shop_info (không thử `gb` trước).
- Chờ trang load hoàn toàn (`load` + `networkidle`) + `TIKTOK_STEP_DELAY` giây
- Nếu URL chứa `homepage` → đã đăng nhập → tiếp tục bước kế.
- Nếu URL không chứa `homepage` → chưa đăng nhập → gửi Telegram **"Not Logged In"**, skip store, chuyển store kế tiếp.
- Nếu `page.goto` raise exception (mạng, profile crash, …) → gửi Telegram **"Playwright Error"** kèm raw exception → exit code `4`, stop profile, tiếp tục store kế tiếp.

### Bước 3 — Pending Balance (trang Bills)

- URL: `TIKTOK_SELLER_BILLS_URL` (có `{region}` placeholder)
- Chờ DOM loaded, sau đó chờ element visible (timeout `TIKTOK_ELEMENT_TIMEOUT`)
- XPath: `XPATH_PENDING_BALANCE`
- Nếu không tìm thấy → default `"0"`, log warning
- **Đợi `TIKTOK_STEP_DELAY` giây**

### Bước 4 — On Hold (trang Bills)

- Cùng trang Bills, không reload
- XPath: `XPATH_ON_HOLD`
- Nếu không tìm thấy → default `"0"`, log warning
- **Đợi `TIKTOK_STEP_DELAY` giây**

### Bước 5 — Bank Account (trang Bills)

- Cùng trang Bills, không reload
- XPath: `XPATH_BANK_ACCOUNT`
- Nếu không tìm thấy → `None`, log warning
- **Đợi `TIKTOK_STEP_DELAY` giây**

### Bước 6 — Shop Status (API call)

- URL: `TIKTOK_SHOP_INFO_API_URL` (có `{region}` placeholder)
- Gọi API qua `page.evaluate()` (fetch trong browser context)
- Parse `resp.data.seller.shop_status`
- Nếu API lỗi hoặc không có data → `None`, log warning
- **Đợi `TIKTOK_STEP_DELAY` giây**

### Bước 7 — Validate & POST Supover

Trước khi POST, script validate kết quả:

| Điều kiện | Ý nghĩa |
|---|---|
| Cả 3 element đều không tìm thấy | Có thể chưa đăng nhập (all_elements_missing) |
| `pending_settlement == "0"` **AND** `payout_on_hold == "0"` | Element read lỗi (cả 2 default) |
| `bank_account_number is None` | Element read lỗi |
| `shop_status is None` | API call lỗi hoặc không có data |

Nếu all_elements_missing:
- Log warning
- Gửi thông báo **Telegram** — "Not Logged In"
- **KHÔNG push data** lên Supover
- Exit code = `6` (`EXIT_NOT_LOGGED_IN`) — **tiếp tục store kế tiếp**

Nếu có lỗi element read (nhưng không phải all missing):
- Log error chi tiết
- Gửi thông báo **Telegram** — "Element Read Error"
- **KHÔNG push data** lên Supover
- Exit code = `5` (`EXIT_ELEMENT_READ`) — **dừng toàn bộ**

Nếu validate OK:
- POST tới `SUPOVER_STORES_SYNC_URL` với `store_id`, `tt_shop_code`, `profile_id`, và 4 field trên

### Bước 8 — Dwell

- Giữ browser mở `TIKTOK_DWELL_SECONDS` giây trước khi stop profile (luôn chạy dù validate fail)

## Exit codes

| Code | Ý nghĩa |
|---|---|
| `0` | Thành công |
| `1` | Lỗi cấu hình (missing key / URL) |
| `2` | Supover unreachable / bad response / no eligible profile |
| `3` | HMA /profiles/start failed — đã gửi Telegram "Profile In Use", tiếp tục store kế tiếp |
| `4` | Playwright connect hoặc navigation error — đã gửi Telegram "Playwright Error", tiếp tục store kế tiếp |
| `5` | Element read error (validate fail → đã gửi Telegram, dừng toàn bộ) |
| `6` | Not logged in (đã gửi Telegram, tiếp tục store kế tiếp) |
| `7` | Proxy dead (đã gửi Telegram, tiếp tục store kế tiếp) |

## File liên quan

| File | Vai trò |
|---|---|
| `app/profile_actions.py` | Hàm `check_seller_status` — login check, đọc element, gọi API |
| `app/supover_stores.py` | Hàm `push_store_status` POST về Supover |
| `app/helpers/telegram.py` | Hàm `send_telegram_message` gửi thông báo lỗi |
| `scripts/check_tiktok_store_status.py` | Script orchestration (loop qua stores, validate, notify) |
| `.env` | Tất cả URL, XPath, timeout, delay, Telegram credentials |

## Chạy

```bash
python -m scripts.check_tiktok_store_status
```

Log file: `logs/check_tiktok_store_status.log`

## Setup trên máy Windows mới

Trước khi chạy script lần đầu trên một máy Windows mới, cần thực hiện đủ 3 bước sau. Thiếu bất kỳ bước nào đều có thể gây lỗi runtime.

### Bước 1 — Cài Microsoft Visual C++ Redistributable

Playwright sử dụng `sync_playwright` qua thư viện `greenlet` — một C extension cần MSVC runtime DLL (`vcruntime140.dll`, `msvcp140.dll`). Nếu chưa cài, script sẽ crash ngay khi import với lỗi:

```
DLL load failed while importing _greenlet: The specified module could not be found.
```

Cài bằng winget (khuyến nghị):

```powershell
winget install Microsoft.VCRedist.2015+.x64
```

Hoặc tải thủ công tại: `https://aka.ms/vs/17/release/vc_redist.x64.exe`, sau đó chạy:

```powershell
Invoke-WebRequest -Uri https://aka.ms/vs/17/release/vc_redist.x64.exe -OutFile vc_redist.x64.exe
.\vc_redist.x64.exe /quiet /norestart
```

### Bước 2 — Cài Python dependencies

```powershell
pip install -r requirements.txt
```

### Bước 3 — Cài Playwright browser binaries

```powershell
python -m playwright install chromium
```

> Bước 3 cài browser binary riêng biệt, không được bao gồm khi `pip install playwright`. Bỏ qua bước này, script sẽ lỗi khi cố kết nối CDP.

---

## Lên lịch chạy tự động (Windows Task Scheduler)

Script chạy **mỗi 2 ngày lúc 06:00** qua Windows Task Scheduler.

### Setup

```powershell
.\scripts\setup_tiktok_store_status_task.ps1
```

Nếu muốn task chạy cả khi không login:

```powershell
.\scripts\setup_tiktok_store_status_task.ps1 -RunWhetherLoggedOn
```

### Test

```powershell
Start-ScheduledTask -TaskName 'HMA-TikTok-Store-Status'
```

### Log

| File | Nội dung |
|---|---|
| `logs/tiktok_store_status.bat.log` | Output từ batch launcher |
| `logs/check_tiktok_store_status.log` | Log chi tiết từ Python |

## Cấu hình

Tất cả thông số nằm trong `.env`, không hardcode trong code:

```env
TIKTOK_SELLER_LOGIN_URL=https://seller-{region}.tiktok.com/account/login
TIKTOK_SELLER_BILLS_URL=https://seller-{region}.tiktok.com/finance/bills
TIKTOK_SHOP_INFO_API_URL=https://seller-{region}.tiktok.com/api/v1/seller/common/get
TIKTOK_ELEMENT_TIMEOUT=15000
TIKTOK_STEP_DELAY=5
TIKTOK_DWELL_SECONDS=60
XPATH_PENDING_BALANCE=...
XPATH_ON_HOLD=...
XPATH_BANK_ACCOUNT=...

# Telegram notifications (bắt buộc để nhận thông báo lỗi)
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

### Hằng số trong script (không nằm trong `.env`)

| Hằng số | Mặc định | Ý nghĩa |
|---|---|---|
| `PROXY_TEST_URL` | `https://api.ipify.org?format=json` | Trang dùng để test proxy |
| `PROXY_TEST_TIMEOUT` | `30` (giây) | Timeout cho request test proxy |
| `PROXY_CHECK_DWELL_SECONDS` | `30` (giây) | Delay sau mỗi lần check proxy (cả alive và dead) |

Khi TikTok thay đổi layout, chỉ cần sửa XPath trong `.env`.
