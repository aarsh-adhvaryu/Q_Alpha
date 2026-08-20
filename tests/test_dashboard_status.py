"""Tests for the paper-run freshness signal + systemic-risk watch render (qalpha.live.dashboard)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import cast

import pandas as pd

from qalpha.accounting.tax_lots import FIFOLedger, TaxLot
from qalpha.live.dashboard import (
    ChecklistItem,
    checklist_markdown,
    ltcg_safe_sell_note,
    next_actions,
    paper_freshness,
    systemic_risk_markdown,
    unverified_tax_branches,
)
from qalpha.live.paper import PaperBook


def _ledger(*acq_dates: date) -> FIFOLedger:
    led = FIFOLedger()
    for d in acq_dates:
        led.add_lot(
            TaxLot(
                ticker="X",
                acquisition_date=d,
                quantity_original=Decimal("10"),
                buy_price=Decimal("100"),
            )
        )
    return led


def test_ltcg_safe_note_already_long_term() -> None:
    # Bought > 365 days ago → whole line already long-term → sell now at 12.5%.
    note = ltcg_safe_sell_note(_ledger(date(2025, 1, 1)), "X", date(2026, 7, 27))
    assert note == "🟢 now (12.5%)"


def test_ltcg_safe_note_still_short_term_shows_days_and_date() -> None:
    # Bought 2026-06-12. §2(42A) needs MORE than 12 months, so the 12-month anniversary
    # (2027-06-12) is still short-term — the first safe date is the day after, 2027-06-13.
    note = ltcg_safe_sell_note(_ledger(date(2026, 6, 12)), "X", date(2026, 7, 27))
    assert note.startswith("⏳ 321d")  # (2027-06-13 - 2026-07-27) = 321 days
    assert "13 Jun 27" in note


def test_ltcg_safe_note_uses_newest_lot_for_whole_line() -> None:
    # One old (LT) lot + one new (ST) lot → the *whole* line is only safe once the newest crosses.
    led = _ledger(date(2024, 1, 1), date(2026, 6, 12))
    note = ltcg_safe_sell_note(led, "X", date(2026, 7, 27))
    assert "13 Jun 27" in note  # governed by the newest lot, not the already-long-term old one


def test_ltcg_safe_note_anniversary_is_not_yet_safe() -> None:
    """The regression this fix exists for: on the 12-month anniversary the line is STILL 20%."""
    led = _ledger(date(2025, 7, 27))
    assert ltcg_safe_sell_note(led, "X", date(2026, 7, 27)) == "⏳ 1d · 28 Jul 26"  # not 🟢
    assert ltcg_safe_sell_note(led, "X", date(2026, 7, 28)) == "🟢 now (12.5%)"


def test_ltcg_safe_note_no_holding() -> None:
    assert ltcg_safe_sell_note(FIFOLedger(), "X", date(2026, 7, 27)) == "—"


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


# ---- the buy-advice gate (PLAN_TRUST_REPAIR.md PR-1 → PR-3) --------------------------------------


def test_buy_advice_is_back_on_the_real_money_surface() -> None:
    """PR-1 switched it off; PR-3 restores it once both defects are actually fixed.

    The flag survives as a working kill-switch, which is the point: turning the buy list off must
    stay a one-constant change, not a revert.
    """
    from qalpha.live.dashboard import BUY_ADVICE_ON_REAL_MONEY

    assert BUY_ADVICE_ON_REAL_MONEY is True


def test_the_kill_switch_notice_does_not_claim_a_fixed_defect_as_the_reason() -> None:
    """A notice that lies about why it is showing would be its own trust failure."""
    from qalpha.live.dashboard import buy_advice_withheld_markdown

    md = buy_advice_withheld_markdown()
    assert "switched off" in md
    assert "VEDL" not in md and "demerger" not in md  # PR-1's reasons; both fixed
    assert "Sell a holding" in md and "Raise cash" in md  # what stays live, always stated


def test_blocked_notice_names_the_failing_guard_and_spares_the_sell_side() -> None:
    """The *data* case, distinct from the kill switch: the rule is fine, the prices are not."""
    from qalpha.live.dashboard import buy_advice_blocked_markdown

    md = buy_advice_blocked_markdown(["latest watchlist price is 2026-07-10 — 27 weekdays stale"])
    assert "2026-07-10" in md
    assert "withheld" in md
    assert "Raise cash" in md


def test_the_scope_note_states_the_screen_was_never_backtested() -> None:
    """T1.5 on screen: the buy rule is not the 18.2% strategy, and must say so on every render."""
    from qalpha.live.dashboard import buy_advice_scope_note

    md = buy_advice_scope_note()
    assert "never been backtested" in md
    assert "18.2%" in md
    assert "no selection code" in md
    assert "₹0 capital-gains tax" in md  # what it *is* still gets said plainly
    # …and since 2026-08-19 it states that the screen decides rather than deferring.
    assert "removes any that its §4.7 breakdown test says" in md
    assert "bought, not adjudicated" in md


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


# ---- the operating checklist -------------------------------------------------------------------


def _actions(**over: object) -> list[ChecklistItem]:
    base: dict[str, object] = {
        "advice_safe": True,
        "tradebook_trades": 4,
        "reconciles": True,
        "idle_cash": Decimal("0"),
        "cash_floor": Decimal("5000"),
        "holdings": 1,
        "days_to_next_ltcg": None,
        "unreconciled_sells": 0,
    }
    base.update(over)
    return next_actions(**base)  # type: ignore[arg-type]


def test_checklist_blocks_when_inputs_are_untrustworthy() -> None:
    item = _actions(advice_safe=False)[0]
    assert item.state == "blocked"
    assert "withheld" in item.detail


def test_checklist_asks_for_a_tradebook_when_there_is_none() -> None:
    item = _actions(tradebook_trades=0)[1]
    assert item.state == "todo"
    assert "Console" in item.detail


def test_checklist_blocks_on_a_tradebook_that_does_not_reconcile() -> None:
    """An unreconciled book means every tax figure is an estimate — that must not read as 'done'."""
    item = _actions(reconciles=False)[1]
    assert item.state == "blocked"
    assert "IPO allotments" in item.detail


def test_checklist_prompts_to_deploy_only_above_the_floor() -> None:
    assert _actions(idle_cash=Decimal("50000"))[2].state == "todo"
    assert _actions(idle_cash=Decimal("100"))[2].state == "done"


def test_checklist_does_not_route_to_a_withheld_buy_list() -> None:
    """With the buy list unavailable, 'use Add money for the buy plan' is a dead pointer.

    Since PR-3 this fires on the *data* path too — a stale watchlist panel makes buy advice
    unavailable even though the flag is on.
    """
    item = _actions(idle_cash=Decimal("50000"), buy_advice_available=False)[2]
    assert item.state == "blocked"
    assert "withheld" in item.detail
    assert "Use **Add money**" not in item.detail
    # Below the floor there is nothing to route either way — the withheld branch must not fire.
    assert _actions(idle_cash=Decimal("100"), buy_advice_available=False)[2].state == "done"


def test_checklist_says_hold_until_the_ltcg_crossover() -> None:
    hold = _actions(days_to_next_ltcg=308)[3]
    assert hold.state == "waiting"
    assert "308 days" in hold.detail
    assert _actions(days_to_next_ltcg=None)[3].state == "done"


def test_checklist_asks_for_the_taxpnl_only_after_a_sell() -> None:
    assert not any("realized tax" in i.label for i in _actions(unreconciled_sells=0))
    assert any("realized tax" in i.label for i in _actions(unreconciled_sells=1))


def test_checklist_markdown_renders_every_item() -> None:
    md = checklist_markdown(_actions())
    assert md.count("\n") == len(_actions()) - 1
    assert "✅" in md


# ---- unverified tax branches --------------------------------------------------------------------


def test_simple_stcg_gain_sale_flags_nothing() -> None:
    """The already-reconciled shape (single lot, STCG, gain) must stay silent."""
    assert (
        unverified_tax_branches(
            has_loss_lot=False, has_ltcg=False, distinct_cost_bases=1, uses_exemption=False
        )
        == []
    )


def test_each_unverified_branch_is_named() -> None:
    out = unverified_tax_branches(
        has_loss_lot=True, has_ltcg=True, distinct_cost_bases=3, uses_exemption=True
    )
    assert len(out) == 4
    assert any("§70" in b for b in out)
    assert any("3 different cost bases" in b for b in out)


# ---- the AI's actual output (PLAN_TRUST_REPAIR.md PR-4 — fixes T2.5) ------------------------------


def test_ai_summary_leads_with_the_signal_and_says_it_picks_no_stock() -> None:
    """The whole machine-readable contract is one line with no ticker field — say so where it shows.

    Rendering per-name prose under a buy list is what made the brief read as "the AI chose these".
    """
    from qalpha.live.dashboard import ai_signal_summary

    md = ai_signal_summary("up", "medium", 1.25, consumed_by="the 🧠 System book only (fake money)")
    assert "lean=up" in md and "confidence=medium" in md
    assert "×1.25" in md and "larger" in md
    assert "no ticker field" in md
    assert "System book only" in md


def test_ai_summary_reports_a_neutral_tilt_as_no_change() -> None:
    from qalpha.live.dashboard import ai_signal_summary

    md = ai_signal_summary("flat", "low", 1.0, consumed_by="the System book")
    assert "no change to deploy size" in md


def test_a_missing_brief_changes_nothing_about_name_selection() -> None:
    from qalpha.live.dashboard import ai_signal_summary

    md = ai_signal_summary(None, None, 1.0, consumed_by="the System book")
    assert "No AI signal today" in md
    assert "×1.00" in md
    assert "changes nothing about which names" in md


# ---- daily-source freshness (PLAN_TRUST_REPAIR.md PR-5 — fixes T3.3) ------------------------------


def test_a_source_written_today_is_fresh() -> None:
    from qalpha.live.dashboard import source_freshness

    s = source_freshness("Track record", date(2026, 6, 18), date(2026, 6, 18))
    assert not s.is_stale
    assert "up to date" in s.note


def test_a_friday_source_read_on_monday_is_still_fresh() -> None:
    """Weekday-aware, with one weekday of grace — today's run may not have fired yet."""
    from qalpha.live.dashboard import source_freshness

    assert not source_freshness("Scoreboard", date(2026, 6, 12), date(2026, 6, 15)).is_stale


