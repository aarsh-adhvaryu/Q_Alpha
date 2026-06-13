"""Baselines the strategy must beat (Q_alpha.md §13, §14 criterion 1).

Four references, each producing a daily equity curve (or summary) aligned to the strategy's dates:

* **do-nothing** — hold cash; the strategy must justify taking any market risk at all.
* **Nifty 50 buy-and-hold** — lump-sum into the index, held.
* **equal-weight buy-and-hold** — naive 1/N diversification across the starting universe.
* **monthly SIP** — rupee-cost-averaging into Nifty (different cash-flow profile, so reported as a
  money-weighted summary rather than a comparable lump-sum curve).

Baselines are intentionally **cost-free and tax-free** — idealised references. The strategy carries
full Zerodha costs and capital-gains tax, so beating even a frictionless baseline is the honest bar.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pandas as pd

from qalpha.data.prices import PriceData
from qalpha.data.universe import Universe


def do_nothing(index: pd.DatetimeIndex, capital: Decimal) -> pd.Series:
    """Flat equity curve at ``capital`` — the opportunity-cost floor."""
    return pd.Series(float(capital), index=index, name="do_nothing")


def buy_and_hold(prices: pd.Series, index: pd.DatetimeIndex, capital: Decimal) -> pd.Series:
    """Lump-sum buy-and-hold of a single (TR-adjusted) price series, aligned to ``index``."""
    aligned = prices.reindex(index).ffill().bfill()
    units = float(capital) / float(aligned.iloc[0])
    return (aligned * units).rename("buy_and_hold")


def equal_weight(prices: PriceData, index: pd.DatetimeIndex, capital: Decimal) -> pd.Series:
    """Equal-weight buy-and-hold across tickers priced on the first date, aligned to ``index``."""
    adj = prices.adj_close.reindex(index).ffill()
    first = adj.iloc[0].dropna()
    valid = first[first > 0].index
    if len(valid) == 0:
        return do_nothing(index, capital).rename("equal_weight")
    per_name = float(capital) / len(valid)
    units = per_name / adj[valid].iloc[0]
    curve = adj[valid].mul(units, axis=1).sum(axis=1)
    return curve.rename("equal_weight")


def equal_weight_pit(
    prices: PriceData,
    universe: Universe,
    index: pd.DatetimeIndex,
    capital: Decimal,
) -> pd.Series:
    """Point-in-time 1/N: monthly-rebalanced equal weight of the *current index members*.

    The plain :func:`equal_weight` buys whatever is priced on day one and holds — fine for a static
    universe where every name is a member throughout, but on a point-in-time universe it would hold
    names *before they entered* the index (front-running future multibaggers) and after dead names
    *left* it. That is look-ahead, and it grossly inflates the 1/N bar.

    This version is the honest naive-diversification benchmark: on the last trading day of each
    month it equal-weights exactly the names that were index members on that date *and* priceable
    then, holding units between rebalances. Still frictionless (no cost/tax) like the other
    baselines — the idealised reference the strategy must beat net of its own friction.
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


@dataclass(frozen=True)
class SipSummary:
    """Money-weighted summary of a monthly SIP into the benchmark."""

    invested: Decimal
    final_value: Decimal
    n_installments: int

    @property
    def multiple(self) -> float:
        return float(self.final_value / self.invested) if self.invested > 0 else 0.0


def monthly_sip(prices: pd.Series, monthly_amount: Decimal) -> SipSummary:
    """Invest ``monthly_amount`` into the benchmark on the last trading day of each month."""
    idx = prices.index
    assert isinstance(idx, pd.DatetimeIndex)
    month_last = prices.groupby(idx.to_period("M")).tail(1)
    units = 0.0
    invested = Decimal("0")
    for price in month_last:
        units += float(monthly_amount) / float(price)
        invested += monthly_amount
    final_value = Decimal(str(units * float(prices.iloc[-1]))).quantize(Decimal("0.01"))
    return SipSummary(invested=invested, final_value=final_value, n_installments=len(month_last))
