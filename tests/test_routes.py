"""Endpoint tests with all upstream HTTP calls mocked."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests


def _hma_get_response(profiles: list[dict]) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = {"code": 0, "data": profiles}
    resp.raise_for_status = MagicMock()
    return resp


def _downstream_response(ok: bool, status: int, body: str) -> MagicMock:
    resp = MagicMock()
    resp.ok = ok
    resp.status_code = status
    resp.text = body
    return resp


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_config_masks_api_key_and_omits_base_url(client):
    r = client.get("/config")
    assert r.status_code == 200
    body = r.json()
    assert body["hma_api_key"] == "***"
    assert body["sync_post_url"].endswith("/api/hma-profiles/sync")
    assert "hma_profiles_sync_url" not in body
    assert body["hma_local_api_base"] == "http://hma.test"
    assert body["hma_http_timeout"] == 5


def test_config_unmasks_empty_api_key(client, settings):
    settings.hma_api_key = ""
    r = client.get("/config")
    assert r.json()["hma_api_key"] == ""


def test_profiles_masks_passwords_by_default(client):
    profiles = [
        {
            "id": "p1",
            "name": "Profile 1",
            "proxy": {
                "host": "h",
                "port": 9,
                "username": "u",
                "password": "secret",
            },
            "userAgent": "ua",
        }
    ]
    with patch("app.routes.requests.Session") as mock_session:
        mock_session.return_value.get.return_value = _hma_get_response(profiles)
        r = client.get("/profiles")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["rows"][0]["password"] == "***"
    assert body["rows"][0]["proxy"] == "h"


def test_profiles_reveal_returns_raw_password(client):
    profiles = [
        {
            "id": "p1",
            "name": "Profile 1",
            "proxy": {
                "host": "h",
                "port": 9,
                "username": "u",
                "password": "secret",
            },
        }
    ]
    with patch("app.routes.requests.Session") as mock_session:
        mock_session.return_value.get.return_value = _hma_get_response(profiles)
        r = client.get("/profiles?reveal=true")
    assert r.json()["rows"][0]["password"] == "secret"


def test_profiles_returns_502_on_upstream_network_error(client):
    with patch("app.routes.requests.Session") as mock_session:
        mock_session.return_value.get.side_effect = requests.ConnectionError("nope")
        r = client.get("/profiles")
    assert r.status_code == 502
    assert "HMA local API error" in r.json()["detail"]


def test_profiles_returns_502_on_malformed_body(client):
    bad = MagicMock()
    bad.json.return_value = {"code": 0, "data": "not-a-list"}
    bad.raise_for_status = MagicMock()
    with patch("app.routes.requests.Session") as mock_session:
        mock_session.return_value.get.return_value = bad
        r = client.get("/profiles")
    assert r.status_code == 502
    assert "Invalid HMA response" in r.json()["detail"]


def test_sync_dry_run_skips_post(client):
    profiles = [
        {
            "id": "p1",
            "name": "n",
            "proxy": {"host": "h", "port": 1, "username": "u", "password": "p"},
        }
    ]
    with patch("app.routes.requests.Session") as mock_session:
        s = mock_session.return_value
        s.get.return_value = _hma_get_response(profiles)
        r = client.post("/sync?dry_run=true")
        assert s.post.call_count == 0
    assert r.status_code == 200
    body = r.json()
    assert body["rows_fetched"] == 1
    assert body["rows_forwarded"] == 0
    assert body["dry_run"] is True
    assert body["downstream_status"] is None


def test_sync_empty_profiles_skips_post(client):
    with patch("app.routes.requests.Session") as mock_session:
        s = mock_session.return_value
        s.get.return_value = _hma_get_response([])
        r = client.post("/sync")
        assert s.post.call_count == 0
    body = r.json()
    assert body["rows_fetched"] == 0
    assert body["rows_forwarded"] == 0
    assert body["downstream_status"] is None


def test_sync_forwards_rows(client):
    profiles = [
        {
            "id": "p1",
            "name": "n",
            "proxy": {"host": "h", "port": 1, "username": "u", "password": "p"},
        }
    ]
    downstream = _downstream_response(ok=True, status=200, body='{"ok": true}')
    with patch("app.routes.requests.Session") as mock_session:
        s = mock_session.return_value
        s.get.return_value = _hma_get_response(profiles)
        s.post.return_value = downstream
        r = client.post("/sync")
        assert s.post.call_count == 1

    assert r.status_code == 200
    body = r.json()
    assert body["rows_fetched"] == 1
    assert body["rows_forwarded"] == 1
    assert body["downstream_status"] == 200
    assert body["sync_url"].endswith("/api/hma-profiles/sync")


def test_sync_requires_api_key_when_not_dry_run(client, settings):
    settings.hma_api_key = ""
    r = client.post("/sync")
    assert r.status_code == 400
    assert "HMA_API_KEY" in r.json()["detail"]


def test_sync_returns_502_on_downstream_non_2xx(client):
    profiles = [
        {
            "id": "p1",
            "name": "n",
            "proxy": {"host": "h", "port": 1, "username": "u", "password": "p"},
        }
    ]
    downstream = _downstream_response(ok=False, status=500, body="boom")
    with patch("app.routes.requests.Session") as mock_session:
        s = mock_session.return_value
        s.get.return_value = _hma_get_response(profiles)
        s.post.return_value = downstream
        r = client.post("/sync")
    assert r.status_code == 502
    assert "500" in r.json()["detail"]


def _delete_response(
    ok: bool, status: int, body: str = "", json_body: dict | None = None
) -> MagicMock:
    resp = MagicMock()
    resp.ok = ok
    resp.status_code = status
    resp.text = body
    if json_body is not None:
        resp.json.return_value = json_body
    else:
        resp.json.side_effect = ValueError("no json")
    return resp


def test_delete_one_profile_ok(client):
    """Per HMA docs, success is HTTP 200 + body {"code": 1}."""
    with patch("app.routes.requests.Session") as mock_session:
        s = mock_session.return_value
        s.delete.return_value = _delete_response(
            ok=True, status=200, body='{"code":1}', json_body={"code": 1}
        )
        r = client.delete("/profiles/abc123")
        called_url = s.delete.call_args.args[0]
        assert called_url == "http://hma.test/profiles/abc123"
    assert r.status_code == 200
    assert r.json() == {
        "profile_id": "abc123",
        "deleted": True,
        "upstream_status": 200,
    }


def test_delete_one_profile_returns_402_when_team_plan_required(client):
    """HMA returns HTTP 402 + {"code": 0} when the account lacks a Team plan."""
    with patch("app.routes.requests.Session") as mock_session:
        mock_session.return_value.delete.return_value = _delete_response(
            ok=False,
            status=402,
            body='{"code":0}',
            json_body={"code": 0},
        )
        r = client.delete("/profiles/abc")
    assert r.status_code == 402
    assert "Team plan" in r.json()["detail"]


def test_delete_one_profile_fails_when_hma_code_not_one(client):
    """Any code != 1 (other than the team-plan 402 case) is a generic failure."""
    with patch("app.routes.requests.Session") as mock_session:
        mock_session.return_value.delete.return_value = _delete_response(
            ok=True,
            status=200,
            body='{"code":2,"message":"unexpected"}',
            json_body={"code": 2, "message": "unexpected"},
        )
        r = client.delete("/profiles/x")
    assert r.status_code == 502
    assert "code=2" in r.json()["detail"]


def test_delete_one_profile_returns_502_on_upstream_5xx(client):
    with patch("app.routes.requests.Session") as mock_session:
        mock_session.return_value.delete.return_value = _delete_response(
            ok=False, status=500, body="boom"
        )
        r = client.delete("/profiles/x")
    assert r.status_code == 502
    assert "500" in r.json()["detail"]


def test_delete_one_profile_returns_502_on_network_error(client):
    with patch("app.routes.requests.Session") as mock_session:
        mock_session.return_value.delete.side_effect = requests.ConnectionError("dead")
        r = client.delete("/profiles/x")
    assert r.status_code == 502
    assert "HMA local API error" in r.json()["detail"]


def test_delete_batch_all_ok(client):
    with patch("app.routes.requests.Session") as mock_session:
        s = mock_session.return_value
        s.delete.return_value = _delete_response(
            ok=True, status=200, body='{"code":1}', json_body={"code": 1}
        )
        r = client.request(
            "DELETE", "/profiles", json={"profile_ids": ["a", "b", "c"]}
        )
        assert s.delete.call_count == 3
    body = r.json()
    assert r.status_code == 200
    assert body == {
        "requested": 3,
        "deleted": 3,
        "failed": 0,
        "deleted_ids": ["a", "b", "c"],
        "failures": [],
    }


def test_delete_batch_partial_failure(client):
    """Mix of success, team-plan failure (402+code:0), and generic 5xx."""
    responses = {
        "a": _delete_response(
            ok=True, status=200, body='{"code":1}', json_body={"code": 1}
        ),
        "b": _delete_response(
            ok=False, status=402, body='{"code":0}', json_body={"code": 0}
        ),
        "c": _delete_response(ok=False, status=500, body="boom"),
    }

    def fake_delete(url, timeout):
        pid = url.rsplit("/", 1)[-1]
        return responses[pid]

    with patch("app.routes.requests.Session") as mock_session:
        mock_session.return_value.delete.side_effect = fake_delete
        r = client.request(
            "DELETE", "/profiles", json={"profile_ids": ["a", "b", "c"]}
        )

    body = r.json()
    assert r.status_code == 200
    assert body["requested"] == 3
    assert body["deleted"] == 1
    assert body["failed"] == 2
    assert body["deleted_ids"] == ["a"]
    fail_by_id = {f["profile_id"]: f for f in body["failures"]}
    assert fail_by_id["b"]["upstream_status"] == 402
    assert "Team plan" in fail_by_id["b"]["error"]
    assert fail_by_id["c"]["upstream_status"] == 500


def test_delete_batch_network_error_records_failure(client):
    with patch("app.routes.requests.Session") as mock_session:
        mock_session.return_value.delete.side_effect = requests.ConnectionError("dead")
        r = client.request("DELETE", "/profiles", json={"profile_ids": ["a"]})
    body = r.json()
    assert r.status_code == 200
    assert body["failed"] == 1
    assert body["failures"][0]["upstream_status"] is None
    assert "dead" in body["failures"][0]["error"]


def test_delete_batch_dedupes_ids(client):
    with patch("app.routes.requests.Session") as mock_session:
        s = mock_session.return_value
        s.delete.return_value = _delete_response(
            ok=True, status=200, body='{"code":1}', json_body={"code": 1}
        )
        r = client.request(
            "DELETE", "/profiles", json={"profile_ids": ["a", "a", "b"]}
        )
        assert s.delete.call_count == 2
    body = r.json()
    assert body["requested"] == 2
    assert body["deleted_ids"] == ["a", "b"]


def test_delete_batch_rejects_empty_list(client):
    r = client.request("DELETE", "/profiles", json={"profile_ids": []})
    assert r.status_code == 422


def test_sync_returns_502_on_downstream_network_error(client):
    profiles = [
        {
            "id": "p1",
            "name": "n",
            "proxy": {"host": "h", "port": 1, "username": "u", "password": "p"},
        }
    ]
    with patch("app.routes.requests.Session") as mock_session:
        s = mock_session.return_value
        s.get.return_value = _hma_get_response(profiles)
        s.post.side_effect = requests.ConnectionError("dead")
        r = client.post("/sync")
    assert r.status_code == 502
    assert "Sync webhook error" in r.json()["detail"]
