"""Momentum factor (Q_alpha.md §3.2, factor 1).

"12-month TR-adjusted return minus the most recent 1-month return (skip short-term reversal
noise)." Implemented as the standard **12-1 momentum**: the cumulative total return from ~12 months
ago to ~1 month ago, i.e. ``adj_close[t-skip] / adj_close[t-lookback] - 1``. Skipping the most
recent month removes the well-documented short-term reversal effect. Higher is better.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from qalpha.data.prices import PriceData


def momentum(prices: PriceData, lookback: int = 252, skip: int = 21) -> pd.Series:
    """12-1 momentum at the panel's last date, per ticker. NaN where history is insufficient."""
    adj = prices.adj_close
    if len(adj) < lookback + 1:
        return pd.Series(np.nan, index=adj.columns, name="momentum")
    p_recent = adj.iloc[-1 - skip]
    p_start = adj.iloc[-1 - lookback]
    mom = p_recent / p_start - 1.0
    return mom.rename("momentum")
