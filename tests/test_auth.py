"""Kite login failures must say what to go and do, not what went wrong internally.

"Invalid `checksum`" is Kite saying that sha256(api_key + request_token + api_secret) did not
match. It names none of the three inputs, it is computed on their side, and reported verbatim it
reads like a bug in this code — when both real causes are on the Kite console.
"""

from __future__ import annotations

import json

from qalpha.live import auth


def test_a_checksum_failure_says_whether_it_ever_worked(tmp_path, monkeypatch) -> None:
    """The hint lists two causes and cannot choose. The date chooses.

    A saved session means the pair WAS valid that day, so something changed on the Kite console
    since — which turns "I don't know what is going on" into "it has not worked since June".
    """
    session = tmp_path / ".kite_session.json"
    session.write_text(
        json.dumps({"access_token": "x" * 32, "user_id": "YHK037", "login_date": "2026-06-16"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(auth, "SESSION_FILE", session)
    msg = auth.explain_login_failure(Exception("Invalid `checksum`."), api_key="abcd1234efgh5678")
    assert "2026-06-16" in msg and "YHK037" in msg
    assert "...5678" in msg, "the hint must name which app's secret to copy"
    assert "x" * 32 not in msg, "the access token must never be printed"


def test_never_logged_in_says_so_rather_than_implying_a_change(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(auth, "SESSION_FILE", tmp_path / "absent.json")
    msg = auth.explain_login_failure(Exception("Invalid `checksum`."), api_key="abcd1234efgh5678")
    assert "never completed a login" in msg


def test_an_unreadable_session_file_does_not_break_the_error_message(tmp_path, monkeypatch) -> None:
    """The diagnostic is a nicety; it must never replace the error it is decorating."""
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(auth, "SESSION_FILE", bad)
    msg = auth.explain_login_failure(Exception("Invalid `checksum`."), api_key="abcd1234efgh5678")
    assert "KITE_API_SECRET" in msg
