"""Demo: portfolio selection as a QUBO — exact vs simulated annealing (Q_alpha.md §15.1).

Builds a cardinality-constrained mean-variance instance and solves it two classical ways. SA
reproducing the exact optimum is the ground truth a quantum QAOA/VQE solver must match — the next
step on this same `PortfolioQUBO`. Run:  uv run python scripts/quantum_demo.py
"""

from __future__ import annotations

import time

import numpy as np

from qalpha.research import build_portfolio_qubo, solve_exact, solve_simulated_annealing


def main() -> int:
    rng = np.random.default_rng(7)
    n, k = 14, 5
    mu = rng.normal(0.12, 0.06, n)
    a = rng.normal(0.0, 1.0, (n, n))
    cov = a @ a.T / n  # symmetric PSD covariance

    qubo = build_portfolio_qubo(mu, cov, k)
    print(f"Portfolio-selection QUBO: choose {k} of {n} names (energy = xᵀQx + offset)\n")

    t0 = time.perf_counter()
    xe, ee = solve_exact(qubo)
    te = time.perf_counter() - t0

    t0 = time.perf_counter()
    xs, es = solve_simulated_annealing(qubo)
    ts = time.perf_counter() - t0

    picks_e = sorted(int(i) for i in np.where(xe)[0])
    picks_s = sorted(int(i) for i in np.where(xs)[0])
    print(f"exact      : energy {ee:+.4f}  picks {picks_e}  ({te * 1000:.0f} ms, enumerated 2^{n})")
    print(f"annealing  : energy {es:+.4f}  picks {picks_s}  ({ts * 1000:.0f} ms)")

    gap = es - ee
    verdict = "✓ matched the exact optimum" if abs(gap) < 1e-6 else "near-optimal"
    print(f"\nSA optimality gap: {gap:+.6f}  →  {verdict}")
    print(
        "Next: solve the same QUBO with QAOA/VQE (qiskit-aer) and benchmark against these baselines."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
