# check_seller_status

Browser action chạy trên HMA profile để lấy 4 thông tin từ TikTok Seller, sau đó validate và POST về Supover.

## Flow

```
Bills page ──► pending_balance ──delay──► on_hold ──delay──► bank_account ──delay──► shop_status (API) ──delay──► Validate ──► POST Supover ──► Dwell
```

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
| `pending_settlement == "0"` **AND** `payout_on_hold == "0"` | Element read lỗi (cả 2 default) |
| `bank_account_number is None` | Element read lỗi |
| `shop_status is None` | API call lỗi hoặc không có data |

Nếu bất kỳ điều kiện nào xảy ra:
- Log error chi tiết
- Gửi thông báo **Telegram** (bot token + chat_id từ `.env`)
- **KHÔNG push data** lên Supover (tránh ghi đè data cũ bằng data rỗng)
- Exit code = `5` (`EXIT_ELEMENT_READ`)

Nếu validate OK:
- Log 4 giá trị: `pending_settlement`, `payout_on_hold`, `bank_account_number`, `shop_status`
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
| `5` | Element read error (validate fail → đã gửi Telegram) |

## File liên quan

| File | Vai trò |
|---|---|
| `app/profile_actions.py` | Hàm `check_seller_status` — đọc element + gọi API |
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

Mở **PowerShell** rồi chạy:

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

### File liên quan

| File | Vai trò |
|---|---|
| `scripts/setup_tiktok_store_status_task.ps1` | Đăng ký scheduled task (2 ngày/lần, 04:00) |
| `scripts/run_tiktok_store_status.bat` | Batch launcher (activate venv, chạy Python, ghi log) |

## Cấu hình

Tất cả thông số nằm trong `.env`, không hardcode trong code:

```env
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
