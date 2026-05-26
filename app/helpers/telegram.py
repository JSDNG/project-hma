"""Telegram Bot API notification helper."""

from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)


def send_telegram_message(
    bot_token: str,
    chat_id: str,
    text: str,
    *,
    timeout: int = 10,
) -> bool:
    """Send a message via Telegram Bot API. Return True on success."""
    if not bot_token or not chat_id:
        log.warning("Telegram not configured (missing bot_token or chat_id); skipping notification.")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}

    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        if resp.ok:
            log.info("Telegram notification sent successfully.")
            return True
        log.warning(
            "Telegram API returned HTTP %s: %s",
            resp.status_code,
            (resp.text or "")[:300],
        )
        return False
    except requests.RequestException as exc:
        log.warning("Telegram notification failed: %s", exc)
        return False
