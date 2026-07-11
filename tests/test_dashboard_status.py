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


# --- watchlist staleness (Ops Layer PR-2) -------------------------------------------------------


def test_watchlist_fresh_across_a_weekend() -> None:
    from qalpha.live.dashboard import watchlist_is_stale

    # Panel last dated Friday, read Monday → one weekday elapsed (grace) → fresh.
    assert not watchlist_is_stale(date(2026, 6, 12), date(2026, 6, 15))


def test_watchlist_stale_after_several_weekdays() -> None:
    from qalpha.live.dashboard import watchlist_is_stale

    # Panel a full week old → past the 3-weekday tolerance → stale, re-download.
    assert watchlist_is_stale(date(2026, 6, 8), date(2026, 6, 15))


# --- live PM brief formatter (Ops Layer PR-2) ---------------------------------------------------


def _advice(level: str, buys: list[tuple[str, int]], leftover: str):  # type: ignore[no-untyped-def]
    from decimal import Decimal

    from qalpha.backtest.portfolio import Side, TradeRecord
    from qalpha.live.advisor import DeployAdvice
    from qalpha.live.deploy import MarketWeakness, WeaknessDeployAdvice

    orders = [
        TradeRecord(
            date(2026, 6, 30), t, Side.BUY, Decimal(q), Decimal("100"), Decimal("1"), Decimal("0")
        )
        for t, q in buys
    ]
    deploy = DeployAdvice(
        as_of=date(2026, 6, 30),
        amount=Decimal("12430"),
        buy_orders=orders,
        buy_cost=Decimal("10"),
        leftover_cash=Decimal(leftover),
        naive_tax=Decimal("0"),
        naive_cost=Decimal("0"),
        tax_saved=Decimal("0"),
    )
    weakness = MarketWeakness(-0.02, level, "note")
    return WeaknessDeployAdvice(
        weakness=weakness, deploy=deploy, target=pd.Series(dtype=float), cheapest=[]
    )


def test_live_pm_brief_aggregates_buys_and_shows_tax_free() -> None:
    from decimal import Decimal

    from qalpha.live.dashboard import live_pm_brief_markdown

    advice = _advice("normal", [("ITC.NS", 2), ("NTPC.NS", 1)], "514")
    md = live_pm_brief_markdown(Decimal("12430"), advice, floor=Decimal("5000"))
    assert "Idle cash ₹12,430" in md
    assert "🟢 normal" in md
    assert "2×ITC" in md and "1×NTPC" in md
    assert "₹0 capital-gains tax" in md
    assert "leftover ₹514" in md


def test_live_pm_brief_suppressed_below_floor() -> None:
    from decimal import Decimal

    from qalpha.live.dashboard import live_pm_brief_markdown

    advice = _advice("normal", [("ITC.NS", 1)], "0")
    assert live_pm_brief_markdown(Decimal("4999"), advice, floor=Decimal("5000")) == ""


# --- plain-English clarity layer (dashboard follow-up) ------------------------------------------


def test_performance_read_ahead_behind_tracking() -> None:
    from qalpha.live.dashboard import performance_read

    assert "Ahead of the market" in performance_read(5.0, 2.0)
    assert "Behind the market" in performance_read(1.0, 4.0)
    assert "tracking" in performance_read(2.0, 2.1)
    assert "since it started" in performance_read(3.0, None)  # no benchmark → graceful


def test_plain_summary_covers_all_four_lines() -> None:
    from qalpha.live.dashboard import plain_summary_markdown

    md = plain_summary_markdown(
        book_return_pct=2.5,
        benchmark_return_pct=1.0,
        market_level="elevated",
        go_verdict="NOT YET",
        action_needed=True,
    )
    assert "In plain English" in md
    assert "How you're doing" in md and "Ahead of the market" in md
    assert "better-than-usual time to add" in md  # elevated market, plain words
    assert "Still proving itself" in md  # NOT YET, plain words
    assert "there's a suggested action below" in md  # action_needed


def test_plain_summary_no_action_and_go() -> None:
    from qalpha.live.dashboard import plain_summary_markdown

    md = plain_summary_markdown(
        book_return_pct=1.0,
        benchmark_return_pct=1.0,
        market_level="normal",
        go_verdict="GO",
        action_needed=False,
    )
    assert "nothing needs your attention" in md
    assert "Cleared" in md  # GO → plain


def test_glossary_defines_key_terms() -> None:
    from qalpha.live.dashboard import glossary_markdown

    md = glossary_markdown()
    for term in ("Nifty 50 TRI", "Drawdown", "Sharpe", "Systemic risk", "Realized tax"):
        assert term in md


def test_live_pm_brief_handles_no_affordable_buys() -> None:
    from decimal import Decimal

    from qalpha.live.dashboard import live_pm_brief_markdown

    advice = _advice("deep", [], "6000")
    md = live_pm_brief_markdown(Decimal("6000"), advice, floor=Decimal("5000"))
    assert "🔴 deep" in md
    assert "nothing fits cleanly" in md
