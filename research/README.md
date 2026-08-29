# research/ — ideas that have **not** passed

Everything here is unproven. It lives in the product repo (one repo, since 2026-08-28) but is
**walled off from it**, and the wall is a test, not a convention:
[`tests/test_repo_boundary.py`](../tests/test_repo_boundary.py) fails if any file under
`src/qalpha/` or `scripts/` imports `research.*`.

## The graduation rule

**Code leaves this directory by *moving*, never by being imported.** A module graduates into
`src/qalpha/` when a **pre-registered** test on it passes — see
[PLAN_REDESIGN.md §2a](../PLAN_REDESIGN.md). Reaching across the line to use something promising is
precisely how an untested idea ends up on a real-money surface.

Graduated on 2026-08-28, when two repos became one:

| Moved to | Was | Why it graduated |
|---|---|---|
| `src/qalpha/live/fragility.py` | `regime/fragility.py` | the cross-asset stress gauge — the documented upgrade path over drawdown-only |
| `src/qalpha/live/hedge_study.py` | `regime/hedge_paper.py` | the forward-run harness, **plus the liveness reporting its 38-day silent death demanded** |
| `src/qalpha/backtest/overlay.py` | `regime/overlay_backtest.py` | already built on the product engine; needed for the Phase 4 composite backtest |

`regime/hedge.py` was **not** moved — it duplicated `qalpha/live/hedge.py`. Verified behaviourally
identical (`hedge_active` across three parameter sets; `apply_futures_hedge` equity, cost, tax and
episode count all equal) and collapsed into the product's copy.

## What is still here, and what would graduate it

| Module | Status | Graduates when |
|---|---|---|
| `regime/options.py` | unproven | an options hedge beats futures net of premium — newly relevant, since **no index derivative trades below ~₹15L notional** (PLAN_REDESIGN §4b-i), so futures are unusable on a small book |
| `regime/risk_state.py` | **published negative** | the HMM sell-overlay *lost* to capital-gains tax: drawdowns mostly recover, so selling to dodge them pays tax for nothing. This is why the system hedges rather than sells |
| `regime/lppls.py` | unproven | a bubble signal beats the drawdown gauge out of sample |
| `quantum/` | **published negative ×2** | AUM-gated (₹50L+) and twice failed to beat the classical optimiser |
| `regime/hedge_readout.py` | superseded | `live/hedge.py` + `live/hedge_study.py` cover it |

## Running these

They are **off the default test path** (`testpaths = ["tests"]`), because the product suite forbids
skips and these legitimately skip without heavy optional deps.

```bash
uv sync --extra research          # hmmlearn (risk state)
uv sync --extra quantum           # qiskit (QAOA) — heavy
uv run pytest research/tests -q
```

CI runs them advisory-only (`continue-on-error`) so the track cannot rot unnoticed, and never lets
them gate the product.
