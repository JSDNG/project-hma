# check_seller_status

Browser action chạy trên HMA profile để lấy 4 thông tin từ TikTok Seller, sau đó validate và POST về Supover.

## Flow

```
Login page ──► Check redirect ──► Bills page ──► pending_balance ──delay──► on_hold ──delay──► bank_account ──delay──► shop_status (API) ──delay──► Validate ──► POST Supover ──► Dwell
```

### Bước 0 — Login Check

- URL: `TIKTOK_SELLER_LOGIN_URL` (có `{region}` placeholder)
- Chờ trang load hoàn toàn (`load` + `networkidle`) + `TIKTOK_STEP_DELAY` giây
- Nếu URL chứa `homepage` → đã đăng nhập → tiếp tục bước 1
- Nếu URL không chứa `homepage` → chưa đăng nhập → gửi Telegram, skip store, chuyển store kế tiếp

### Bước 1 — Pending Balance (trang Bills)

- URL: `TIKTOK_SELLER_BILLS_URL` (có `{region}` placeholder)
- Chờ DOM loaded, sau đó chờ element visible (timeout `TIKTOK_ELEMENT_TIMEOUT`)
- XPath: `XPATH_PENDING_BALANCE`
- Nếu không tìm thấy → default `"0"`, log warning
- **Đợi `TIKTOK_STEP_DELAY` giây**

### Bước 2 — On Hold (trang Bills)

- Cùng trang Bills, không reload
- XPath: `XPATH_ON_HOLD`
- Nếu không tìm thấy → default `"0"`, log warning
- **Đợi `TIKTOK_STEP_DELAY` giây**

### Bước 3 — Bank Account (trang Bills)

- Cùng trang Bills, không reload
- XPath: `XPATH_BANK_ACCOUNT`
- Nếu không tìm thấy → `None`, log warning
- **Đợi `TIKTOK_STEP_DELAY` giây**

### Bước 4 — Shop Status (API call)

- URL: `TIKTOK_SHOP_INFO_API_URL` (có `{region}` placeholder)
- Gọi API qua `page.evaluate()` (fetch trong browser context)
- Parse `resp.data.seller.shop_status`
- Nếu API lỗi hoặc không có data → `None`, log warning
- **Đợi `TIKTOK_STEP_DELAY` giây**

### Bước 5 — Validate & POST Supover

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

### Bước 6 — Dwell

- Giữ browser mở `TIKTOK_DWELL_SECONDS` giây trước khi stop profile (luôn chạy dù validate fail)

## Exit codes

| Code | Ý nghĩa |
|---|---|
| `0` | Thành công |
| `1` | Lỗi cấu hình (missing key / URL) |
| `2` | Supover unreachable / bad response / no eligible profile |
| `3` | HMA /profiles/start failed |
| `4` | Playwright connect hoặc navigation error |
| `5` | Element read error (validate fail → đã gửi Telegram, dừng toàn bộ) |
| `6` | Not logged in (đã gửi Telegram, tiếp tục store kế tiếp) |

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

## Lên lịch chạy tự động (Windows Task Scheduler)

Script chạy **mỗi 2 ngày lúc 04:00** qua Windows Task Scheduler.

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

Khi TikTok thay đổi layout, chỉ cần sửa XPath trong `.env`.
