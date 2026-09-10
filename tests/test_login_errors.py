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
