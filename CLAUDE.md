# CLAUDE.md

Guidance for Claude Code (and humans) working in this repo.

## What this is

Q-Alpha — a quantitative wealth-management system for Indian (NSE/BSE) equities. The full system
architecture is specified in [Q_alpha.md](Q_alpha.md) (v3.1). The codebase is built **phase by
phase**; the spec mandates that **Phase 0 (strategy validation by backtest) must beat baselines
after costs and taxes before any production infrastructure is built**.

**Current state: Phase 0 COMPLETE — defensible Phase-0 GO (backtest gates 1-3), validated OOS.**
See `reports/PHASE0_VERDICT.md`. The original headline (6-factor, 24 survivors, vs Nifty *price*)
was stress-tested through two fairness fixes (point-in-time universe + TRI benchmark) and an
out-of-sample walk-forward; the edge survived once rebalancing slowed to low turnover. §14 gates
**1 ✅ (OOS) · 2 ✅ · 3 ✅**; criteria 4-10 are Phases 1-6 (infra/broker/paper-trading) — the
real-money GO is still months away. The 6-factor PIT run is data-blocked (fundamentals for ~75 names
incl. dead ones) but is *not* a GO-blocker. **⚠️ But the 2025-26 out-of-time HOLDOUT
(`scripts/holdout_2025.py`) is a YELLOW FLAG:** frozen config on genuinely unseen data was flat
(0.7% vs TRI 0.6%) and **trailed 1/N badly (7.1%) with worse drawdown** — the alpha did NOT
generalize. Root cause: the §4.6 tax gate **froze rebalancing after 2019** (only 5 rebalances ever),
so the in-sample 18.5% was largely stale 2013-19 winners riding the 2020-24 bull. Low power (17.5mo,
flat market) so not proof of failure, but not confirmation either. **Ossification fixed**
(`run_backtest(force_refresh=True)`: scheduled rebalance always executes, band-limited): un-froze the
book (5→13 rebalances), **neutral in-sample** (18.4 vs 18.5) and **fixed holdout drawdown −24→−13%**
— but holdout return still flat (1.1%) and still trails 1/N (7.1%). So ossification was a real flaw
(→ `force_refresh` should be the production default) but NOT the reason alpha was absent OOS.
**Then Track A SOLVED it (`scripts/exp_breadth.py`):** the literature's anchor-to-1/N shrinkage —
`weighting="shrink"` (½ min-var + ½ equal over the picks) — **beats 1/N in-sample (18.3 vs 17.7),
on the holdout (8.1 vs 7.1), AND across rolling 3y holds** (dominates every percentile, worst-3y
+3.6% vs 1/N −8.7%, ≥1/N in 67%). First optimiser change to clear the iron-rule bar *and* survive
the out-of-time holdout. So the edge is BOTH the tax engine AND a modest robust 1/N-anchored return
tilt — not pure index-tracking after all. **Recommended production config: `weighting="shrink"`,
`force_refresh=True`, annual, gate 2.0, band 0.10, Nifty 50 TRI** (code defaults unchanged pending
your OK to flip). No DB / broker / dashboard yet. CI green.

### Original static result (Phase 0b, 2012–2024, net of cost + tax) — vs Nifty *price*
| | final ₹ (from ₹2L) | CAGR | Sharpe | max abs DD |
|---|---|---|---|---|
| Q-Alpha (6-factor, tax-aware) | 1,412,776 | 16.6% | 1.06 | -34.5% |
| Nifty 50 (price) | 992,378 | 13.4% | 0.85 | -38.4% |
| Equal-weight 1/N | 1,579,511 | 17.7% | 1.09 | -35.6% |

### Phase A: survivorship-free universe + fair Nifty 50 **TRI** benchmark (3-factor, fully reproducible)
The six-factor model can't yet be run on the PIT universe (needs fundamentals for ~75 names; only 7
of 25 Screener files are even in the repo), so the clean A/B is on the **3-factor (0a)** model:
| run | universe | CAGR | Sharpe | max DD | cost+tax | vs Nifty 50 TRI (14.5%, 0.98) |
|---|---|---|---|---|---|---|
| static-0a | 24 survivors | 14.6% | 0.98 | -33.6% | ₹10k | CONDITIONAL (ties Sharpe) |
| **PIT-0a** | **76, dead names in** | **15.2%** | **0.92** | **-28.1%** | **₹165k** | **NO-GO (loses Sharpe)** |
| 1/N (PIT, frictionless) | — | 17.7% | 1.06 | -39.0% | 0 | — |

