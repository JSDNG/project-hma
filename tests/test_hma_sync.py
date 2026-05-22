"""Unit tests for the pure mapping helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.hma_sync import (
    delete_profile,
    interpret_start_response,
    profile_to_sync_row,
    start_profile,
    stop_profile,
)


def test_profile_to_sync_row_with_proxy_dict():
    profile = {
        "id": "abc",
        "name": "test profile",
        "proxy": {
            "host": "proxy.example.com",
            "port": 8080,
            "username": "user",
            "password": "secret",
        },
    }
    assert profile_to_sync_row(profile) == {
        "profile_id": "abc",
        "profile_name": "test profile",
        "proxy": "proxy.example.com",
        "port": "8080",
        "username": "user",
        "password": "secret",
    }


def test_profile_to_sync_row_falls_back_to_auto_proxy_fields():
    profile = {
        "id": 123,
        "name": "fallback",
        "proxy": {
            "autoProxyServer": "auto.example.com",
            "autoProxyUsername": "auto-user",
            "autoProxyPassword": "auto-pass",
        },
    }
    row = profile_to_sync_row(profile)
    assert row["proxy"] == "auto.example.com"
    assert row["username"] == "auto-user"
    assert row["password"] == "auto-pass"
    assert row["profile_id"] == "123"
    assert row["port"] == ""


def test_profile_to_sync_row_handles_missing_proxy():
    row = profile_to_sync_row({"id": "x", "name": "y"})
    assert row["proxy"] == ""
    assert row["port"] == ""
    assert row["password"] == ""


def test_profile_to_sync_row_handles_zero_port():
    row = profile_to_sync_row(
        {"id": "x", "name": "y", "proxy": {"port": 0, "host": "h"}}
    )
    assert row["port"] == ""


def test_profile_to_sync_row_accepts_string_port():
    row = profile_to_sync_row(
        {"id": "x", "name": "y", "proxy": {"port": "3128", "host": "h"}}
    )
    assert row["port"] == "3128"


def test_profile_to_sync_row_accepts_boundary_ports():
    low = profile_to_sync_row(
        {"id": "x", "name": "y", "proxy": {"port": 1, "host": "h"}}
    )
    high = profile_to_sync_row(
        {"id": "x", "name": "y", "proxy": {"port": 65535, "host": "h"}}
    )
    assert low["port"] == "1"
    assert high["port"] == "65535"


def test_profile_to_sync_row_drops_port_above_tcp_max(caplog):
    with caplog.at_level("WARNING"):
        row = profile_to_sync_row(
            {"id": "bad-1", "name": "y", "proxy": {"port": 70000, "host": "h"}}
        )
    assert row["port"] == ""
    assert "bad-1" in caplog.text
    assert "70000" in caplog.text


def test_profile_to_sync_row_drops_huge_port(caplog):
    # The Supover incident: an upstream record with a non-port number leaking
    # into proxy.port (>INT max) used to abort the entire batch INSERT.
    with caplog.at_level("WARNING"):
        row = profile_to_sync_row(
            {"id": "bad-2", "name": "y", "proxy": {"port": 2_147_483_648, "host": "h"}}
        )
    assert row["port"] == ""
    assert "bad-2" in caplog.text


def test_profile_to_sync_row_drops_negative_port(caplog):
    with caplog.at_level("WARNING"):
        row = profile_to_sync_row(
            {"id": "bad-3", "name": "y", "proxy": {"port": -1, "host": "h"}}
        )
    assert row["port"] == ""
    assert "bad-3" in caplog.text


def test_profile_to_sync_row_drops_non_numeric_port(caplog):
    with caplog.at_level("WARNING"):
        row = profile_to_sync_row(
            {"id": "bad-4", "name": "y", "proxy": {"port": "abc", "host": "h"}}
        )
    assert row["port"] == ""
    assert "bad-4" in caplog.text
    assert "abc" in caplog.text


def test_delete_profile_builds_correct_url():
    session = MagicMock()
    delete_profile(session, "http://hma.test/", "abc123", 10)
    session.delete.assert_called_once_with("http://hma.test/profiles/abc123", timeout=10)


def test_delete_profile_strips_trailing_slash_from_base():
    session = MagicMock()
    delete_profile(session, "http://hma.test", "id1", 5)
    session.delete.assert_called_once_with("http://hma.test/profiles/id1", timeout=5)


def test_delete_profile_rejects_empty_id():
    session = MagicMock()
    with pytest.raises(ValueError):
        delete_profile(session, "http://hma.test", "   ", 5)
    session.delete.assert_not_called()


def test_start_profile_builds_correct_url():
    session = MagicMock()
    start_profile(session, "http://hma.test/", "abc123", 10)
    session.post.assert_called_once_with(
        "http://hma.test/profiles/start/abc123", timeout=10
    )


def test_start_profile_strips_trailing_slash_from_base():
    session = MagicMock()
    start_profile(session, "http://hma.test", "id1", 5)
    session.post.assert_called_once_with(
        "http://hma.test/profiles/start/id1", timeout=5
    )


def test_start_profile_rejects_empty_id():
    session = MagicMock()
    with pytest.raises(ValueError):
        start_profile(session, "http://hma.test", "  ", 5)
    session.post.assert_not_called()


def test_stop_profile_builds_correct_url():
    session = MagicMock()
    stop_profile(session, "http://hma.test", "abc123", 10)
    session.post.assert_called_once_with(
        "http://hma.test/profiles/stop/abc123", timeout=10
    )


def test_stop_profile_rejects_empty_id():
    session = MagicMock()
    with pytest.raises(ValueError):
        stop_profile(session, "http://hma.test", "", 5)
    session.post.assert_not_called()


def _start_resp(
    status_code: int = 200,
    json_body: dict | None = None,
    text: str = "",
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    if json_body is None:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = json_body
    return resp


def test_interpret_start_response_happy_path():
    body = {
        "code": 1,
        "data": {
            "success": True,
            "port": 27999,
            "wsUrl": "ws://127.0.0.1:27999/devtools/browser/abc",
            "userAgent": "Mozilla/5.0",
            "majorVersion": 113,
        },
    }
    result = interpret_start_response(_start_resp(200, body))
    assert result.ok is True
    assert result.ws_url == "ws://127.0.0.1:27999/devtools/browser/abc"
    assert result.port == 27999
    assert result.major_version == 113
    assert result.user_agent == "Mozilla/5.0"
    assert result.error is None


def test_interpret_start_response_rejects_non_2xx():
    result = interpret_start_response(_start_resp(500, text="boom"))
    assert result.ok is False
    assert "HTTP 500" in (result.error or "")


def test_interpret_start_response_rejects_non_json_body():
    result = interpret_start_response(_start_resp(200, json_body=None, text="oops"))
    assert result.ok is False
    assert "non-JSON" in (result.error or "")


def test_interpret_start_response_rejects_wrong_code():
    body = {"code": 0, "data": {"success": True, "wsUrl": "ws://x"}}
    result = interpret_start_response(_start_resp(200, body))
    assert result.ok is False
    assert "code=0" in (result.error or "")


def test_interpret_start_response_rejects_data_success_false():
    body = {"code": 1, "data": {"success": False, "wsUrl": "ws://x"}}
    result = interpret_start_response(_start_resp(200, body))
    assert result.ok is False
    assert "success=False" in (result.error or "")


def test_interpret_start_response_rejects_missing_ws_url():
    body = {"code": 1, "data": {"success": True, "wsUrl": ""}}
    result = interpret_start_response(_start_resp(200, body))
    assert result.ok is False
    assert "wsUrl" in (result.error or "")


def test_interpret_start_response_rejects_non_object_data():
    body = {"code": 1, "data": "nope"}
    result = interpret_start_response(_start_resp(200, body))
    assert result.ok is False
    assert "data" in (result.error or "")
