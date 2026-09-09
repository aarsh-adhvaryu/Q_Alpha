"""Memory: what the system already decided, and what it is still waiting for.

The behaviour asked for, in the user's words: *"I just don't want it to invest like — ok, it
invested — after running every time. It should actually take decisions of 'fine, I am waiting on
this', or 'this seems to be invested well', then it monitors."*

Before this module, measured: ₹2,01,117 → offers ₹50,000; spend it → offers ₹50,000; spend it →
offers ₹50,000. ``Mandate.deployable`` is stateless by design — it answers "what does the mandate
allow", not "what is left". These tests pin the second question, and the distinction the whole
module turns on: **a recommendation is not a fill.**
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from qalpha.live.commitments import (
    Commitment,
    allowance,
    already_committed,
    load,
    open_proposals,
    record,
    stale_proposals,
    summary,
    waiting,
)

SEPT = date(2026, 9, 1)
AUTHORISED = Decimal("50000")


def _c(id_: str, ticker: str, state: str, amount: str, on: date, **kw: object) -> Commitment:
    return Commitment(
        id=id_,
        ticker=ticker,
        state=state,  # type: ignore[arg-type]
        amount=Decimal(amount),
        on=on,
        reason=str(kw.get("reason", "")),
        trigger=str(kw.get("trigger", "")),
        filled_on=kw.get("filled_on"),  # type: ignore[arg-type]
    )


# --- the defect this module exists for ----------------------------------------------------------
def test_the_allowance_does_not_reset_every_run() -> None:
    """The measured behaviour before this: ₹50,000 offered, spent, offered again, spent, offered."""
    bought = [_c("1", "VBL.NS", "filled", "30000", date(2026, 9, 3), filled_on=date(2026, 9, 3))]
    left = allowance(AUTHORISED, bought, period=SEPT)
    assert left.remaining == Decimal("20000")
    assert not left.exhausted


def test_a_proposal_reserves_the_allowance_before_it_is_money() -> None:
    """The distinction the module turns on. A proposal that did not hold back allowance would let
    the next run propose the same rupees again — which is the behaviour being removed."""
    proposed = [_c("1", "VBL.NS", "proposed", "50000", date(2026, 9, 8))]
    left = allowance(AUTHORISED, proposed, period=SEPT)
    assert left.reserved == Decimal("50000")
    assert left.spent == Decimal("0"), "proposing is not buying"
    assert left.exhausted, "nothing more may be proposed against the same rupees"


def test_a_declined_proposal_releases_its_allowance() -> None:
    """Abandoned money is spendable again — otherwise one declined suggestion costs a month."""
    trail = [
        _c("1", "VBL.NS", "proposed", "50000", date(2026, 9, 8)),
        _c("1", "VBL.NS", "abandoned", "50000", date(2026, 9, 9), reason="user declined"),
    ]
    assert allowance(AUTHORISED, trail, period=SEPT).remaining == AUTHORISED


def test_a_confirmed_fill_moves_reserved_into_spent_without_double_counting() -> None:
    """The same rupees must not be counted twice as they move through the states."""
    trail = [
        _c("1", "VBL.NS", "proposed", "30000", date(2026, 9, 8)),
        _c("1", "VBL.NS", "filled", "30000", date(2026, 9, 8), filled_on=date(2026, 9, 9)),
    ]
    left = allowance(AUTHORISED, trail, period=SEPT)
    assert (left.spent, left.reserved) == (Decimal("30000"), Decimal("0"))
    assert left.remaining == Decimal("20000")


def test_last_months_purchases_do_not_eat_this_month() -> None:
    """The allowance is monthly. August's basket must not reduce September's instalment."""
    august = [_c("1", "VBL.NS", "filled", "50000", date(2026, 8, 5), filled_on=date(2026, 8, 5))]
    assert allowance(AUTHORISED, august, period=SEPT).remaining == AUTHORISED


def test_the_allowance_never_goes_negative() -> None:
    over = [_c("1", "VBL.NS", "filled", "80000", date(2026, 9, 3), filled_on=date(2026, 9, 3))]
    assert allowance(AUTHORISED, over, period=SEPT).remaining == Decimal("0")


# --- waiting, which is the state a memoryless system loses every night --------------------------
def test_a_wait_records_what_would_justify_buying() -> None:
    """ "Nothing happened today" is only checkable if the system said what it was waiting for."""
    trail = [
        _c(
            "1",
            "INFY.NS",
            "waiting",
            "0",
            date(2026, 9, 8),
            trigger="below ₹1,000 and filings read",
        )
    ]
    held = waiting(trail)
    assert len(held) == 1 and "below ₹1,000" in held[0].trigger
    assert allowance(AUTHORISED, trail, period=SEPT).remaining == AUTHORISED, (
        "waiting reserves nothing — only a proposal does"
    )


def test_an_open_decision_blocks_a_second_one_on_the_same_name() -> None:
    """Running the analysis again is not a reason to buy the same thing twice."""
    trail = [_c("1", "VBL.NS", "proposed", "20000", date(2026, 9, 8))]
    assert already_committed(trail, "VBL.NS") is not None
    assert already_committed(trail, "TCS.NS") is None


def test_a_filled_or_abandoned_name_is_open_to_a_new_decision() -> None:
    trail = [
        _c("1", "VBL.NS", "proposed", "20000", date(2026, 9, 1)),
        _c("1", "VBL.NS", "filled", "20000", date(2026, 9, 1), filled_on=date(2026, 9, 2)),
    ]
    assert already_committed(trail, "VBL.NS") is None, "a closed decision is not an open one"


# --- a proposal nobody answered -----------------------------------------------------------------
def test_an_unanswered_proposal_is_named_never_promoted_and_never_dropped() -> None:
    """Promoting it would claim a purchase that may not exist; dropping it would release money that
    may already be spent. Both misstate the account, so it is reported and left alone."""
    trail = [_c("1", "VBL.NS", "proposed", "50000", date(2026, 9, 1))]
    stale = stale_proposals(trail, date(2026, 9, 9))
    assert [c.ticker for c in stale] == ["VBL.NS"]
    assert open_proposals(trail), "still open — not silently resolved either way"
    assert allowance(AUTHORISED, trail, period=SEPT).exhausted, "and still holding the allowance"


def test_a_fresh_proposal_is_not_stale() -> None:
    trail = [_c("1", "VBL.NS", "proposed", "50000", date(2026, 9, 8))]
    assert stale_proposals(trail, date(2026, 9, 9)) == []


# --- what the run says on a day it bought nothing -----------------------------------------------
def test_a_quiet_day_reports_waiting_and_reserved_rather_than_silence() -> None:
    """The difference between a system that is waiting on purpose and one that did nothing."""
    trail = [
        _c("1", "VBL.NS", "proposed", "20000", date(2026, 9, 8), reason="screen rank 1"),
        _c("2", "INFY.NS", "waiting", "0", date(2026, 9, 8), trigger="needs filings read"),
    ]
    text = summary(trail, allowance(AUTHORISED, trail, period=SEPT), date(2026, 9, 9))
    assert "VBL" in text and "not yet confirmed" in text
    assert "INFY" in text and "needs filings read" in text
    assert "₹30,000 of this month's ₹50,000 is uncommitted" in text


def test_an_exhausted_allowance_explains_itself() -> None:
    """An allowance that silently reaches zero looks like a broken run."""
    trail = [_c("1", "VBL.NS", "filled", "50000", date(2026, 9, 3), filled_on=date(2026, 9, 3))]
    text = allowance(AUTHORISED, trail, period=SEPT).explain()
    assert "fully committed" in text and "₹50,000 already bought" in text
    assert "until next month" in text


# --- the trail --------------------------------------------------------------------------------
def test_the_trail_is_append_only_so_a_purchase_can_be_audited(tmp_path: Path) -> None:
    """ "It bought VBL" is not auditable. "It waited nine days citing this trigger, proposed the day
    it fired, and the fill confirmed two days later" is."""
    p = tmp_path / "commitments.jsonl"
    record(_c("1", "VBL.NS", "waiting", "0", date(2026, 9, 1), trigger="below ₹400"), p)
    record(_c("1", "VBL.NS", "proposed", "20000", date(2026, 9, 8)), p)
    record(_c("1", "VBL.NS", "filled", "20000", date(2026, 9, 8), filled_on=date(2026, 9, 9)), p)

    trail = load(p)
    assert [c.state for c in trail] == ["waiting", "proposed", "filled"]
    assert allowance(AUTHORISED, trail, period=SEPT).spent == Decimal("20000")


def test_a_torn_line_costs_one_row_not_the_next_record(tmp_path: Path) -> None:
    """The same defect as the task ledger, which shipped because its test wrote a partial line WITH
    a newline — which is not a torn write at all."""
    p = tmp_path / "commitments.jsonl"
    record(_c("1", "VBL.NS", "filled", "10000", date(2026, 9, 2), filled_on=date(2026, 9, 2)), p)
    with p.open("a", encoding="utf-8") as fh:
        fh.write('{"id": "2", "ticker": "TC')  # killed mid-write, NO trailing newline
    record(_c("3", "INFY.NS", "filled", "5000", date(2026, 9, 3), filled_on=date(2026, 9, 3)), p)

    ids = [c.id for c in load(p)]
    assert ids == ["1", "3"], f"the record after the tear was lost: {ids}"
    assert allowance(AUTHORISED, load(p), period=SEPT).spent == Decimal("15000")


def test_an_unreadable_row_does_not_take_the_ledger_down(tmp_path: Path) -> None:
    p = tmp_path / "commitments.jsonl"
    p.write_text(
        json.dumps({"id": "1", "ticker": "X", "state": "filled", "amount": "1", "on": "nonsense"})
        + "\n",
        encoding="utf-8",
    )
    assert load(p) == []
