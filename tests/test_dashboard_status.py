"""Tests for the paper-run freshness signal + systemic-risk watch render (qalpha.live.dashboard)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import cast

import pandas as pd

from qalpha.live.dashboard import paper_freshness, systemic_risk_markdown
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


def _index(last: float) -> pd.Series:
    # 300 trading days at 100, then drift to ``last`` on the final day → sets the 1y-high drawdown.
    vals = [100.0] * 299 + [last]
    return pd.Series(vals, index=pd.bdate_range(end="2026-06-18", periods=300))


def test_systemic_risk_normal_when_near_highs() -> None:
    md = systemic_risk_markdown(_index(99.0), date(2026, 6, 18))
    assert "NORMAL" in md
    assert "No hedge indicated" in md
    assert "never trades" in md  # read-only framing is always present


def test_systemic_risk_elevated_suggests_hedge_but_no_action() -> None:
    md = systemic_risk_markdown(_index(80.0), date(2026, 6, 18))  # 20% below high → deep
    assert "DEEP STRESS" in md or "ELEVATED" in md
    assert "consider" in md.lower()
    assert "places no derivatives trade" in md  # informational only, never executes
