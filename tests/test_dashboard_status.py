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


def test_today_brief_markdown_assembles_all_sections() -> None:
    from datetime import date

    from qalpha.live.dashboard import today_brief_markdown

    md = today_brief_markdown(
        date(2026, 6, 30),
        core_action="holding — next scheduled rebalance on/after 2027-01-01",
        market_level="elevated",
        market_drawdown=-0.087,
        market_note="market has pulled back — lean into it.",
        hedge_note="stress elevated — consider the hedge.",
        health_note="all holdings healthy — nothing to sell.",
        go_verdict="NOT YET",
        deploy_candidates=[("VEDL.NS", 0.61), ("TRENT.NS", 0.49)],
    )
    assert "📋 Today" in md
    assert "holding — next scheduled rebalance" in md
    assert "elevated" in md and "-8.7%" in md
    assert "VEDL.NS (61% off high)" in md
    assert "NOT YET" in md
    assert "all holdings healthy" in md
    assert "Add money" in md


def test_today_brief_markdown_minimal_normal_market() -> None:
    from datetime import date

    from qalpha.live.dashboard import today_brief_markdown

    md = today_brief_markdown(
        date(2026, 6, 30),
        core_action="Hold",
        market_level="normal",
        market_drawdown=-0.01,
        market_note="near highs — deploy steadily.",
        hedge_note="no hedge indicated.",
        health_note="no holdings yet.",
    )
    assert "🟢" in md  # normal-market badge
    assert "Add money" in md
