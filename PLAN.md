# Q-Alpha — Optimizer + Quantum Plan (June 2026)

**Objective:** A better portfolio optimizer, with quantum math integrated where it honestly fits.
**Discipline (unchanged):** every optimizer change must beat equal-weight 1/N **walk-forward, net
of Zerodha cost + capital-gains tax**, on a survivorship-free universe. No in-sample tuning.
**Decisions taken:** two tracks in parallel; point-in-time universe built first; GPU available but
off by default — CPU for development, GPU only for the quantum scaling experiments.

The honest framing from Phase 0: the strategy already beats Nifty 50 net of friction (16.6% vs
13.4% CAGR, Sharpe 1.06 vs 0.85) but not naive 1/N (17.7%, 1.09). Quantum methods solve the
*integer-constrained* allocation problem — real money is bought in whole shares — they do not
manufacture alpha. So Track A hunts the edge classically; Track B builds the quantum formulation
as a rigorously validated research showcase with a production trigger at ₹50L+ AUM (spec §15.1).

---

## Phase A — Survivorship-free universe (the gate) — ✅ DONE (2026-06-12)

**Outcome (honest):** universe built & validated (`data/universes/nifty50_membership.csv`, 81 names,
dead names included; `scripts/build_nifty_universe.py`). Found & fixed a **look-ahead bug in the 1/N
baseline** (front-ran future entrants → fake 22.4%; now `equal_weight_pit`). Added fair **Nifty 50
TRI** benchmark (NIFTYBEES adj-close) + §5.1 bad-tick sanitizer. **Result:** survivorship wasn't
flattering the edge (static-0a 14.6% → PIT-0a 15.2%, drawdown improved), BUT vs the fair TRI bar
(14.5%, Sharpe 0.98) the reproducible 3-factor model **loses Sharpe (0.92)** because turnover/tax
exploded (₹2.7k→₹117k) — §4.6 gate too lenient at universe scale. Real verdict needs **6-factor on
PIT** (data-blocked: fundamentals for ~75 names) + gate recalibration. This sharpens Track B. Details
in CLAUDE.md status table; reports in `reports/phase0_pit_report.md`, `phase0_static0a_report.md`.

### (original Phase A plan, for reference)

The #1 blocker on the GO verdict (§14 criterion 3) and the precondition for trusting any
optimizer comparison.

1. **Point-in-time Nifty 50 constituent table** from free sources (Wikipedia constituent-change
   history + community GitHub datasets), back to ≥2012 (2005 if cheap). Output: the CSV format
   `Universe.from_csv` already accepts (`--universe-csv` is wired in `run_phase0.py`).
2. **Pull prices for dropped names** via the existing ingest. Delisted tickers are the hard part —
   yfinance coverage will be imperfect. Policy: ingest what exists; for unpriceable dead names,
   document each one and bound the residual bias (delistings ≈0.81% of Nifty-500 mcap, so the
   bound should be small — but it must be *written down*, not assumed).
3. **Benchmark upgrade while we're in the harness:** Nifty 50 **TRI** (free from
   niftyindices.com) replaces the price index. Raises the bar ~1.5%/yr; strategy reportedly still
   clears it — verify.
4. **Re-run Phase 0** on the PIT universe + TRI benchmark. Regenerate `reports/phase0_report.md`.
   Criterion 3 flips to ✅ (or the report states exactly what residual bias remains). This may
   move the CONDITIONAL verdict — in either direction. We report what we find.

**Exit criteria:** PIT universe CSV committed; dropped-name price coverage documented; Phase 0
report regenerated with TRI benchmark; verdict updated honestly.

---

## Phase B — Track A: classical optimizer candidates vs 1/N — ~weeks 2–3

**Harness first.** One `compare_optimizers` walk-forward harness that plugs any weighting scheme
into the existing engine (same tax-aware execution, same §4.6 net-benefit gate, same costs) and
scores everything net of cost+tax against 1/N on the PIT universe. Every candidate below is one
function conforming to one interface; the harness is the judge.

Candidates, in order of expected value:

1. **Factor-tilted weighting** — use the composite alpha score at the *weighting* stage, not just
   selection. Concretely: shrink the min-variance solution toward score-proportional weights
   (tilt strength is a walk-forward-calibrated parameter), or treat scores as a heavily-shrunk
   expected-return proxy. Today the optimizer throws the ranking away after top-N selection —
   this is the most likely source of real improvement.
