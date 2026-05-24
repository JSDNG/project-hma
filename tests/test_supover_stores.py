"""Unit tests for the Supover dead-with-balance fetch helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests

from app.supover_stores import (
    fetch_dead_stores_with_balance,
)
API_KEY_HEADER = "x-api-key"

URL = "https://supover.test/api/hma/stores/dead-with-balance"


def _envelope(data: list[dict]) -> dict:
    return {
        "status": True,
        "page": 1,
        "limit": 100,
        "total": len(data),
        "last_page": 1,
        "data": data,
    }


def _row(profile_id: str | None = "p1", *, store_id: int = 5911) -> dict:
    profile_hma = (
        None
        if profile_id is None
        else {
            "id": 1,
            "profile_id": profile_id,
            "profile_name": "Tk15",
            "proxy": "1.2.3.4",
            "port": 80,
        }
    )
    return {
        "store_id": store_id,
        "domain": "Retro Vibe",
        "shop_code": "USLCPMEYM8",
        "region": "US",
        "status": "inactive",
        "profile_hma": profile_hma,
    }


def _resp(status_code: int = 200, json_body=None, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    if json_body is None:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = json_body
    resp.raise_for_status = MagicMock()
    return resp


def test_fetch_unwraps_list_envelope():
    session = MagicMock()
    data = [_row("p1"), _row("p2")]
    session.get.return_value = _resp(200, [_envelope(data)])

    out = fetch_dead_stores_with_balance(session, URL, "secret", 10, "x-api-key")

    assert out == data
    args, kwargs = session.get.call_args
    assert args == (URL,)
    assert kwargs["params"] == {"page": 1, "limit": 100}
    assert kwargs["headers"][API_KEY_HEADER] == "secret"
    assert kwargs["timeout"] == 10


def test_fetch_strips_whitespace_from_url_and_key():
    session = MagicMock()
    session.get.return_value = _resp(200, [_envelope([])])
    fetch_dead_stores_with_balance(session, f"  {URL}  ", "  secret  ", 10, "x-api-key")
    args, kwargs = session.get.call_args
    assert args == (URL,)
    assert kwargs["headers"][API_KEY_HEADER] == "secret"


def test_fetch_accepts_bare_dict_envelope():
    session = MagicMock()
    data = [_row("p1")]
    session.get.return_value = _resp(200, _envelope(data))

    out = fetch_dead_stores_with_balance(session, URL, "secret", 10, "x-api-key")
    assert out == data


def test_fetch_returns_empty_list_when_data_empty():
    session = MagicMock()
    session.get.return_value = _resp(200, [_envelope([])])

    out = fetch_dead_stores_with_balance(session, URL, "secret", 10, "x-api-key")
    assert out == []


def test_fetch_passes_page_and_limit():
    session = MagicMock()
    session.get.return_value = _resp(200, [_envelope([])])

    fetch_dead_stores_with_balance(
        session, URL, "secret", 10, "x-api-key", page=3, limit=25,
    )
    _, kwargs = session.get.call_args
    assert kwargs["params"] == {"page": 3, "limit": 25}


def test_fetch_rejects_empty_api_key():
    session = MagicMock()
    with pytest.raises(ValueError, match="SUPOVER_API_KEY"):
        fetch_dead_stores_with_balance(session, URL, "  ", 10, "x-api-key")
    session.get.assert_not_called()


def test_fetch_rejects_empty_url():
    session = MagicMock()
    with pytest.raises(ValueError, match="SUPOVER_DEAD_STORES_URL"):
        fetch_dead_stores_with_balance(session, "  ", "k", 10, "x-api-key")
    session.get.assert_not_called()


def test_fetch_rejects_unexpected_data_type():
    session = MagicMock()
    session.get.return_value = _resp(200, [{"data": "nope"}])
    with pytest.raises(ValueError, match="'data' is not a list"):
        fetch_dead_stores_with_balance(session, URL, "secret", 10, "x-api-key")


def test_fetch_rejects_unexpected_envelope_type():
    session = MagicMock()
    session.get.return_value = _resp(200, "string-body")
    with pytest.raises(ValueError, match="unexpected top-level type"):
        fetch_dead_stores_with_balance(session, URL, "secret", 10, "x-api-key")


def test_fetch_rejects_non_singleton_list():
    session = MagicMock()
    session.get.return_value = _resp(200, [_envelope([]), _envelope([])])
    with pytest.raises(ValueError, match="single envelope object"):
        fetch_dead_stores_with_balance(session, URL, "secret", 10, "x-api-key")


def test_fetch_propagates_network_error():
    session = MagicMock()
    session.get.side_effect = requests.ConnectionError("unreachable")
    with pytest.raises(requests.ConnectionError):
        fetch_dead_stores_with_balance(session, URL, "secret", 10, "x-api-key")


