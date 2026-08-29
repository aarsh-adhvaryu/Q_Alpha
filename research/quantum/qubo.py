"""Portfolio selection as a QUBO (Q_alpha.md §15.1).

Pick a subset of ``k`` names from ``n`` candidates that minimises risk net of expected return,
with a cardinality constraint — the binary (hold / don't-hold) cousin of the continuous optimiser.
With ``x ∈ {0,1}^n`` the objective is

    minimise   q · xᵀΣx  −  μᵀx  +  P · (1ᵀx − k)²

— risk aversion ``q`` times portfolio variance, minus expected return, plus a penalty ``P`` that
enforces "exactly ``k`` selected". Because ``xᵢ² = xᵢ`` for binary ``x``, every linear term folds
onto the diagonal, giving a single symmetric matrix ``Q`` with ``energy(x) = xᵀQx + const``. That
matrix is exactly what a QAOA/VQE circuit or a quantum annealer ingests — so this formulation is the
bridge from the classical optimiser to the quantum solvers, and the classical solvers in
``solvers.py`` are the ground truth any quantum result must match.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int_]


@dataclass(frozen=True)
class PortfolioQUBO:
    """A QUBO instance: ``energy(x) = xᵀ Q x + offset`` over binary ``x``."""

    matrix: FloatArray  # symmetric (n, n)
    offset: float
    k: int  # target cardinality (for reference / decoding)

    @property
    def n(self) -> int:
        return int(self.matrix.shape[0])


def build_portfolio_qubo(
    expected_returns: FloatArray,
    covariance: FloatArray,
    k: int,
    *,
    risk_aversion: float = 1.0,
    penalty: float | None = None,
) -> PortfolioQUBO:
    """Build the cardinality-constrained mean-variance QUBO.

    ``penalty`` defaults to a value large enough to dominate the objective so the cardinality
    constraint is (almost) always satisfied at the optimum: a few times the largest objective scale.
    """
    mu = np.asarray(expected_returns, dtype=np.float64)
    sigma = np.asarray(covariance, dtype=np.float64)
    n = mu.shape[0]
    if sigma.shape != (n, n):
        raise ValueError(f"covariance must be ({n},{n}), got {sigma.shape}")
    if not 1 <= k <= n:
        raise ValueError(f"k must be in [1, {n}], got {k}")

    if penalty is None:
        scale = risk_aversion * float(np.abs(sigma).sum()) + float(np.abs(mu).sum())
        penalty = 2.0 * scale + 1.0

    # Quadratic part: risk + the penalty's all-pairs term P·(1ᵀx)² = P·xᵀ(11ᵀ)x.
    q = risk_aversion * sigma + penalty * np.ones((n, n), dtype=np.float64)
    # Linear part (onto the diagonal, since xᵢ²=xᵢ): −return and the penalty's −2Pk·1ᵀx.
    q = q + np.diag(-mu - 2.0 * penalty * k)
    q = 0.5 * (q + q.T)  # symmetrise (defensive; inputs should already be symmetric)
    offset = penalty * k * k
    return PortfolioQUBO(matrix=q, offset=offset, k=k)


def qubo_energy(qubo: PortfolioQUBO, x: IntArray) -> float:
    """Energy of a binary selection vector ``x`` under the QUBO (lower is better)."""
    xf = np.asarray(x, dtype=np.float64)
    return float(xf @ qubo.matrix @ xf) + qubo.offset