2. **1/N-shrinkage hybrid** — `w = α·w_model + (1−α)·w_equal`. The literature's honest answer to
   DeMiguel: if 1/N is hard to beat, anchor to it and add only as much model as validates.
3. **HRP / NCO** (hierarchical risk parity, nested clustered optimization) — no expected returns,
   robust to covariance noise, beats min-variance out-of-sample in the literature.
4. **§4.6 gate-multiplier calibration done right** — 2.0 vs 3.0 (the 0b sweep favored 3.0
   in-sample), adopted only via walk-forward validation per §6.2.

**Ship rule:** a candidate replaces the production optimizer only if it beats 1/N net of
cost+tax on the PIT universe, walk-forward, without materially worsening max drawdown or
turnover. If nothing beats 1/N, the production answer is the hybrid anchored at the validated α
(possibly α≈0 — that finding is itself valuable and gets written down, not buried).

---

## Phase C — Track B: quantum / QUBO research track — weeks 2–3, parallel

> **Moved out:** this track now lives in the separate **`Q_Alpha_Research`** repo
> (`github.com/aarsh-adhvaryu/Q_Alpha_Research`), which imports this engine as a dependency.
> The notes below are retained as the original design record.

Lives in `research/` (spec §15) — production code does not import from it. Reuses the harness
from Phase B for any walk-forward claims.

1. **Formulate the real integer problem as a QUBO.** Select exactly K stocks and whole-share lot
   sizes under: budget (₹), per-stock cap (20%), sector bounds, cardinality K. Hamiltonian =
   risk term (w'Σw on conditioned covariance) − alpha term (factor scores) + quadratic penalties
   (budget, cardinality, sector). Binary-encode share counts (log encoding keeps qubit counts
   sane). This extends the spec's §15.1 sketch to the *actual* production constraints.
2. **Classical baselines (the truth-tellers):**
   - exact enumeration where feasible (choose 10 of 24 ≈ 2M combos — enumerable; gives the true
     integer optimum),
   - simulated annealing on the same QUBO,
   - the current scipy continuous solution + greedy whole-share rounding.
3. **Quantum solvers:** QAOA and VQE via Qiskit + Aer simulator. CPU for development and all
   instances ≤ ~20 qubits; flip the studio GPU on for cuQuantum-accelerated Aer
   (`AerSimulator(device="GPU")`) only for the scaling experiments beyond that. (Optional
   stretch: one small instance on IBM Quantum's free tier for a real-hardware data point.)
4. **The deliverable is a validation report**, not a demo: (a) how big the integer-vs-rounding
   gap actually is in ₹ at ₹2L and at ₹50L AUM (this is the number that justifies — or kills —
   the §15.1 production trigger); (b) where QAOA/VQE matches the exact optimum and where it
   degrades vs simulated annealing; (c) qubit/depth scaling story. Honesty rule: at these sizes
   classical solvers will win on wall-clock — the value is the formulation, the validation
   rigor, and the scaling narrative.
5. **Production hook, gated:** define the optimizer backend interface so a QUBO backend is a
   swap (spec's "one backend swap activates the quantum pipeline"), but wire it only if the
   report shows the integer solution measurably beats rounding in walk-forward.

---

## Phase D — Integration + verdict — end of week 3/4

- Promote the Track A winner (or the validated hybrid) to `src/qalpha/alloc/`.
- Full Phase 0 re-run: PIT universe, TRI benchmark, winning optimizer. Regenerate the go/no-go
  report; update CLAUDE.md (results table, brainstorm section, §14 scorecard).
- All four gates green (ruff, ruff-format, mypy strict, pytest) at every commit, as always.

## Risks, stated up front

- **1/N may survive.** DeMiguel et al. is a robust result. The fallback (shrinkage hybrid + the
  tax-aware gate that is already the system's real edge) is still a defensible production
  optimizer. We do not torture parameters until 1/N loses — iron rule.
- **Delisted-price coverage** will be incomplete; the report bounds the bias rather than hiding it.
- **PIT re-run may weaken the current verdict.** If beating Nifty was partly survivorship, we
  want to know now, not at Phase 5 paper trading.
- **Quantum solvers won't beat classical wall-clock at n≤50 binaries.** Expected; the report says
  so explicitly. The §15.1 production trigger (₹50L+, 15+ stocks) stays evidence-gated.
