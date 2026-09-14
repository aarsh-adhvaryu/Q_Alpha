"""The equal-weight Nifty-50 index, point in time — the series ``BASELINE_EW`` buys units of.

**On names that stop having prices.** A one-day hole in a vendor panel is ordinary and is carried
over; a name that stops trading for good is not, and holding it at its last price forever would make
a dead company a permanent, riskless position in the bar. So the fill is bounded
(:data:`STALE_LIMIT`), and past that a held name has no price rather than an old one — the day's
level is unknown, and unknown is what is reported.

Measured on this panel over 2012-2026: the fill supplies a price on 14 member-days in total, never
more than two consecutive sessions. Bounding it changes no number here. It is a guard against the
case the panel has not yet contained, not a correction of one it has.

TATAMOTORS is the live example of the other kind: its NSE symbol retired at the 2025 demerger, the
membership file still carries it with no end date, and no price exists for it at all. It is
therefore never held by the bar — and :func:`unpriceable_members` now says so on every run, instead
of the name simply not appearing.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from qalpha.data.prices import PriceData
from qalpha.data.universe import Universe

#: How many sessions a price may be carried before the name counts as unpriced. Two consecutive
#: missing sessions is the worst this panel has held in fourteen years; five is loose enough for a
#: bad week at the vendor and tight enough that a delisting cannot hide behind it.
STALE_LIMIT = 5


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
    adj = prices.adj_close.reindex(index).ffill(limit=STALE_LIMIT)
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
        # A held name with no price makes the whole day unknown. The alternative — counting it as
        # ₹0 — reports the bar falling by 1/N on the day a vendor goes quiet, and counting it at
        # its last price reports a dead company still trading.
        if invested and any(t not in priced for t in units):
            values.append(float("nan"))
        else:
            values.append(sum(u * priced[t] for t, u in units.items()) if invested else cap)
    return pd.Series(values, index=index, name="equal_weight")


def unpriceable_members(
    prices: PriceData, universe: Universe, index: pd.DatetimeIndex
) -> dict[str, int]:
    """Index members the panel cannot price, and on how many sessions — named, never just absent.

    A member with no price is silently left out of the equal weighting, which is the right number
    and the wrong silence: the bar is then computed over 49 names while calling itself the fifty.
    """
    adj = prices.adj_close.reindex(index).ffill(limit=STALE_LIMIT)
    missing: dict[str, int] = {}
    for day in index:
        priced = {
            str(t): float(v) for t, v in adj.loc[day].to_dict().items() if pd.notna(v) and v > 0
        }
        for member in universe.members_on(day.date()):
            if member not in priced:
                missing[member] = missing.get(member, 0) + 1
    return dict(sorted(missing.items(), key=lambda kv: -kv[1]))
