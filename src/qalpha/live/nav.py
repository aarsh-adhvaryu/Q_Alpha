"""Unitized NAV — the only honest way to compare books that money keeps arriving into.

**The problem.** A rupee equity curve cannot be told apart from the deposits that grew it. Every
statistic computed straight off one is contaminated: ``cummax`` sees no drawdown because contributions
keep minting new highs, ``pct_change`` reads a ₹50,000 deposit into a ₹1,00,000 book as a +50% day,
and a ratio of two such curves is diluted by every rupee added to both — 110/100 is a 10% lead, but
add ₹100 to each and 210/200 is only 5%, with nothing having happened in the market.

**The fix** is what a mutual fund does to quote a NAV while money flows in and out: hold *units*, and
on a contribution day buy new units at the prevailing price rather than inflating the price.

    nav_t     = value_t / units_t
    units_new = units_prev + contribution / nav_at_contribution

A deposit then moves ``units`` and leaves ``nav`` alone, so the series responds only to what the
investments did. Drawdowns are what the holder actually felt; successive ratios are true returns, safe
to compound, to hedge against, or to divide by another book's.

Used by the SIP backtest (``scripts/backtest_sip.py``) and by the twin's GO criterion 3, which is why
it lives here rather than in either of them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

import pandas as pd


def unitized_nav(
    values: pd.Series,
    flows: Sequence[tuple[date, float]] | Mapping[date, float],
    *,
    base: float = 1.0,
) -> pd.Series:
    """Convert a contribution-bearing value series into a contribution-free NAV series.

    Args:
        values: dated book value (shares **plus** cash — a book holding nothing still holds its
            money). Its first entry establishes the opening basis.
        flows: dated contributions. A flow dated on or before the first value is folded into the
            opening basis rather than treated as a purchase, so a series that starts mid-life is
            measured from where it starts instead of inheriting an unknowable prior path.
        base: the NAV to start from. Arbitrary — only ratios of a NAV series mean anything.

    Returns:
        A NAV series on ``values``' index. Empty in, empty out.
    """
    if len(values) == 0:
        return values
    by_day: dict[pd.Timestamp, float] = {}
    items = flows.items() if isinstance(flows, Mapping) else flows
    for when, amount in items:
        ts = pd.Timestamp(when)
        by_day[ts] = by_day.get(ts, 0.0) + float(amount)

    # A DatetimeIndex so the loop keys are Timestamps rather than bare Hashables — the flow lookup
    # has to match on the same type the flows were keyed with.
    idx = pd.DatetimeIndex(values.index)
    first = idx[0]
    units = 0.0
    out: list[float] = []
    for day, value in zip(idx, values.to_numpy(), strict=True):
        added = by_day.get(day)
        # A contribution landing on the opening mark is part of the basis, not a purchase into an
        # already-priced book: there is no prior NAV to buy it at.
        if added and day != first and units > 0:
            before = float(value) - added
            if before > 0:
                units += added / (before / units)
        elif units == 0:
            units = float(value) / base if float(value) > 0 else 0.0
        out.append(float(value) / units if units > 0 else base)
    return pd.Series(out, index=values.index, name="nav")