def test_a_source_that_missed_a_weekday_is_stale() -> None:
    from qalpha.live.dashboard import source_freshness

    s = source_freshness("Scoreboard", date(2026, 6, 15), date(2026, 6, 18))  # Mon → Thu
    assert s.is_stale
    assert s.weekdays_stale == 2
    assert "weekday(s) missed" in s.note


def test_a_source_that_was_never_written_is_stale_not_silent() -> None:
    from qalpha.live.dashboard import source_freshness

    s = source_freshness("AI brief", None, date(2026, 6, 18))
    assert s.is_stale
    assert "never written" in s.note


def test_the_summary_names_every_stale_source() -> None:
    """A stopped cron must be legible, not inferred from numbers that stopped moving."""
    from qalpha.live.dashboard import source_freshness, sources_freshness_markdown

    today = date(2026, 6, 18)
    md = sources_freshness_markdown(
        [
            source_freshness("Track record", date(2026, 6, 18), today),
            source_freshness("Scoreboard", date(2026, 6, 10), today),
            source_freshness("AI brief", None, today),
        ]
    )
    assert "2 of 3 daily sources are stale" in md
    assert "Scoreboard" in md and "AI brief" in md
    assert "frozen at its last successful pass" in md


def test_the_summary_is_a_single_quiet_line_when_everything_is_current() -> None:
    from qalpha.live.dashboard import source_freshness, sources_freshness_markdown

    today = date(2026, 6, 18)
    md = sources_freshness_markdown([source_freshness("Track record", today, today)])
    assert md.startswith("✓")
    assert "stale" not in md
    assert sources_freshness_markdown([]) == ""


