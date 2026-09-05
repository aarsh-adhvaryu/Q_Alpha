"""CORE_V1 — the deterministic screen's own clock (reports/PREREGISTRATION_CORE_V1.md).

The experiment exists to break one coupling: every ``TWIN_*`` book is the composite minus a flag, so
it moves whenever the composite moves, and a book that moves cannot carry a twelve-month clock. Each
test here pins one half of that isolation. If any of them goes red, the core clock has been
re-coupled to something under construction and the window has silently restarted.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from qalpha.live.policy import (
    ALL_POLICIES,
    CORE_POLICY,
    POLICIES,
    assert_core_is_not_an_ablation,
    assert_single_factor_ablations,
)
from qalpha.live.twin import (
    ALL_BOOKS,
    AUTONOMOUS,
    BASELINE_EW,
    CORE_EVALUATION_START,
    CORE_GATING_PAIR,
    CORE_V1,
    DECIDING,
    EVALUATION_START,
    GATING_PAIR,
    TWIN_FULL,
    BookMark,
    compare,
)


def _mark(
    name: str, value: str, invested: str = "300000", as_of: date = date(2026, 10, 1)
) -> BookMark:
    return BookMark(
        name=name,
        as_of=as_of,
        start=date(2026, 9, 8),
        net_invested=Decimal(invested),
        value=Decimal(value),
        rate=None,
    )


# --- the treatment is frozen and independent -------------------------------------------------


def test_core_policy_is_deterministic_only() -> None:
    assert CORE_POLICY.use_ai is False
    assert CORE_POLICY.use_hedge is False
    assert CORE_POLICY.use_exits is True


def test_core_is_not_in_the_ablation_family() -> None:
    """In POLICIES it would be defined relative to TWIN_FULL, which is the coupling it breaks."""
    assert CORE_V1 not in POLICIES
    assert CORE_V1 not in AUTONOMOUS
    assert_core_is_not_an_ablation()
    assert_single_factor_ablations()


def test_core_still_steps_daily() -> None:
    assert CORE_V1 in DECIDING and CORE_V1 in ALL_POLICIES and CORE_V1 in ALL_BOOKS


def test_the_two_clocks_are_different_dates() -> None:
    """A shared start date would make one experiment's window the other's by accident."""
    assert CORE_EVALUATION_START > EVALUATION_START


def test_the_core_window_opens_after_every_observed_day() -> None:
    """Run 2's observed days are 09-01 to 09-04. Starting inside them is selection on the outcome."""
    assert date(2026, 9, 4) < CORE_EVALUATION_START


# --- the gates do not steal each other ---------------------------------------------------------


def test_each_track_has_its_own_gating_pair() -> None:
    assert GATING_PAIR == (TWIN_FULL, BASELINE_EW)
    assert CORE_GATING_PAIR == (CORE_V1, BASELINE_EW)
    assert GATING_PAIR != CORE_GATING_PAIR


def test_compare_labels_every_gap_with_its_track() -> None:
    marks = {
        n: _mark(n, "310000")
        for n in (TWIN_FULL, CORE_V1, BASELINE_EW, "BASELINE", "TWIN_NO_AI", "REAL")
    }
    gaps = compare(marks)
    tracks = {(g.left, g.right): g.track for g in gaps}
    assert tracks[(CORE_V1, BASELINE_EW)] == "core_v1"
    assert tracks[(TWIN_FULL, BASELINE_EW)] == "run2"


def test_exactly_one_gating_pair_per_track() -> None:
    marks = {n: _mark(n, "310000") for n in (TWIN_FULL, CORE_V1, BASELINE_EW)}
    gating = [g for g in compare(marks) if g.gates]
    assert sorted(g.track for g in gating) == ["core_v1", "run2"]


def test_run2_gate_is_still_twin_full_vs_the_fund() -> None:
    """The GO gate belongs to run 2. Picking the first gating gap would silently move it."""
    marks = {n: _mark(n, "310000") for n in (TWIN_FULL, CORE_V1, BASELINE_EW)}
    run2 = next(g for g in compare(marks) if g.gates and g.track == "run2")
    assert (run2.left, run2.right) == GATING_PAIR


def test_each_track_counts_months_from_its_own_start() -> None:
    """On 2026-10-01 run 2 has served a month and the core window has served 23 days."""
    marks = {n: _mark(n, "310000") for n in (TWIN_FULL, CORE_V1, BASELINE_EW)}
    by_track = {g.track: g for g in compare(marks) if g.gates}
    assert (by_track["run2"].months, by_track["core_v1"].months) == (1, 0)


def test_a_partial_month_rounds_down() -> None:
    """Calendar-month subtraction called 23 days "one month". Over-counting opens a gate early."""
    from qalpha.live.twin import evaluation_months

    assert evaluation_months(date(2026, 10, 7), start=CORE_EVALUATION_START) == 0
    assert evaluation_months(date(2026, 10, 8), start=CORE_EVALUATION_START) == 1


def test_the_core_window_needs_twelve_served_months_not_twelve_calendar_boundaries() -> None:
    from qalpha.live.twin import evaluation_months

    assert evaluation_months(date(2027, 9, 1), start=CORE_EVALUATION_START) == 11
    assert evaluation_months(date(2027, 9, 8), start=CORE_EVALUATION_START) == 12


def test_run_2_month_counting_is_unchanged() -> None:
    """It opens on the 1st, so the day-aware fix cannot move it. Pinned so nobody has to re-check."""
    from qalpha.live.twin import evaluation_months

    assert evaluation_months(date(2027, 9, 1), start=EVALUATION_START) == 12
    assert evaluation_months(date(2026, 9, 30), start=EVALUATION_START) == 0


def test_a_track_never_borrows_the_other_tracks_nav() -> None:
    """Namespaced NAV keys. A NAV unitized from run 2's start says nothing about a later window."""
    marks = {n: _mark(n, "310000") for n in (TWIN_FULL, CORE_V1, BASELINE_EW)}
    navs = {
        "run2:TWIN_FULL": 1.10,
        "run2:BASELINE_EW": 1.00,
        "core_v1:CORE_V1": 1.02,
        "core_v1:BASELINE_EW": 1.01,
    }
    by_track = {g.track: g for g in compare(marks, navs=navs) if g.gates}
    assert by_track["run2"].left_nav == 1.10
    assert by_track["core_v1"].left_nav == 1.02
    assert by_track["core_v1"].right_nav == 1.01


def test_a_missing_core_nav_cannot_assess_rather_than_defaulting() -> None:
    marks = {n: _mark(n, "310000") for n in (TWIN_FULL, CORE_V1, BASELINE_EW)}
    core = next(g for g in compare(marks, navs={}) if g.track == "core_v1" and g.gates)
    assert core.left_nav is None and core.log_rel_wealth is None
