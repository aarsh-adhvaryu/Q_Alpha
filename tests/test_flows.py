"""Dated flows, XIRR, and the same money in a benchmark instead.

The properties that matter: lumpy deposits are money-weighted, a one-way set of flows has no rate
rather than an invented one, and the benchmark leg never uses a price from after the trade.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from qalpha.accounting.costs import Side
from qalpha.live.flows import (
    Flow,
    benchmark_leg,
    flows_from_trades,
    xirr,
)
from qalpha.live.tradebook import TradebookTrade

_START = date(2024, 1, 1)


def _trade(day: date, ticker: str, side: Side, qty: str, price: str) -> TradebookTrade:
    return TradebookTrade(
        trade_date=day,
        ticker=ticker,
        side=side,
        quantity=Decimal(qty),
        price=Decimal(price),
    )


def _flat_index(days: int = 900, level: float = 100.0, growth: float = 0.0) -> pd.Series:
    idx = pd.bdate_range(_START - timedelta(days=5), periods=days)
    values = [level * (1.0 + growth) ** (i / 252.0) for i in range(days)]
    return pd.Series(values, index=idx)


# ---- the rate itself ----------------------------------------------------------------------------


def test_a_single_year_at_ten_percent_solves_to_ten_percent() -> None:
    rate = xirr([(_START, Decimal("-100")), (_START + timedelta(days=365), Decimal("110"))])
    assert rate is not None
    assert rate == pytest.approx(0.10, abs=1e-4)


def test_a_loss_solves_to_a_negative_rate() -> None:
    rate = xirr([(_START, Decimal("-100")), (_START + timedelta(days=365), Decimal("80"))])
    assert rate is not None
    assert rate == pytest.approx(-0.20, abs=1e-4)


def test_lumpy_deposits_are_money_weighted_not_averaged() -> None:
    """Money present for half the window cannot earn a full year's worth — that is the whole point.

    ₹100 at the start and ₹100 at the six-month mark ending at ₹210 is a +5% simple return, but the
    second ₹100 was only working for half the time, so the *rate* is meaningfully higher than 5%.
    """
    flows = [
        (_START, Decimal("-100")),
        (_START + timedelta(days=182), Decimal("-100")),
        (_START + timedelta(days=365), Decimal("210")),
    ]
    rate = xirr(flows)
    assert rate is not None
    assert rate > 0.05


def test_flows_all_one_way_have_no_rate_rather_than_a_fabricated_one() -> None:
    assert xirr([(_START, Decimal("-100")), (_START + timedelta(days=30), Decimal("-100"))]) is None


# ---- turning trades into flows ------------------------------------------------------------------


def test_buys_are_money_in_and_sells_are_money_out() -> None:
    trades = [
        _trade(_START, "A.NS", Side.BUY, "10", "100"),
        _trade(_START + timedelta(days=30), "A.NS", Side.SELL, "4", "150"),
    ]
    flows = flows_from_trades(trades)
    assert [f.amount for f in flows] == [Decimal("1000"), Decimal("-600")]


def test_same_day_trades_collapse_to_their_net_effect() -> None:
    """Selling A to buy B on one day moved no new money in — it must not read as ₹2 lakh of flow."""
    day = _START
    trades = [
        _trade(day, "A.NS", Side.SELL, "10", "100"),
        _trade(day, "B.NS", Side.BUY, "5", "202"),
    ]
    flows = flows_from_trades(trades)
    assert len(flows) == 1
    assert flows[0].amount == Decimal("10")


def test_trades_come_back_oldest_first_whatever_order_they_arrived_in() -> None:
    later = _trade(_START + timedelta(days=60), "A.NS", Side.BUY, "1", "100")
    earlier = _trade(_START, "A.NS", Side.BUY, "1", "100")
    assert [f.on for f in flows_from_trades([later, earlier])] == [
        earlier.trade_date,
        later.trade_date,
    ]


# ---- the index counterfactual -------------------------------------------------------------------


def test_the_index_leg_buys_the_same_rupees_on_the_same_days() -> None:
    series = _flat_index()
    flows = [Flow(on=_START, amount=Decimal("10000"))]
    leg = benchmark_leg(flows, series, _START + timedelta(days=200))
    assert leg is not None
    assert leg.units == pytest.approx(Decimal("100"))  # ₹10,000 at ₹100
    assert leg.value == pytest.approx(Decimal("10000"))  # flat index → unchanged


def test_the_index_price_is_never_taken_from_after_the_trade() -> None:
    """A trade on a holiday must mark at the *previous* session, never the next one."""
    idx = pd.DatetimeIndex([pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-10")])
    series = pd.Series([100.0, 1000.0], index=idx)
    leg = benchmark_leg(
        [Flow(on=date(2024, 1, 5), amount=Decimal("1000"))], series, date(2024, 1, 10)
    )
    assert leg is not None
    assert leg.units == Decimal("10")  # priced at 100, the prior session — not at the 1000 ahead


def test_no_index_history_before_the_first_trade_yields_no_comparison() -> None:
    series = pd.Series([100.0], index=pd.DatetimeIndex([pd.Timestamp("2025-01-01")]))
    assert (
        benchmark_leg([Flow(on=_START, amount=Decimal("1000"))], series, date(2025, 6, 1)) is None
    )


def test_selling_more_than_the_index_sleeve_holds_is_flagged_not_shorted() -> None:
    series = _flat_index()
    flows = [
        Flow(on=_START, amount=Decimal("1000")),
        Flow(on=_START + timedelta(days=100), amount=Decimal("-5000")),
    ]
    leg = benchmark_leg(flows, series, _START + timedelta(days=200))
    assert leg is not None
    assert leg.units == Decimal("0")  # floored, never negative
    assert leg.exhausted
