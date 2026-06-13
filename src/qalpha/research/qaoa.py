"""QAOA solver for the portfolio-selection QUBO (Q_alpha.md §15.1) — the quantum optimiser.

Solves the **same** :class:`~qalpha.research.qubo.PortfolioQUBO` as the classical baselines, on a
quantum-circuit simulator, so it can be benchmarked head-to-head against exact enumeration and
simulated annealing. Requires the optional ``quantum`` extra (``uv sync --extra quantum``).

QAOA is variational/heuristic: it does **not** guarantee the optimum, so we always report its
optimality gap vs :func:`~qalpha.research.solvers.solve_exact` rather than assume it matches. This is
the honest "does the quantum solver work, and how well does it scale" question — it is **not** a claim
that quantum improves portfolio *returns* (that would need a walk-forward backtest of the strategy).
"""

from __future__ import annotations

import numpy as np
from qiskit.primitives import StatevectorSampler
from qiskit_algorithms import QAOA
from qiskit_algorithms.optimizers import COBYLA
from qiskit_optimization import QuadraticProgram
from qiskit_optimization.algorithms import MinimumEigenOptimizer

from qalpha.research.qubo import IntArray, PortfolioQUBO, qubo_energy


def _to_quadratic_program(qubo: PortfolioQUBO) -> QuadraticProgram:
    """Map ``energy(x) = xᵀQx + offset`` to a qiskit ``QuadraticProgram`` (diagonal → linear)."""
    n = qubo.n
    q = qubo.matrix
    qp = QuadraticProgram()
    for i in range(n):
        qp.binary_var(f"x{i}")
    linear = {f"x{i}": float(q[i, i]) for i in range(n)}  # xᵢ² = xᵢ for binary, so diag is linear
    quadratic = {
        (f"x{i}", f"x{j}"): float(2.0 * q[i, j]) for i in range(n) for j in range(i + 1, n)
    }
    qp.minimize(constant=float(qubo.offset), linear=linear, quadratic=quadratic)
    return qp


def solve_qaoa(
    qubo: PortfolioQUBO,
    *,
    reps: int = 2,
    maxiter: int = 100,
    seed: int = 0,
) -> tuple[IntArray, float]:
    """Solve the QUBO with QAOA on a statevector simulator. Returns ``(selection, energy)``.

    ``reps`` is the QAOA circuit depth p (more = more expressive, more parameters to optimise);
    ``maxiter`` caps the classical COBYLA outer loop optimising the circuit angles.
    """
    qp = _to_quadratic_program(qubo)
    qaoa = QAOA(
        sampler=StatevectorSampler(seed=seed),
        optimizer=COBYLA(maxiter=maxiter),
        reps=reps,
    )
    result = MinimumEigenOptimizer(qaoa).solve(qp)
    x = np.asarray(result.x, dtype=np.int_)
    return x, qubo_energy(qubo, x)
