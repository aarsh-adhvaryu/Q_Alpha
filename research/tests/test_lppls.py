"""LPPLS fitter sanity: it must recover a known synthetic bubble and stay quiet on a random walk."""

from __future__ import annotations

import numpy as np

from research.regime.lppls import (
    confidence_indicator,
    fit_lppls,
    lppls_filter_ok,
)


def _synthetic_bubble(n: int, tc: float, m: float, omega: float) -> np.ndarray:
    """Generate a clean positive-bubble log-price series with known parameters (B<0)."""
    t = np.arange(n, dtype=np.float64)
    dt = tc - t
    # Strong power-law trend, modest oscillation → passes the Bothmer–Meister damping filter.
    a, b, c1, c2 = 9.0, -0.1, 0.003, 0.003
    log_p = (
        a + b * dt**m + dt**m * (c1 * np.cos(omega * np.log(dt)) + c2 * np.sin(omega * np.log(dt)))
    )
    return log_p


def test_recovers_synthetic_bubble_tc() -> None:
    n, true_tc, m, omega = 250, 270.0, 0.5, 9.0
    log_p = _synthetic_bubble(n, true_tc, m, omega)
    fit = fit_lppls(log_p, n_starts=6, seed=1)
    # tc should land near the true critical time (within a few % of the window).
    assert abs(fit.tc - true_tc) < 0.1 * n
    assert fit.is_positive_bubble
    assert lppls_filter_ok(fit)


def test_random_walk_rarely_qualifies() -> None:
    rng = np.random.default_rng(42)
    # A driftless random walk is not a bubble; confidence should be low.
    log_p = np.cumsum(rng.normal(0, 0.01, size=400)) + 9.0
    conf = confidence_indicator(log_p, min_window=60, max_window=300, step=40, n_starts=2)
    assert conf <= 0.5
