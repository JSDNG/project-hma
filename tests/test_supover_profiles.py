"""Unit tests for the Supover profiles-to-delete helper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from app.supover_profiles import (
    all_deletable_profiles,
    fetch_all_profiles_to_delete,
    fetch_profiles_to_delete,
)

API_KEY_HEADER = "x-api-key"


def _resp(body) -> MagicMock:
    resp = MagicMock(status_code=200, text="ok")
    resp.json.return_value = body
    resp.raise_for_status.return_value = None
    return resp


def _row(pid="p1", name="n1", opened="2026-03-16T16:48:54.000000Z") -> dict:
    return {"profile_id": pid, "profile_name": name, "last_opened_at": opened}


def _envelope(rows, page=1, total=None) -> list:
    """Mirror the real shape: a single-element list wrapping the envelope."""
    return [{"status": True, "page": page, "limit": 1000,
             "total": len(rows) if total is None else total, "data": rows}]


def test_fetch_builds_correct_get_and_returns_page():
    session = MagicMock()
    session.get.return_value = _resp(_envelope([_row(), _row("p2")], total=1234))

    result = fetch_profiles_to_delete(
        session,
        "https://supover.test/delete",
        "secret-key",
        timeout=15,
        api_key_header=API_KEY_HEADER,
    )

    session.get.assert_called_once()
    args, kwargs = session.get.call_args
    assert args == ("https://supover.test/delete",)
    assert kwargs["timeout"] == 15
    assert kwargs["params"] == {"page": 1, "limit": 1000}
    assert kwargs["headers"][API_KEY_HEADER] == "secret-key"
    assert "Content-Type" not in kwargs["headers"]
    assert len(result.rows) == 2
    assert result.total == 1234


def test_fetch_accepts_bare_dict_envelope():
    session = MagicMock()
    session.get.return_value = _resp({"data": [_row()], "total": 1})
    result = fetch_profiles_to_delete(
        session, "https://supover.test/delete", "key", 10, API_KEY_HEADER,
    )
    assert len(result.rows) == 1


def test_fetch_defaults_total_to_row_count_when_absent():
    session = MagicMock()
    session.get.return_value = _resp({"data": [_row(), _row("p2")]})
    result = fetch_profiles_to_delete(
        session, "https://supover.test/delete", "key", 10, API_KEY_HEADER,
    )
    assert result.total == 2


def test_fetch_rejects_empty_api_key():
    session = MagicMock()
    with pytest.raises(ValueError, match="SUPOVER_API_KEY"):
        fetch_profiles_to_delete(session, "https://supover.test/delete", "  ", 10, API_KEY_HEADER)
    session.get.assert_not_called()


def test_fetch_rejects_empty_url():
    session = MagicMock()
    with pytest.raises(ValueError, match="SUPOVER_DELETE_PROFILES_URL"):
        fetch_profiles_to_delete(session, "", "key", 10, API_KEY_HEADER)
    session.get.assert_not_called()


def test_fetch_rejects_data_not_a_list():
    session = MagicMock()
    session.get.return_value = _resp([{"data": {"nope": True}}])
    with pytest.raises(ValueError, match="'data' is not a list"):
        fetch_profiles_to_delete(session, "https://supover.test/delete", "key", 10, API_KEY_HEADER)


def test_fetch_propagates_network_error():
    session = MagicMock()
    session.get.side_effect = requests.ConnectionError("unreachable")
    with pytest.raises(requests.ConnectionError):
        fetch_profiles_to_delete(session, "https://supover.test/delete", "key", 5, API_KEY_HEADER)


@patch("app.supover_profiles.time.sleep")
def test_fetch_all_walks_every_page_when_total_exceeds_limit(mock_sleep):
    session = MagicMock()
    # total=5 with limit=2 -> 3 pages.
    session.get.side_effect = [
        _resp(_envelope([_row("p1"), _row("p2")], page=1, total=5)),
        _resp(_envelope([_row("p3"), _row("p4")], page=2, total=5)),
        _resp(_envelope([_row("p5")], page=3, total=5)),
    ]

    rows = fetch_all_profiles_to_delete(
        session, "https://supover.test/delete", "key", 10, API_KEY_HEADER, limit=2,
    )

    assert [r["profile_id"] for r in rows] == ["p1", "p2", "p3", "p4", "p5"]
    assert session.get.call_count == 3
    pages = [c.kwargs["params"]["page"] for c in session.get.call_args_list]
    assert pages == [1, 2, 3]
    # 5s wait before each of the 2 follow-up fetches, none after the last.
    assert mock_sleep.call_count == 2
    mock_sleep.assert_called_with(5)


@patch("app.supover_profiles.time.sleep")
def test_fetch_all_stops_when_total_within_limit(mock_sleep):
    session = MagicMock()
    session.get.return_value = _resp(_envelope([_row("p1")], page=1, total=1))
    rows = fetch_all_profiles_to_delete(
        session, "https://supover.test/delete", "key", 10, API_KEY_HEADER, limit=1000,
    )
    assert [r["profile_id"] for r in rows] == ["p1"]
    assert session.get.call_count == 1
    mock_sleep.assert_not_called()


def test_all_deletable_profiles_maps_and_strips():
    rows = [_row(pid="  p1  ", name="  n1  ", opened="  2026-01-01T00:00:00Z  ")]
    result = all_deletable_profiles(rows)
    assert result == [("p1", "n1", "2026-01-01T00:00:00Z")]


def test_all_deletable_profiles_skips_rows_without_profile_id():
    rows = [
        _row(pid="p1"),
        {"profile_name": "no-id"},
        {"profile_id": "", "profile_name": "blank"},
        {"profile_id": "   ", "profile_name": "whitespace"},
        {"profile_id": 123, "profile_name": "non-string"},
    ]
    result = all_deletable_profiles(rows)
    assert [p.profile_id for p in result] == ["p1"]


def test_all_deletable_profiles_defaults_missing_optional_fields():
    result = all_deletable_profiles([{"profile_id": "p1"}])
    assert result == [("p1", "", "")]