# ---- the Add-money audit banner (PLAN_TRUST_REPAIR.md PR-6 — fixes T3.1) --------------------------


def test_the_drift_banner_reports_the_gap_and_reassures_about_the_money() -> None:
    """₹240,500 of drift sat in a cron log for a month. A print is not a report."""
    from qalpha.live.dashboard import injection_drift_markdown

    md = injection_drift_markdown(Decimal("440500"), Decimal("200000"))
    assert "₹240,500" in md
    assert "₹440,500" in md and "₹200,000" in md
    assert "Your money is fine" in md  # the books were never wrong; say so before anything else
    assert "state.json" in md
    assert "never by deleting entries" in md


def test_the_banner_is_silent_when_the_log_reconciles() -> None:
    from qalpha.live.dashboard import injection_drift_markdown

    assert injection_drift_markdown(Decimal("200000"), Decimal("200000")) == ""


def test_the_banner_handles_an_under_counting_log_too() -> None:
    """Drift in the other direction is just as much a broken audit trail."""
    from qalpha.live.dashboard import injection_drift_markdown

    md = injection_drift_markdown(Decimal("150000"), Decimal("200000"))
    assert "₹50,000" in md
    assert "less than" in md


# ---- the health panel renders once, and reads for a human (2026-08-19) ---------------------------


