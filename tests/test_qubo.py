"""QUBO portfolio-selection tests: cardinality, exact optimum, and SA matching exact (no network).

These are the classical ground truth a quantum (QAOA/VQE) solver must reproduce (Q_alpha.md §15.1).
"""

from __future__ import annotations

import numpy as np

from qalpha.research.qubo import build_portfolio_qubo, qubo_energy
from qalpha.research.solvers import solve_exact, solve_simulated_annealing


def _instance(n: int = 8, k: int = 3, seed: int = 0) -> tuple[np.ndarray, np.ndarray, int]:
    rng = np.random.default_rng(seed)
    mu = rng.normal(0.10, 0.05, n)
    a = rng.normal(0.0, 1.0, (n, n))
    cov = a @ a.T / n  # symmetric PSD
    return mu, cov, k


def test_exact_optimum_respects_cardinality() -> None:
    mu, cov, k = _instance(n=9, k=3)
    qubo = build_portfolio_qubo(mu, cov, k)
    x, _ = solve_exact(qubo)
    assert int(x.sum()) == k  # the penalty forces exactly k names selected


def test_single_pick_prefers_high_return_low_risk() -> None:
    mu = np.array([0.20, 0.10])
    cov = np.array([[0.04, 0.0], [0.0, 0.09]])
    qubo = build_portfolio_qubo(mu, cov, 1, risk_aversion=1.0)
    x, _ = solve_exact(qubo)
    assert x.tolist() == [1, 0]  # higher return AND lower variance → asset 0


def test_simulated_annealing_matches_exact() -> None:
    mu, cov, k = _instance(n=8, k=4, seed=2)
    qubo = build_portfolio_qubo(mu, cov, k)
    _, e_exact = solve_exact(qubo)
    x_sa, e_sa = solve_simulated_annealing(qubo, seed=1)
    assert int(x_sa.sum()) == k
    assert e_sa >= e_exact - 1e-9  # exact is the global minimum; SA cannot beat it
    assert abs(e_sa - e_exact) < 1e-6  # and on this small instance it finds it


def test_energy_is_consistent_with_solver() -> None:
    mu, cov, k = _instance(n=7, k=2, seed=3)
    qubo = build_portfolio_qubo(mu, cov, k)
    x, e = solve_exact(qubo)
    assert abs(qubo_energy(qubo, x) - e) < 1e-9
