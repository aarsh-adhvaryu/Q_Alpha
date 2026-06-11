"""Volatility factor (Q_alpha.md §3.2, factor 4).

30-day realized volatility on TR-adjusted returns, annualized. Lower is better (the scorer flips
the direction via ``HIGHER_IS_BETTER``). Not sector-normalized in the spec, but the scorer applies
sector-relative ranking uniformly; for Phase 0 that is an acceptable simplification and is noted.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from qalpha.data.prices import PriceData


def volatility(prices: PriceData, window: int = 30, trading_days: int = 252) -> pd.Series:
    """Annualized realized volatility over the trailing ``window`` days, per ticker."""
    rets = prices.returns()
    if len(rets) < window:
        return pd.Series(np.nan, index=prices.adj_close.columns, name="volatility")
    daily_std = rets.iloc[-window:].std()
    annualized = daily_std * np.sqrt(trading_days)
    return annualized.rename("volatility")
