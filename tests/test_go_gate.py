"""The GO gate: six criteria, and the distinction between 'failing' and 'cannot tell'."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from qalpha.live.go_gate import (
    CANNOT_ASSESS,
    GREEN,
    MIN_MONTHS,
    Evidence,
    build_gate,
)

_AS_OF = date(2026, 8, 29)


def _all_green() -> Evidence:
    return Evidence(
        months_of_flows=18,
        worst_drawdown_in_window=-0.14,
        gap_vs_ew_baseline=Decimal("2000000"),
        log_rel_wealth=0.18,
        null_p95=0.05,
        reconciled_complex_sale=True,
        reconciled_corporate_action=True,
        tradebook_reconciles=True,
        unguarded_price_gaps=0,
    )


def test_all_six_green_opens_the_gate() -> None:
    report = build_gate(_all_green(), _AS_OF)
    assert len(report.criteria) == 6
    assert report.verdict == "GO"
    assert report.blocking == []


def test_an_empty_evidence_set_cannot_assess_anything_and_blocks() -> None:
    """Nothing defaults. A gate with no evidence must not read as a pass OR as a failure."""
    report = build_gate(Evidence(), _AS_OF)
    assert report.verdict == "NOT YET"
    assert all(c.verdict == CANNOT_ASSESS for c in report.criteria)
    assert len(report.blocking) == 6


def test_cannot_assess_is_not_the_same_as_red() -> None:
    """Missing evidence is not failure — collapsing them is how a stale benchmark read a fall as 0.0%."""
    unknown = build_gate(Evidence(worst_drawdown_in_window=None), _AS_OF).criteria[1]
    calm = build_gate(Evidence(worst_drawdown_in_window=-0.02), _AS_OF).criteria[1]
    assert unknown.verdict == CANNOT_ASSESS
    assert calm.verdict != CANNOT_ASSESS
    assert unknown.reading != calm.reading


def test_every_blocking_criterion_says_what_would_settle_it() -> None:
    for c in build_gate(Evidence(), _AS_OF).blocking:
        assert c.settles_it, f"{c.name} blocks without saying what would resolve it"


def test_a_gap_without_a_null_cannot_be_read() -> None:
    """Forward run 1 was voided for exactly this: a difference with no bar behind it."""
    ev = Evidence(gap_vs_ew_baseline=Decimal("50000000"), log_rel_wealth=2.0, null_p95=None)
    c = build_gate(ev, _AS_OF).criteria[2]
    assert c.verdict == CANNOT_ASSESS
    assert "has not been run" in c.reading


def test_a_gap_inside_the_null_band_is_not_a_pass() -> None:
    ev = Evidence(gap_vs_ew_baseline=Decimal("500"), log_rel_wealth=0.004, null_p95=0.05)
    assert build_gate(ev, _AS_OF).criteria[2].verdict != GREEN


def test_the_bar_is_the_fund_not_the_index() -> None:
    """Phase 4: 76% of the gap over NIFTYBEES is a premium anyone can buy for 0.41%/yr."""
    c = build_gate(Evidence(), _AS_OF).criteria[2]
    assert "equal-weight fund" in c.name.lower()


def test_a_calm_market_blocks_and_says_nobody_has_watched_it_fall() -> None:
    ev = Evidence(worst_drawdown_in_window=-0.022)
    c = build_gate(ev, _AS_OF).criteria[1]
    assert c.blocks
    assert "nobody has watched" in c.settles_it.lower()


def test_short_track_names_the_months_remaining() -> None:
    c = build_gate(Evidence(months_of_flows=2), _AS_OF).criteria[0]
    assert f"2 of {MIN_MONTHS}" in c.reading
    assert "10 more months" in c.settles_it


def test_the_render_never_calls_a_blocked_system_validated() -> None:
    md = build_gate(Evidence(), _AS_OF).render()
    assert "NOT YET" in md
    assert "not validated for real money" in md
    assert "What would settle each" in md


def test_one_red_is_enough_to_block() -> None:
    ev = Evidence(**{**_all_green().__dict__, "tradebook_reconciles": False})
    report = build_gate(ev, _AS_OF)
    assert report.verdict == "NOT YET"
    assert len(report.blocking) == 1
