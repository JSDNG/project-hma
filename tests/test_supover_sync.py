"""Unit tests for the outbound Supover sync helper."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests

from app.supover_sync import (
    SUPOVER_API_KEY_HEADER,
    build_supover_payload,
    push_to_supover,
)


def _row(profile_id: str = "p1", profile_name: str = "n1") -> dict[str, str]:
    return {
        "profile_id": profile_id,
        "profile_name": profile_name,
        "proxy": "h",
        "port": "9",
        "username": "u",
        "password": "s",
        "user_agent": "ua",
    }


def test_build_supover_payload_wraps_rows_with_count():
    rows = [_row("a"), _row("b")]
    assert build_supover_payload(rows) == {"count": 2, "data": rows}


def test_build_supover_payload_empty_rows():
    assert build_supover_payload([]) == {"count": 0, "data": []}


def test_push_to_supover_sends_expected_request():
    session = MagicMock()
    session.post.return_value = MagicMock(status_code=200, text="ok")

    rows = [_row("a")]
    resp = push_to_supover(
        session,
        "https://supover.test/sync",
        "secret-key",
        rows,
        timeout=15,
    )

    session.post.assert_called_once()
    args, kwargs = session.post.call_args
    assert args == ("https://supover.test/sync",)
    assert kwargs["timeout"] == 15
    assert kwargs["json"] == {"count": 1, "data": rows}
    assert kwargs["headers"][SUPOVER_API_KEY_HEADER] == "secret-key"
    assert kwargs["headers"]["Content-Type"] == "application/json"
    assert resp.status_code == 200


def test_push_to_supover_rejects_empty_api_key():
    session = MagicMock()
    with pytest.raises(ValueError, match="SUPOVER_API_KEY"):
        push_to_supover(session, "https://supover.test/sync", "   ", [], 10)
    session.post.assert_not_called()


def test_push_to_supover_rejects_empty_url():
    session = MagicMock()
    with pytest.raises(ValueError, match="SUPOVER_SYNC_URL"):
        push_to_supover(session, "", "key", [], 10)
    session.post.assert_not_called()


def test_push_to_supover_propagates_network_error():
    session = MagicMock()
    session.post.side_effect = requests.ConnectionError("unreachable")
    with pytest.raises(requests.ConnectionError):
        push_to_supover(
            session, "https://supover.test/sync", "key", [_row()], 5
        )


def test_push_to_supover_strips_whitespace_from_key_and_url():
    session = MagicMock()
    session.post.return_value = MagicMock(status_code=200, text="ok")
    push_to_supover(
        session,
        "  https://supover.test/sync  ",
        "  key  ",
        [],
        10,
    )
    args, kwargs = session.post.call_args
    assert args == ("https://supover.test/sync",)
    assert kwargs["headers"][SUPOVER_API_KEY_HEADER] == "key"
