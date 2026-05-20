"""Unit tests for the outbound Supover sync helper."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests

from app.supover_sync import (
    SUPOVER_API_KEY_HEADER,
    push_to_supover,
)


def _hma_body() -> dict:
    """A representative raw HMA /profiles response body."""
    return {
        "code": 1,
        "data": [
            {"id": "p1", "name": "n1", "proxy": {"host": "h", "port": 9}},
            {"id": "p2", "name": "n2", "proxy": {"host": "h2", "port": 10}},
        ],
    }


def test_push_to_supover_forwards_payload_verbatim():
    session = MagicMock()
    session.post.return_value = MagicMock(status_code=200, text="ok")

    payload = _hma_body()
    resp = push_to_supover(
        session,
        "https://supover.test/sync",
        "secret-key",
        payload,
        timeout=15,
    )

    session.post.assert_called_once()
    args, kwargs = session.post.call_args
    assert args == ("https://supover.test/sync",)
    assert kwargs["timeout"] == 15
    assert kwargs["json"] == payload
    assert kwargs["json"] is payload
    assert kwargs["headers"][SUPOVER_API_KEY_HEADER] == "secret-key"
    assert kwargs["headers"]["Content-Type"] == "application/json"
    assert resp.status_code == 200


def test_push_to_supover_rejects_empty_api_key():
    session = MagicMock()
    with pytest.raises(ValueError, match="SUPOVER_API_KEY"):
        push_to_supover(session, "https://supover.test/sync", "   ", {}, 10)
    session.post.assert_not_called()


def test_push_to_supover_rejects_empty_url():
    session = MagicMock()
    with pytest.raises(ValueError, match="SUPOVER_SYNC_URL"):
        push_to_supover(session, "", "key", {}, 10)
    session.post.assert_not_called()


def test_push_to_supover_propagates_network_error():
    session = MagicMock()
    session.post.side_effect = requests.ConnectionError("unreachable")
    with pytest.raises(requests.ConnectionError):
        push_to_supover(
            session, "https://supover.test/sync", "key", _hma_body(), 5
        )


def test_push_to_supover_strips_whitespace_from_key_and_url():
    session = MagicMock()
    session.post.return_value = MagicMock(status_code=200, text="ok")
    push_to_supover(
        session,
        "  https://supover.test/sync  ",
        "  key  ",
        {},
        10,
    )
    args, kwargs = session.post.call_args
    assert args == ("https://supover.test/sync",)
    assert kwargs["headers"][SUPOVER_API_KEY_HEADER] == "key"
