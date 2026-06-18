"""Tests for the paper-run freshness signal (qalpha.live.dashboard.paper_freshness)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import cast

from qalpha.live.dashboard import paper_freshness
from qalpha.live.paper import PaperBook


def _book(last_date: str | None) -> PaperBook:
    curve = [] if last_date is None else [{"date": last_date, "equity": "1", "cash": "1"}]
    return cast(PaperBook, SimpleNamespace(equity_curve=curve))


def test_fresh_across_a_weekend() -> None:
    # Last marked Friday, today Monday → only today's (ungraded) weekday elapsed → fresh.
    f = paper_freshness(_book("2026-06-12"), date(2026, 6, 15))  # Fri → Mon
    assert not f.is_stale
    assert f.weekdays_stale == 0
    assert f.last_update == date(2026, 6, 12)


def test_stale_when_a_weekday_is_missed() -> None:
    # Last marked Monday, today Thursday → Tue/Wed missed (Thu = grace) → stale.
    f = paper_freshness(_book("2026-06-15"), date(2026, 6, 18))  # Mon → Thu
    assert f.is_stale
    assert f.weekdays_stale == 2


def test_empty_curve_is_stale() -> None:
    f = paper_freshness(_book(None), date(2026, 6, 18))
    assert f.is_stale
    assert f.last_update is None
