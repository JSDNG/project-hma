"""Unit tests for the pure mapping helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.hma_sync import (
    delete_profile,
    mask_secrets,
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


def test_profile_to_sync_row_non_string_user_agent():
    row = profile_to_sync_row({"id": "x", "name": "y", "userAgent": 12345})
    assert row["user_agent"] == "12345"


def test_mask_secrets_redacts_password():
    out = mask_secrets({"username": "u", "password": "sekret"})
    assert out["password"] == "***"
    assert out["username"] == "u"


def test_mask_secrets_leaves_empty_password_alone():
    out = mask_secrets({"username": "u", "password": ""})
    assert out["password"] == ""


def test_mask_secrets_returns_a_copy():
    src = {"username": "u", "password": "p"}
    mask_secrets(src)
    assert src["password"] == "p", "original dict must not be mutated"


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
