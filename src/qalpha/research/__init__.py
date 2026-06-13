"""Research track (Q_alpha.md §15) — quantum & advanced optimisation, gated out of production.

Portfolio *selection* (which K of N names to hold) is a binary quadratic problem, so it maps onto a
QUBO and thus onto quantum optimisers (QAOA/VQE/annealing). This package formulates that QUBO and
provides classical baselines (exact enumeration + simulated annealing) to validate any quantum
solver against — the spec's §15.1 discipline: prove it on classical baselines before claiming a
quantum edge, and keep it research-only until an AUM threshold justifies it.
"""

from qalpha.research.qubo import PortfolioQUBO, build_portfolio_qubo, qubo_energy
from qalpha.research.solvers import solve_exact, solve_simulated_annealing

__all__ = [
    "PortfolioQUBO",
    "build_portfolio_qubo",
    "qubo_energy",
    "solve_exact",
    "solve_simulated_annealing",
]
