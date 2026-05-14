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

### Inspect mapped rows with passwords revealed (local debug only)

```bash
curl -s 'http://127.0.0.1:8000/profiles?reveal=true' | jq
```
