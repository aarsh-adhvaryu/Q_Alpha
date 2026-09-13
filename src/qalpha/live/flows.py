"""Dated cash flows, a money-weighted return, and the same money put into a benchmark instead.

Every book receives the same dated flows — derived from the user's tradebook — so the books differ
only in what they did with the money. :func:`xirr` is the annual rate that makes the dated flows net
to today's value, which is what a bank would quote. :func:`benchmark_leg` answers "had the same
rupees gone into this series on the same days, where would they be?".

*Known approximation:* Zerodha's tradebook records execution price, not charges. Delivery brokerage
is ₹0, so the flows understate cost by roughly the STT/stamp/DP leg (~0.1%), on every book alike.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd

from qalpha.accounting.costs import Side

#: XIRR search bracket. The lower bound is just above total loss (−100% is a pole); the upper bound is
#: absurdly generous, so a failure to bracket means the flows are degenerate, not that the rate is high.
_RATE_FLOOR = -0.9999
_RATE_CEILING = 10.0
_TOLERANCE = 1e-7
_MAX_ITERATIONS = 200


@dataclass(frozen=True)
class Flow:
    """One dated movement of money into (positive) or out of (negative) the equity book.

    The brokerage cash account sits *outside* the portfolio by this definition, so selling A to buy B
    on the same day is an outflow and an inflow that very nearly cancel — which is the correct
    treatment: no new money arrived.
    """

    on: date
    amount: Decimal


def flows_from_trades(trades: Sequence[object]) -> list[Flow]:
    """Dated cash flows from a Zerodha tradebook, one per day, oldest first.

    Accepts anything with ``trade_date``/``side``/``quantity``/``price`` — i.e.
    :class:`~qalpha.live.tradebook.TradebookTrade`, which is what the private-gist master holds.
    Same-day trades are summed so a rebalance reads as its net effect rather than as churn.
    """
    by_day: dict[date, Decimal] = {}
    for trade in trades:
        value = Decimal(str(trade.quantity)) * Decimal(str(trade.price))  # type: ignore[attr-defined]
        signed = value if trade.side is Side.BUY else -value  # type: ignore[attr-defined]
        day = trade.trade_date  # type: ignore[attr-defined]
        by_day[day] = by_day.get(day, Decimal("0")) + signed
    return [Flow(on=d, amount=by_day[d]) for d in sorted(by_day)]


def xirr(dated: Sequence[tuple[date, Decimal]]) -> float | None:
    """The annual rate that discounts ``dated`` flows to zero — the money-weighted return.

    Sign convention is the spreadsheet one: money **leaving you** is negative, money **coming back**
    (including the terminal value of what you still hold) is positive.

    Solved by bisection rather than Newton because the NPV curve has a pole at −100% and Newton
    happily walks into it from a bad guess. Bisection cannot diverge; it just needs the root
    bracketed, and returns ``None`` when it is not — which for real flows means every one has the
    same sign (nothing to solve) or the answer lies outside a −99.99%…+1000% range.
    """
    if len(dated) < 2:
        return None
    flows = sorted(dated, key=lambda p: p[0])
    if not (any(a > 0 for _, a in flows) and any(a < 0 for _, a in flows)):
        return None
    t0 = flows[0][0]
    years = [(d - t0).days / 365.0 for d, _ in flows]
    amounts = [float(a) for _, a in flows]

    def npv(rate: float) -> float:
        return sum(a / (1.0 + rate) ** t for a, t in zip(amounts, years, strict=True))

    low, high = _RATE_FLOOR, _RATE_CEILING
    f_low, f_high = npv(low), npv(high)
    if f_low * f_high > 0:
        return None
    for _ in range(_MAX_ITERATIONS):
        mid = (low + high) / 2.0
        f_mid = npv(mid)
        if abs(f_mid) < _TOLERANCE or (high - low) < _TOLERANCE:
            return mid
        if f_low * f_mid <= 0:
            high, f_high = mid, f_mid
        else:
            low, f_low = mid, f_mid
    return (low + high) / 2.0


def _price_on(series: pd.Series, day: date) -> Decimal | None:
    """The last index level at or before ``day`` — never after, so no future price is ever used."""
    stamp = pd.Timestamp(day)
    window = series.loc[:stamp].dropna()
    if window.empty:
        return None
    return Decimal(str(float(window.iloc[-1])))


@dataclass(frozen=True)
class BenchmarkLeg:
    """The counterfactual: the same rupees, on the same days, in the index instead."""

    units: Decimal
    value: Decimal
    exhausted: bool  # a sell exceeded the index sleeve — it ran out of units before you ran out


def benchmark_leg(flows: Sequence[Flow], series: pd.Series, as_of: date) -> BenchmarkLeg | None:
    """Replay ``flows`` into ``series`` (NIFTYBEES) and mark the result at ``as_of``.

    Returns ``None`` when the index has no price at or before the first flow — the comparison would
    otherwise be invented rather than measured.

    ``exhausted`` records the one case the arithmetic cannot represent honestly: if your book grew
    far faster than the index and you then sold a large chunk, the index sleeve funded with the same
    money does not hold enough to sell. Units are floored at zero and the flag is raised, because
    silently going short the index would report a number no one could have achieved.
    """
    units = Decimal("0")
    exhausted = False
    for flow in flows:
        price = _price_on(series, flow.on)
        if price is None or price <= 0:
            return None
        delta = flow.amount / price
        if units + delta < 0:
            delta, exhausted = -units, True
        units += delta
    now = _price_on(series, as_of)
    if now is None:
        return None
    return BenchmarkLeg(units=units, value=units * now, exhausted=exhausted)
