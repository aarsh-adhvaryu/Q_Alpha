"""risk_state.py — HMM market-regime risk-state for the Nifty 50 (regime track, Sprint 1).

The LPPLS negative ([PREREGISTRATION.md]) showed Nifty large-cap drawdowns are driven by rich
valuation + macro/vol *regimes*, not parabolic singularities. This module models that mechanism: a
Gaussian Hidden Markov Model over index features (log-return, trailing realised volatility,
drawdown-from-high) whose latent states are persistent market regimes — calm vs. stress. The
filtered probability of the stress state is the **risk-state** signal a defensive overlay can act on.

**No look-ahead — the load-bearing rule (see PREREGISTRATION_riskstate.md).** An HMM's *smoothed*
posterior P(state_t | all data) peeks at the future and is forbidden here. We use only the
**filtered** posterior P(state_t | data ≤ t): the model is re-fit on an expanding window ≤ the refit
date, and the signal at date t comes from a scaled forward recursion that consumes observations only
up to t. ``fit_predict_walkforward`` is the honest, walk-forward object; ``fit_hmm`` exists for the
synthetic-recovery test and in-sample inspection only.

State labelling is mechanical, not outcome-fitted: "stress" := the state with the highest fitted
mean on the *volatility* feature, decided from the model parameters alone — never by which state
happened to line up with a known crash.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from hmmlearn.hmm import GaussianHMM

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int_]

# Column order of the feature matrix produced by ``make_features``.
RET_COL = 0
VOL_COL = 1  # the stress marker — labelling keys off this column
DD_COL = 2


# --------------------------------------------------------------------------------------------------
# Features (all causal — row t uses only data ≤ t)
# --------------------------------------------------------------------------------------------------
def _rolling_std(x: FloatArray, window: int) -> FloatArray:
    """Causal rolling std; warms up as an expanding std until ``window`` points exist."""
    out = np.empty_like(x)
    for t in range(len(x)):
        lo = max(0, t - window + 1)
        seg = x[lo : t + 1]
        out[t] = seg.std() if seg.size > 1 else 0.0
    return out


def _rolling_max(x: FloatArray, window: int) -> FloatArray:
    """Causal rolling max; expanding until ``window`` points exist."""
    out = np.empty_like(x)
    for t in range(len(x)):
        lo = max(0, t - window + 1)
        out[t] = x[lo : t + 1].max()
    return out


def make_features(close: FloatArray, vol_window: int = 21, dd_window: int = 252) -> FloatArray:
    """Build the (T, 3) observation matrix: [log-return, trailing realised vol, drawdown-from-high].

    Every row is causal: it is a function of ``close`` up to and including that index only.
    """
    close = np.asarray(close, dtype=np.float64)
    log_close = np.log(close)
    ret: FloatArray = np.diff(log_close, prepend=log_close[0])  # ret[0] = 0
    vol = _rolling_std(ret, vol_window)
    dd = close / _rolling_max(close, dd_window) - 1.0
    return np.column_stack([ret, vol, dd]).astype(np.float64)


# --------------------------------------------------------------------------------------------------
# HMM fitting + the no-look-ahead filtered posterior
# --------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class RiskStateConfig:
    """Knobs for the walk-forward risk-state. Defaults chosen a priori, tuned only on 2012–2019."""

    n_states: int = 2
    vol_window: int = 21
    dd_window: int = 252
    refit_every: int = 252  # re-fit the HMM annually (trading days)
    min_train: int = 504  # ≥2y of data before the first signal is emitted
    n_iter: int = 200
    seed: int = 0


@dataclass(frozen=True)
class RiskStateResult:
    """Walk-forward risk-state. ``p_stress``/``state`` are NaN/-1 during the warmup (< min_train)."""

    p_stress: FloatArray  # filtered P(stress | data ≤ t)
    state: IntArray  # argmax of the filtered posterior (−1 in warmup)
    refit_points: IntArray  # indices at which the HMM was re-fit (audit trail)


def _gaussian_log_emission(x: FloatArray, means: FloatArray, variances: FloatArray) -> FloatArray:
    """Per-frame diagonal-Gaussian log-likelihood. Returns (T, K) log N(x_t | μ_k, diag σ²_k)."""
    # x: (T, F)  means/variances: (K, F)  ->  (T, K)
    var = np.clip(variances, 1e-12, None)
    diff = x[:, None, :] - means[None, :, :]  # (T, K, F)
    log_norm = -0.5 * (np.log(2.0 * np.pi * var) + diff**2 / var)  # (T, K, F)
    return log_norm.sum(axis=2).astype(np.float64)


def _forward_filter(
    framelogprob: FloatArray, startprob: FloatArray, transmat: FloatArray
) -> FloatArray:
    """Scaled forward algorithm → filtered posterior P(state_t | obs_{0..t}), shape (T, K).

    Renormalising every step keeps it numerically stable over long series while using only past and
    present observations — this is exactly the no-look-ahead guarantee (cf. the smoothed posterior,
    which would also fold in future frames).
    """
    n, k = framelogprob.shape
    filtered = np.empty((n, k), dtype=np.float64)
    # work in probability space per step, rescaled by the row max for stability
    emis = np.exp(framelogprob - framelogprob.max(axis=1, keepdims=True))
    alpha = startprob * emis[0]
    alpha /= alpha.sum()
    filtered[0] = alpha
    for t in range(1, n):
        alpha = (alpha @ transmat) * emis[t]
        alpha /= alpha.sum()
        filtered[t] = alpha
    return filtered


def fit_hmm(features: FloatArray, config: RiskStateConfig | None = None) -> tuple[GaussianHMM, int]:
    """Fit a diagonal Gaussian HMM in-sample and return (model, stress_state_index).

    For the synthetic-recovery test and inspection only — NOT walk-forward. Standardises features by
    their own (full-sample) mean/std purely for optimiser conditioning.
    """
    cfg = config or RiskStateConfig()
    mu = features.mean(axis=0)
    sd = features.std(axis=0)
    sd[sd == 0] = 1.0
    x = (features - mu) / sd
    model = GaussianHMM(
        n_components=cfg.n_states,
        covariance_type="diag",
        n_iter=cfg.n_iter,
        random_state=cfg.seed,
    )
    model.fit(x)
    stress_idx = int(np.argmax(model.means_[:, VOL_COL]))  # highest-vol state = stress
    return model, stress_idx


def fit_predict_walkforward(
    close: FloatArray, config: RiskStateConfig | None = None
) -> RiskStateResult:
    """The honest object: walk-forward, filtered (no-look-ahead) P(stress) for each date.

    The HMM is re-fit on an expanding window every ``refit_every`` days (first fit at ``min_train``).
    Within each epoch the signal is the filtered posterior under that epoch's model, computed by a
    forward pass that consumes observations only up to the decision date. The feature scaler is fit
    on the training window alone, so nothing known only in the future touches the decision at date t.
    """
    cfg = config or RiskStateConfig()
    features = make_features(close, cfg.vol_window, cfg.dd_window)
    n = len(features)
    p_stress = np.full(n, np.nan, dtype=np.float64)
    state = np.full(n, -1, dtype=np.int_)
    refits: list[int] = list(range(cfg.min_train, n, cfg.refit_every))

    for i, rp in enumerate(refits):
        epoch_end = refits[i + 1] if i + 1 < len(refits) else n
        train = features[:rp]  # data strictly before the decision dates of this epoch
        mu = train.mean(axis=0)
        sd = train.std(axis=0)
        sd[sd == 0] = 1.0

        model = GaussianHMM(
            n_components=cfg.n_states,
            covariance_type="diag",
            n_iter=cfg.n_iter,
            random_state=cfg.seed,
        )
        model.fit((train - mu) / sd)
        stress_idx = int(np.argmax(model.means_[:, VOL_COL]))
        variances = np.stack([np.diag(c) for c in model.covars_]).astype(np.float64)

        # forward-filter from index 0 to the end of this epoch under the (frozen) epoch model,
        # then read off only this epoch's decision dates [rp, epoch_end).
        x_all = (features[:epoch_end] - mu) / sd
        framelogprob = _gaussian_log_emission(x_all, model.means_.astype(np.float64), variances)
        filtered = _forward_filter(
            framelogprob, model.startprob_.astype(np.float64), model.transmat_.astype(np.float64)
        )
        p_stress[rp:epoch_end] = filtered[rp:epoch_end, stress_idx]
        state[rp:epoch_end] = filtered[rp:epoch_end].argmax(axis=1)

    return RiskStateResult(
        p_stress=p_stress, state=state, refit_points=np.asarray(refits, dtype=np.int_)
    )
