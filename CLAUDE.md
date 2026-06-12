# CLAUDE.md

Guidance for Claude Code (and humans) working in this repo.

## What this is

Q-Alpha — a quantitative wealth-management system for Indian (NSE/BSE) equities. The full system
architecture is specified in [Q_alpha.md](Q_alpha.md) (v3.1). The codebase is built **phase by
phase**; the spec mandates that **Phase 0 (strategy validation by backtest) must beat baselines
after costs and taxes before any production infrastructure is built**.

**Current state: Phase 0 substantially complete (verdict CONDITIONAL).** The walk-forward backtest
runs the full **six-factor** model on real NSE data (24 large-caps, 2012–2024) and, **net of Zerodha
costs and Indian capital-gains tax, beats Nifty 50** — clearing the spec's §14 criterion-1 gate. The
only thing capping the verdict at CONDITIONAL (not GO) is **survivorship bias** (static survivor
universe). No DB / broker / dashboard exists yet — all gated behind a real GO. CI is green.

### Current results (Phase 0b, 2012–2024, net of cost + tax)
| | final ₹ (from ₹2L) | CAGR | Sharpe | max abs DD |
|---|---|---|---|---|
| Q-Alpha (6-factor, tax-aware) | 1,412,776 | **16.6%** | **1.06** | -34.5% |
| Nifty 50 (price) | 992,378 | 13.4% | 0.85 | -38.4% |
| Equal-weight 1/N | 1,579,511 | 17.7% | 1.09 | -35.6% |

Honest read: a **real edge over the index** net of friction; **does not decisively beat naive 1/N**
(matches the DeMiguel result that 1/N is hard to beat). Drawdown passes the *dynamic* criterion 8
(below) — the -34.5% was a market crash the strategy weathered better than the Nifty.

## Key decisions (deviations from the spec, deliberate)

- **Broker = Zerodha (Kite Connect), not HDFC.** Notably ₹0 delivery brokerage, which changes the
  cost-gate math. Cost constants live in `src/qalpha/accounting/costs.py`.
- **Tax-aware optimizer** (`run_backtest(tax_aware=True)`): the spec's §4.6 net-benefit gate done
  properly — a rebalance is suppressed unless its annual risk reduction (₹) beats 2× its real
  cost + FIFO capital-gains tax. This is the core edge: friction is modelled *inside* the decision,
  not bolted on. It turned a NO-GO (5.4% CAGR, taxed to death) into beating Nifty 50 net (14.6%).
- The **accounting engine** (`src/qalpha/accounting/`) is standalone so the future live decision
  engine reuses the exact same FIFO/cost/tax code.
