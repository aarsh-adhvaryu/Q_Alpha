"""Protective-put hedge sanity: Black–Scholes pricing, no look-ahead, cuts a crash, keeps upside.

The "keeps upside" test is the point of puts vs futures: on a false alarm that rebounds, the put
(defined-risk) gives up only premium, while a short future would have surrendered the whole rebound.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from qalpha.live.hedge import apply_futures_hedge, hedge_active
from research.regime.options import apply_put_hedge, bs_put


def test_bs_put_sanity() -> None:
    assert bs_put(100, 100, 30 / 365, 0.20) > 0
    # monotonic: lower spot → more valuable put
    assert bs_put(90, 100, 30 / 365, 0.20) > bs_put(110, 100, 30 / 365, 0.20)
    # deep in-the-money ≈ discounted intrinsic, and ≥ intrinsic
    assert bs_put(50, 100, 30 / 365, 0.20) >= 100 - 50 - 1.0
    # expired put = intrinsic
    assert bs_put(95, 100, 0.0, 0.20) == 5.0


def _frame(
    ret: np.ndarray, vix_vals: np.ndarray, g: np.ndarray
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    idx = pd.bdate_range("2010-01-03", periods=len(ret))
    rser = pd.Series(ret, index=idx)
    level = pd.Series(1000 * np.exp(np.cumsum(ret)), index=idx)
    return rser, level, pd.Series(vix_vals, index=idx), pd.Series(g, index=idx)


def test_put_cuts_a_crash() -> None:
    ret = np.concatenate([np.full(150, 0.0006), np.full(40, -0.02), np.full(210, 0.0008)])
    vix = np.concatenate([np.full(150, 14.0), np.full(40, 45.0), np.full(210, 16.0)])
    g = np.concatenate([np.full(150, 0.1), np.full(40, 0.9), np.full(210, 0.1)])
    rser, level, vser, gser = _frame(ret, vix, g)
    active = hedge_active(gser, 0.7, 3)
    hedged = apply_put_hedge(rser, level, vser, active, h=1.0).equity
    unhedged = (1.0 + rser).cumprod()
    assert (hedged / hedged.cummax() - 1).min() > (unhedged / unhedged.cummax() - 1).min()


def test_put_keeps_upside_vs_futures_on_false_alarm() -> None:
    """Gauge fires, then the market RISES (a false alarm). The put keeps more upside than futures."""
    ret = np.concatenate([np.full(100, 0.0005), np.full(50, 0.004), np.full(150, 0.0005)])
    vix = np.concatenate([np.full(100, 16.0), np.full(50, 28.0), np.full(150, 16.0)])
    g = np.concatenate(
        [np.full(100, 0.1), np.full(50, 0.9), np.full(150, 0.1)]
    )  # fires on the rally
    rser, level, vser, gser = _frame(ret, vix, g)
    active = hedge_active(gser, 0.7, 3)
    put = apply_put_hedge(rser, level, vser, active, h=1.0).equity
    fut = apply_futures_hedge(rser, rser, active, h=1.0).equity
    assert (
        put.iloc[-1] > fut.iloc[-1]
    )  # short futures surrendered the rally; the put only lost premium


def test_no_look_ahead() -> None:
    n = 500
    rng = np.random.default_rng(0)
    ret = rng.normal(0.0003, 0.012, n)
    vix = np.full(n, 18.0) + rng.normal(0, 2, n)
    g = rng.random(n)
    rser, level, vser, gser = _frame(ret, vix, g)
    cut = 380
    full = apply_put_hedge(rser, level, vser, hedge_active(gser, 0.7, 5), h=1.0).equity
    trunc = apply_put_hedge(
        rser.iloc[:cut],
        level.iloc[:cut],
        vser.iloc[:cut],
        hedge_active(gser.iloc[:cut], 0.7, 5),
        h=1.0,
    ).equity
    np.testing.assert_allclose(full.iloc[:cut].to_numpy(), trunc.to_numpy(), rtol=0, atol=1e-12)
