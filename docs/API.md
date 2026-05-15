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

## Authentication

Every request to this service **must** include the header

```
x-api-key: <HMA_PROFILE_SYNC_API_KEY>
```

where the value matches the server's `HMA_PROFILE_SYNC_API_KEY`
environment variable. Comparison is constant-time
(`secrets.compare_digest`).

| Situation                                    | Status | Body                                                                 |
|----------------------------------------------|--------|----------------------------------------------------------------------|
| Header missing                               | `401`  | `{ "detail": "Invalid or missing x-api-key" }`                       |
| Header present but value does not match      | `401`  | `{ "detail": "Invalid or missing x-api-key" }`                       |
| Server has no `HMA_PROFILE_SYNC_API_KEY` set | `500`  | `{ "detail": "HMA_PROFILE_SYNC_API_KEY is not configured on the server" }` |

The gate is enforced at the router level, so it applies to **every**
endpoint listed below — including `/healthz`.

---

## `GET /healthz`  — Liveness

**Tags:** `system`

Cheap, dependency-free liveness probe. Does not call the local HMA API.

**Response — 200 OK**

```json
{ "status": "ok" }
```

---

## `GET /config`  — Effective configuration

**Tags:** `system`

Returns the resolved, non-secret configuration the service is using.
Useful for debugging "did my env var take effect?". The inbound
`HMA_PROFILE_SYNC_API_KEY` is never echoed back — clients already know it
because they had to send it to reach this endpoint.

**Response — 200 OK**

```json
{
  "hma_local_api_base": "http://127.0.0.1:2268",
  "hma_http_timeout": 30,
  "hma_log_level": "INFO"
}
```

---

## `GET /profiles`  — Mapped profile rows

**Tags:** `profiles`

Fetches profiles from the local HideMyAcc API and returns them mapped to a
flat row shape (one row per profile, all string fields). Proxy passwords
are returned in clear text — the endpoint is gated by `x-api-key`, so
treat the key as sensitive.

**Response — 200 OK**

```json
{
  "count": 2,
  "data": [
    {
      "profile_id": "abc123",
      "profile_name": "Acme - US east",
      "proxy": "proxy.example.com",
      "port": "8080",
      "username": "user1",
      "password": "s3cret",
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

## Conventions

- All timestamps (if added later) will be ISO-8601 UTC.
- All endpoints accept and return `application/json`.
- The `x-api-key` header is required on every call (see
  [Authentication](#authentication) above).

---

## Examples

> The examples below assume `HMA_PROFILE_SYNC_API_KEY` is exported in your
> shell. Pipe through `jq` if you want pretty output.

### List mapped profile rows

```bash
curl -s -H "x-api-key: $HMA_PROFILE_SYNC_API_KEY" \
  http://127.0.0.1:8000/profiles | jq
```

### Delete a profile

```bash
curl -s -X DELETE -H "x-api-key: $HMA_PROFILE_SYNC_API_KEY" \
  http://127.0.0.1:8000/profiles/abc123 | jq
```

### Batch-delete profiles

```bash
curl -s -X DELETE http://127.0.0.1:8000/profiles \
  -H "x-api-key: $HMA_PROFILE_SYNC_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"profile_ids": ["abc123", "def456"]}' | jq
```
