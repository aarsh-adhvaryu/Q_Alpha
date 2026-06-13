"""Solver-quality benchmark: exact vs simulated annealing vs QAOA on the portfolio QUBO (§15.1).

The honest question for the quantum track: *does the quantum solver actually work, and how does it
scale* — measured as optimality gap vs the exact optimum, plus runtime, across instance sizes. This
is a solver benchmark, NOT a claim that quantum improves portfolio returns (that needs a walk-forward
backtest of the strategy). Writes a committable report. Requires the quantum extra:

    uv run --extra quantum python scripts/quantum_benchmark.py
"""

from __future__ import annotations

import time
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from qalpha.research.qaoa import solve_qaoa
from qalpha.research.qubo import build_portfolio_qubo
from qalpha.research.solvers import solve_exact, solve_simulated_annealing

warnings.filterwarnings("ignore")  # silence qiskit-optimization's scipy-sparse warnings

REPORT = Path("reports/quantum_benchmark.md")
# Kept ≤ 8 so the benchmark re-runs in ~75 s. n=10 was measured once (see the scaling note in the
# report): QAOA took ~12 min and missed the optimum by 0.20 — the NISQ-era simulator/optimiser wall.
SIZES = [(4, 2), (6, 2), (8, 3)]


@dataclass(frozen=True)
class Row:
    n: int
    k: int
    exact_energy: float
    sa_gap: float
    sa_ms: float
    qaoa_gap: float
    qaoa_s: float


def _instance(n: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    mu = rng.normal(0.12, 0.06, n)
    a = rng.normal(0.0, 1.0, (n, n))
    return mu, a @ a.T / n


def _bench(n: int, k: int) -> Row:
    mu, cov = _instance(n, seed=n)
    qubo = build_portfolio_qubo(mu, cov, k)

    _, ee = solve_exact(qubo)
    t = time.perf_counter()
    _, es = solve_simulated_annealing(qubo, seed=1)
    sa_ms = (time.perf_counter() - t) * 1000
    t = time.perf_counter()
    _, eq = solve_qaoa(qubo, reps=2, maxiter=100)
    qaoa_s = time.perf_counter() - t

    return Row(n, k, ee, es - ee, sa_ms, eq - ee, qaoa_s)


def _markdown(rows: list[Row]) -> str:
    out = [
        "# Quantum solver benchmark — portfolio selection QUBO",
        "",
        "_Exact enumeration vs simulated annealing vs **QAOA** (qiskit statevector sim) on the same "
        "cardinality-constrained mean-variance QUBO (Q_alpha.md §15.1). `gap` = solver energy − exact "
        "optimum (0 = found the optimum; lower is better). This measures **solver quality**, not "
        "portfolio returns._",
        "",
        "| n | k | exact energy | SA gap | SA time | QAOA gap | QAOA time |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        out.append(
            f"| {r.n} | {r.k} | {r.exact_energy:+.4f} | {r.sa_gap:+.4f} | {r.sa_ms:.0f} ms "
            f"| {r.qaoa_gap:+.4f} | {r.qaoa_s:.1f} s |"
        )
    matched = sum(1 for r in rows if abs(r.qaoa_gap) < 1e-6)
    out += [
        "",
        f"**QAOA matched the exact optimum on {matched}/{len(rows)} instances** "
        "(depth p=2, COBYLA ≤100 iters). It is a heuristic — no optimality guarantee — so the gap is "
        "reported, not assumed. Exact enumeration is O(2ⁿ) and stops being feasible past n≈22; QAOA "
        "and SA are the scalable routes, and SA is the classical bar a quantum advantage must beat.",
        "",
        "**Scaling wall (measured once, n=10, k=3):** QAOA took **~12 minutes** and **missed the "
        "optimum by +0.20** (vs SA's 0.00 in <1 s). On a statevector simulator the cost is the "
        "classical angle-optimisation loop, and deeper/wider circuits need more iterations to "
        "converge — the honest NISQ-era reality. SA stays exact and instant here; QAOA's interest is "
        "as a *method* (and on future hardware), not a present-day speed/quality win.",
        "",
        "_Honest scope: this validates the quantum **solver**. Whether QUBO-based selection improves "
        "the **strategy** is a separate question that requires a walk-forward backtest vs the shrink "
        "weighting and 1/N, net of cost+tax — and the literature/our own results suggest it likely "
        "won't beat the robust baseline._",
    ]
    return "\n".join(out) + "\n"


def main() -> int:
    rows = []
    for n, k in SIZES:
        row = _bench(n, k)
        rows.append(row)
        print(
            f"n={row.n:>2} k={row.k}: exact {row.exact_energy:+.4f} | "
            f"SA gap {row.sa_gap:+.4f} ({row.sa_ms:.0f} ms) | "
            f"QAOA gap {row.qaoa_gap:+.4f} ({row.qaoa_s:.1f} s)"
        )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(_markdown(rows))
    print(f"\n✓ Report written to {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
