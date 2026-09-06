"""The decision loop: skip, replace, park the remainder, and never ask about a company.

The version this replaced had five exit paths and four of them were ``HUMAN_REQUIRED``. Run against
the live basket it asked the user to adjudicate nineteen companies and deployed nothing. These tests
pin the three properties that fixed it, and the fourth that makes the experiment answerable.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from qalpha.live.evidence import BLOCK, PASS, UNKNOWN, WATCH, Assessment, Indicator, Provenance
from qalpha.live.pipeline import (
    ANCHOR_TICKER,
    EXECUTE,
    FREEZE_ADDITIONS,
    HOLD_STEADY,
    NO_ACTION,
    PROPOSE_EXIT,
    ProposedOrder,
    decision_rows,
    propose,
    review_holding,
)
from qalpha.live.pretrade import AnnouncementCoverage, assess_candidate

AS_OF = date(2026, 8, 27)
FULL = AnnouncementCoverage(index_fetched=True, extraction_ran=True)
PRICES = {
    "A.NS": Decimal("100"),
    "B.NS": Decimal("200"),
    "C.NS": Decimal("50"),
    "D.NS": Decimal("400"),
    ANCHOR_TICKER: Decimal("276"),
}
SECTORS = {"A.NS": "IT", "B.NS": "FMCG", "C.NS": "AUTO", "D.NS": "ENERGY"}


def _prov() -> Provenance:
    return Provenance("u", datetime(2026, 9, 5, tzinfo=UTC), 200, "a" * 64, 1, AS_OF)


def _ex(state: str) -> Assessment:
    return Assessment(
        "X", state, (Indicator("c", "0"),) if state != PASS else (), _prov(), f"{state} detail"
    )


def _run(states: dict[str, str], *, target: int = 2, **kw: object):
    tickers = list(states)
    defaults: dict[str, object] = {
        "as_of": AS_OF,
        "candidates": [ProposedOrder(t, 10, PRICES[t], rank=i) for i, t in enumerate(tickers)],
        "target_names": target,
        "holdings": {},
        "prices": PRICES,
        "sector_of": SECTORS,
        "exchange": {t: _ex(s) for t, s in states.items()},
        "coverage": dict.fromkeys(tickers, FULL),
    }
    defaults.update(kw)
    return propose(**defaults)  # type: ignore[arg-type]


# --- 1. replacement ------------------------------------------------------------------------------


def test_a_skipped_candidate_is_replaced_by_the_next_in_rank() -> None:
    p = _run({"A.NS": WATCH, "B.NS": PASS, "C.NS": PASS}, target=2)
    assert p.outcome == EXECUTE
    assert [o.ticker for o in p.orders] == ["B.NS", "C.NS"]
    assert [c.ticker for c in p.skipped] == ["A.NS"]


def test_the_basket_fills_to_target_even_with_several_rejections() -> None:
    p = _run({"A.NS": BLOCK, "B.NS": UNKNOWN, "C.NS": PASS, "D.NS": PASS}, target=2)
    assert [o.ticker for o in p.orders] == ["C.NS", "D.NS"]
    assert len(p.skipped) == 2


def test_rank_order_is_preserved_so_the_screen_still_decides_preference() -> None:
    p = _run({"A.NS": PASS, "B.NS": PASS, "C.NS": PASS}, target=2)
    assert [o.ticker for o in p.orders] == ["A.NS", "B.NS"]
    assert [o.rank for o in p.orders] == [0, 1]


def test_every_replacement_is_assessed_too() -> None:
    """A substitute must clear the same checks; replacing a bad name with an unchecked one is worse."""
    p = _run({"A.NS": WATCH, "B.NS": BLOCK, "C.NS": PASS}, target=1)
    assert [o.ticker for o in p.orders] == ["C.NS"]
    assert {c.ticker for c in p.considered} == {"A.NS", "B.NS", "C.NS"}


def test_exhausting_the_ranking_is_not_an_error() -> None:
    p = _run({"A.NS": WATCH, "B.NS": BLOCK}, target=2, budget=Decimal("0"))
    assert p.outcome == NO_ACTION and p.orders == ()


# --- 2. the anchor -------------------------------------------------------------------------------


def test_leftover_cash_goes_to_the_anchor_rather_than_sitting_idle() -> None:
    p = _run(
        {"A.NS": PASS},
        target=1,
        budget=Decimal("10000"),
        anchor_price=PRICES[ANCHOR_TICKER],
    )
    anchor = [o for o in p.orders if o.is_anchor]
    assert len(anchor) == 1 and anchor[0].ticker == ANCHOR_TICKER
    # 10,000 budget − 10×100 spent = 9,000 → 32 units at 276
    assert anchor[0].quantity == 32
    assert p.anchor_value == Decimal("32") * Decimal("276")


def test_a_day_where_nothing_clears_still_invests_via_the_anchor() -> None:
    """The whole point: uncertainty about companies must not become uninvested cash."""
    p = _run(
        {"A.NS": WATCH, "B.NS": UNKNOWN},
        target=2,
        budget=Decimal("50000"),
        anchor_price=PRICES[ANCHOR_TICKER],
    )
    assert p.outcome == EXECUTE
    assert all(o.is_anchor for o in p.orders)
    assert p.anchor_value > Decimal("49000")


def test_the_anchor_is_excluded_from_the_sector_measurement() -> None:
    """A broad fund is not a sector bet and must not be charged as one."""
    p = _run({"A.NS": PASS}, target=1, budget=Decimal("50000"), anchor_price=PRICES[ANCHOR_TICKER])
    assert p.concentration is not None
    assert "UNKNOWN" not in [e.sector for e in p.concentration.exposures]


def test_no_anchor_price_means_no_anchor_and_no_invention() -> None:
    p = _run({"A.NS": PASS}, target=1, budget=Decimal("50000"), anchor_price=None)
    assert p.anchor_value == Decimal("0")
    assert not any(o.is_anchor for o in p.orders)


# --- 3. what happens to something already held ------------------------------------------------------


def _held(state: str):
    return review_holding("H.NS", assess_candidate("H.NS", exchange=_ex(state), coverage=FULL))


def test_a_hard_block_on_a_holding_proposes_an_exit() -> None:
    assert _held(BLOCK).action == PROPOSE_EXIT


@pytest.mark.parametrize("state", [WATCH, UNKNOWN])
def test_a_warning_or_a_gap_freezes_additions_but_never_sells(state: str) -> None:
    """Selling realises tax, and this screen buys names that are already down."""
    review = _held(state)
    assert review.action == FREEZE_ADDITIONS
    assert "not sold" in review.reason


def test_a_clean_holding_is_left_alone() -> None:
    assert _held(PASS).action == HOLD_STEADY


def test_a_holding_with_no_assessment_freezes_rather_than_passing() -> None:
    assert review_holding("H.NS", None).action == FREEZE_ADDITIONS


def test_holdings_are_reviewed_even_when_the_day_needs_a_human() -> None:
    p = _run({"A.NS": PASS}, target=1, account_ok=False, account_detail="broker mismatch")
    assert p.outcome != EXECUTE and p.reason == "broker mismatch"


# --- 4. the cohort record ---------------------------------------------------------------------------


def test_every_candidate_considered_is_recorded_with_its_price() -> None:
    """One portfolio a year is one observation. 15 names x 12 months is 180."""
    p = _run({"A.NS": WATCH, "B.NS": PASS, "C.NS": PASS}, target=2)
    rows = decision_rows(p)
    assert len(rows) == 3
    assert {r["ticker"] for r in rows} == {"A.NS", "B.NS", "C.NS"}
    assert all(r["price_at_decision"] for r in rows)
    assert [r["taken"] for r in rows] == [False, True, True]


def test_the_skipped_names_keep_a_price_so_they_become_the_control_group() -> None:
    """Without a price at decision, a rejection is an opinion with no outcome attached."""
    p = _run({"A.NS": BLOCK, "B.NS": PASS}, target=1)
    skipped = next(r for r in decision_rows(p) if r["ticker"] == "A.NS")
    assert skipped["price_at_decision"] == str(PRICES["A.NS"])
    assert skipped["state"] == BLOCK and skipped["taken"] is False


def test_rows_are_keyed_so_a_rerun_corrects_rather_than_duplicates() -> None:
    p = _run({"A.NS": PASS}, target=1)
    assert decision_rows(p)[0]["_key"] == f"{AS_OF.isoformat()}:A.NS"


# --- 5. the cap applies only where it can discriminate ----------------------------------------------


def test_the_cap_does_not_fire_on_a_book_too_small_to_satisfy_it() -> None:
    """A 30% cap needs four sectors. On an empty book the first buy is 100% of its sector.

    Enforcing it there rejects every name and deploys nothing — which is exactly what the first
    version of this loop did, and why it asked nineteen questions and bought nothing.
    """
    p = _run({"A.NS": PASS, "B.NS": PASS}, target=2, holdings={})
    assert p.outcome == EXECUTE and len(p.orders) == 2


def test_the_cap_does_fire_once_the_book_spans_enough_sectors() -> None:
    from qalpha.live.pipeline import MIN_SECTORS_FOR_CAP

    held = {"A.NS": 10, "B.NS": 10, "C.NS": 10, "D.NS": 10}  # IT, FMCG, AUTO, ENERGY
    heavy = [
        ProposedOrder("A.NS", 500, PRICES["A.NS"], rank=0),
        ProposedOrder("C.NS", 1, PRICES["C.NS"], rank=1),
    ]
    p = propose(
        as_of=AS_OF,
        candidates=heavy,
        target_names=2,
        holdings=held,
        prices=PRICES,
        sector_of=SECTORS,
        exchange={t: _ex(PASS) for t in ("A.NS", "C.NS")},
        coverage=dict.fromkeys(["A.NS", "C.NS"], FULL),
    )
    assert MIN_SECTORS_FOR_CAP == 4
    assert [c.ticker for c in p.skipped] == ["A.NS"], "the concentrating name is skipped"
    assert [o.ticker for o in p.orders] == ["C.NS"], "and the next one still gets bought"
