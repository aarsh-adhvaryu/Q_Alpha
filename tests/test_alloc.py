"""Allocation-layer tests: conditioning, sector allocator, optimizer."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from qalpha.alloc.conditioning import conditioned_covariance
from qalpha.alloc.optimizer import optimize_weights
from qalpha.alloc.sectors import allocate_sectors, sector_returns_from_stocks
from qalpha.config import OptimizerConfig

CFG = OptimizerConfig()


def _returns(n_obs: int, vols: dict[str, float], seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    data = {t: rng.normal(0.0, v, n_obs) for t, v in vols.items()}
    idx = pd.bdate_range("2020-01-01", periods=n_obs)
    return pd.DataFrame(data, index=idx)


def test_conditioned_cov_is_symmetric_psd() -> None:
    rets = _returns(250, {"A": 0.01, "B": 0.02, "C": 0.015})
    cov = conditioned_covariance(rets, halflife=60)
    m = cov.matrix
    assert m.shape == (3, 3)
    assert np.allclose(m, m.T)  # symmetric
    eigvals = np.linalg.eigvalsh(m)
    assert (eigvals > 0).all()  # positive definite (LW guarantees invertibility)


def test_conditioned_cov_drops_nan_columns() -> None:
    rets = _returns(250, {"A": 0.01, "B": 0.02, "C": 0.015})
    rets["C"] = np.nan
    cov = conditioned_covariance(rets)
    assert cov.tickers == ["A", "B"]


def test_conditioned_cov_needs_enough_obs() -> None:
    rets = _returns(2, {"A": 0.01, "B": 0.02, "C": 0.015})
    with pytest.raises(ValueError, match="more observations"):
        conditioned_covariance(rets)


def test_sector_allocator_respects_bounds_and_sums_to_one() -> None:
    # 4 sectors, one much more volatile -> min-variance should underweight it (but >= 5% floor).
    rets = _returns(300, {"FIN": 0.01, "IT": 0.011, "PHARMA": 0.012, "ENERGY": 0.04})
    weights = allocate_sectors(rets, CFG)
    assert abs(weights.sum() - 1.0) < 1e-6
    assert (weights >= CFG.sector_weight_min - 1e-6).all()
    assert (weights <= CFG.sector_weight_max + 1e-6).all()
    # Most volatile sector should sit at or near the floor.
    assert weights["ENERGY"] < weights["FIN"]


def test_sector_allocator_infeasible_bounds() -> None:
    rets = _returns(300, {"A": 0.01, "B": 0.02})  # 2 sectors, max 0.30 each -> can't reach 1.0
    with pytest.raises(ValueError, match="infeasible"):
        allocate_sectors(rets, CFG)


def test_sector_returns_aggregation() -> None:
    rets = _returns(50, {"A": 0.01, "B": 0.01, "C": 0.01})
    sector_of = {"A": "IT", "B": "IT", "C": "FIN"}
    sect = sector_returns_from_stocks(rets, sector_of)
    assert set(sect.columns) == {"IT", "FIN"}
    # IT sector return is the mean of A and B on each day.
    assert np.allclose(sect["IT"].to_numpy(), rets[["A", "B"]].mean(axis=1).to_numpy())


def test_optimizer_honors_sector_totals_and_cap() -> None:
    rets = _returns(300, {"A": 0.01, "B": 0.012, "C": 0.011, "D": 0.013, "E": 0.02}, seed=7)
    sector_of = {"A": "IT", "B": "IT", "C": "FIN", "D": "FIN", "E": "ENERGY"}
    sector_targets = pd.Series({"IT": 0.4, "FIN": 0.4, "ENERGY": 0.2})

    w = optimize_weights(rets, sector_of, sector_targets, CFG)

    assert abs(w.sum() - 1.0) < 1e-6
    assert (w <= CFG.max_single_stock + 1e-6).all()
    assert (w >= -1e-9).all()
    # Sector totals match the allocator's targets.
    assert abs(w[["A", "B"]].sum() - 0.4) < 1e-4
    assert abs(w[["C", "D"]].sum() - 0.4) < 1e-4
    assert abs(w["E"] - 0.2) < 1e-4


def test_optimizer_clips_infeasible_single_stock_sector() -> None:
    # ENERGY target 0.30 but its lone stock is capped at 0.20 -> clipped to 0.20; the freed 0.10
    # spills into IT (4 stocks, capacity 0.80). Needs >= 5 stocks total to sum to 1 under the cap.
    rets = _returns(300, {"A": 0.01, "B": 0.012, "C": 0.011, "D": 0.009, "E": 0.02}, seed=3)
    sector_of = {"A": "IT", "B": "IT", "C": "IT", "D": "IT", "E": "ENERGY"}
    sector_targets = pd.Series({"IT": 0.7, "ENERGY": 0.3})
    w = optimize_weights(rets, sector_of, sector_targets, CFG)
    assert abs(w.sum() - 1.0) < 1e-6
    assert w["E"] <= CFG.max_single_stock + 1e-6
    assert abs(w["E"] - 0.20) < 1e-4  # clipped to the per-stock cap
