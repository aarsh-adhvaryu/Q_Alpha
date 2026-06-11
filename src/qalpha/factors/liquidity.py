"""Liquidity factor + gate (Q_alpha.md §3.2 factor 5, §3.3 gate).

20-day ADV (Average Daily traded Value) in ₹. Higher is better. The same ADV figure drives the
hard pre-screening liquidity gate: tactical names need >= ₹25L ADV, core >= ₹50L (§3.3), because
the order-size cap is 1% of ADV and a single chunk must clear without moving the market.
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pandas as pd

from qalpha.data.prices import PriceData


def liquidity(prices: PriceData, window: int = 20) -> pd.Series:
    """20-day ADV in ₹ at the panel's last date, per ticker."""
    adv = prices.adv(window)
    if adv.empty:
        return pd.Series(np.nan, index=prices.adj_close.columns, name="liquidity")
    return adv.iloc[-1].rename("liquidity")


def passes_liquidity_gate(adv_value: pd.Series, min_adv: Decimal) -> pd.Series:
    """Boolean mask of tickers whose ADV clears ``min_adv`` (NaN ADV -> fails)."""
    threshold = float(min_adv)
    return (adv_value >= threshold).fillna(False)