- **Dynamic drawdown control** (`src/qalpha/backtest/drawdown.py`, spec §0 amended): the flat
  "20% = FULL FREEZE" was *replaced* (evidence: it misfires almost only at crash bottoms). New rule
  is market-relative — absolute DD → defensive posture; **adaptive excess-DD vs benchmark** (beyond
  the strategy's own 95th-pct, sustained ≥60d) → strategy-failure halt; catastrophic (~-40%) →
  human alert. The spec is a *proposal we improve*, not scripture — amend it when evidence warrants.

## Commands

```bash
uv sync --extra dev                       # set up venv + deps
uv run pytest                             # tests (must stay green)
uv run ruff check . && uv run ruff format --check .   # lint + format
uv run mypy src                           # strict type-check
uv run python scripts/run_phase0.py       # run the backtest + print go/no-go report
uv run python -m qalpha.data.ingest --tickers TCS INFY --start 2012-01-01   # pull prices
uv run python -m qalpha.data.fundamentals --raw data/fundamentals/raw       # ingest Screener xlsx
```

All four gates (ruff, ruff-format, mypy strict, pytest) must pass before committing.

## Architecture (the funnel)

```
data/         price panel (yfinance→Parquet), point-in-time universe, Screener fundamentals
factors/      momentum, volatility, liquidity (0a) + value, quality, dividend (0b); regime; scoring
alloc/        Ledoit-Wolf+EWMA covariance conditioning → scipy sector allocator → scipy optimizer
accounting/   FIFO tax lots + Zerodha costs + capital-gains tax   (reused by the future live system)
backtest/     walk-forward engine, portfolio accountant, baselines, metrics, go/no-go report
config.py     every tunable parameter (Q_alpha.md §16) in one place
```

Data flow each rebalance: `as_of` slice (no look-ahead) → liquidity gate → factor scores under the
regime's weights → top-N selection → sector allocator → portfolio optimizer → tax-aware execution.

## Conventions

- **Money is `decimal.Decimal`** everywhere it touches accounting; never float (spec §5.2). Factor
  / covariance math uses numpy float64.
- **No look-ahead, ever.** All historical reads go through `PriceData.as_of(date)`; fundamentals
  carry an `effective_date = report_date + 90d` lag. There is a test that fails on look-ahead.
- **Reuse before adding.** The sector-percentile ranker, cost engine, and FIFO ledger are shared;
  prefer extending them. Match the surrounding style; keep functions typed (mypy strict).
- Reference the spec by section (e.g. "§4.6") in comments so code maps back to the architecture.
- Phase 0a (3 price/volume factors) runs without fundamentals; Phase 0b (6 factors) activates when
  Screener exports are present in `data/fundamentals/raw/`. The scorer renormalises over whatever
  factors exist, so the same code path serves both.

## Path to a real GO — §14 scorecard

"GO" = the spec's §14 (10 criteria, all true before real money), spanning Phase 0 → Phase 6.
Status: **1 ✅ | 2 ✅ | 3 ❌ survivorship (the blocker) | 4 ⚠️ validate vs real Zerodha Tax P&L |
5 ❌ corp-actions (Phase 1) | 6 ❌ 50+ paper events, 3–6 mo (Phase 5, unskippable) | 7 ✅ |
8 ✅ (dynamic rule) | 9 ❌ data-confidence (Phase 1) | 10 ❌ recommendation layer (Phase 4)**.
Two tiers: a *defensible Phase-0 GO* is ~2–3 weeks of mostly-free-data work; the *real-money GO* is
months away and gated by a mandatory paper-trading run.

## Brainstorming / open threads (what we're actively deciding)

- **Survivorship-free universe (next up, the #1 unlock).** Build a point-in-time Nifty 50 universe
  from free data (Wikipedia constituent-change table since 2005 + GitHub datasets), pull the dropped
  names' prices, re-run. `Universe.from_csv` + `--universe-csv` are already wired; needs the CSV.
  Note: for large-caps survivorship bias is *modest* (delistings ≈0.81% of Nifty-500 mcap).
- **"A better, different optimizer."** Tax-aware net-benefit gate = done (the current edge). Open
  candidates to close the gap to 1/N: **factor-tilted weighting** (use the alpha signal at the
  weighting stage, not just selection), **HRP / NCO** (robust, beats min-variance OOS), and
  **QUBO/VQE** as the research-track showcase for the integer-constrained problem (AUM-gated to
  ₹50L+, §15). **Discipline: every optimizer change must beat 1/N walk-forward, net of cost+tax.**
- **§4.6 gate multiplier calibration.** A 0b sweep showed 2.0 too lenient (3.0 ~halves tax AND
  lifts return). Kept at 2.0 — adopt the value via **walk-forward / out-of-sample** validation
  (§6.2), never by picking the in-sample winner.
- **Size-aware slippage.** Replace flat 0.2% with the **square-root law** `impact ≈ k·σ·√(value/ADV)`
  before the ₹50L+ scaling numbers are trustworthy (spec §13).
- **Benchmark fairness.** Move to **Nifty 50 TRI** (total-return, free from niftyindices.com) — raises
  the bar ~1.5%/yr; the strategy still clears it.
- **Tax-engine validation (criterion 4).** Validate the FIFO engine against a real **Zerodha Console →
  Reports → Tax P&L** export (user action).
- **Risk-tolerance reckoning.** Backtest the full **50/25/25** pool structure (not 100% core) to see
  the blended drawdown, then confirm the real tolerance (long-only equity ≈ -30% in crashes; a hard
  ≤20% implies a hedging overlay = a v2 feature).

## Iron rules (don't violate)

- Do **not** auto-tune parameters to manufacture a GO — that defeats Phase 0. Validate out-of-sample.
- Keep all four gates green (ruff, ruff-format, mypy strict, pytest) before every commit.
- Surface honest caveats in the report; never let a survivor-only universe silently earn a GO.
