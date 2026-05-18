"""Unit tests for the pure mapping helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.hma_sync import (
    delete_profile,
    profile_to_sync_row,
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
        "userAgent": "Mozilla/5.0",
    }
    assert profile_to_sync_row(profile) == {
        "profile_id": "abc",
        "profile_name": "test profile",
        "proxy": "proxy.example.com",
        "port": "8080",
        "username": "user",
        "password": "secret",
        "user_agent": "Mozilla/5.0",
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
    assert row["user_agent"] == ""


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


def test_profile_to_sync_row_non_string_user_agent():
    row = profile_to_sync_row({"id": "x", "name": "y", "userAgent": 12345})
    assert row["user_agent"] == "12345"


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
