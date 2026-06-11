"""Portfolio optimizer: min-variance stock weights within sector boundaries (Q_alpha.md §3.4).

Minimum-variance by design — it never estimates expected returns (the most fragile Markowitz
input; §3.4). The sector allocator has already set each sector's total weight; this stage finds
the exact per-stock weights *inside* those totals:

    minimize   w'Σw
    subject to sum of weights in sector s == sector_target[s]   (group equality)
               0 <= w_i <= max_single_stock                     (per-stock cap, §3.4 = 20%)

Only sectors that actually contain selected stocks can receive weight, so the incoming sector
targets are restricted to present sectors and renormalised to sum to 1. A sector target that would
require a single stock to exceed the per-stock cap is clipped to keep the problem feasible.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from qalpha.alloc.conditioning import FloatArray, conditioned_covariance
from qalpha.config import OptimizerConfig


def _feasible_sector_targets(
    sector_targets: pd.Series, members: dict[str, list[int]], cap: float
) -> pd.Series:
    """Restrict targets to present sectors, renormalise to 1, and clip to ``count·cap`` feasibility."""
    present = sector_targets.loc[[s for s in sector_targets.index if s in members]].copy()
    if present.empty or present.sum() <= 0:
        raise ValueError("no sector targets overlap the selected stocks")
    present = present / present.sum()
    # A sector with k stocks can hold at most k·cap. Clip, then renormalise the survivors.
    for _ in range(len(present)):
        ceilings = pd.Series({s: len(members[s]) * cap for s in present.index})
        over = present > ceilings + 1e-12
        if not over.any():
            break
        present[over] = ceilings[over]
        slack = 1.0 - present[over].sum()
        room = present[~over]
        if room.sum() > 0:
            present[~over] = room / room.sum() * slack
    return present


def optimize_weights(
    stock_returns: pd.DataFrame,
    sector_of: dict[str, str],
    sector_targets: pd.Series,
    cfg: OptimizerConfig,
    halflife: int = 60,
) -> pd.Series:
    """Return min-variance per-stock weights respecting sector totals and the per-stock cap.

    ``stock_returns`` columns are the selected, data-complete tickers. Falls back to the
    equal-within-sector seed if SLSQP fails to converge.
    """
    cov = conditioned_covariance(stock_returns, halflife=halflife)
    tickers = cov.tickers
    sigma = cov.matrix
    n = len(tickers)
    cap = cfg.max_single_stock

    # Map each present sector -> indices of its member stocks (in cov ordering).
    members: dict[str, list[int]] = {}
    for i, t in enumerate(tickers):
        members.setdefault(sector_of.get(t, "UNKNOWN"), []).append(i)

    targets = _feasible_sector_targets(sector_targets, members, cap)

    # Equal-within-sector seed (also the fallback).
    x0 = np.zeros(n)
    for s, tgt in targets.items():
        idx = members[str(s)]
        x0[idx] = tgt / len(idx)

    # Scale the objective to O(1) so SLSQP's ftol doesn't stop it at the starting point.
    scale = 1.0 / float(np.trace(sigma) / n)

    def objective(w: FloatArray) -> float:
        return float(w @ sigma @ w) * scale

    def jac(w: FloatArray) -> FloatArray:
        return 2.0 * sigma @ w * scale

    constraints = []
    for s, tgt in targets.items():
        idx = members[str(s)]
        constraints.append(
            {"type": "eq", "fun": (lambda w, idx=idx, tgt=tgt: float(np.sum(w[idx]) - tgt))}
        )

    bounds = [(0.0, cap)] * n
    result = minimize(
        objective,
        x0,
        jac=jac,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"ftol": 1e-10, "maxiter": 200},
    )
    weights = result.x if result.success else x0
    # Clean tiny negatives, then rescale to the achievable target total (==1 when feasible).
    weights = np.clip(weights, 0.0, None)
    total = weights.sum()
    target_total = float(targets.sum())
    if total > 0:
        weights = weights / total * target_total
    return pd.Series(weights, index=tickers, name="weight")