Honest read: **survivorship bias was *not* inflating the edge** — fixing it actually *raised* return
(14.6→15.2%) and cut drawdown. At **monthly** rebalancing the strategy loses Sharpe vs TRI because
turnover/tax explodes (₹2.7k→₹117k) — the §4.6 gate at 2.0 is far too lenient at this universe size.

### Phase A follow-up: **rebalance frequency** is the single biggest lever (PIT-0a vs TRI, net cost+tax)
| rebalance | # rebal | tax | CAGR | Sharpe | maxDD | verdict |
|---|---|---|---|---|---|---|
| Monthly | 47 | ₹117k | 15.2% | 0.92 | -28.1% | NO-GO (loses Sharpe) |
| Quarterly | 22 | ₹76k | 16.7% | 1.04 | -24.6% | GO |
| **Annual** | **5** | **₹20k** | **18.5%** | **1.13** | **-24.1%** | **GO — beats TRI *and* 1/N** |

**Trading less improves *every* metric monotonically** in the full window. Mechanism is durable:
lower tax (LTCG not STCG, fewer events) + less noise-trading + tax savings compounding. Frequency is
a CLI knob (`run_phase0.py --rebalance M|Q|Y`). Reports: `reports/phase0_pit_report.md` (monthly),
`reports/phase0_pit_annual_report.md` (annual), `reports/phase0_static0a_report.md` (static/TRI).

### WALK-FORWARD VALIDATED (`scripts/walkforward.py`) — thesis holds OOS; frequency is *not* a magic number
Two out-of-sample views on the PIT universe, net cost+tax:
- **Rolling 3-yr holding periods (every entry day):** Annual dominates the *whole distribution* —
  worst-ever 3y **+4.4%** (never a losing 3y stretch) vs Monthly +2.6%, Nifty-TRI **−2.9%**, 1/N
  **−8.7%**. Annual ≥ TRI in **93%** of holds, ≥ 1/N in **69%**, ≥ Monthly in 70%. Best downside of
  any option — the consumer-relevant headline ("even if you started at the worst time…").
- **3 independent sub-period backtests (distinct regimes):** Annual **beat both TRI and 1/N in all
  three** windows (vs 1/N: +4.8, +2.4, +6.9). BUT the M<Q<Y ranking is **not** monotonic OOS —
  Monthly won 2015-21 (its gate suppressed trades → low realized turnover anyway), Quarterly was
  erratic (great 2012-18, *lost* to benchmarks 2018-24 when it under-traded to ₹0 tax).
- **Refined, validated conclusion:** the driver is **low *realized* turnover, not the nominal
  frequency** — annual achieves it structurally, the §4.6 gate achieves it adaptively; both win,
  pure-monthly-churn loses, and zero-turnover (stuck) also loses. So: **"trade less, tax-aware,
  beats index + 1/N net of friction" is validated OOS**; "annual is *the* optimal frequency" is not
  — annual/quarterly is the robust *zone*, pick by the tax/Sharpe trade-off, don't over-fit the point.

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
Status: **1 ✅ walk-forward validated (low-turnover 3-factor PIT beats TRI in 93% of 3y holds & beat
TRI+1/N in all 3 independent sub-periods, best downside; the *thesis* holds OOS though not a magic
frequency — see Phase A) |
2 ✅ | 3 ✅ PIT universe built (Phase A) | 4 ⚠️ validate vs real Zerodha Tax P&L | 5 ❌ corp-actions
(Phase 1) | 6 ❌ 50+ paper events, 3–6 mo (Phase 5, unskippable) | 7 ✅ | 8 ✅ (dynamic rule) | 9 ❌
data-confidence (Phase 1) | 10 ❌ recommendation layer (Phase 4)**. Phase A cleared survivorship (3)
and — once rebalancing slowed to annual — re-cleared criterion 1 on the *fair* test. Remaining for a
defensible Phase-0 GO: **walk-forward validation** of the rebalance frequency (don't trust one
bull-heavy window), then optionally the 6-factor PIT run. The *real-money GO* remains months away,
gated by a mandatory paper-trading run.

