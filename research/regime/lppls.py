"""LPPLS — Log-Periodic Power Law Singularity (Sornette) bubble detector.

A *positive bubble* is faster-than-exponential price growth decorated with accelerating
log-periodic oscillations, heading toward a critical time ``tc`` at which the regime ends (a crash
or a sharp change of regime). The model for the log-price is:

    ln p(t) = A + B (tc - t)^m + C (tc - t)^m cos(ω ln(tc - t) - φ)

We use the **Filimonov–Sornette** reformulation: expand the cosine so the 4 *linear* parameters
(A, B, C1, C2) are solved exactly by least squares for any given triple of *nonlinear* parameters
(tc, m, ω). That reduces the hard search from 7 dimensions to 3 and removes the notoriously unstable
phase φ. See Filimonov & Sornette (2013), "A stable and robust calibration scheme for the LPPLS".

Single fits are unstable by design — the **confidence indicator** (Sornette et al.) is the honest
object: fit over many window lengths ending at the same "present" date and report the *fraction* of
fits that qualify as a bubble under standard filter conditions. High fraction ⇒ bubble regime.

This module is data-agnostic: it takes a log-price array. No look-ahead — a fit at index t2 uses
only data up to t2 (``tc`` may lie beyond t2; that is the forecast horizon, not look-ahead).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from scipy.optimize import minimize

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True)
class LPPLSFit:
    """One LPPLS calibration over a window. ``tc``/``t`` are in index (trading-day) units."""

    tc: float
    m: float
    omega: float
    a: float
    b: float
    c1: float
    c2: float
    sse: float
    t_end: float  # last index of the fitting window (tc is measured against this)
    n: int

    @property
    def is_positive_bubble(self) -> bool:
        """B < 0 makes (tc - t)^m a rising, accelerating contribution → a positive (upward) bubble."""
        return self.b < 0.0

    @property
    def damping(self) -> float:
        """Bothmer–Meister damping  m|B| / (ω·√(C1²+C2²)).  ≥ ~1 ⇒ oscillations don't dominate."""
        c = float(np.hypot(self.c1, self.c2))
        if c == 0.0 or self.omega == 0.0:
            return np.inf
        return (self.m * abs(self.b)) / (self.omega * c)

    @property
    def tc_ahead(self) -> float:
        """How far the critical time lies beyond the window end, in trading days (can be negative)."""
        return self.tc - self.t_end


def _linear_solve(
    t: FloatArray, y: FloatArray, tc: float, m: float, omega: float
) -> tuple[float, float, float, float, float]:
    """Solve the 4 linear params (A,B,C1,C2) by least squares for fixed (tc,m,ω); return them + SSE."""
    dt = tc - t
    # tc must sit beyond the whole window; guard against domain errors.
    if np.any(dt <= 0.0):
        return 0.0, 0.0, 0.0, 0.0, np.inf
    dtm = dt**m
    log_dt = np.log(dt)
    f = dtm
    g = dtm * np.cos(omega * log_dt)
    h = dtm * np.sin(omega * log_dt)
    design = np.column_stack([np.ones_like(t), f, g, h])
    coef, _res, _rank, _sv = np.linalg.lstsq(design, y, rcond=None)
    resid = y - design @ coef
    sse = float(resid @ resid)
    a, b, c1, c2 = (float(coef[0]), float(coef[1]), float(coef[2]), float(coef[3]))
    return a, b, c1, c2, sse


def fit_lppls(
    log_price: FloatArray,
    *,
    n_starts: int = 4,
    seed: int = 0,
) -> LPPLSFit:
    """Calibrate LPPLS on a window of log-prices (index 0..n-1). Multi-start Nelder–Mead over (tc,m,ω)."""
    y = np.asarray(log_price, dtype=np.float64)
    n = y.size
    t = np.arange(n, dtype=np.float64)
    t_end = float(n - 1)

    def objective(theta: FloatArray) -> float:
        tc, m, omega = float(theta[0]), float(theta[1]), float(theta[2])
        if not (0.0 < m < 1.0) or not (1.0 < omega < 40.0) or tc <= t_end:
            return 1e18
        _a, _b, _c1, _c2, sse = _linear_solve(t, y, tc, m, omega)
        return sse

    rng = np.random.default_rng(seed)
    best: tuple[float, FloatArray] | None = None
    span = max(n, 1)
    for _ in range(n_starts):
        tc0 = t_end + rng.uniform(0.01, 0.25) * span
        m0 = rng.uniform(0.2, 0.8)
        omega0 = rng.uniform(4.0, 15.0)
        res = minimize(
            objective,
            x0=np.array([tc0, m0, omega0]),
            method="Nelder-Mead",
            options={"maxiter": 1500, "xatol": 1e-3, "fatol": 1e-9},
        )
        if best is None or res.fun < best[0]:
            best = (float(res.fun), res.x)

    assert best is not None
    tc, m, omega = float(best[1][0]), float(best[1][1]), float(best[1][2])
    a, b, c1, c2, sse = _linear_solve(t, y, tc, m, omega)
    return LPPLSFit(tc=tc, m=m, omega=omega, a=a, b=b, c1=c1, c2=c2, sse=sse, t_end=t_end, n=n)


def lppls_filter_ok(
    fit: LPPLSFit,
    *,
    m_range: tuple[float, float] = (0.1, 0.9),
    omega_range: tuple[float, float] = (2.0, 25.0),
    max_tc_ahead_frac: float = 0.2,
    min_damping: float = 0.8,
) -> bool:
    """Standard Sornette bubble-qualification filter for a single fit (positive bubble)."""
    if not fit.is_positive_bubble:
        return False
    if not (m_range[0] <= fit.m <= m_range[1]):
        return False
    if not (omega_range[0] <= fit.omega <= omega_range[1]):
        return False
    # critical time must be near/after the present, not far in the future and not in the past
    if not (-0.05 * fit.n <= fit.tc_ahead <= max_tc_ahead_frac * fit.n):
        return False
    return fit.damping >= min_damping


def confidence_indicator(
    log_price: FloatArray,
    *,
    min_window: int = 60,
    max_window: int = 500,
    step: int = 25,
    n_starts: int = 3,
) -> float:
    """DS-LPPLS confidence at the *last* point of ``log_price``.

    Fit over many window lengths all ending at the present; return the fraction passing the bubble
    filter. ∈ [0,1]; higher ⇒ stronger evidence the present sits inside a positive bubble.
    """
    y = np.asarray(log_price, dtype=np.float64)
    n = y.size
    upper = min(max_window, n)
    windows = list(range(min_window, upper + 1, step))
    if not windows:
        return 0.0
    passes = 0
    for w in windows:
        fit = fit_lppls(y[n - w :], n_starts=n_starts, seed=w)
        if lppls_filter_ok(fit):
            passes += 1
    return passes / len(windows)
