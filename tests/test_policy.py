"""The autonomy layer: single-factor ablations, and decisions that must explain themselves."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from qalpha.live.policy import (
    DEPLOY,
    HOLD,
    POLICIES,
    Decision,
    Policy,
    assert_single_factor_ablations,
    decisions_markdown,
)
from qalpha.live.twin import AUTONOMOUS, TWIN_FULL, TWIN_NO_AI, TWIN_NO_EXITS, TWIN_NO_HEDGE


def test_there_is_a_policy_for_every_autonomous_book() -> None:
    assert set(POLICIES) == set(AUTONOMOUS)


def test_the_headline_runs_everything() -> None:
    assert POLICIES[TWIN_FULL].ablated is None


@pytest.mark.parametrize(
    ("book", "removed"),
    [(TWIN_NO_AI, "AI"), (TWIN_NO_HEDGE, "hedge"), (TWIN_NO_EXITS, "exits")],
)
def test_each_ablation_names_the_one_factor_it_removes(book: str, removed: str) -> None:
    assert POLICIES[book].ablated == removed


def test_every_ablation_differs_in_exactly_one_factor() -> None:
    """Two differences and the gap is attributable to neither — worse than no diagnostic, because
    it invites a story."""
    assert_single_factor_ablations()  # must not raise


def test_a_two_factor_ablation_is_refused() -> None:
    bad = dict(POLICIES)
    bad["BROKEN"] = Policy("BROKEN", use_ai=False, use_hedge=False)
    with pytest.raises(ValueError, match="differs from TWIN_FULL in 2 factors"):
        assert_single_factor_ablations(bad)


# ---- decisions must explain themselves ----------------------------------------------------------


def test_a_decision_without_a_reason_is_refused() -> None:
    """An unexplained decision is not auditable. Enforced by the type, not by review."""
    with pytest.raises(ValueError, match="no reason"):
        Decision(on=date(2026, 9, 1), book=TWIN_FULL, action=DEPLOY, reason="   ")


def test_a_decision_renders_what_and_why() -> None:
    d = Decision(
        on=date(2026, 9, 1),
        book=TWIN_FULL,
        action=DEPLOY,
        reason="market weakness elevated; pre-committed tranche 50% of idle cash",
        ticker="INFY.NS",
        quantity=Decimal("15"),
    )
    text = d.render()
    assert "INFY.NS" in text and "15" in text
    assert "pre-committed tranche" in text, "the WHY must survive into the log"


def test_a_hold_is_still_a_recorded_decision() -> None:
    """Holding is a choice the comparison charges the book for; it must appear, not be inferred."""
    d = Decision(on=date(2026, 9, 1), book=TWIN_NO_AI, action=HOLD, reason="market normal")
    assert HOLD in d.render()


def test_an_empty_log_does_not_look_like_a_quiet_day() -> None:
    """The 38-day silent death again: 'nothing happened' and 'nothing ran' must not read alike."""
    md = decisions_markdown([])
    assert "check the last mark date" in md
