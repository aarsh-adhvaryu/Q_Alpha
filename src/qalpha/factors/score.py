"""Composite factor scoring (Q_alpha.md §3.2).

Each factor is converted to a **sector-relative percentile rank** (0–100), then combined into a
single composite (0–100) using the regime's factor weights. Two design choices matter:

* **Direction** — ``HIGHER_IS_BETTER`` flips factors where small raw values are good (volatility)
  so a high percentile always means "more attractive".
* **Partial factor sets** — weights are renormalised per ticker over the factors actually present
  and non-NaN. This is what lets Phase 0a run on three factors and Phase 0b on six without code
  changes: absent factors simply drop out and the remaining weights rescale to sum to 1.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

# True => larger raw value is more attractive. Volatility is the only "lower is better" factor.
HIGHER_IS_BETTER: dict[str, bool] = {
    "momentum": True,
    "value": True,  # value.py returns cheapness (already oriented so higher = cheaper = better)
    "quality": True,
    "volatility": False,
    "liquidity": True,
    "dividend": True,
}

_UNKNOWN_SECTOR = "UNKNOWN"
_NEUTRAL = 50.0  # percentile assigned to a lone stock in its sector (no peers to rank against)


def sector_percentile_ranks(
    factor_values: pd.Series,
    sectors: Mapping[str, str],
    *,
    higher_is_better: bool,
) -> pd.Series:
    """Percentile-rank ``factor_values`` (0–100) within each ticker's sector.

    NaN inputs stay NaN. A sector with a single ranked stock yields the neutral score (50) rather
    than a spurious 0 or 100.
    """
    sector_of = pd.Series(
        {t: sectors.get(t, _UNKNOWN_SECTOR) for t in factor_values.index},
        dtype="object",
    )
    out = pd.Series(np.nan, index=factor_values.index, dtype="float64")

    for _sector, members in sector_of.groupby(sector_of):
        idx = members.index
        vals = factor_values.loc[idx].dropna()
        if vals.empty:
            continue
        if len(vals) == 1:
            out.loc[vals.index] = _NEUTRAL
            continue
        pct = vals.rank(ascending=higher_is_better, pct=True) * 100.0
        out.loc[pct.index] = pct
    out.name = factor_values.name
    return out


def composite_score(
    factor_frame: pd.DataFrame,
    sectors: Mapping[str, str],
    weights: Mapping[str, float],
) -> pd.Series:
    """Combine raw factor columns into a 0–100 composite using regime ``weights``.

    Args:
        factor_frame: index = ticker, columns = factor names with RAW values.
        sectors: ticker -> sector mapping (missing tickers fall into an UNKNOWN bucket).
        weights: factor -> weight (e.g. from ``regime_weights``). Only factors present in both
            ``factor_frame`` and ``weights`` are used; their weights are renormalised to sum to 1.

    Returns:
        Composite score per ticker (0–100), NaN where no factor was available.
    """
    used_factors = [f for f in factor_frame.columns if f in weights]
    if not used_factors:
        raise ValueError("no overlapping factors between factor_frame and weights")

    ranks = pd.DataFrame(index=factor_frame.index)
    for factor in used_factors:
        ranks[factor] = sector_percentile_ranks(
            factor_frame[factor], sectors, higher_is_better=HIGHER_IS_BETTER[factor]
        )

    w = pd.Series({f: weights[f] for f in used_factors}, dtype="float64")
    # Per-row renormalisation over non-NaN factors.
    weighted_sum = ranks.mul(w, axis=1).sum(axis=1, skipna=True)
    weight_present = ranks.notna().mul(w, axis=1).sum(axis=1)
    composite = weighted_sum / weight_present.replace(0.0, np.nan)
    return composite.rename("composite")
