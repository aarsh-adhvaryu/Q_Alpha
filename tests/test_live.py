"""Live-layer tests: credential loading, login-URL + request_token parsing, session staleness.

Network paths (token exchange, the localhost listener) are not unit-tested; only their pure helpers
are. No real Kite calls are made.
"""

import datetime as dt

import pytest

from qalpha.live.auth import IST, KiteSession, login_url, parse_request_token
from qalpha.live.credentials import load_credentials


def test_login_url_carries_api_key_and_version() -> None:
    url = login_url("abc123")
    assert "api_key=abc123" in url
    assert "v=3" in url
    assert url.startswith("https://kite.zerodha.com/connect/login")


def test_parse_request_token_from_full_redirect_url() -> None:
    url = "http://127.0.0.1:5000/redirect?action=login&status=success&request_token=XYZ789"
    assert parse_request_token(url) == "XYZ789"


def test_parse_request_token_from_bare_query() -> None:
    assert parse_request_token("request_token=TOK&status=success") == "TOK"


def test_parse_request_token_from_bare_token() -> None:
    assert parse_request_token("  rawtoken123  ") == "rawtoken123"


def test_parse_request_token_rejects_empty() -> None:
    with pytest.raises(ValueError):
        parse_request_token("   ")


def test_session_freshness_is_date_based() -> None:
    today = dt.datetime.now(IST).date().isoformat()
    yesterday = (dt.datetime.now(IST).date() - dt.timedelta(days=1)).isoformat()
    assert KiteSession("tok", "AB1234", today).is_fresh
    assert not KiteSession("tok", "AB1234", yesterday).is_fresh


def test_load_credentials_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KITE_API_KEY", "key")
    monkeypatch.setenv("KITE_API_SECRET", "secret")
    monkeypatch.setenv("KITE_ACCESS_TOKEN", "")
    creds = load_credentials()
    assert creds.api_key == "key"
    assert creds.api_secret == "secret"
    assert creds.access_token is None
    assert not creds.has_session


def test_load_credentials_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KITE_API_KEY", "")
    monkeypatch.setenv("KITE_API_SECRET", "secret")
    with pytest.raises(RuntimeError, match="KITE_API_KEY"):
        load_credentials()
