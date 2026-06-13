"""Portfolio (live/paper book) persistence: to_state/from_state must round-trip exactly.

Covers the parts that would silently corrupt a live book: partially-consumed FIFO lots, cash, and
the per-FY LTCG exemption tally (which determines tax on the *next* sell, not just past ones).
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pandas as pd

from qalpha.backtest.portfolio import Portfolio, to_decimal_price
from qalpha.config import Config


def _prices(d: dict[str, str]) -> dict[str, Decimal]:
    return {k: to_decimal_price(float(v)) for k, v in d.items()}


def _funded_book() -> Portfolio:
    """A book with two names, one partially sold, so a lot is partially consumed + tax realized."""
    cfg = Config()
    pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal("1000000"))
    buy = pd.Series({"AAA": 0.5, "BBB": 0.5})
    pf.rebalance(date(2020, 1, 1), buy, _prices({"AAA": "100", "BBB": "200"}))
    # Partial trim of AAA a year+ later → realizes LTCG and leaves a partially-consumed lot.
    trim = pd.Series({"AAA": 0.25, "BBB": 0.5})
    pf.rebalance(date(2021, 6, 1), trim, _prices({"AAA": "180", "BBB": "210"}))
    return pf


def test_to_from_state_round_trips() -> None:
    pf = _funded_book()
    cfg = Config()
    marks = _prices({"AAA": "180", "BBB": "210"})

    state = pf.to_state()
    # Must survive a real JSON round-trip (the live book is stored on disk).
    restored = Portfolio.from_state(json.loads(json.dumps(state)), cfg.cost, cfg.tax)

    assert restored.cash == pf.cash
    assert restored.positions() == pf.positions()
    assert restored.market_value(marks) == pf.market_value(marks)
    assert restored.gains.realized_ltcg_by_fy() == pf.gains.realized_ltcg_by_fy()


def test_restored_book_taxes_next_sell_identically() -> None:
    """The exemption tally must carry over: a sell after restore is taxed like one before."""
    cfg = Config()
    marks = _prices({"AAA": "260", "BBB": "260"})
    sell = pd.Series({"BBB": 1.0})  # dump AAA, concentrate BBB → realizes more LTCG

    a = _funded_book()
    a.rebalance(date(2022, 7, 1), sell, marks)

    b = Portfolio.from_state(json.loads(json.dumps(_funded_book().to_state())), cfg.cost, cfg.tax)
    b.rebalance(date(2022, 7, 1), sell, marks)

    assert a.cash == b.cash
    assert a.positions() == b.positions()
    assert a.gains.realized_ltcg_by_fy() == b.gains.realized_ltcg_by_fy()
