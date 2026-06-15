"""Zerodha tradebook → dated FIFO Portfolio (Q_alpha.md §14 crit 4).

A fixture CSV in the Console export shape drives parse + replay; the key checks are that dated lots
make the holding period (LTCG vs STCG) exact and that an unmatched sell warns instead of crashing.
"""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal

from qalpha.accounting.costs import Side
from qalpha.config import Config
from qalpha.live.advisor import advise_sell
from qalpha.live.tradebook import (
    parse_tradebook,
    reconcile_positions,
    replay_tradebook,
)

# Console tradebook columns; INFY held long-term (small gain → exempt), TCS a short-term taxed gain.
_CSV = """symbol,isin,trade_date,exchange,segment,series,trade_type,auction,quantity,price,trade_id,order_id,order_execution_time
INFY,INE009A01021,2023-01-02,NSE,EQ,EQ,buy,FALSE,10,1500,1,1,2023-01-02 09:30:00
HDFCBANK,INE040A01034,2023-01-02,NSE,EQ,EQ,buy,FALSE,5,1600,2,2,2023-01-02 09:31:00
TCS,INE467B01029,2024-03-01,NSE,EQ,EQ,buy,FALSE,100,3000,3,3,2024-03-01 10:00:00
TCS,INE467B01029,2024-06-01,NSE,EQ,EQ,sell,FALSE,100,3500,4,4,2024-06-01 10:00:00
INFY,INE009A01021,2024-06-03,NSE,EQ,EQ,sell,FALSE,10,1800,5,5,2024-06-03 11:00:00
"""


def _trades():  # type: ignore[no-untyped-def]
    return parse_tradebook(io.StringIO(_CSV))


def test_parse_normalizes_tickers_and_sides() -> None:
    trades = _trades()
    assert len(trades) == 5
    first = trades[0]
    assert first.ticker == "INFY.NS"
    assert first.side is Side.BUY
    assert first.trade_date == date(2023, 1, 2)
    assert first.quantity == Decimal("10")
    assert first.price == Decimal("1500.00")
    assert {t.side for t in trades} == {Side.BUY, Side.SELL}


def test_replay_builds_dated_lots_and_realizes_tax() -> None:
    result = replay_tradebook(_trades(), Config(), cash=Decimal("1000"))
    assert result.n_trades == 5
    # INFY + TCS fully sold; only HDFCBANK remains open.
    assert result.portfolio.positions() == {"HDFCBANK.NS": Decimal("5")}
    assert result.portfolio.cash == Decimal("1000")
    # TCS was a ~₹50k short-term gain → taxed at 20%; INFY long-term gain sits inside the exemption.
    assert Decimal("8000") < result.realized_tax < Decimal("11000")
    assert not result.warnings


def test_dated_lot_makes_advice_long_term() -> None:
    pf = replay_tradebook(_trades(), Config(), cash=Decimal("0")).portfolio
    # HDFCBANK bought 2023-01-02; selling on 2024-06-03 is long-term (>365d) — exact only because the
    # lot is dated. A holdings-snapshot (undated) portfolio would wrongly treat it as short-term.
    advice = advise_sell(pf, "HDFCBANK.NS", Decimal("1700"), date(2024, 6, 3), Config())
    assert advice.ltcg_gain > 0
    assert advice.stcg_gain == 0


def test_reconcile_positions_flags_mismatch() -> None:
    pf = replay_tradebook(_trades(), Config()).portfolio
    assert reconcile_positions(pf, {"HDFCBANK.NS": Decimal("5")}) == []
    issues = reconcile_positions(pf, {"HDFCBANK.NS": Decimal("6")})
    assert len(issues) == 1 and "HDFCBANK.NS" in issues[0]


def test_unmatched_sell_warns_not_crashes() -> None:
    csv = (
        "symbol,trade_date,trade_type,quantity,price\n"
        "ZZZ,2024-01-01,sell,5,100\n"  # sold without a prior buy in the export
    )
    result = replay_tradebook(parse_tradebook(io.StringIO(csv)), Config())
    assert result.n_trades == 0
    assert result.portfolio.positions() == {}
    assert len(result.warnings) == 1
    assert "ZZZ.NS" in result.warnings[0]
