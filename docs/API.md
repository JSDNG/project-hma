# API Reference

Base URL (local dev): `http://127.0.0.1:8000`

All endpoints return JSON. Errors use the standard FastAPI shape:

```json
{ "detail": "<human-readable message>" }
```

Interactive docs are auto-generated:
- Swagger UI: `/docs`
- ReDoc:      `/redoc`
- OpenAPI:    `/openapi.json`

---

## `GET /healthz`  — Liveness

**Tags:** `system`

Cheap, dependency-free liveness probe. Does not call the local HMA API or the
downstream webhook.

**Response — 200 OK**

```json
{ "status": "ok" }
```

---

## `GET /config`  — Effective configuration (secrets masked)

**Tags:** `system`

Returns the resolved configuration the service is using. Useful for debugging
"did my env var take effect?". The API key is replaced with `"***"` if set,
or `""` if unset.

**Response — 200 OK**

```json
{
  "hma_local_api_base": "http://127.0.0.1:2268",
  "sync_post_url": "https://n8n.supover.com/webhook/api/hma-profiles/sync",
  "hma_api_key": "***",
  "hma_http_timeout": 30,
  "hma_log_level": "INFO"
}
```

`sync_post_url` is the **resolved** URL the service will POST to (the result
of `resolve_sync_post_url` applied to the `HMA_PROFILES_SYNC_URL` env var).
The raw base URL is intentionally omitted — only the resolved, final URL is
shown.

---

## `GET /profiles`  — Mapped profile rows

**Tags:** `profiles`

Fetches profiles from the local HideMyAcc API and returns them mapped to the
sync row shape — the exact rows that would be POSTed to the n8n webhook by
`/sync`. **Does not** forward anything downstream.

**Query parameters**

| Name      | Type    | Default | Description                                              |
|-----------|---------|---------|----------------------------------------------------------|
| `reveal`  | `bool`  | `false` | If `true`, returns proxy passwords in clear text.        |

**Response — 200 OK**

```json
{
  "count": 2,
  "rows": [
    {
      "profile_id": "abc123",
      "profile_name": "Acme - US east",
      "proxy": "proxy.example.com",
      "port": "8080",
      "username": "user1",
      "password": "***",
      "user_agent": "Mozilla/5.0 ..."
    },
    {
      "profile_id": "def456",
      "profile_name": "Acme - EU",
      "proxy": "",
      "port": "",
      "username": "",
      "password": "",
      "user_agent": ""
    }
  ]
}
```

When `reveal=true` the `password` field contains the raw value. Intended for
**local debugging only**.

**Errors**

| Status | When                                                              |
|--------|-------------------------------------------------------------------|
| `502`  | Local HMA API unreachable, timed out, or returned a malformed body. |

---

## `DELETE /profiles/{profile_id}`  — Delete one profile

**Tags:** `profiles`

Deletes a single profile by ID via the local HMA API
(`DELETE http://127.0.0.1:2268/profiles/{profile_id}`).

**Path parameters**

| Name         | Type   | Description                       |
|--------------|--------|-----------------------------------|
| `profile_id` | `str`  | HideMyAcc profile ID to delete.   |

**Response — 200 OK**

```json
{
  "profile_id": "abc123",
  "deleted": true,
  "upstream_status": 200
}
```

**Errors**

| Status | When                                                                       |
|--------|----------------------------------------------------------------------------|
| `402`  | HMA returned `{"code": 0}` with HTTP 402 — endpoint requires a Team plan.  |
| `502`  | Local HMA API unreachable, or signaled any other failure.                  |

