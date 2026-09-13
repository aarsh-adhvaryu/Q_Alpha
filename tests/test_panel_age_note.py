"""A closed market is not a stale panel.

On a Saturday the newest bar is Friday's and the panel is perfectly current. The buy screen told
the user to "refresh the panel for a current basket" anyway — an instruction that cannot succeed,
on the surface he places orders from. `evidence.py` already knew ("no file for 2026-09-12
(non-trading day)"); this surface did not. Same concept, one call site.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import local_run


def _note_for(last_bar: date, today: date, monkeypatch) -> str:
    class _Date(date):
        @classmethod
        def today(cls) -> date:
            return today

    monkeypatch.setattr(local_run, "date", _Date)
    return local_run._panel_age_note(last_bar)


def test_a_weekend_says_the_panel_is_current(monkeypatch) -> None:
    """Friday's bar read on a Saturday. There is no newer price in existence."""
    note = _note_for(date(2026, 9, 11), date(2026, 9, 12), monkeypatch)
    assert "panel is current" in note
    assert "Refresh" not in note and "refresh" not in note, (
        "the user was sent to press a button that cannot change anything"
    )
    assert "Friday" in note


def test_a_sunday_still_reads_as_the_weekend(monkeypatch) -> None:
    note = _note_for(date(2026, 9, 11), date(2026, 9, 13), monkeypatch)
    assert "panel is current" in note


def test_a_weekday_gap_still_asks_for_a_refresh(monkeypatch) -> None:
    """A Monday missing from the panel is either a holiday or a real lag — it must not be waved off.

    This is the direction that matters: claiming 'current' when the panel is genuinely behind would
    be a stale price wearing a clean bill, which is strictly worse than a spurious nag.
    """
    note = _note_for(date(2026, 9, 8), date(2026, 9, 12), monkeypatch)
    assert "refresh" in note.lower()
    assert "panel is current" not in note


def test_a_long_closure_counts_the_days(monkeypatch) -> None:
    """Sat + Sun only; a three-day weekend contains a weekday and must fall through to the nag."""
    note = _note_for(date(2026, 9, 11), date(2026, 9, 14), monkeypatch)
    assert "refresh" in note.lower(), "Monday is a trading day — the panel really is behind"


def test_every_note_names_the_date_it_is_talking_about(monkeypatch) -> None:
    for last, today in (
        (date(2026, 9, 11), date(2026, 9, 12)),
        (date(2026, 9, 8), date(2026, 9, 12)),
    ):
        assert str(last) in _note_for(last, today, monkeypatch)
