"""QAOA solver tests — skipped unless the optional ``quantum`` extra is installed.

QAOA is a heuristic with no optimality guarantee, so these check the *contract* (a feasible binary
selection whose energy never beats the exact optimum), not a fixed quality bar. Solver quality is
demonstrated by ``scripts/quantum_benchmark.py`` instead.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("qiskit_optimization")  # skip cleanly when the quantum extra isn't installed

from qalpha.research.qaoa import solve_qaoa
from qalpha.research.qubo import build_portfolio_qubo, qubo_energy
from qalpha.research.solvers import solve_exact


def _instance(n: int = 5, k: int = 2, seed: int = 0) -> tuple[np.ndarray, np.ndarray, int]:
    rng = np.random.default_rng(seed)
    mu = rng.normal(0.10, 0.05, n)
    a = rng.normal(0.0, 1.0, (n, n))
    return mu, a @ a.T / n, k


def test_qaoa_returns_a_feasible_binary_selection() -> None:
    mu, cov, k = _instance()
    qubo = build_portfolio_qubo(mu, cov, k)
    x, energy = solve_qaoa(qubo, reps=2, maxiter=60)
    assert x.shape == (qubo.n,)
    assert {int(v) for v in x} <= {0, 1}
    assert abs(qubo_energy(qubo, x) - energy) < 1e-9  # returned energy matches the selection


def test_qaoa_never_beats_the_exact_optimum() -> None:
    mu, cov, k = _instance(n=5, k=2, seed=3)
    qubo = build_portfolio_qubo(mu, cov, k)
    _, ee = solve_exact(qubo)
    _, eq = solve_qaoa(qubo, reps=2, maxiter=80)
    assert eq >= ee - 1e-9  # exact enumeration is the global minimum
