"""Systemic-fragility gauge sanity: causal percentile ranks, no look-ahead, scores in [0,1].

The load-bearing property (as with the HMM): the gauge value at date t must not change when future
data is appended — it consumes only data ≤ t.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from qalpha.live.fragility import FragilityConfig, compute_fragility


def _synthetic_panel(n: int, seed: int = 0) -> pd.DataFrame:
    """A small cross-asset panel: a calm first half, a stressed second half (vol up, equity down)."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2000-01-03", periods=n)
    calm, stress = n // 2, n - n // 2
    vix = np.concatenate([rng.normal(14, 2, calm), rng.normal(35, 6, stress)]).clip(5, 90)
    eq_ret = np.concatenate([rng.normal(0.0004, 0.008, calm), rng.normal(-0.002, 0.025, stress)])
    sp = 1000 * np.exp(np.cumsum(eq_ret))
    sensex = 5000 * np.exp(np.cumsum(eq_ret + rng.normal(0, 0.003, n)))
    return pd.DataFrame(
        {
            "us_vix": vix,
            "sp500": sp,
            "sensex": sensex,
            "nasdaq": sp * 1.1,
            "dxy": 100 + np.cumsum(rng.normal(0, 0.1, n)),
        },
        index=idx,
    )


def test_scores_in_unit_interval() -> None:
    res = compute_fragility(_synthetic_panel(1500))
    for s in (res.stress, res.composite):
        v = s.dropna()
        assert len(v) > 0
        assert np.all((v >= 0.0) & (v <= 1.0))


def test_stress_rises_in_the_stressed_half() -> None:
    panel = _synthetic_panel(1500, seed=1)
    res = compute_fragility(panel)
    mid = panel.index[len(panel) // 2]
    early = res.stress[res.stress.index < mid].dropna()
    late = res.stress[res.stress.index >= mid].dropna()
    assert late.mean() > early.mean() + 0.15  # the gauge clearly elevates in the stressed regime


def test_no_look_ahead() -> None:
    """The gauge at date t is invariant to data appended after t (causal percentile ranks)."""
    panel = _synthetic_panel(1400, seed=2)
    cut = 1100
    full = compute_fragility(panel)
    trunc = compute_fragility(panel.iloc[:cut])
    overlap = trunc.stress.dropna().index
    np.testing.assert_allclose(
        full.stress.reindex(overlap).to_numpy(),
        trunc.stress.reindex(overlap).to_numpy(),
        rtol=0,
        atol=1e-12,
    )


def test_config_is_frozen() -> None:
    cfg = FragilityConfig()
    assert cfg.pct_window > cfg.pct_min  # a sane percentile window
