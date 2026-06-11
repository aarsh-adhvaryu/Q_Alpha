"""Shared test fixtures: a small synthetic price panel (no network)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from qalpha.data.prices import PriceData


@pytest.fixture
def synthetic_long() -> pd.DataFrame:
    """Three tickers, 300 business days, deterministic geometric random walks."""
    rng = np.random.default_rng(42)
    dates = pd.bdate_range("2022-01-03", periods=300)
    tickers = ["AAA", "BBB", "CCC"]
    rows = []
    for t_i, ticker in enumerate(tickers):
        # Different drifts so factor ranks are non-degenerate.
        drift = 0.0003 * (t_i + 1)
        shocks = rng.normal(drift, 0.012, size=len(dates))
        price = 100.0 * np.exp(np.cumsum(shocks))
        volume = rng.integers(50_000, 200_000, size=len(dates))
        for d, p, v in zip(dates, price, volume, strict=True):
            rows.append({"date": d, "ticker": ticker, "close": p, "adj_close": p, "volume": int(v)})
    return pd.DataFrame(rows)


@pytest.fixture
def synthetic_prices(synthetic_long: pd.DataFrame) -> PriceData:
    return PriceData.from_long(synthetic_long)
