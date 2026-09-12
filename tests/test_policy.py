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


def test_the_live_policy_is_the_one_that_was_registered() -> None:
    """PL-1, `reports/PREREGISTRATION_LIVE_POLICY.md`, registered 2026-09-12.

    This test exists to make a silent change loud. The policy was frozen two days before
    `EVALUATION_START`; if someone flips a flag during the window, the run is a rehearsal rather
    than an experiment — which is exactly how run 2 was demoted. Changing this assertion is
    therefore a deliberate act that has to be argued for in the registration's section 8, not a
    line edited to make a suite go green.
    """
    live = POLICIES[SYSTEM]
    assert live.use_exits is False, "PL-1 (A): the §4.7 exits lose to the tax, measured twice"
    assert live.use_ai is True
    assert live.use_hedge is True


def test_the_mandate_is_the_one_that_was_registered() -> None:
    """The other half of PL-1 — B, C and D live in the mandate, not in the policy.

    **Two of the three were refused by the measurement**, and they are pinned here at the values
    that survived, because the refusal is the valuable part rather than an embarrassment to tidy
    away. See `reports/PREREGISTRATION_LIVE_POLICY.md` §8.
    """
    from qalpha.live.mandate import Mandate

    m = Mandate()
    assert m.max_names == 8, "PL-1 (C): PO-2 is monotone in concentration — 8 beat 15 beat 30"
    # Turning the breakdown filter off scored +8 points in PO-2's hand-written loop and -23.2%
    # through the real runner, because the filter is also the only thing that evicts a collapsing
    # holding once `use_exits` is off. Two honest measurements of what looked like one switch.
    assert m.exclude_breaking is True, "PL-1 (B) was REJECTED: -23.2% through runner.step"
    assert m.concentrate is False, "PL-1 (D) was neutral: -0.5%, so it did not ship"


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
