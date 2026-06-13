# Quantum solver benchmark — portfolio selection QUBO

_Exact enumeration vs simulated annealing vs **QAOA** (qiskit statevector sim) on the same cardinality-constrained mean-variance QUBO (Q_alpha.md §15.1). `gap` = solver energy − exact optimum (0 = found the optimum; lower is better). This measures **solver quality**, not portfolio returns._

| n | k | exact energy | SA gap | SA time | QAOA gap | QAOA time |
|---|---|---|---|---|---|---|
| 4 | 2 | +2.2112 | +0.0000 | 754 ms | +0.0000 | 3.4 s |
| 6 | 2 | +0.1676 | +0.0000 | 868 ms | +0.0000 | 10.7 s |
| 8 | 3 | +1.0913 | +0.0000 | 851 ms | +0.0105 | 73.0 s |

**QAOA matched the exact optimum on 2/3 instances** (depth p=2, COBYLA ≤100 iters). It is a heuristic — no optimality guarantee — so the gap is reported, not assumed. Exact enumeration is O(2ⁿ) and stops being feasible past n≈22; QAOA and SA are the scalable routes, and SA is the classical bar a quantum advantage must beat.

**Scaling wall (measured once, n=10, k=3):** QAOA took **~12 minutes** and **missed the optimum by +0.20** (vs SA's 0.00 in <1 s). On a statevector simulator the cost is the classical angle-optimisation loop, and deeper/wider circuits need more iterations to converge — the honest NISQ-era reality. SA stays exact and instant here; QAOA's interest is as a *method* (and on future hardware), not a present-day speed/quality win.

_Honest scope: this validates the quantum **solver**. Whether QUBO-based selection improves the **strategy** is a separate question that requires a walk-forward backtest vs the shrink weighting and 1/N, net of cost+tax — and the literature/our own results suggest it likely won't beat the robust baseline._