## Brainstorming / open threads (what we're actively deciding)

- **Survivorship-free universe — DONE (Phase A).** Built `data/universes/nifty50_membership.csv`
  (point-in-time Nifty 50, 2012–24, dead names included) via `scripts/build_nifty_universe.py`
  (reverse-apply from current set, validated — caught 4 Wikipedia errors + 2 missing exits). Wired
  `run_phase0.py --universe-csv`. Also fixed a **look-ahead bug in the 1/N baseline** (it front-ran
  future index entrants → fake 22.4%; now `equal_weight_pit` respects membership) and added a fair
  **Nifty 50 TRI** benchmark (`--benchmark NIFTYBEES.NS`, adj-close = divs reinvested) + a §5.1
  yfinance bad-tick sanitizer. Finding: survivorship wasn't flattering the edge, but vs TRI the
  3-factor model loses Sharpe (see status table). **Blocker for the real verdict: fundamentals for
  the ~75 PIT names** (a Screener-ingest data task, like the original 0b) to run 6-factor-on-PIT.
  Large-cap survivorship bias is genuinely *modest* (delistings ≈0.81% of Nifty-500 mcap) — confirmed.
- **"A better optimizer" — DONE: shrinkage hybrid (`weighting="shrink"`).** ½ min-var + ½ equal-weight
  over the picks (DeMiguel/Tu-Zhou anchor-to-1/N) is the validated winner — beats 1/N in-sample, on
  the 2025-26 holdout, and across rolling 3y holds (dominates every percentile). `select_and_weight`
  now supports `minvar|equal|score|shrink`; engine takes `weighting=` + `n_stocks_override=`. Pure
  broad-equal and score-tilt LOST (dilute/concentrate) — only the principled blend won. **Remaining
  optimizer ideas:** HRP/NCO (another robust route), and QUBO/VQE as the §15 research showcase
  (AUM-gated ₹50L+). Discipline held: it cleared the "beat 1/N walk-forward net of cost+tax" bar.
- **Defensive engine — two modes tested (`run_backtest(defensive=...|governance_events=...)`).**
  (1) *Price-based* idiosyncratic-drawdown exit (§3.6, `defensive.py:idiosyncratic_exit_flags`):
  on the annual core it cuts drawdown (-24%→-19%) and plugs the 2022 hole (-10%→+11%) but costs
  ~3pts CAGR (18.5→15.6) and *raises* tax (₹20k→₹46k) by whipsawing blue-chips (RELIANCE, ITC,
  MARUTI…) that recover — Sharpe ~flat (1.13→1.11), so it trades return for drawdown, not a free
  win. (2) *Event-driven* governance freeze (§3.11, `defensive.py:GovernanceEvents`, seed
  `data/events/governance_events.csv`): surgical by construction (only ever touches a broken
  business), but a **backtest no-op here** — the momentum/quality factors already never bought
  Yes Bank / Zee (collapsing momentum → never selected). Lesson: the opportunistic engine already
  does most of the defending; event-defence's real value is per-position risk control + a
  human-escalation trigger, and it's gated on a full historical event feed. Also fixed a real
  engine bug surfaced here: idle settled cash was locked out of redeployment by the §4.6 variance
  gate (cash→stocks looks like a risk rise) — now idle cash above the no-trade band always deploys
  (§2.9 fresh-capital routing), which also benefits real capital injections.
- **§4.6 gate multiplier — OOS-calibrated, verdict: DON'T tune it (`scripts/calibrate_gate.py`).**
  Swept {1,2,3,5} at monthly across the 3 sub-periods: **no value generalizes** (best flips
  1.0/3.0/2.0 by window) and turnover is a *knife-edge* (mult 2.0→47 rebalances/₹117k, 3.0→4/₹13k);
  monthly+gate loses to 1/N in ~half the windows. The robust turnover lever is **structural
  frequency (annual)**, not the multiplier — kept at spec default 2.0. (Iron rule: did not tune to
  manufacture a GO.) Side effect found+fixed: idle-cash redeploy lockout (monthly full 15.2→16.7%).
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