> **Note — HMA response convention** (per
> [official docs](https://eng-hidemyacc.gitbook.io/hidemyacc-docs-vietnamese/hidemyacc-3.0-tinh-nang/hidemyacc-3.0-api/profile/xoa-profile)):
> success is HTTP `200` with body `{"code": 1}`. The most common error is
> HTTP `402` with `{"code": 0}` meaning "API supported from Team plan" —
> i.e. the HMA account on this machine doesn't have the subscription tier
> required by the API. The service passes that through as a `402` so it
> stays distinguishable from generic upstream errors.

**Example**

```bash
curl -s -X DELETE http://127.0.0.1:8000/profiles/abc123
```

---

## `DELETE /profiles`  — Delete many profiles (batch)

**Tags:** `profiles`

Deletes an array of profiles by ID. Each ID is sent to the local HMA API as
its own `DELETE /profiles/{id}` request. The operation is **best-effort**:
individual failures do not abort the rest. Duplicate IDs in the input are
deduplicated (order preserved).

**Request body**

```json
{
  "profile_ids": ["abc123", "def456", "ghi789"]
}
```

| Field         | Type        | Notes                                                                 |
|---------------|-------------|-----------------------------------------------------------------------|
| `profile_ids` | `list[str]` | Required. Must contain at least one ID. Duplicates are removed.       |

**Response — 200 OK**

```json
{
  "requested": 3,
  "deleted": 2,
  "failed": 1,
  "deleted_ids": ["abc123", "ghi789"],
  "failures": [
    {
      "profile_id": "def456",
      "upstream_status": 404,
      "error": "not found"
    }
  ]
}
```

Field semantics:

- `requested` — number of unique, non-empty IDs after deduplication.
- `deleted` — count of IDs the local HMA API accepted (2xx).
- `failed` — count of IDs that returned non-2xx or raised a network error.
- `deleted_ids` — IDs that succeeded, in submission order.
- `failures[].upstream_status` — HTTP status from HMA, or `null` if the call
  never reached it (network error, timeout).
- `failures[].error` — truncated upstream body or exception message.

**Errors**

| Status | When                                                              |
|--------|-------------------------------------------------------------------|
| `422`  | Validation failure (`profile_ids` missing, not a list, or empty). |

Per-ID failures are **not** reported as HTTP errors — they appear inside
`failures`. The endpoint returns `200` as long as the request body is valid.

**Example**

```bash
curl -s -X DELETE http://127.0.0.1:8000/profiles \
  -H 'Content-Type: application/json' \
  -d '{"profile_ids": ["abc123", "def456"]}'
```

```powershell
# PowerShell
Invoke-RestMethod -Method Delete -Uri http://127.0.0.1:8000/profiles `
  -ContentType 'application/json' `
  -Body '{"profile_ids": ["abc123", "def456"]}'
```

---

## `POST /sync`  — Run the full pipeline

**Tags:** `sync`

Fetches profiles from local HMA, maps them, and POSTs the result to the n8n
webhook. The downstream URL is resolved via `resolve_sync_post_url`.

**Query parameters**

| Name      | Type   | Default | Description                                                          |
|-----------|--------|---------|----------------------------------------------------------------------|
| `dry_run` | `bool` | `false` | If `true`, perform GET + map and **skip** the downstream POST.       |

**Response — 200 OK**

```json
{
  "rows_fetched": 12,
  "rows_forwarded": 12,
  "dry_run": false,
  "sync_url": "https://n8n.supover.com/webhook/api/hma-profiles/sync",
  "downstream_status": 200,
  "downstream_body": "{\"ok\":true}"
}
```

Field semantics:

- `rows_fetched` — number of profiles returned by the local HMA API.
- `rows_forwarded` — number of rows actually sent downstream. `0` on
  `dry_run=true` or when `rows_fetched == 0`.
- `dry_run` — echo of the query flag.
- `sync_url` — the resolved POST URL that was (or would have been) used.
- `downstream_status` — HTTP status code returned by the n8n webhook, or
  `null` if `dry_run` or `rows_fetched == 0`.
- `downstream_body` — first ~4 KB of the downstream response body, or `null`.

**Errors**

| Status | When                                                              |
|--------|-------------------------------------------------------------------|
| `400`  | `dry_run=false` and `HMA_API_KEY` is empty.                       |
| `502`  | Local HMA API or the downstream webhook failed (network error, non-2xx response, malformed response). |

---

## Conventions

- All timestamps (if added later) will be ISO-8601 UTC.
- All endpoints accept and return `application/json`.
- The service is bound to `127.0.0.1` by default. There is **no
  authentication** in this iteration — do not expose it publicly without
  adding an API-key dependency first.

---

## Examples

### Preview what would be synced

```bash
curl -s -X POST 'http://127.0.0.1:8000/sync?dry_run=true' | jq
```

### Trigger a real sync

```bash
curl -s -X POST http://127.0.0.1:8000/sync | jq
```

### Delete a profile

```bash
curl -s -X DELETE http://127.0.0.1:8000/profiles/abc123 | jq
```

### Batch-delete profiles

```bash
curl -s -X DELETE http://127.0.0.1:8000/profiles \
  -H 'Content-Type: application/json' \
  -d '{"profile_ids": ["abc123", "def456"]}' | jq
```

### Inspect mapped rows with passwords revealed (local debug only)

```bash
curl -s 'http://127.0.0.1:8000/profiles?reveal=true' | jq
```
