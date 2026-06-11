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
