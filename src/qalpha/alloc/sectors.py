"""Sector allocator: scipy min-variance over sectors (Q_alpha.md §3.3).

For v1's ~12 NSE sectors this is a small convex problem: minimise ``w'Σw`` subject to weights
summing to 1 and each sector bounded to 5%–30%. scipy's SLSQP solves it to optimality in
milliseconds. Sector returns are the equal-weighted mean of constituent stock returns; their
covariance is conditioned (Ledoit-Wolf + EWMA) before optimisation.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from qalpha.alloc.conditioning import FloatArray, conditioned_covariance
from qalpha.config import OptimizerConfig


def sector_returns_from_stocks(
    stock_returns: pd.DataFrame, sector_of: dict[str, str]
) -> pd.DataFrame:
    """Equal-weighted sector return series from constituent stock returns (§3.3 input)."""
    sectors = pd.Series(sector_of)
    aligned = sectors.reindex(stock_returns.columns).dropna()
    grouped = stock_returns[aligned.index].T.groupby(aligned).mean().T
    return grouped


def allocate_sectors(
    sector_returns: pd.DataFrame,
    cfg: OptimizerConfig,
    halflife: int = 60,
    *,
    bounds_override: Mapping[str, tuple[float, float]] | None = None,
) -> pd.Series:
    """Min-variance sector weights within [sector_weight_min, sector_weight_max], summing to 1.

    If the bounds cannot sum to 1 for the given number of sectors, the bounds are infeasible and a
    ValueError is raised (e.g. 2 sectors each capped at 0.30 can never reach 1.0).

    ``bounds_override`` optionally tightens *specific* sectors' ``(lo, hi)`` box — the label-only
    injection point for the satellite sector footprint (``live/satellite.tighten_sector_bounds``):
    holding a telecom IPO shrinks the core's telecom box so the book diversifies around it. It is a
    pure **constraint** change; the satellite is **never** folded into the ``w'Σw`` objective/Σ (that
    would need an index proxy and would oversize the unmodellable IPO). Sectors absent from the
    override keep the uniform ``[min, max]`` box, so ``bounds_override=None`` is identical to before.
    """
    cov = conditioned_covariance(sector_returns, halflife=halflife)
    sectors = cov.tickers
    n = len(sectors)
    lo, hi = cfg.sector_weight_min, cfg.sector_weight_max

    bounds: list[tuple[float, float]]
    x0: FloatArray
    if bounds_override:
        los = [bounds_override.get(s, (lo, hi))[0] for s in sectors]
        his = [bounds_override.get(s, (lo, hi))[1] for s in sectors]
        if sum(his) < 1.0 - 1e-9 or sum(los) > 1.0 + 1e-9:
            raise ValueError(
                f"per-sector bounds infeasible for {n} sectors "
                f"(Σhi={sum(his):.3f}, Σlo={sum(los):.3f})"
            )
        bounds = list(zip(los, his, strict=True))
        x0 = np.clip(np.full(n, 1.0 / n), np.array(los), np.array(his))
    else:
        # Unchanged original path (uniform box) — kept byte-identical so the validated headline is
        # provably untouched when no override is supplied (the backtest never supplies one).
        if n * hi < 1.0 - 1e-9 or n * lo > 1.0 + 1e-9:
            raise ValueError(f"sector bounds [{lo},{hi}] infeasible for {n} sectors")
        bounds = [(lo, hi)] * n
        x0 = np.full(n, 1.0 / n)

    sigma = cov.matrix
    # Daily-variance magnitudes (~1e-4) sit below SLSQP's default ftol, which makes it "converge"
    # at the starting point. Scale the objective to O(1) — this leaves the argmin unchanged.
    scale = 1.0 / float(np.trace(sigma) / n)

    def objective(w: FloatArray) -> float:
        return float(w @ sigma @ w) * scale

    def jac(w: FloatArray) -> FloatArray:
        return 2.0 * sigma @ w * scale

    constraints = [{"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0)}]

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
    return pd.Series(weights, index=sectors, name="sector_weight")
