# check_seller_status

Browser action chạy trên HMA profile để lấy 4 thông tin từ TikTok Seller US, sau đó POST về Supover.

## Flow

```
Bills page ──► pending_balance ──delay──► on_hold ──delay──► bank_account ──delay──► Health-center page ──► account_status ──delay──► Log 4 giá trị ──► POST Supover ──► Dwell
```

### Bước 1 — Pending Balance (trang Bills)

- URL: `TIKTOK_SELLER_BILLS_URL`
- Chờ DOM loaded, sau đó chờ element visible (timeout `TIKTOK_ELEMENT_TIMEOUT`)
- XPath: `XPATH_PENDING_BALANCE`
- Nếu không tìm thấy → `None`
- **Đợi `TIKTOK_STEP_DELAY` giây**

### Bước 2 — On Hold (trang Bills)

- Cùng trang Bills, không reload
- XPath: `XPATH_ON_HOLD`
- Nếu không tìm thấy → `None`
- **Đợi `TIKTOK_STEP_DELAY` giây**

### Bước 3 — Bank Account (trang Bills)

- Cùng trang Bills, không reload
- XPath: `XPATH_BANK_ACCOUNT`
- Nếu không tìm thấy → `None`
- **Đợi `TIKTOK_STEP_DELAY` giây**

### Bước 4 — Account Status (trang Health Center)

- URL: `TIKTOK_HEALTH_CENTER_URL`
- XPath: `XPATH_ACCOUNT_STATUS`
- Chỉ ghi nhận nếu text đúng là `TIKTOK_ACCOUNT_DEACTIVATED_TEXT`
- Nếu text khác hoặc element không tồn tại → `None`
- **Đợi `TIKTOK_STEP_DELAY` giây**

### Bước 5 — Log & POST Supover

- Log 4 giá trị: `pending_balance`, `on_hold`, `bank_account`, `account_status`
- POST tới `SUPOVER_STORES_SYNC_URL` với `store_id`, `profile_id`, và 4 field trên

### Bước 6 — Dwell

- Giữ browser mở `TIKTOK_DWELL_SECONDS` giây trước khi stop profile

## File liên quan

| File | Vai trò |
|---|---|
| `app/profile_actions.py` | Hàm `check_seller_status` |
| `app/supover_stores.py` | Hàm `push_store_status` POST về Supover |
| `scripts/check_tiktok_store_status.py` | Script orchestration (loop qua stores) |
| `.env` | Tất cả URL, XPath, timeout, delay |

## Chạy

```bash
python -m scripts.check_tiktok_store_status
```

Log file: `logs/check_tiktok_store_status.log`

## Cấu hình

Tất cả thông số nằm trong `.env`, không hardcode trong code:

```env
TIKTOK_SELLER_BILLS_URL=https://seller-us.tiktok.com/finance/bills
TIKTOK_HEALTH_CENTER_URL=https://seller-us.tiktok.com/health-center
TIKTOK_ACCOUNT_DEACTIVATED_TEXT=Account deactivated
TIKTOK_ELEMENT_TIMEOUT=15000
TIKTOK_STEP_DELAY=5
TIKTOK_DWELL_SECONDS=100
XPATH_PENDING_BALANCE=...
XPATH_ON_HOLD=...
XPATH_BANK_ACCOUNT=...
XPATH_ACCOUNT_STATUS=...
```

Khi TikTok thay đổi layout, chỉ cần sửa XPath trong `.env`.
