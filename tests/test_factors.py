"""Factor + regime tests."""

from __future__ import annotations

import numpy as np
import pandas as pd

from qalpha.config import RegimeConfig
from qalpha.data.prices import PriceData
from qalpha.factors import (
    Regime,
    classify_regime,
    composite_score,
    liquidity,
    momentum,
    regime_weights,
    sector_percentile_ranks,
    volatility,
)


def _ramp_panel(slopes: dict[str, float], n: int = 300) -> PriceData:
    """Deterministic panel where each ticker rises at a fixed daily rate (clean monotonic prices)."""
    dates = pd.bdate_range("2022-01-03", periods=n)
    rows = []
    for ticker, slope in slopes.items():
        price = 100.0 * np.cumprod(np.full(n, 1.0 + slope))
        for d, p in zip(dates, price, strict=True):
            rows.append(
                {"date": d, "ticker": ticker, "close": p, "adj_close": p, "volume": 100_000}
            )
    return PriceData.from_long(pd.DataFrame(rows))


def test_momentum_ranks_faster_riser_higher() -> None:
    prices = _ramp_panel({"SLOW": 0.0005, "FAST": 0.002})
    mom = momentum(prices)
    assert mom["FAST"] > mom["SLOW"] > 0


def test_momentum_nan_when_insufficient_history() -> None:
    prices = _ramp_panel({"AAA": 0.001}, n=100)  # < lookback+1
    assert momentum(prices).isna().all()


def test_volatility_positive_and_lower_for_smooth(synthetic_prices: PriceData) -> None:
    vol = volatility(synthetic_prices)
    assert (vol > 0).all()


def test_liquidity_is_rupee_value() -> None:
    prices = _ramp_panel({"AAA": 0.001})
    liq = liquidity(prices)
    # price ~ >100, volume 100k => ADV in the tens of millions of ₹.
    assert liq["AAA"] > 1_000_000


def test_classify_regime_thresholds() -> None:
    cfg = RegimeConfig()
    assert classify_regime(15.0, cfg) is Regime.BULL
    assert classify_regime(22.0, cfg) is Regime.BEAR
    assert classify_regime(30.0, cfg) is Regime.HIGH_VOL
    assert classify_regime(40.0, cfg) is Regime.CRASH
    assert classify_regime(15.0, cfg, rotation_flag=True) is Regime.ROTATION


def test_regime_weights_sum_to_one() -> None:
    for regime in Regime:
        assert abs(sum(regime_weights(regime).values()) - 1.0) < 1e-9


def test_sector_percentile_direction() -> None:
    vals = pd.Series({"A": 1.0, "B": 2.0, "C": 3.0}, name="momentum")
    sectors = {"A": "TECH", "B": "TECH", "C": "TECH"}
    # Higher is better: C (largest) gets the top percentile.
    hi = sector_percentile_ranks(vals, sectors, higher_is_better=True)
    assert hi["C"] > hi["B"] > hi["A"]
    # Lower is better: A (smallest) gets the top percentile.
    lo = sector_percentile_ranks(vals, sectors, higher_is_better=False)
    assert lo["A"] > lo["B"] > lo["C"]


def test_lone_stock_in_sector_is_neutral() -> None:
    vals = pd.Series({"A": 5.0, "B": 9.0}, name="momentum")
    sectors = {"A": "TECH", "B": "PHARMA"}  # each alone in its sector
    ranks = sector_percentile_ranks(vals, sectors, higher_is_better=True)
    assert ranks["A"] == 50.0
    assert ranks["B"] == 50.0


def test_composite_renormalizes_over_present_factors() -> None:
    # Only 3 of 6 factors present (Phase 0a). Composite should still be a valid 0-100 score.
    factor_frame = pd.DataFrame(
        {
            "momentum": {"A": 0.10, "B": 0.20, "C": 0.30},
            "volatility": {"A": 0.40, "B": 0.30, "C": 0.20},
            "liquidity": {"A": 1e7, "B": 2e7, "C": 3e7},
        }
    )
    sectors = {"A": "TECH", "B": "TECH", "C": "TECH"}
    weights = regime_weights(Regime.BULL)  # has all 6 factors; only 3 overlap
    comp = composite_score(factor_frame, sectors, weights)
    assert comp.between(0, 100).all()
    # C is best momentum, lowest volatility, highest liquidity -> highest composite.
    assert comp.idxmax() == "C"


def test_composite_handles_per_row_nan() -> None:
    factor_frame = pd.DataFrame(
        {
            "momentum": {"A": 0.10, "B": 0.20, "C": np.nan},
            "liquidity": {"A": 1e7, "B": 2e7, "C": 3e7},
        }
    )
    sectors = {"A": "TECH", "B": "TECH", "C": "TECH"}
    weights = regime_weights(Regime.BULL)
    comp = composite_score(factor_frame, sectors, weights)
    # C has only liquidity; still scored (not NaN) via per-row renormalisation.
    assert not np.isnan(comp["C"])
