"""Kite login failures, translated into the thing to go and do.

The failure that prompted this, in full:

    18:43:28 Opening Kite in your browser…
    18:43:41 TokenException: Invalid `checksum`.

That is Kite reporting that a signature over ``api_key + request_token + api_secret`` did not match
— computed on its side, over three inputs it does not name. Rendered verbatim it reads like a bug in
this code, and both real causes are on the Kite developer console. A user cannot act on it.

The rule these hold to: **an unrecognised error is reported plainly rather than explained
confidently.** A wrong diagnosis costs more than none, because it sends someone to change a thing
that was right.
"""

from __future__ import annotations

import pytest

from qalpha.live import auth
from qalpha.live.auth import explain_login_failure


class _TokenError(Exception):
    pass


def test_a_checksum_failure_points_at_the_secret_and_the_console() -> None:
    """THE ONE THIS FILE EXISTS FOR."""
    text = explain_login_failure(_TokenError("Invalid `checksum`."), api_key="d0lr3pdceh51lgeb")
    assert "SECRET" in text
    assert "developers.kite.trade" in text
    assert "KITE_API_SECRET" in text


def test_the_checksum_hint_names_the_key_so_the_right_app_is_picked() -> None:
    """Several apps on one console look identical until you match the key."""
    text = explain_login_failure(_TokenError("Invalid `checksum`."), api_key="d0lr3pdceh51lgeb")
    assert "...lgeb" in text


def test_the_checksum_hint_also_offers_the_second_cause() -> None:
    """A spent request_token gives the same error, and pressing Log in again is the cheaper test."""
    text = explain_login_failure(_TokenError("Invalid `checksum`."))
    assert "used " in text and "twice" in text


def test_a_key_too_short_to_abbreviate_does_not_produce_a_broken_hint() -> None:
    text = explain_login_failure(_TokenError("Invalid `checksum`."), api_key="ab")
    assert "your key" in text
    assert "..." not in text.split("ends ")[1][:12]


def test_an_expired_request_token_says_it_is_spent() -> None:
    text = explain_login_failure(_TokenError("Token is invalid or has expired."))
    assert "single-use" in text
    assert "SECRET" not in text, "do not send someone to change a credential that is fine"


def test_an_unrecognised_api_key_is_distinguished_from_a_bad_secret() -> None:
    text = explain_login_failure(_TokenError("Invalid api_key or access_token."))
    assert "KITE_API_KEY" in text


def test_an_account_not_enabled_says_it_is_not_ours_to_fix() -> None:
    text = explain_login_failure(_TokenError("User is not enabled on this app."))
    assert "not something this code can fix" in text


def test_an_unknown_error_is_reported_verbatim_rather_than_guessed_at() -> None:
    """A confident wrong explanation is worse than none — it sends you to change a working thing."""
    text = explain_login_failure(_TokenError("Something nobody has seen before"))
    assert text == "_TokenError: Something nobody has seen before"


def test_matching_is_case_insensitive() -> None:
    assert "SECRET" in explain_login_failure(_TokenError("INVALID CHECKSUM"))


def test_a_network_error_is_not_diagnosed_as_a_credential_problem() -> None:
    text = explain_login_failure(OSError("Connection reset by peer"))
    assert "OSError" in text
    assert "KITE_API_SECRET" not in text


# --- a login that succeeds must leave a session behind --------------------------------------------
#
# `exchange()` returns a KiteSession and saves nothing. Every interactive path except the CLI called
# it and DISCARDED the return value — the app's Log in button, its paste box, and `--login`. So a
# login that succeeded completely left no session on disk, the next run said "Kite was not
# reachable", and the page said:
#
#     Session minted and written to .env.
#
# False twice: nothing was written, and .env is not where a session goes. `get_access_token` reads
# `.kite_session.json`. These assert what is on disk afterwards, because that is the only thing that
# made the difference between a working login and a silent no-op.
@pytest.fixture
def session_file(tmp_path, monkeypatch):
    path = tmp_path / ".kite_session.json"
    monkeypatch.setattr(auth, "SESSION_FILE", path)
    monkeypatch.setattr(
        auth,
        "exchange",
        lambda creds, token: auth.KiteSession(
            access_token="tok-abc", user_id="AB1234", login_date="2026-09-10"
        ),
    )
    return path


def _creds():
    from qalpha.live.credentials import KiteCredentials

    return KiteCredentials(api_key="k" * 16, api_secret="s" * 32)


def test_minting_a_session_writes_it_where_the_broker_path_reads_it(session_file) -> None:
    """THE ONE THIS BLOCK EXISTS FOR."""
    auth.mint_session(_creds(), "req-token")
    assert session_file.exists(), "a successful login that saves nothing is a silent no-op"
    assert "tok-abc" in session_file.read_text()


def test_the_saved_session_is_the_one_get_access_token_returns(session_file, monkeypatch) -> None:
    """Written and readable are different claims; assert the round trip."""
    monkeypatch.setattr(auth.dt, "datetime", auth.dt.datetime)
    auth.mint_session(_creds(), "req-token")
    session = auth.load_cached_session()
    assert session is not None and session.access_token == "tok-abc"
    assert session.user_id == "AB1234"


def test_no_interactive_caller_uses_bare_exchange_any_more() -> None:
    """The caller test. `exchange` still exists for the tests that check the network call alone —
    but a path that logs a user in and does not persist is the bug, so none may use it."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for name in ("src/qalpha/live/server.py", "scripts/local_run.py"):
        text = (root / name).read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "exchange(" not in stripped:
                continue
            assert "mint_session" in stripped or "explain" in stripped, (
                f"{name} calls exchange() directly at: {stripped!r} — use mint_session, which "
                "saves the session the rest of the system reads"
            )


def test_the_app_never_claims_the_session_went_to_dot_env() -> None:
    """It goes to .kite_session.json. Naming the wrong file is how this stayed invisible."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    server = (root / "src/qalpha/live/server.py").read_text(encoding="utf-8")
    assert "written to .env" not in server
