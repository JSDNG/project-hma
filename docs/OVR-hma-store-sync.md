# OVR — HMA Store Sync

**Ngày:** 2026-06-03
**Người soạn:** KhanhNN (Dev Lead)
**Đối tượng đọc:** CEO, Head of Resource, Management, Dev team
**Trạng thái doc:** phản ánh **source code đã deploy** tại branch hiện tại. Phần chưa triển khai được đánh dấu rõ **[ĐỀ XUẤT — chưa code]**.

---

## TL;DR

Tính năng **"Kết nối store với HMA"** dùng bảng `profile_hma` làm **source-of-truth mapping store ↔ HMA profile** kiêm **mirror cache** pool profile từ HMA. Một **Tool VPS** (repo riêng) làm cầu nối giữa Supover (cloud) và HMA (local API `127.0.0.1:2268`). Toàn bộ tích hợp gói trong 3 nhóm:

- **Nhóm A — API ở Supover** (3 endpoint inbound cho Tool VPS gọi, auth `hma.inbound` x-api-key): `POST /api/hma/profiles/sync`, `GET /api/hma/stores/dead-with-balance`, `POST /api/hma/stores/sync`.
- **Nhóm B — Giao diện ở Supover** (4 tab HMA tại `Store → Store List → Store HMA`): Store Unmapped, Store Dead Sync, Store Dead Error Sync, HMA Profile Deletion. + UI gán profile khi Edit Store.
- **Nhóm C — Xử lý ở Tool VPS** (repo `project-hma`, Python + Playwright + Windows Task Scheduler, 2 job): Job 1 pull pool HMA → push mirror sync (00:00 & 12:00); Job 2 pull store DIE còn tiền → mở HMA browser (Playwright qua `wsUrl`) scrape TikTok Seller Center → push sync (mỗi 2 ngày 04:00).

**[ĐỀ XUẤT — chưa code]** Cleanup profile không dùng: thêm cột `last_opened_at` lấy từ cloud API `lastActivity`, tab "HMA Profile Deletion" lọc **chưa map store VÀ > 60 ngày chưa open** (xem §9).

---

## Mục lục

