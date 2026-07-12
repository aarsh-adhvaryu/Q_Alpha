"""Tests for the tax-free short-futures hedge overlay (downside protection)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from qalpha.live.hedge import apply_futures_hedge, hedge_active, stress_gauge


def _dates(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range("2026-01-01", periods=n)


def test_stress_gauge_zero_at_high_one_in_deep_drawdown() -> None:
    idx = _dates(300)
    # ramp up (fresh highs → gauge 0), then a 20% fall (≥15% → gauge 1.0)
    close = pd.Series(np.linspace(100, 200, 300), index=idx)
    g = stress_gauge(close)
    assert g.iloc[250] == 0.0  # still climbing → no drawdown
    close2 = close.copy()
    close2.iloc[260:] = 140.0  # ~25% below the pre-drop high → deep stress
    g2 = stress_gauge(close2)
    assert g2.iloc[-1] == 1.0  # ≥15% drawdown → full stress


def test_hedge_active_turns_on_after_persistence_and_off_below_tau() -> None:
    idx = _dates(10)
    gauge = pd.Series([0, 0, 0.8, 0.8, 0.8, 0.8, 0.2, 0.2, 0.9, 0.9], index=idx, dtype=float)
    active = hedge_active(gauge, tau=0.7, persist=3)
    assert not active.iloc[2] and not active.iloc[3]  # not yet 3 in a row
    assert active.iloc[4]  # 3rd consecutive ≥τ → ON
    assert not active.iloc[6]  # dropped < τ → OFF immediately
    assert not active.iloc[9]  # only 2 back ≥τ → not yet re-armed


def test_hedge_cuts_the_drawdown_in_a_fall() -> None:
    idx = _dates(30)
    # a book that falls 10% alongside the index; the hedge (short) should offset part of the fall
    ret = pd.Series([-0.01] * 30, index=idx)
    active = pd.Series([True] * 30, index=idx)
    hedged = apply_futures_hedge(ret, ret, active, h=0.5, apply_costs=False)
    unhedged_pv = float((1 + ret).prod())
    assert hedged.equity.iloc[-1] > unhedged_pv  # short offsets ~half the loss → less negative


def test_hedge_no_lookahead() -> None:
    idx = _dates(40)
    rng = np.random.default_rng(0)
    ret = pd.Series(rng.normal(0, 0.01, 40), index=idx)
    gauge = stress_gauge((1 + ret).cumprod() * 100)
    active = hedge_active(gauge, tau=0.5, persist=2)
    full = apply_futures_hedge(ret, ret, active, h=0.5)
    cut = 30
    trunc = apply_futures_hedge(ret.iloc[:cut], ret.iloc[:cut], active.iloc[:cut], h=0.5)
    # the equity path up to cut-1 must be identical (a later bar can't change an earlier one)
    pd.testing.assert_series_equal(
        full.equity.iloc[: cut - 1], trunc.equity.iloc[: cut - 1], check_names=False
    )
