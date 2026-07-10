"""Tests for the Telegram notification spine — assert the wire and the fail-soft contract."""

from __future__ import annotations

import json

import pytest

from qalpha.live.notify import html_escape, send_telegram, telegram_configured


@pytest.fixture
def _telegram_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOK123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "CHAT456")


def test_configured_needs_both(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert not telegram_configured()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    assert not telegram_configured()  # chat id still missing
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "y")
    assert telegram_configured()


def test_send_posts_expected_request(_telegram_env: None) -> None:
    captured: dict[str, object] = {}

    def transport(url: str, body: bytes) -> int:
        captured["url"] = url
        captured["payload"] = json.loads(body)
        return 200

    assert send_telegram("hello <b>world</b>", transport=transport) is True
    assert "botTOK123/sendMessage" in str(captured["url"])
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["chat_id"] == "CHAT456"
    assert payload["text"] == "hello <b>world</b>"
    assert payload["parse_mode"] == "HTML"


def test_erroring_transport_returns_false_no_raise(_telegram_env: None) -> None:
    def boom(url: str, body: bytes) -> int:
        raise RuntimeError("network down")

    # Must swallow the error and report failure — the cron can never go red on a send.
    assert send_telegram("x", transport=boom) is False


def test_non_2xx_status_is_false(_telegram_env: None) -> None:
    assert send_telegram("x", transport=lambda u, b: 500) is False


def test_missing_env_never_calls_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    calls: list[str] = []

    def transport(url: str, body: bytes) -> int:
        calls.append(url)
        return 200

    assert send_telegram("x", transport=transport) is False
    assert calls == []  # never attempted a send without config


def test_html_escape() -> None:
    assert html_escape("a < b & c") == "a &lt; b &amp; c"