def _report(*rows: tuple[str, float, float, str]):  # type: ignore[no-untyped-def]
    from qalpha.live.position_health import HoldingHealth, PositionHealthReport

    return PositionHealthReport(
        date(2026, 8, 19),
        [HoldingHealth(t, ret, exc, 0.0, lvl, f"{t}: note") for t, ret, exc, lvl in rows],
    )


def test_a_weak_name_is_listed_exactly_once() -> None:
    """The bug the user hit: every holding printed, then the weak ones printed *again* below.

    One weak name appeared twice on one screen, which is what made the panel read as twice as
    complicated as it is.
    """
    from qalpha.live.dashboard import health_panel_markdown

    md = health_panel_markdown(
        _report(("NTPC.NS", -0.09, -0.07, "watch"), ("BEL.NS", -0.08, -0.06, "watch"))
    )
    assert md.count("| NTPC |") == 1
    assert md.count("| BEL |") == 1


def test_the_headline_says_whether_anything_needs_doing() -> None:
    from qalpha.live.dashboard import health_panel_markdown

    healthy = health_panel_markdown(_report(("ITC.NS", 0.10, 0.09, "healthy")))
    assert "All 1 holdings healthy" in healthy and "Nothing to do" in healthy

    watching = health_panel_markdown(
        _report(("NTPC.NS", -0.09, -0.07, "watch"), ("ITC.NS", 0.10, 0.09, "healthy"))
    )
    assert "weak, none broken" in watching
    assert "this is a watch, not an alert" in watching  # a 🟠 is not a call to action

    broken = health_panel_markdown(
        _report(("VEDL.NS", -0.55, -0.56, "breaking"), ("ITC.NS", 0.10, 0.09, "healthy"))
    )
    assert "1 of 2 holdings look broken" in broken
    assert "VEDL" in broken.splitlines()[0]  # named in the headline, not buried in the table


def test_the_worst_holding_is_listed_first() -> None:
    from qalpha.live.dashboard import health_panel_markdown

    md = health_panel_markdown(
        _report(("GOOD.NS", 0.20, 0.19, "healthy"), ("BAD.NS", -0.40, -0.41, "breaking"))
    )
    # The header row contains "6-month" and the separator starts with "|-", so both are already out.
    rows = [ln for ln in md.splitlines() if ln.startswith("| ") and "6-month" not in ln]
    assert "BAD" in rows[0]
    assert "GOOD" in rows[1]


def test_no_holdings_says_so_rather_than_rendering_an_empty_table() -> None:
    from qalpha.live.dashboard import health_panel_markdown

    assert health_panel_markdown(_report()) == "No holdings to watch yet."
