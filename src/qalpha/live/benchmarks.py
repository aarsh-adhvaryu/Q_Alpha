"""The equal-weight Nifty-50 index, point in time — the series ``BASELINE_EW`` buys units of."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from qalpha.data.prices import PriceData
from qalpha.data.universe import Universe


def equal_weight_pit(
    prices: PriceData,
    universe: Universe,
    index: pd.DatetimeIndex,
    capital: Decimal,
) -> pd.Series:
    """Point-in-time 1/N: monthly-rebalanced equal weight of the *current index members*.

    Buying whatever is priced on day one and holding would, on a point-in-time universe, hold names
    *before they entered* the index (front-running future multibaggers) and after dead names *left*
    it. That is look-ahead, and it grossly inflates the 1/N bar.

    This version is the honest naive-diversification benchmark: on the last trading day of each
    month it equal-weights exactly the names that were index members on that date *and* priceable
    then, holding units between rebalances. Frictionless (no cost/tax); ``BASELINE_EW`` charges the
    fund's fee on top of it.
    """
    adj = prices.adj_close.reindex(index).ffill()
    rebal_days = set(pd.Series(index, index=index).groupby(index.to_period("M")).last())

    units: dict[str, float] = {}  # ticker -> units held
    invested = False
    cap = float(capital)
    values: list[float] = []
    for day in index:
        row = adj.loc[day]
        priced: dict[str, float] = {
            str(t): float(p) for t, p in row.to_dict().items() if pd.notna(p) and float(p) > 0.0
        }
        if day in rebal_days or not invested:
            value = sum(u * priced.get(t, 0.0) for t, u in units.items()) if invested else cap
            members = [t for t in universe.members_on(day.date()) if t in priced]
            if members:
                per_name = value / len(members)
                units = {t: per_name / priced[t] for t in members}
                invested = True
        values.append(sum(u * priced.get(t, 0.0) for t, u in units.items()) if invested else cap)
    return pd.Series(values, index=index, name="equal_weight")
