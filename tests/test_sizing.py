"""A portfolio that expands without ever being forced to sell.

The scenarios registered for EXPAND-1, each a property the rules must hold:
skip a month → ₹1,00,000 available; a queued order reduces the allowance; a holding that drifts from
20% to 28% on price is never sold and pauses further buying; at a ₹3 lakh book a starter opens at
₹15,000 or not at all; a small existing position is never sold; expiring allowance never destroys
cash; the name ceiling stops new names only.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from qalpha.accounting.portfolio import Portfolio
from qalpha.config import Config
from qalpha.live import sizing
from qalpha.live.mandate import CURRENT_SIZING, EXPAND_SIZING

ON = date(2026, 10, 5)
SECTORS = {"AAA.NS": "IT", "BBB.NS": "BANK", "CCC.NS": "FMCG", "DDD.NS": "IT", "EEE.NS": "POWER"}


def _book(cash: str, holdings: dict[str, tuple[int, str]] | None = None) -> Portfolio:
    cfg = Config()
    pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal(cash))
    for ticker, (qty, price) in (holdings or {}).items():
        pf.cash += Decimal(qty) * Decimal(price) * Decimal("1.01")
        pf.buy(date(2026, 1, 5), ticker, Decimal(qty), Decimal(price))
    return pf


def _intent(
    ticker: str,
    intent: str,
    *,
    conviction: str = "standard",
    share: str | None = "0.05",
    reason: str = "r",
) -> sizing.Intention:
    return sizing.Intention(
        ticker=ticker,
        intent=intent,
        conviction=conviction,
        desired_exposure=None if share is None else Decimal(share),
        thesis="t",
        reason=reason,
        invalidate_if="i",
        evidence_ids=("price:" + ticker,),
    )


# ---- the allowance ----------------------------------------------------------------------------


def test_a_skipped_month_rolls_over_to_the_ceiling_and_no_further() -> None:
    purchases: dict[str, Decimal] = {"2026-09": Decimal("0")}
    assert sizing.allowance(
        "2026-10", purchases, first_month="2026-09", rules=EXPAND_SIZING
    ) == Decimal("100000")
    assert sizing.allowance("2026-12", {}, first_month="2026-09", rules=EXPAND_SIZING) == Decimal(
        "100000"
    )
    # the worked example: spend ₹20,000 in September → October has ₹80,000
    assert sizing.allowance(
        "2026-10", {"2026-09": Decimal("20000")}, first_month="2026-09", rules=EXPAND_SIZING
    ) == Decimal("80000")
    # the live limits never roll over
    assert sizing.allowance("2026-10", {}, first_month="2026-09", rules=CURRENT_SIZING) == Decimal(
        "50000"
    )


def test_a_queued_order_reduces_what_may_still_be_committed() -> None:
    book = _book("500000")
    queued = [{"ticker": "AAA.NS", "action": "BUY", "quantity": 100, "price": "250"}]
    pending = sizing.commitment(queued, {}, book)
    assert Decimal("25000") < pending < Decimal("25200")  # value plus estimated costs
    left = sizing.available(
        "2026-10",
        {"2026-10": Decimal("10000")},
        pending_commitments=pending,
        first_month="2026-10",
        rules=EXPAND_SIZING,
    )
    assert left == Decimal("50000") - Decimal("10000") - pending


def test_expiring_allowance_never_touches_cash() -> None:
    book = _book("300000")
    before = book.cash
    sizing.allowance("2027-06", {}, first_month="2026-09", rules=EXPAND_SIZING)
    sizing.plan(
        book, [], prices={}, sectors=SECTORS, on=ON, rules=EXPAND_SIZING, budget=Decimal("0")
    )
    assert book.cash == before


# ---- nothing is ever forced out ----------------------------------------------------------------


def test_a_holding_that_drifts_to_28_percent_is_not_sold_and_further_buying_pauses() -> None:
    book = _book("0", {"AAA.NS": (100, "200"), "BBB.NS": (100, "200")})
    book.cash = Decimal("0")
    # AAA has risen: 100 × 560 = 56,000 of a 2,00,000 book = 28%
    prices = {"AAA.NS": Decimal("560"), "BBB.NS": Decimal("200")}
    book.cash = Decimal("124000")
    outcomes = sizing.plan(
        book,
        [
            _intent("AAA.NS", sizing.ADD, conviction="core", share="0.10"),
            _intent("BBB.NS", sizing.HOLD, share=None),
        ],
        prices=prices,
        sectors=SECTORS,
        on=ON,
        rules=EXPAND_SIZING,
        budget=Decimal("100000"),
    )
    by = {o.ticker: o for o in outcomes}
    assert (
        by["AAA.NS"].order is None
        and "paused" in by["AAA.NS"].status
        and "not a sale" in by["AAA.NS"].status
    )
    assert all(o.order is None or o.order.action != sizing.SELL for o in outcomes)


def test_a_small_existing_position_is_never_sold_and_the_name_ceiling_stops_new_names_only() -> (
    None
):
    rules = EXPAND_SIZING
    small = {"AAA.NS": (10, "500")}  # ₹5,000: below the ₹15,000 new-position minimum
    book = _book("2000000", small)
    prices = {t: Decimal("500") for t in SECTORS}
    from dataclasses import replace

    tight = replace(rules, max_names=1)
    outcomes = sizing.plan(
        book,
        [_intent("AAA.NS", sizing.HOLD, share=None), _intent("BBB.NS", sizing.OPEN)],
        prices=prices,
        sectors=SECTORS,
        on=ON,
        rules=tight,
        budget=Decimal("100000"),
    )
    by = {o.ticker: o for o in outcomes}
    assert by["AAA.NS"].order is None and by["AAA.NS"].status == "held"
    assert by["BBB.NS"].order is None and "new names only" in by["BBB.NS"].status
    # adding to an existing name is still allowed above the ceiling
    added = sizing.plan(
        book,
        [_intent("AAA.NS", sizing.ADD, share="0.05")],
        prices=prices,
        sectors=SECTORS,
        on=ON,
        rules=tight,
        budget=Decimal("100000"),
    )
    assert added[0].order is not None and added[0].order.action == sizing.BUY


def test_no_intention_without_a_reason_can_sell() -> None:
    book = _book("0", {"AAA.NS": (100, "200")})
    with pytest.raises(sizing.IntentionError, match="reason"):
        sizing.plan(
            book,
            [_intent("AAA.NS", sizing.EXIT, share=None, reason=" ")],
            prices={"AAA.NS": Decimal("200")},
            sectors=SECTORS,
            on=ON,
            rules=EXPAND_SIZING,
            budget=Decimal("0"),
        )


# ---- depth and breadth -------------------------------------------------------------------------


@pytest.mark.parametrize(("cash", "opens"), [("300000", True), ("14000", False)])
def test_at_a_3_lakh_book_a_starter_opens_at_15000_or_not_at_all(cash: str, opens: bool) -> None:
    book = _book(cash)
    outcomes = sizing.plan(
        book,
        [_intent("CCC.NS", sizing.OPEN, conviction="starter", share="0.02")],
        prices={"CCC.NS": Decimal("1000")},
        sectors=SECTORS,
        on=ON,
        rules=EXPAND_SIZING,
        budget=Decimal("50000"),
    )
    order = outcomes[0].order
    if opens:
        assert order is not None and order.quantity * 1000 >= 15000
        assert order.quantity * 1000 < 16000  # the minimum, not the ₹6,000 tier target and not more
    else:
        assert order is None and "minimum does not fit" in outcomes[0].status


def test_desired_exposure_is_held_to_its_conviction_tier() -> None:
    book = _book("1000000")
    outcomes = sizing.plan(
        book,
        [_intent("AAA.NS", sizing.OPEN, conviction="core", share="0.30")],
        prices={"AAA.NS": Decimal("100")},
        sectors=SECTORS,
        on=ON,
        rules=EXPAND_SIZING,
        budget=Decimal("200000"),
    )
    order = outcomes[0].order
    assert order is not None and "lowered to the core tier's 12%" in order.status
    assert order.quantity * 100 <= 120000


def test_the_allowance_and_the_limits_cut_a_buy_and_say_which() -> None:
    book = _book("1000000")
    outcomes = sizing.plan(
        book,
        [_intent("AAA.NS", sizing.OPEN, conviction="core", share="0.10")],
        prices={"AAA.NS": Decimal("100")},
        sectors=SECTORS,
        on=ON,
        rules=EXPAND_SIZING,
        budget=Decimal("30000"),
    )
    order = outcomes[0].order
    assert (
        order is not None
        and order.estimated_outlay <= Decimal("30000")
        and "cut from" in order.status
    )


def test_the_same_intentions_order_differently_under_the_two_rule_sets() -> None:
    """The shadow comparison's premise: one set of intentions, two books, two sets of orders."""
    intentions = [_intent(t, sizing.OPEN, conviction="standard", share="0.05") for t in SECTORS]
    prices = {t: Decimal("100") for t in SECTORS}
    live = sizing.plan(
        _book("1000000"),
        intentions,
        prices=prices,
        sectors=SECTORS,
        on=ON,
        rules=CURRENT_SIZING,
        budget=Decimal("50000"),
    )
    shadow = sizing.plan(
        _book("1000000"),
        intentions,
        prices=prices,
        sectors=SECTORS,
        on=ON,
        rules=EXPAND_SIZING,
        budget=Decimal("100000"),
    )
    bought_live = sum(o.order.estimated_outlay for o in live if o.order)
    bought_shadow = sum(o.order.estimated_outlay for o in shadow if o.order)
    assert bought_shadow > bought_live
    assert bought_live <= Decimal("50000")


def test_metrics_measure_breadth_and_concentration() -> None:
    book = _book("50000", {"AAA.NS": (100, "500"), "BBB.NS": (100, "500")})
    book.cash = Decimal("100000")
    m = sizing.metrics(book, {"AAA.NS": Decimal("500"), "BBB.NS": Decimal("500")}, SECTORS)
    assert m["names"] == 2 and m["effective_names"] == 2.0
    assert m["deployed_pct"] == 50.0 and m["largest_name_pct"] == 25.0
