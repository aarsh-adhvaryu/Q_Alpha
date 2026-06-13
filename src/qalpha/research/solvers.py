"""Classical QUBO solvers — the ground truth for the quantum track (Q_alpha.md §15.1).

* ``solve_exact`` — brute-force enumeration of all 2ⁿ selections. The optimum, feasible only for
  small ``n`` (≲ 20), but the gold standard a quantum (QAOA/VQE) result must reproduce.
* ``solve_simulated_annealing`` — a metaheuristic that scales past brute force; the *classical*
  competitor a quantum solver has to beat to claim any advantage.

A quantum solver (next step: QAOA on the same ``PortfolioQUBO.matrix``) plugs in here as a third
``solve_*`` returning the same ``(selection, energy)`` contract.
"""

from __future__ import annotations

from itertools import product

import numpy as np

from qalpha.research.qubo import IntArray, PortfolioQUBO, qubo_energy


def solve_exact(qubo: PortfolioQUBO) -> tuple[IntArray, float]:
    """Global optimum by enumerating all 2ⁿ binary vectors. Raises if ``n`` is too large."""
    n = qubo.n
    if n > 22:
        raise ValueError(f"exact enumeration is infeasible for n={n} (2^n); use annealing")
    best_x = np.zeros(n, dtype=np.int_)
    best_e = float("inf")
    for bits in product((0, 1), repeat=n):
        x = np.array(bits, dtype=np.int_)
        e = qubo_energy(qubo, x)
        if e < best_e:
            best_e, best_x = e, x
    return best_x, best_e


def _temperature_scale(qubo: PortfolioQUBO, rng: np.random.Generator) -> float:
    """Typical |ΔE| of a single bit flip — sets the starting temperature so early moves are accepted.

    Without this, a large cardinality penalty dwarfs any fixed temperature and the annealer freezes
    at the wrong cardinality. Scaling to the problem keeps SA robust across instances.
    """
    x = rng.integers(0, 2, size=qubo.n).astype(np.int_)
    e = qubo_energy(qubo, x)
    deltas = []
    for i in range(qubo.n):
        x[i] ^= 1
        deltas.append(abs(qubo_energy(qubo, x) - e))
        x[i] ^= 1
    return max(float(np.mean(deltas)), 1e-9)


def solve_simulated_annealing(
    qubo: PortfolioQUBO,
    *,
    steps: int = 20_000,
    restarts: int = 8,
    seed: int = 0,
) -> tuple[IntArray, float]:
    """Single-bit-flip simulated annealing with geometric cooling and random restarts.

    The temperature schedule auto-scales to the QUBO (see :func:`_temperature_scale`) so the
    cardinality penalty doesn't freeze the search.
    """
    rng = np.random.default_rng(seed)
    n = qubo.n
    t_start = _temperature_scale(qubo, rng)
    t_end = t_start * 1e-4
    cooling = (t_end / t_start) ** (1.0 / max(steps - 1, 1))

    best_x = np.zeros(n, dtype=np.int_)
    best_e = float("inf")
    for _ in range(restarts):
        x = rng.integers(0, 2, size=n).astype(np.int_)
        e = qubo_energy(qubo, x)
        temp = t_start
        for _ in range(steps):
            i = int(rng.integers(0, n))
            x[i] ^= 1
            e_new = qubo_energy(qubo, x)
            if e_new <= e or rng.random() < np.exp((e - e_new) / max(temp, 1e-12)):
                e = e_new
            else:
                x[i] ^= 1  # reject: flip back
            if e < best_e:
                best_e, best_x = e, x.copy()
            temp *= cooling
    return best_x, best_e
