"""Forward track record (PR-71) — does the system actually beat the index with *your* money?

The backtest is history; this is the instrument. The tests that matter are not "does 16.4% come out"
— they are the honesty properties: the panel must be able to say **behind**, it must refuse to read a
verdict into three months, and the index leg must never use a price from after the trade.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from qalpha.accounting.costs import Side
from qalpha.live.track_record import (
    MIN_MONTHS_FOR_A_VERDICT,
    Flow,
    benchmark_leg,
    flows_from_trades,
    track_record,
    track_record_markdown,
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


# ---- the record and its panel -------------------------------------------------------------------


def _record(value: str, *, growth: float = 0.0, months: int = 24, sells: bool = False):
    trades = [_trade(_START, "A.NS", Side.BUY, "100", "1000")]
    if sells:
        trades.append(_trade(_START + timedelta(days=30), "A.NS", Side.SELL, "10", "1100"))
    as_of = _START + timedelta(days=int(months * 30.44))
    return track_record(trades, Decimal(value), _flat_index(growth=growth), as_of)


def test_no_trades_means_no_record_rather_than_a_zeroed_one() -> None:
    assert track_record([], Decimal("0"), _flat_index(), date(2025, 1, 1)) is None
    assert "No track record yet" in track_record_markdown(None)


def test_the_basis_is_money_in_net_of_what_came_out() -> None:
    record = _record("120000", sells=True)
    assert record is not None
    assert record.net_invested == Decimal("100000") - Decimal("11000")


def test_beating_the_index_reports_the_gap_in_rupees() -> None:
    record = _record("150000")  # index flat, so the whole ₹50,000 gain is the gap
    assert record is not None
    assert record.ahead_by == pytest.approx(Decimal("50000"))
    assert "ahead by ₹50,000" in track_record_markdown(record)


def test_losing_to_the_index_says_so_plainly() -> None:
    """The load-bearing test: a panel that can only report good news is marketing, not evidence."""
    record = _record("100000", growth=0.20)  # book flat, index up 20%/yr
    assert record is not None
    assert record.ahead_by is not None and record.ahead_by < 0
    panel = track_record_markdown(record)
    assert "behind by" in panel
    assert "ahead by" not in panel


def test_a_short_window_carries_the_noise_caveat() -> None:
    record = _record("150000", months=3)
    assert record is not None
    assert record.too_early
    assert "noise, not as a verdict" in track_record_markdown(record)


def test_a_long_window_drops_the_noise_caveat() -> None:
    record = _record("150000", months=MIN_MONTHS_FOR_A_VERDICT + 6)
    assert record is not None
    assert not record.too_early
    assert "noise, not as a verdict" not in track_record_markdown(record)


def test_both_columns_carry_a_basis_and_a_window() -> None:
    """PR-4's rule: a return that reaches a screen without both is unreadable — and this repo's
    trust problem began as eight such numbers on one page."""
    record = _record("150000")
    assert record is not None
    for measure in (record.measure(), record.benchmark_measure()):
        assert measure is not None
        assert "net money in" in measure.basis_text
        assert measure.window_text() == f"{record.start} → {record.as_of}"


def test_the_panel_discloses_that_charges_are_in_neither_column() -> None:
    record = _record("150000")
    assert record is not None
    assert "charges" in track_record_markdown(record)


def test_a_book_that_tracks_the_index_exactly_shows_no_edge() -> None:
    """The null case must come out null — if it does not, the instrument has a bias."""
    record = _record("120000", growth=0.0954, months=24)  # ~+20% over two years, as the index does
    assert record is not None
    assert record.ahead_by is not None
    assert abs(record.ahead_by) < Decimal("1500")  # within a rounding band of the index leg


def test_parked_cash_is_not_investment_performance() -> None:
    """Findings #1 of the final audit (2026-08-28): the call site passed cash + holdings as ``value``.

    The benchmark leg is built from the traded rupees alone, so counting idle cash on the other side
    compares a column that contains next month's SIP instalment against one that cannot. On the real
    account shape — a ₹1L opening basket with ₹4L parked — the panel rendered "+444.2%, ahead by
    ₹4,01,677" where the truth was +1.2% and ₹1,677, and every instalment that landed before it was
    deployed would have added its full value as phantom outperformance.

    The panel's asserted design property is that it must be able to say "behind by ₹X". Fed the
    account total it structurally cannot, which is what makes this the audit's most serious finding.
    """
    from dataclasses import dataclass
    from datetime import date
    from decimal import Decimal

    import pandas as pd

    from qalpha.accounting.costs import Side
    from qalpha.live.track_record import track_record

    @dataclass(frozen=True)
    class _T:
        trade_date: date
        ticker: str
        side: Side
        quantity: Decimal
        price: Decimal

    trades = [_T(date(2026, 1, 5), "A.NS", Side.BUY, Decimal("100"), Decimal("1000"))]
    index = pd.bdate_range("2026-01-01", periods=200)
    bench = pd.Series([100.0] * len(index), index=index)
    as_of = index[-1].date()

    shares_only = track_record(trades, Decimal("99000"), bench, as_of)  # the basket fell 1%
    with_parked_cash = track_record(trades, Decimal("99000") + Decimal("400000"), bench, as_of)

    # Marked on shares alone the panel reports the loss, which is the entire point of it existing.
    assert shares_only.ahead_by < 0
    # Fed the account total it reports a windfall instead — the defect, pinned so it cannot return.
    assert with_parked_cash.ahead_by > Decimal("390000")
