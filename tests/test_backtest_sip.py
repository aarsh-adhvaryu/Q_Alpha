"""The SIP simulation's accounting: contributions are not returns, and cash is not nothing.

There were no tests over this file at all, which is how a docstring promising that contributions were
stripped sat above code that stripped nothing — and how the figure it fed ("the hedge costs 21.5% of
terminal wealth") reached a commit message.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from backtest_sip import Result, _mark

_IDX = pd.bdate_range("2020-01-01", periods=60)


def _book_that_falls_20pct() -> Result:
    """₹50,000 a month into a book whose price falls 20% mid-window and fully recovers."""
    prices = pd.Series(1.0, index=_IDX)
    prices.iloc[20:40] = 0.80
    flows: list[tuple[object, Decimal]] = []
    units = 0.0
    values: list[float] = []
    for i, ts in enumerate(_IDX):
        if i % 20 == 0:
            flows.append((ts.date(), Decimal("50000")))
            units += 50000 / float(prices.iloc[i])
        values.append(units * float(prices.iloc[i]))
    return Result(
        label="t",
        equity_curve=pd.Series(values, index=_IDX),
        flows=flows,  # type: ignore[arg-type]
        contributed=Decimal("150000"),
    )


def test_a_deposit_is_not_a_return() -> None:
    """The defect in one line: money arriving must not move the NAV.

    ``backtest_phase4`` drove the hedge off ``equity_curve.pct_change()``, so a ₹50,000 deposit into
    an early ₹1,00,000 book was a **+50% one-day return**. Compounding those is where ×286.2
    "terminal wealth" came from — a number that measured the contributions, not the strategy.
    """
    nav = _book_that_falls_20pct().nav()
    # Days 0..19 are a single deposit followed by flat prices: the NAV must not budge.
    assert nav.iloc[0] == pytest_approx(nav.iloc[19])


def test_the_drawdown_is_the_one_the_holder_actually_felt() -> None:
    """A book that fell 20% must report −20%, not the 0% the rupee curve reports.

    This is the sharpest form of the bug: deposits landing *during* the fall keep the rupee curve
    making new highs, so ``cummax`` sees no drawdown at all. Not merely understated — erased.
    """
    book = _book_that_falls_20pct()
    curve = book.equity_curve
    naive = float(((curve - curve.cummax()) / curve.cummax()).min() * 100)
    assert naive > -1.0, "precondition: the raw rupee curve hides the fall entirely"
    assert book.max_drawdown_pct() == pytest_approx(-20.0, abs=0.01)


def test_a_book_holding_nothing_still_holds_its_money() -> None:
    """``_mark`` returned an empty frame with no holdings, dropping the month and its cash with it."""
    adj = pd.DataFrame({"A.NS": [100.0] * len(_IDX)}, index=_IDX)
    seg = _mark({}, adj, _IDX[-1], cash=7500.0)
    assert len(seg) == len(_IDX), "a month with no buys must still produce a curve segment"
    assert set(seg.unique()) == {7500.0}


def test_uninvested_cash_is_part_of_the_mark() -> None:
    """Whole-share rounding leaves a residue every month; marking only shares writes it off.

    It biases both legs, and *differently*, so the screen-minus-index gap carries a rounding artefact
    no reader of the report could see.
    """
    adj = pd.DataFrame({"A.NS": [100.0] * len(_IDX)}, index=_IDX)
    assert _mark({"A.NS": 3}, adj, _IDX[-1], cash=250.0).iloc[-1] == pytest_approx(550.0)
    assert _mark({"A.NS": 3}, adj, _IDX[-1]).iloc[-1] == pytest_approx(300.0)


def test_nav_needs_no_flows_to_be_safe() -> None:
    """A Result built without flows must not raise — it degrades to the rupee curve, not a crash."""
    r = Result(label="t", equity_curve=pd.Series([1.0, 2.0], index=_IDX[:2]))
    assert len(r.nav()) == 2


def pytest_approx(value: float, abs: float = 1e-9):
    import pytest

    return pytest.approx(value, abs=abs)
