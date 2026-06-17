"""Size-aware market-impact slippage (Q_alpha.md §13, the Almgren square-root law).

Flat per-trade slippage is blind to order size — acceptable for a handful of deep large-caps, but it
under-charges the cost of pushing a big position through a thinner mid-cap (the gating risk for any
Nifty 100–200 expansion). The square-root law makes slippage scale with how much of a day's liquidity
the order consumes and how volatile the name is:

    slippage_fraction ≈ k · σ_daily · √(trade_value / ADV)

* **σ_daily** — the stock's daily return volatility (a more volatile name fills worse).
* **trade_value / ADV** — the order as a fraction of average daily traded *value* (₹). Trading one
  whole day's volume costs ~one day's volatility; a tiny slice costs almost nothing.
* **k** — the impact coefficient (≈1). At ``k=1`` the law equals ~0.2% exactly when an order is 1% of
  ADV at 2% daily vol, so it agrees with the old flat assumption at the §3.3 order-size cap, and is
  cheaper below it / dearer above it.

Making slippage size-aware is also what lets the §4.6 net-benefit gate and the optimiser *minimise*
it: a rebalance that would move a large notional through a thin name now shows its true cost and is
suppressed. Slippage is an execution cost (price impact), **not** portfolio risk — though it is driven
by the same volatility, which is why σ appears in the formula.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


class SlippageModel(Protocol):
    """Returns the slippage fraction (of trade value) for one trade of ``ticker``."""

    def pct(self, ticker: str, trade_value: Decimal) -> Decimal: ...


def _clamp(x: Decimal, lo: Decimal, hi: Decimal) -> Decimal:
    return min(max(x, lo), hi)


@dataclass(frozen=True)
class FlatSlippage:
    """The flat, size-blind slippage (the legacy default): a constant fraction of trade value."""

    rate: Decimal

    def pct(self, ticker: str, trade_value: Decimal) -> Decimal:
        return self.rate


def square_root_impact_pct(
    trade_value: Decimal,
    adv_value: float,
    daily_vol: float,
    *,
    k: Decimal,
    floor: Decimal,
    cap: Decimal,
) -> Decimal:
    """The square-root market-impact slippage fraction, clamped to ``[floor, cap]``.

    ``adv_value`` is average daily traded value in ₹; ``daily_vol`` is the daily return std. Unknown
    or non-positive liquidity/vol (or a non-positive trade) is treated as the conservative ``cap`` —
    a name we cannot size against is assumed maximally costly (and so avoided by the gate).
    """
    tv = float(trade_value)
    if (
        tv <= 0.0
        or adv_value <= 0.0
        or daily_vol <= 0.0
        or math.isnan(adv_value)
        or math.isnan(daily_vol)
    ):
        return cap
    frac = float(k) * daily_vol * math.sqrt(tv / adv_value)
    return _clamp(Decimal(str(frac)), floor, cap)


@dataclass(frozen=True)
class SquareRootSlippage:
    """Size-aware slippage from per-ticker ADV (₹) and daily volatility, evaluated at execution.

    The ADV/vol maps are snapshots taken causally (as-of the trade date) by the backtest engine, so
    no future data reaches the cost of a historical trade.
    """

    adv: Mapping[str, float]  # ₹ average daily traded value, per ticker
    daily_vol: Mapping[str, float]  # daily return std, per ticker
    k: Decimal
    floor: Decimal
    cap: Decimal

    def pct(self, ticker: str, trade_value: Decimal) -> Decimal:
        return square_root_impact_pct(
            trade_value,
            self.adv.get(ticker, 0.0),
            self.daily_vol.get(ticker, 0.0),
            k=self.k,
            floor=self.floor,
            cap=self.cap,
        )
