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
    decisions_markdown,
)
from qalpha.live.twin import AUTONOMOUS, SYSTEM


def test_there_is_a_policy_for_every_autonomous_book() -> None:
    assert set(POLICIES) == set(AUTONOMOUS)


def test_the_headline_runs_everything() -> None:
    assert POLICIES[SYSTEM].ablated is None


def test_a_decision_without_a_reason_is_refused() -> None:
    """An unexplained decision is not auditable. Enforced by the type, not by review."""
    with pytest.raises(ValueError, match="no reason"):
        Decision(on=date(2026, 9, 1), book=SYSTEM, action=DEPLOY, reason="   ")


def test_a_decision_renders_what_and_why() -> None:
    d = Decision(
        on=date(2026, 9, 1),
        book=SYSTEM,
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
    d = Decision(on=date(2026, 9, 1), book=SYSTEM, action=HOLD, reason="market normal")
    assert HOLD in d.render()


def test_an_empty_log_does_not_look_like_a_quiet_day() -> None:
    """The 38-day silent death again: 'nothing happened' and 'nothing ran' must not read alike."""
    md = decisions_markdown([])
    assert "check the last mark date" in md
