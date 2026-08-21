"""Deliberate exits — the one filter that records the user's intent, not the market's.

The gap it closes: selling is taxed, buying is not, and the screen has no memory. Sell out of a name
because you have gone off the company and next month's deploy may re-buy it because it still ranks —
real tax paid to exit something the system re-entered weeks later.

Because this filter encodes an instruction rather than a measurement, the tests below care as much
about its *limits* as its function: it must expire, it must be clearable, it must never block a sell,
and it must always be visible.
"""

from __future__ import annotations

from datetime import date

from qalpha.live.cooling_off import (
    DEFAULT_MONTHS,
    Exit,
    clear_exit,
    excluded_on,
    exits_note,
    load_exits,
    record_exit,
    save_exits,
)

_ON = date(2026, 8, 20)


def test_an_exit_blocks_the_name_while_it_stands() -> None:
    exits = record_exit("VEDL.NS", _ON, months=6, reason="demerger mess")
    assert excluded_on(_ON, exits) == {"VEDL.NS"}
    assert excluded_on(date(2027, 1, 1), exits) == {"VEDL.NS"}  # still inside six months


def test_an_exit_lapses_on_its_own() -> None:
    """A view held in August is not evidence about the following June — it must not ossify."""
    exits = record_exit("VEDL.NS", _ON, months=6)
    assert excluded_on(date(2027, 2, 20), exits) == set()  # six months later, gone
    assert exits[0].until == date(2027, 2, 20)


def test_re_recording_restarts_the_clock_rather_than_stacking() -> None:
    exits = record_exit("VEDL.NS", _ON, months=6)
    exits = record_exit("VEDL.NS", date(2026, 10, 20), months=6, exits=exits)
    assert len(exits) == 1  # one entry per name, not a growing pile
    assert exits[0].until == date(2027, 4, 20)


def test_the_user_can_change_their_mind() -> None:
    exits = record_exit("VEDL.NS", _ON, exits=record_exit("ITC.NS", _ON))
    assert excluded_on(_ON, clear_exit("VEDL.NS", exits)) == {"ITC.NS"}


def test_month_arithmetic_clamps_to_the_end_of_a_short_month() -> None:
    """31 Aug + 6 months is 28/29 Feb, not an invalid date."""
    assert record_exit("X.NS", date(2026, 8, 31), months=6)[0].until == date(2027, 2, 28)
    assert record_exit("X.NS", date(2027, 8, 31), months=6)[0].until == date(2028, 2, 29)  # leap


def test_the_list_is_always_visible_never_a_silent_filter() -> None:
    """Six months on, an invisible exclusion is indistinguishable from a bug."""
    note = exits_note(_ON, record_exit("VEDL.NS", _ON, months=6, reason="demerger mess"))
    assert "VEDL" in note
    assert "2027-02-20" in note  # when it lapses
    assert "demerger mess" in note  # why you did it
    assert exits_note(_ON, []) == ""
    assert (
        exits_note(date(2028, 1, 1), record_exit("VEDL.NS", _ON)) == ""
    )  # expired → nothing shown


def test_a_corrupt_file_fails_open_rather_than_blocking_every_deploy(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A guard that can brick the buy list on a bad byte is worse than the problem it solves."""
    path = tmp_path / "cooling_off.json"
    path.write_text("{not json at all", encoding="utf-8")
    assert load_exits(path) == []


def test_it_round_trips_through_disk(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "cooling_off.json"
    original = record_exit("VEDL.NS", _ON, months=9, reason="governance")
    save_exits(original, path)
    back = load_exits(path)
    assert back == original
    assert back[0].months == 9 and back[0].reason == "governance"


def test_a_missing_file_is_simply_no_exits() -> None:
    from pathlib import Path

    assert load_exits(Path("data/definitely-not-here.json")) == []


def test_the_default_window_is_months_not_forever() -> None:
    """The design intent, pinned: this is a cooling-off period, never a permanent blacklist."""
    assert 1 <= DEFAULT_MONTHS <= 12
    assert Exit("X.NS", _ON).months == DEFAULT_MONTHS