1. [Bối cảnh](#1-bối-cảnh)
2. [Vấn đề cần giải quyết](#2-vấn-đề-cần-giải-quyết)
3. [Kiến trúc tổng thể](#3-kiến-trúc-tổng-thể)
4. [Nhóm A — API ở Supover](#4-nhóm-a--api-ở-supover)
5. [Nhóm B — Giao diện ở Supover (4 tab)](#5-nhóm-b--giao-diện-ở-supover-4-tab)
6. [Cron dọn `profile_hma` (chạy trên Supover)](#6-cron-dọn-profile_hma-chạy-trên-supover)
7. [Nhóm C — Xử lý ở Tool VPS](#7-nhóm-c--xử-lý-ở-tool-vps)
8. [Rủi ro chính](#8-rủi-ro-chính)
9. [Đề xuất chưa triển khai — cleanup profile theo last-opened](#9-đề-xuất-chưa-triển-khai--cleanup-profile-theo-last-opened)
10. [Quyết định đã chốt](#10-quyết-định-đã-chốt)
11. [Open Questions](#11-open-questions)
12. [Ngoài phạm vi](#12-ngoài-phạm-vi)

---

## 1. Bối cảnh

Supover Beta quản lý hàng trăm TikTok Shop + Etsy store. Mỗi store cần **1 HMA profile riêng** (antidetect browser: fingerprint + proxy) để nền tảng không nhận diện cùng 1 thiết bị quản nhiều shop. Công ty dùng gói **Hidemyacc Business** ($99/tháng, 1000 profile slot, sub-account, có API access — API yêu cầu **Team plan trở lên**).

**Phân loại store**: 4 trạng thái **NEW(1), LIVE(2), DEACTIVE(3), FROZEN(4)**. DEACTIVE + FROZEN = **DIE/SUSPEND**, cần theo dõi sát.

**Hiện trạng sync store info** qua extension **Supover Seller Hub** (Chrome extension): auto sync mỗi 15 phút khi seller online + có tab TikTok mở. Hạn chế: phụ thuộc seller online → store DIE/SUSPEND bị bỏ rơi không sync → mất visibility. Update này bổ sung **Tool VPS** gap-fill cho nhóm store đó.

**3 cơ chế dựa trên sync timestamp đã có** (giữ nguyên): `block_sync` per-order, `block_user_status` per-user, dashboard "Important Task (Sync Info Store)".

---

## 2. Vấn đề cần giải quyết

1. **Không có source-of-truth mapping HMA ↔ Store** → giải bằng bảng `profile_hma` (`store_id` nullable UNIQUE).
2. **Gap visibility store DIE/SUSPEND seller bỏ rơi** → Tool VPS scrape gap-fill.
3. **Không phân biệt LIVE vs DIE/SUSPEND** → chỉ scrape DIE/SUSPEND còn tiền treo (tiết kiệm effort + giảm risk detect).
4. **HMA profile orphan ăn quota** → list profile chưa map để review/xóa. *Lưu ý:* không thể xóa chỉ vì `store_id IS NULL` — nhiều profile **đang dùng nhưng chưa map** (Etsy, chờ gán); cần thêm tín hiệu "lâu không mở" (xem §9).
5. **Seller bị bắt sync manual oan** → Tool VPS refresh timestamp DIE/SUSPEND qua endpoint dedicated.

---

## 3. Kiến trúc tổng thể

### 3.1. Kiến trúc 3 lớp

API Hidemyacc **local** (`http://127.0.0.1:2268`) chỉ gọi từ máy đang mở app HMA → bắt buộc có **agent trung gian** = Tool VPS.

```text
┌─────────────────────────────────────────────┐
│ LỚP 1 — SUPOVER (cloud)                       │
│  Nhóm A: 3 API inbound (hma.inbound)          │
│  Nhóm B: 4 tab web UI + Edit Store mapping    │
│  DB: profile_hma (mapping + mirror) + cron    │
└───────────────┬───────────────────────────────┘
                │ HTTPS + x-api-key
                ▼
┌─────────────────────────────────────────────┐
│ LỚP 2 — TOOL VPS (repo project-hma, Python)   │
│  Python + Playwright + Windows Task Scheduler │
│  HMA desktop login; stateless; 2 scheduled job│
└───────────────┬───────────────────────────────┘
                │ HTTP localhost 2268  +  Playwright CDP wsUrl
                ▼
┌─────────────────────────────────────────────┐
│ LỚP 3 — HMA LOCAL API + BROWSER               │
│  /profiles, /profiles/start|stop, browser     │
└─────────────────────────────────────────────┘
```

### 3.2. Bảng `profile_hma` — 2 vai trò

- **(a) Mapping** store ↔ profile: cột `store_id` nullable **UNIQUE** (1 profile ↔ tối đa 1 store).
- **(b) Mirror cache** pool profile từ HMA: Tool VPS định kỳ push toàn bộ pool → upsert keyed `profile_id`, stamp `last_seen_at = NOW()`.

Source-of-truth của **profile entity** = HMA app; của **mapping** = Supover. Mirror cache cho phép: validate ID instant (query bảng), orphan detect (`store_id IS NULL`), phát hiện profile bị xóa thủ công bên HMA (`last_seen_at` ngừng update → cron cleanup).

Quan hệ **1-1**: mỗi store có tối đa 1 profile, mỗi profile thuộc tối đa 1 store (enforce bằng `UNIQUE(store_id)`).

---

## 4. Nhóm A — API ở Supover

**Auth chung:** mọi endpoint yêu cầu header **`x-api-key`** = shared secret (env `HMA_INBOUND_API_KEY`). Sai/thiếu key → **401**; server chưa cấu hình key → **503**.

**Chỉ 3 endpoint inbound** cho Tool VPS gọi. (Danh sách profile/store "unmapped" KHÔNG phải API — là tab web, xem Nhóm B.)

### 4.1. `POST /api/hma/profiles/sync` — Mirror sync pool profile

**Tác dụng:** Tool VPS đẩy toàn bộ danh sách profile từ HMA về Supover; Supover lưu/cập nhật vào bảng `profile_hma` (mirror cache).

**Body:**
```json
{
  "data": [
    {
      "id": "<profile-id>",
      "name": "<profile-name>",
      "proxy": {
        "autoProxyServer": "<host>",
        "port": 8080,
        "autoProxyUsername": "<user>",
        "autoProxyPassword": "<pass>"
      }
    }
  ]
}
```
*(proxy host đọc từ `autoProxyServer`, nếu trống thì lấy `host`.)*

**Xử lý:** upsert theo `profile_id` (bỏ profile thiếu `id`; port không hợp lệ → null); **giữ nguyên `store_id`** đã map (không ghi đè mapping seller); stamp `last_seen_at = NOW()` cho mọi row. Với profile đã map store → đánh dấu store đó coi như vừa sync.

**Response:**
```json
{ "status": true, "received": 3000, "upserted": 2987 }
```
`received` (số nhận) vs `upserted` (số ghi) để Tool tự kiểm drift.

### 4.2. `GET /api/hma/stores/dead-with-balance` — Store DIE còn tiền treo

**Tác dụng:** trả danh sách store TikTok **đã chết (DIE/SUSPEND) nhưng còn tiền** để Tool VPS mở HMA browser vào scrape kiểm tra.

**Query:** `page` (mặc định 1), `limit` (≤ 1000).

**Điều kiện chọn store:** TikTok · `active=0` · **đã gán** HMA profile · còn `payout_on_old > 50` HOẶC `pending_settlement > 50` (USD) · seller thuộc team **Dragon Media**.

**Response:**
```json
{
  "status": true,
  "page": 1, "limit": 100, "total": 42, "last_page": 1,
  "data": [
    {
      "store_id": 123, "domain": "...", "shop_code": "...", "region": "US",
      "status": "inactive", "hold": 1250.50, "pending": 800,
      "bank_account": "...", "seller": "<username>", "telegram": "...",
      "last_synced_at": "2026-06-01 09:16:53",
      "profile_hma": {
        "profile_id": "...", "profile_name": "...",
        "proxy": "<host>", "port": 8080,
        "username": "...", "password": "...", "user_agent": "..."
      }
    }
  ]
}
```
Mỗi row kèm **đầy đủ thông tin profile HMA** → đủ cho Tool mở profile + scrape.

### 4.3. `POST /api/hma/stores/sync` — Tool VPS đẩy kết quả scrape về

**Tác dụng:** sau khi scrape TikTok Seller Center, Tool đẩy số liệu store về; Supover so với dữ liệu cũ → cập nhật → bắn Telegram khi có thay đổi.

**Body:**
```jsonc
{
  "store_id": 123,             // bắt buộc
  "tt_shop_code": "...",       // bắt buộc
  "profile_id": "...",         // bắt buộc
  "payout_on_hold": 1250.50,
  "pending_settlement": 800,
  "bank_account_number": "...",
  "shop_status": 3,            // 1=New 2=Live 3=Deactive 4=Frozen
  "region": "US"               // US/GB/UK/DE/ES/FR
}
```

**Xử lý:**
1. Kiểm tra store tồn tại (sai → **404**); `tt_shop_code` và `profile_id` phải khớp store (sai → **422**).
2. Quy đổi tiền local → **USD** theo region (GB/UK→GBP, DE/ES/FR→EUR, còn lại ×1.0).
3. So field cũ vs mới (tiền làm tròn 2 số). Cập nhật dữ liệu store; nếu `shop_status` đổi → cập nhật cờ `active` (LIVE→1, khác→0) + ghi timeline `store_died`/`store_reconnected`; refresh mốc `hma_last_synced_at`.
4. **Bắn Telegram** liệt kê các field thay đổi (`old → new`).

**Response:**
```json
{
  "status": true,
  "message": "Store data updated.",
  "updated": 2,
  "changes": {
    "payout_on_old": { "old": "1000.00", "new": "1250.50" },
    "shop_status":   { "old": 2, "new": 3 }
  }
}
```
(`changes` = các field thay đổi, kèm cặp old/new.)

> **Pattern Smart Server – Dumb Agent:** mọi so sánh + alert + đổi trạng thái nằm ở Supover. Tool chỉ scrape + POST. Đổi template/credential/chat Telegram không cần redeploy Tool.

### 4.4. Endpoint legacy (ngoài bộ inbound)

`POST /api/update-hma` — trigger nội bộ cũ, **không** qua auth `hma.inbound`, không thuộc bộ 3 endpoint của Tool VPS.

---

## 5. Nhóm B — Giao diện ở Supover (4 tab)

**Entry point:** `Store → Store List` → nút **"Store HMA"** → trang `/store/hma` (quyền `manage.store`). Trang có **5 tab**: 4 tab HMA dưới đây + 1 tab **TikTok Resource** (tính năng cũ đặt chung trang, không thuộc luồng HMA-sync). Mỗi tab 20 dòng/trang, đều có nút **Export Excel**.

**Phân quyền hiển thị:** Admin/Dev/Resource thấy hết; Leader thấy team mình; Seller thấy store mình.

### 5.1. Tab "Store Unmapped"

Store TikTok/Etsy **chưa gán** profile HMA, seller team Dragon Media, thuộc 1 trong 2 nhóm: **(active)** đang hoạt động + tạo > 1 ngày; **(inactive)** đã tắt nhưng còn tiền (`payout_on_old > 50` hoặc `pending_settlement > 50`). Mặc định hiện cả 2; filter `status` lọc riêng từng nhóm. Etsy cũng vào danh sách (Etsy cũng dùng HMA browser).

### 5.2. Tab "Store Dead Sync" / "Store Dead Error Sync"

Dùng chung dữ liệu với API §4.2 (store DIE đã gán, còn tiền > 50). Tab **Error Sync** thêm điều kiện **`hma_last_synced_at` quá 2 ngày** (hoặc chưa từng sync) → soi store DIE còn tiền mà Tool lâu chưa scrape.

### 5.3. Tab "HMA Profile Deletion" — profile gợi ý xóa

**Hiện tại (đã deploy):** liệt kê profile **chưa map store nào** + còn tồn tại trên HMA (vừa sync trong 24h qua) + đã qua 7 ngày onboarding.
→ hiện **chỉ dựa vào "chưa map store"**. Phần "> 60 ngày chưa open" là **[ĐỀ XUẤT — chưa code]**, xem §9.

### 5.4. UI gán profile khi Edit Store

Màn Edit Store có ô nhập **HMA Profile ID**. Khi lưu:
- ID rỗng / trùng binding cũ → bỏ qua; ID đã thuộc store khác → **báo lỗi**; ID hợp lệ (chưa gán, hoặc của chính store này) → gán; ID chưa có trong mirror → tạo **bản ghi tạm** (Tool sync sau sẽ điền đủ proxy/tên).
- Gán **atomic** (gỡ binding cũ rồi gán mới, ràng buộc UNIQUE chống tranh chấp). Hai người gán cùng lúc 1 profile → 1 người nhận lỗi **"please retry"** (HTTP 409).

---

## 6. Cron dọn `profile_hma` (chạy trên Supover)

> Cron này là **job phía Supover** (Laravel scheduler), KHÔNG phải việc của Tool VPS.

**Cron `hma:cleanup-pending-stubs`** — chạy **hằng ngày 03:00 (giờ VN)** trên Supover, xóa bản ghi `profile_hma` quá **3 ngày** không được refresh:

```sql
DELETE FROM profile_hma
WHERE last_seen_at < NOW() - INTERVAL 3 DAY
   OR (last_seen_at IS NULL AND created_at < NOW() - INTERVAL 3 DAY)
```
Cover: (a) stub seller nhập sai (never promote), (b) admin xóa profile thủ công bên HMA (Tool VPS ngừng push → `last_seen_at` đứng), (c) free-pool rớt khỏi HMA. **Không có health gate** → nếu Tool VPS sập > 3 ngày, cron sẽ wipe pool → **phải monitor uptime Tool VPS SLA < 3 ngày**.

---

## 7. Nhóm C — Xử lý ở Tool VPS

**Repo:** `project-hma` (riêng, `D:\Projects\project-hma`). **Stack:** Python 3.11+ · `requests` · **Playwright** (Chromium, connect qua CDP) · `pydantic-settings`. **Stateless** (không DB / queue / cache đĩa / API server). Chạy bằng **Windows Task Scheduler** = **2 task** (không phải service thường trú). Mọi tham số từ `.env`, không hardcode.

### 7.1. HMA local API Tool dùng (`http://127.0.0.1:2268`, envelope `{code:1,data}` / `{code:0}`; 402 nếu < Team plan)

| Mục đích | Method + Path | Dùng ở |
|---|---|---|
| List pool | `GET /profiles` | Job 1 |
| Start profile | `POST /profiles/start/:id` → `{ wsUrl: "ws://127.0.0.1:<port>/devtools/browser/<id>", port, userAgent, majorVersion }` | Job 2 |
| Stop profile | `POST /profiles/stop/:id` (luôn gọi trong `finally`) | Job 2 |
| Delete profile | `DELETE /profiles/:id` — có hàm gọi sẵn nhưng **chưa job nào dùng** | — |

Cloud API `api.hidemyacc.com/browser` (`lastActivity`): **Tool chưa dùng** — thuộc đề xuất §9.

### 7.2. Job 1 — Supover Profile Sync (`scripts/sync_to_supover.py`)

**Lịch:** **00:00 & 12:00 hằng ngày** (`setup_sync_task.ps1`, task `HMA-Supover-Sync`).
```
GET HMA /profiles  →  POST nguyên văn body sang SUPOVER_SYNC_URL (= /api/hma/profiles/sync)
                       header x-api-key: SUPOVER_API_KEY
```
Forward **verbatim** (Supover tự chuẩn hoá). Exit: 0 ok · 1 config · 2 HMA unreachable · 3 Supover lỗi.

### 7.3. Job 2 — TikTok Store Status Check (`scripts/check_tiktok_store_status.py`)

**Lịch:** **mỗi 2 ngày lúc 04:00** (`setup_tiktok_store_status_task.ps1`, task `HMA-TikTok-Store-Status`).
```
GET SUPOVER_DEAD_STORES_URL?page=1&limit=100   (= /api/hma/stores/dead-with-balance)
  → mỗi store gồm: store_id, shop_code, region, profile_id, profile_name,
       proxy host/port/user/pass, seller, telegram
  for each store:
    0. Proxy alive check: GET api.ipify.org qua proxy (timeout 60s) ── dead → TG "Proxy Dead", skip (exit 7)
    1. POST /profiles/start/:id → wsUrl                             ── 400/code≠1 → TG "Profile In Use", skip (exit 3)
    2. Playwright mở browser qua wsUrl → kiểm tra TikTok Seller:
         - Login page (region gb→uk) → URL chứa "homepage"? ── không → TG "Not Logged In", skip (exit 6)
         - Bills page → scrape 3 field DOM (XPath .env): pending_settlement, payout_on_hold, bank_account_number
         - Shop info API (page.evaluate fetch) → shop_status
         - delay TIKTOK_STEP_DELAY giữa mỗi field
    3. Validate ── all element missing → TG "Not Logged In" (exit 6, tiếp store kế)
                ── pending&hold đều "0" / bank None / shop_status None → TG "Element Read Error" (exit 5, DỪNG toàn bộ)
                ── Playwright raise → TG "Playwright Error" (exit 4, tiếp store kế)
    4. OK → POST SUPOVER_STORES_SYNC_URL (= /api/hma/stores/sync): store_id, tt_shop_code, profile_id, region + 4 field
    5. Dwell TIKTOK_DWELL_SECONDS → POST /profiles/stop/:id (luôn, trong finally)
```
Trả về **worst exit code**; lỗi element-read **break** vòng lặp (dừng store còn lại). Tool **stateless**: chỉ scrape + POST, không compare/business-logic.

### 7.4. Telegram từ Tool = cảnh báo LỖI VẬN HÀNH (khác alert của Supover)

Tool gửi Telegram (`TELEGRAM_BOT_TOKEN`/`CHAT_ID` **riêng của Tool**) khi **fail vận hành**: Proxy Dead · Profile In Use · Not Logged In · Element Read Error · Playwright Error. **Khác** Telegram của Supover (`telegram.hma.*`) — cái đó báo **thay đổi dữ liệu store** khi sync thành công (§4.3). → 2 kênh, 2 mục đích.

### 7.5. Cleanup profile — Tool CHƯA có job

Tool hiện **chỉ 2 job** trên. **Không có** job xóa profile thừa (có sẵn hàm gọi `DELETE /profiles/:id` nhưng chưa job nào dùng). Cleanup thuộc đề xuất §9 + Resource xóa thủ công qua HMA desktop.

### 7.6. Operational prerequisites (trước go-live)
1. Sub-account HMA dedicated cho Tool VPS; folder share toàn bộ profile (SOP: profile mới cũng vào folder).
2. Admin HMA session trên VPS (cho manual delete) + 2FA + auto-logout + RDP-only + Event Log.
3. `.env` đầy đủ: HMA local (base/path/timeout/port range), Supover (3 URL + key + header), TikTok (login/bills/shop-info URL + 3 XPath + timeout/delay/dwell), Telegram. Initial run Job 1 populate `profile_hma`.
4. `python -m venv` + `pip install -r requirements.txt` + `python -m playwright install chromium`.

---

## 8. Rủi ro chính

| # | Rủi ro | Mức | Mitigation |
|---|---|---|---|
| 1 | TikTok Seller Center đổi DOM → scrape hỏng | Cao | Selector pack config-driven; try/catch từng field |
| 2 | HMA desktop app crash | TB | Tool fail-fast → Resource restart |
| 3 | TikTok detect bot → ban | Cao | Fingerprint qua HMA + chỉ scrape DIE/SUSPEND + scrape chậm + jitter |
| 4 | Seller nhập sai/duplicate profile_id | TB | Validate khi gán + UNIQUE(store_id) + báo lỗi 409 retry |
| 5 | Tool VPS down → daily sync fail | TB | Monitor uptime; SLA < 3 ngày (cron cleanup) |
| 6 | Profile xóa thủ công bên HMA giữa 2 sync | Thấp | `last_seen_at` đứng → cron cleanup sau 3 ngày |
| 7 | Tool VPS sập > 3 ngày → cron wipe pool | TB→Cao | Monitor uptime bắt buộc; cân nhắc thêm health-gate cho cron |
| 8 | Admin HMA session trên VPS bị compromise | TB | 2FA + auto-logout + RDP-only + Event Log |
| 9 | Race seller submit + cron / 2 seller cùng profile_id | Thấp | Atomic unmap-then-bind + UNIQUE backstop |

---

## 9. Đề xuất chưa triển khai — cleanup profile theo last-opened

**Vấn đề:** tab "HMA Profile Deletion" hiện chỉ lọc `store_id IS NULL` → profile **đang dùng nhưng chưa map** (Etsy, chờ gán) bị liệt kê nhầm. Cần biết "profile có còn được mở không". HMA **local API không có** last-opened; **cloud API** `GET api.hidemyacc.com/browser` có field **`lastActivity`** (đúng giá trị "ngày mở cuối" UI hiển thị). HMA support đã từ chối thêm vào API → đi đường cloud.

**Thiết kế đề xuất:**
1. **Migration** thêm `last_opened_at timestamp nullable indexed` vào `profile_hma`.
2. **Tool VPS — Job 1** gọi thêm cloud `/browser` → merge `lastActivity` vào payload `POST /api/hma/profiles/sync` (1 writer duy nhất, không tách luồng → tránh drift). *Lưu ý:* Job 1 hiện **forward verbatim** body HMA `/profiles` → cần đổi thành **enrich** (gọi `/browser`, gắn `lastActivity` vào từng profile trước khi push). Nếu muốn auto-delete: thêm **job thứ 3** (hiện chưa có) gọi `DELETE /profiles/:id` cho list đã review.
3. **Khi Supover nhận sync**: parse `lastActivity` → lưu vào cột `last_opened_at` (NULL nếu thiếu/lỗi).
4. **Filter tab HMA Profile Deletion** đổi thành **chưa map VÀ > 60 ngày chưa open**:
```sql
WHERE store_id IS NULL
  AND ( last_opened_at < NOW() - INTERVAL 60 DAY
     OR (last_opened_at IS NULL AND created_at < NOW() - INTERVAL 60 DAY) )
```
→ profile Etsy/đang-dùng (vẫn được mở) **không** lọt list. Threshold `IDLE_PROFILE_DAYS = 60`.

**Fail-safe:** parse lỗi/thiếu → `last_opened_at = NULL` (fallback `created_at`, không xóa); Tool VPS phải lấy **đủ trang** cloud trước khi push (thiếu trang = coi như fetch fail, KHÔNG sync) → tránh đánh dấu nhầm idle.

**Token cloud API:** ưu tiên **API token tĩnh** (HMA Settings→API, không hết hạn); fallback đọc session token app desktop persist tại `AppData\Roaming\hidemyacc-3\Local Storage` (app giữ login qua restart → token luôn trên đĩa).

*(Đã cân nhắc Option Y — đo bằng `store_meta.hma_last_synced_at` store-level, không cần cloud — nhưng chọn tín hiệu profile-open vì đúng "profile có được mở không".)*

---

## 10. Quyết định đã chốt

1. **Source-of-truth = bảng `profile_hma`** (`store_id` nullable UNIQUE), kiêm mirror cache.
2. **Seller nhập profile_id thủ công** qua UI Edit Store (không Pool/auto-match).
3. **3 endpoint inbound** auth `hma.inbound` (x-api-key, hash_equals). Restrict team **Dragon Media** ở các list store.
4. **4 tab web** tại `Store → Store List → Store HMA` (+ tab TikTok Resource legacy). Profile/store "unmapped" là **web UI**, không phải API.
5. **Sync-report = `POST /api/hma/stores/sync`** — Supover so sánh + quy đổi tiền→USD + cập nhật + Telegram. KHÔNG đụng `/api/store/tiktok/create` của extension (decoupling).
6. **Cron `hma:cleanup-pending-stubs`** daily 03:00 ICT, threshold 3 ngày. Self-healing qua DB state; cần monitor uptime Tool VPS.
7. **Tool VPS** = repo `project-hma` (Python + Playwright + Windows Task Scheduler, stateless). 2 job: profile sync (00:00 & 12:00) + store status check (mỗi 2 ngày 04:00). Playwright connect `wsUrl` từ `POST /profiles/start/:id`. Smart Server – Dumb Agent: compare/data-alert ở Supover; Tool tự gửi Telegram **lỗi vận hành**. Chưa có job cleanup.
8. **[ĐỀ XUẤT]** `last_opened_at` + cloud `lastActivity` + filter idle-60 cho tab HMA Profile Deletion (§9).

---

## 11. Open Questions

| # | Câu hỏi | Ảnh hưởng |
|---|---|---|
| Q1 | Số liệu thực tế: bao nhiêu store LIVE/SUSPEND/DIE? bao nhiêu HMA profile? orphan ước tính? | Sizing + monitoring baseline |
| Q2 | Sub-account HMA có quyền **DELETE /profiles/:id** không (hay phải admin desktop thủ công)? | Luồng cleanup §7.5 |
| Q3 | **[ĐỀ XUẤT]** Format `lastActivity` (ISO vs epoch giây/ms)? | Parse `last_opened_at` |
| Q4 | **[ĐỀ XUẤT]** `GET /browser` có phân trang không (đủ ~3000/lần)? | Thiếu trang = xóa nhầm |
| Q5 | **[ĐỀ XUẤT]** HMA Settings→API có token tĩnh không? | Auth/refresh token Tool VPS |
| Q6 | Cron cleanup nên thêm health-gate (skip nếu pool sync gần nhất quá cũ) để chống wipe khi Tool VPS sập? | Rủi ro #7 |

---

## 12. Ngoài phạm vi

- Pool concept + dropdown seller pick; auto-match (by proxy/name).
- UI quản lý HMA profile đầy đủ (dashboard summary, filter folder/region/expiry).
- Đa sub-account HMA phối hợp; auto tạo profile khi tạo store; auto-renew/track proxy expiry.
- Scrape TikTok analytics (views/GMV/conversion).
- Tool VPS chạy 24/7 unattended; async validation qua queue.
- Drop cột/bảng data cũ (`store_meta.proxy_hma`/`hma_id`/`user_agent` giữ song song).
- Fix extension throttle bug (ticket riêng repo extension).
- Chi tiết implementation Tool VPS nằm ở repo `project-hma` (đã tóm tắt §7) — không lặp lại code ở đây.

---

Liên hệ: toocbaby@gmail.com.
