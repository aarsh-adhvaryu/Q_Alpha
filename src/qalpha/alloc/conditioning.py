"""Covariance conditioning: EWMA weighting + Ledoit-Wolf shrinkage (Q_alpha.md §3.8).

Mandatory preprocessing before any matrix enters the sector allocator, optimizer, or anomaly
detector. Two stabilisers are combined:

1. **EWMA weighting** (half-life ~60 trading days) so recent observations dominate.
2. **Ledoit-Wolf shrinkage** toward a structured target, which keeps the matrix well-conditioned
   and invertible even when the number of stocks approaches the number of observations.

We fuse them with the standard reweighting trick: scale each centered return row by
``sqrt(T · w_t)`` so its ordinary sample covariance equals the EWMA-weighted covariance, then run
``sklearn.covariance.LedoitWolf`` on the scaled rows. This gives EWMA emphasis *and* LW shrinkage
in one estimator, which is more than adequate for Phase-0 validation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pandas as pd
from sklearn.covariance import LedoitWolf

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True)
class Covariance:
    """A conditioned covariance matrix with its ticker ordering."""

    matrix: FloatArray  # (N, N)
    tickers: list[str]

    def as_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.matrix, index=self.tickers, columns=self.tickers)


def _ewma_weights(n_obs: int, halflife: int) -> FloatArray:
    """Normalised EWMA weights, oldest first, summing to 1 (most recent obs weighted highest)."""
    decay = 0.5 ** (1.0 / halflife)
    ages = np.arange(n_obs)[::-1]  # oldest row has the largest age
    w = decay**ages
    return w / w.sum()


def conditioned_covariance(returns: pd.DataFrame, halflife: int = 60) -> Covariance:
    """Return the EWMA-weighted, Ledoit-Wolf-shrunk covariance of ``returns``.

    Columns with any NaN in the window are dropped (insufficient overlap to estimate). Requires at
    least 2 columns and more rows than columns for a meaningful estimate; raises otherwise.
    """
    clean = returns.dropna(axis=1, how="any")
    n_obs, n_assets = clean.shape
    if n_assets < 2:
        raise ValueError("need >= 2 assets with complete returns to estimate covariance")
    if n_obs <= n_assets:
        raise ValueError(f"need more observations ({n_obs}) than assets ({n_assets})")

    w = _ewma_weights(n_obs, halflife)
    values = clean.to_numpy(dtype=float)
    mu = (values * w[:, None]).sum(axis=0)
    centered = values - mu
    scaled = centered * np.sqrt(w * n_obs)[:, None]

    lw = LedoitWolf(assume_centered=True).fit(scaled)
    return Covariance(matrix=np.asarray(lw.covariance_, dtype=float), tickers=list(clean.columns))
