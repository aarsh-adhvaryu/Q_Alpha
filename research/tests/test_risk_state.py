"""HMM risk-state sanity: it must recover a known synthetic HMM and never look ahead.

Mirrors the LPPLS discipline (recover a synthetic ground truth → a found signal is the model
working, not a fitting artifact). The no-look-ahead test is the load-bearing one for an HMM: it
proves the walk-forward signal at date t is invariant to data after t.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("hmmlearn", reason="research extra: uv sync --extra research")

from research.regime.risk_state import (
    VOL_COL,
    RiskStateConfig,
    fit_hmm,
    fit_predict_walkforward,
    make_features,
)


def _synthetic_two_state_series(n: int, seed: int = 0) -> np.ndarray:
    """A close-price series from a known 2-state HMM: a calm low-vol state and a stress high-vol one.

    Returns the price path; ``make_features`` will rediscover return/vol/drawdown that the HMM splits
    back into the two regimes.
    """
    rng = np.random.default_rng(seed)
    # sticky regimes: stay-probabilities 0.98 / 0.95
    trans = np.array([[0.98, 0.02], [0.05, 0.95]])
    mu = np.array([0.0006, -0.0015])  # calm drifts up, stress drifts down
    sig = np.array([0.006, 0.030])  # stress is 5x as volatile
    state = 0
    rets = np.empty(n)
    for t in range(n):
        if rng.random() >= trans[state, state]:  # leave the current regime
            state = 1 - state
        rets[t] = rng.normal(mu[state], sig[state])
    return 100.0 * np.exp(np.cumsum(rets))


def test_recovers_synthetic_hmm_regimes() -> None:
    """Fit recovers the two regimes: the stress state has materially higher return-volatility."""
    close = _synthetic_two_state_series(3000, seed=1)
    feats = make_features(close)
    model, stress_idx = fit_hmm(feats, RiskStateConfig(n_states=2))

    # the labelled stress state must be the higher-variance state on the return feature
    variances = np.stack([np.diag(c) for c in model.covars_])
    calm_idx = 1 - stress_idx
    assert variances[stress_idx, VOL_COL] > variances[calm_idx, VOL_COL]
    # and the stress state's mean return is below the calm state's (it drifts down)
    assert model.means_[stress_idx, 0] < model.means_[calm_idx, 0]


def test_walkforward_is_not_look_ahead() -> None:
    """The signal at date t must not change when future data is appended — the HMM cannot peek.

    Run on a truncated series and the full series; within a shared epoch (same refit point, same
    forward pass from 0) the filtered P(stress) must be bit-for-bit identical on the overlap.
    """
    close = _synthetic_two_state_series(1400, seed=2)
    cfg = RiskStateConfig()  # min_train=504, refit_every=252 → refits at 504, 756, 1008, 1260
    cut = 900  # lands inside the epoch that starts at refit 756 (next refit is 1008)

    full = fit_predict_walkforward(close, cfg)
    trunc = fit_predict_walkforward(close[:cut], cfg)

    # dates [756, 900) belong to the same epoch in both runs (model fit at 756, forward pass from 0)
    lo, hi = 756, cut
    np.testing.assert_allclose(full.p_stress[lo:hi], trunc.p_stress[lo:hi], rtol=0, atol=1e-12)


def test_warmup_is_silent_and_signal_in_unit_interval() -> None:
    close = _synthetic_two_state_series(1200, seed=3)
    cfg = RiskStateConfig()
    res = fit_predict_walkforward(close, cfg)
    assert np.all(np.isnan(res.p_stress[: cfg.min_train]))  # no signal before min_train
    sig = res.p_stress[cfg.min_train :]
    assert np.all((sig >= 0.0) & (sig <= 1.0))  # a probability
