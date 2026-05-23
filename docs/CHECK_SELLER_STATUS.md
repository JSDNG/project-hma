# check_seller_status

Browser action chạy trên HMA profile để lấy 3 thông tin từ TikTok Seller US.

## Flow

```
Bills page ──► pending_balance ──5s──► bank_account ──5s──► Health-center page ──► account_status ──5s──► Log 3 giá trị ──► Dwell 300s
```

### Bước 1 — Pending Balance (trang Bills)

- URL: `https://seller-us.tiktok.com/finance/bills`
- Chờ DOM loaded, sau đó chờ element visible (timeout 15s)
- XPath:
  ```
  //div/div/div[3]/div/div[2]/div/div[1]/div/div/div/div[1]/div/div/div[1]/div[1]/div[2]/span
  ```
- Kết quả: text content của span → `pending_balance`
- Nếu không tìm thấy → `None`, log warning
- **Đợi 5 giây**

### Bước 2 — Bank Account (trang Bills)

- Cùng trang Bills, không reload
- XPath:
  ```
  //div[1]/div[2]/main/div/div/div[3]/div/div[2]/div/div[1]/div/div/div/div[2]/div/div/div/div[2]/div/div[2]/div/span[2]
  ```
- Kết quả: text content của span → `bank_account`
- Nếu không tìm thấy → `None`, log warning
- **Đợi 5 giây**

### Bước 3 — Account Status (trang Health Center)

- URL: `https://seller-us.tiktok.com/health-center`
- Chờ DOM loaded, sau đó chờ element visible (timeout 15s)
- XPath:
  ```
  //div[1]/section/nav/div/div/div/div/div/div/div[1]/div[1]/div[2]
  ```
- Chỉ ghi nhận nếu text **đúng** là `"Account deactivated"`
- Nếu text khác hoặc element không tồn tại → `None`
- **Đợi 5 giây**

### Bước 4 — Log kết quả

```
pending_balance=$VALUE bank_account=$VALUE account_status=$VALUE
```

### Bước 5 — Dwell 300 giây

Giữ browser mở 5 phút trước khi disconnect CDP.

## File liên quan

| File | Vai trò |
|---|---|
| `app/profile_actions.py` | Hàm `check_seller_status` và các XPath constant |
| `scripts/open_first_dead_store_tiktok.py` | Script gọi hàm này (start profile → action → stop profile) |

## Chạy

```bash
python -m scripts.open_first_dead_store_tiktok
```

Log file: `logs/open_first_dead_store_tiktok.log`

## Sửa đổi XPath

Tất cả XPath nằm ở đầu file `app/profile_actions.py` dưới dạng constant:

```python
PENDING_BALANCE_XPATH = "//div/div/div[3]/..."
BANK_ACCOUNT_XPATH   = "//div[1]/div[2]/main/..."
ACCOUNT_STATUS_XPATH  = "//div[1]/section/nav/..."
```

Khi TikTok thay đổi layout, chỉ cần cập nhật các constant này.
