# CLAUDE.md

Guidance for Claude Code (and humans) working in this repo.

## What this is

Q-Alpha — a quantitative wealth-management system for Indian (NSE/BSE) equities. The full system
architecture is specified in [Q_alpha.md](Q_alpha.md) (v3.1). The codebase is built **phase by
phase**; the spec mandates that **Phase 0 (strategy validation by backtest) must beat baselines
after costs and taxes before any production infrastructure is built**.

**Current state: Phase 0 COMPLETE + live build well underway — all on `main`.** Beyond the validated
Phase-0 GO, the repo now has the live layer (Kite auth, replay harness), a running **paper-trading
book** (notional, started 2026-06-12) with a **dashboard + autonomous daily pipeline**. The
**research track (quantum QUBO/QAOA, + planned regime/bubble & agentic work) now lives in a separate
repo** — `github.com/aarsh-adhvaryu/Q_Alpha_Research` — which imports this engine as a dependency, so
this repo stays product-clean. See the "NEXT SESSION" block for the active plan (a
deterministic tax-smart advisor + a live Zerodha-wired dashboard). Phase-0 evidence:
`reports/PHASE0_VERDICT.md`. The original headline (6-factor, 24 survivors, vs Nifty *price*)
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
tilt — not pure index-tracking after all. No DB / broker / dashboard yet. CI green.

## ⏯️ NEXT SESSION — START HERE (a brainstorm; build is paused here)

**Next session = brainstorming, not a queued build.** Everything below is current. Two PRs are open
and **awaiting the user's manual merge — order #10 then #11** (or merge #10 and retarget #11 to main):
- **PR #10 `cleanups`→main:** deploy cash-utilization fix + CLAUDE.md refresh + **live Zerodha
  holdings reader** (`src/qalpha/live/holdings.py`, advisor `--source live`, dashboard Live toggle).
- **PR #11 `tradebook-upload`→`cleanups` (stacked):** upload a Zerodha Console **tradebook CSV** in the
  dashboard → exact **dated** FIFO tax (`src/qalpha/live/tradebook.py`), `advisor --tradebook`.

**On `main` (9 PRs merged, 2026-06-13):** Phase 0 (validated GO) + a **live layer** (`src/qalpha/live/`:
Kite auth, replay harness, shared `decide_rebalance`) + a **paper-trading runner** (`scripts/paper.py`,
notional ₹2L book started 2026-06-12, 5 holdings) + a **dashboard + autonomous daily GitHub Actions
pipeline** (`paper.yml`) + the **deterministic tax-smart advisor** + a **live Streamlit dashboard**.
(The quantum research track was moved to the separate `Q_Alpha_Research` repo.) Four gates green.

**🏁 FINALIZATION (2026-06-18) — Nifty-100 deploy-in-weakness, the manual-investor solution.** The
user's real need: diversify + find better entries; Nifty-50 large-caps are rarely cheap outside a
crash, so the *opportunity set* must widen to Nifty 100. Built (branch `nifty100-advisor-deploy`):
**`scripts/build_nifty100_watchlist.py` → `data/universes/nifty100_watchlist.csv`** (96 current names
+ sectors — a *forward-looking* watchlist, so survivorship is irrelevant: it lists what's investable
*today*, not a backtest universe); **`src/qalpha/live/deploy.py`** (tested) — three deterministic
price-based layers on top of the validated `advise_deploy` (₹0-tax greedy buys): (1) `market_weakness`
(index drawdown from 1y high → normal/elevated/deep "when to deploy more" advisory; a self-contained
signal — the richer research **fragility gauge** is the upgrade path), (2) `cheapness_scores` (pullback
below each name's 1y high — a **technical** out-of-favour proxy, *honestly NOT* fundamental P/E, which
stays data-blocked), (3) `deploy_target` (diversified equal-weight + sector-capped water-filling, tilted
to cheaper names) → `advise_deploy_into_weakness`. CLI: **`advisor.py deploy-weakness AMOUNT [--tilt]`**.
`tests/test_deploy.py`. **This is the tax-free "buy cheap, diversify" lever** — new money only, ₹0
capital-gains tax. **Honest framing locked in:** the *validated backtested strategy* default stays
Nifty 50 (no proven alpha from breadth — see the research breadth/QUBO findings); this widens only the
*manual investor's* opportunity set, which the advisor/tax engine already serve on any holdings.
**Data note:** the on-disk panel prices only ~24 names; the full 96-name watchlist needs a yfinance
ingest for cheapness history (the engine already filters to priced names). **"Closed" = build-complete
v1; the real-money GO remains gated by the unskippable forward paper run** (criterion 6) — that calendar
time cannot be compressed. QUBO/breadth stay in research; the fragility-gauge promotion (as a read-only
"systemic risk" advisory) is the clean next integration if revisited.

**⭐ USER MADE FIRST REAL TRADES (2026-06-13):** funded YHK037, **HDFCBANK BUY 5 @₹785.45 COMPLETE**
(CNC/delivery), INFY BUY 5 still OPEN/pending; cash ₹445.75. **A same-day delivery buy sits in
`positions()` day-book, NOT `holdings()`** (→ T+1 it lands in `holdings()` as `t1_quantity`), so
`--source live` (which reads `holdings()`) shows EMPTY until tomorrow. Possible quick win:
also read `positions()` for same-day visibility (offered, not built). Kite token expires daily
~06:00 IST → re-mint `python -m qalpha.live.auth --manual`. **Streamlit server can't run in the agent
harness** (sandbox kills port-binding, exit 144); the user runs it + forwards port 8501 via VSCode
PORTS. I verify rendering with Streamlit `AppTest` (in-process, no socket).

**🎯 USER'S VISION + AGREED NEXT PLAN (the active direction — build this):** the user trades **manually
(all his own decisions)** and wants an **advisor + proper live web dashboard wired to his REAL Zerodha
account** — it reads his holdings (`kite.holdings()`) + live prices, reflects every trade *he* makes,
and tells him the **tax-smart move**. It NEVER auto-executes. Tax math is **deterministic** (exact/
auditable — NOT an LLM computing numbers; an LLM "concierge" that routes NL questions to the engine is
an optional *later* flourish, never the calculator). **Build order:**
1. ✅ **DONE — Deterministic tax-smart advisor** (= §14 criterion 10, the recommendation layer):
   `src/qalpha/live/advisor.py`. Three modes, all on the validated FIFO/cost/tax engine (no LLM, no
   second formula), source-agnostic (takes a `Portfolio`): `advise_sell` (STCG/LTCG split, exact tax,
   exemption shelter, largest ₹0-tax quantity, wait-out-365 flag), `advise_raise_cash` (least-tax
   source order — losers/long-term first — vs naive pro-rata), `advise_deploy` (route new money to
   underweights, buys-only ₹0 tax, vs a taxable full rebalance). CLI `scripts/advisor.py`
   (`sell`/`raise-cash`/`deploy`). `Portfolio` gained `clone()`, public `sell()`/`buy()`,
   `preview_sell()`. Tests `tests/test_advisor.py`.
2. ✅ **DONE — Live web dashboard** (Streamlit): `scripts/dashboard_app.py` — equity vs Nifty 50 TRI,
   holdings, today's recommendation, and the advisor as interactive tabs. Read-only (never trades).
   Source = paper book now → `kite.holdings()` later (the `_load` seam). `streamlit` is an optional
   **`dashboard`** extra (UI-only, not in CI/pipeline). Run: `uv run --extra dashboard streamlit run
   scripts/dashboard_app.py`. `AppTest` smoke test skips dev-only (CI) / without on-disk data.
3. ✅ **DONE — Live Zerodha holdings reader** (PR #10): `src/qalpha/live/holdings.py` reads
   `kite.holdings()` + `ltp()` + `margins()` into the same `Portfolio`. Source swap is a sidebar toggle
   (dashboard) / `--source live` (CLI). **Caveat:** `holdings()` has no purchase dates → undated lots
   (tax short-term-assumed) flagged via `LiveHoldings.lots_dated`/`.tax_caveat`.
4. ✅ **DONE — Tradebook upload → exact dated tax** (PR #11, the criterion-4 reconstruction half):
   `src/qalpha/live/tradebook.py` (`parse_tradebook` path-or-file, `replay_tradebook`→`ReplayResult`,
   `reconcile_positions`). Dashboard Live view has an `st.file_uploader`; upload the Console tradebook
   CSV → exact dated FIFO lots + realized tax + holdings reconciliation; advisor uses the accurate book.
**Trust gate** before real-money reliance: **criterion 4** = reconcile our realized tax vs the real
Zerodha **Tax P&L** export. Reconstruction (tradebook replay) is built; still needs a real **SELL**
(only buys so far) → export Console **Tax P&L** + **Tradebook** (T+1) → build a Tax P&L parser →
reconcile to the rupee. **Parked (declined/deferred):** auto-execution, LLM-for-numbers, Monte Carlo,
GPU, more quantum.

**✅ PAPER CRON FIXED (2026-06-15, PR [#14](https://github.com/aarsh-adhvaryu/Q_Alpha/pull/14), merged).** Root cause of the never-firing
schedule: `cron: "0 12"` was the **top of the hour** — GitHub throttles/silently-drops on-the-hour
scheduled workflows under load. Moved to `"23 12 * * 1-5"` (off-hour). Proved the pipeline works
end-to-end via a manual `workflow_dispatch` run (green; it marked the book + pushed the track record,
commit `1a799e1`). First scheduled firing expected next weekday 12:23 UTC — **still verify it fires
on schedule** (dispatch ≠ cron). The job itself was always sound; only the trigger timing was broken.

**🅿️ PARKED VISION (2026-06-15, user said "do later") — autonomous system + Nifty 100–200.** The
user wants the product to become **autonomous data→scoring→recommendation, human approves + trades
manually** (never auto-executes — already the design). Daily data refresh + a weekly decision/advisor
run (two cron cadences; the `paper.yml` skeleton already does the no-AI-in-loop pattern). Scale the
universe **5 → Nifty 100–200** (user's chosen scope). Two findings that reshape this:
1. **Kite Connect API does NOT expose fundamentals/Tijori** (verified vs kite.trade/docs/connect/v3:
   categories are auth/orders/GTT/alerts/portfolio/quotes/WebSocket/historical-candles/MF/margin — no
   fundamentals). Tijori on Zerodha is the **consumer Kite UI only**; programmatic Tijori = its own
   **separate paid API**. So fundamentals can't ride the existing Kite integration.
2. **The validated edge is 3-factor (price/volume) — it needs ZERO fundamentals.** So scaling to
   Nifty 100–200 is **data-cheap** (price history via yfinance + the bad-tick sanitizer; no data
   deal). Fundamentals/6-factor stays the *optional later* enhancement (only then weigh Tijori-API vs
   NSE/BSE-filings parsing). **Critical path for the expansion (a fresh, pre-registered Phase-0 pass —
   the Nifty-50 result does NOT auto-transfer):** (a) extend the PIT universe 50→~200 via
   `build_nifty_universe.py`; (b) add the **square-root slippage law** `impact≈k·σ·√(value/ADV)`
   *before* trusting mid-cap numbers (flat 0.2% is too optimistic off large-caps — see §13 / the
   open-threads slippage item); (c) re-validate 3-factor net cost+tax, walk-forward, **vs 1/N**. Run
   as a **validation experiment**; promote the new universe into the product default **only after it
   clears the bar** (keep qalpha pristine — see the research-untouched rule). **Trap to avoid:** a
   "weekly decision" cadence must NOT loosen the §4.6 gate — weekly *monitoring* is fine, but actual
   trades must stay rare (low realized turnover is the validated edge).

**🧠 OTHER OPEN THREADS** — same-day `positions()` reading; the Tax P&L parser + crit-4 reconciliation
(once a real sell exists); corporate-actions (crit 5); the tax-alpha whitepaper; LLM "concierge"
routing NL → the deterministic engine; an equity-curve chart + dashboard screenshot in the README
(the only "last-mile" polish for resume-readiness — repo is otherwise resume-ready: 100 tests green,
CI green, honest README). Let the user steer.

**The validated config is now the default** of `scripts/run_phase0.py` (no args needed):
PIT universe + **Nifty 50 TRI** benchmark + **annual** rebalance + **`weighting=shrink`** (½ min-var +
½ equal, the anchor-to-1/N edge) + **`force_refresh=True`** (anti-ossification) + §4.6 gate 2.0 + band
0.10. Reproduce the headline (**18.2% CAGR / Sharpe 1.13 / GO**, beats Nifty TRI 14.5% and 1/N 17.7%):
```bash
uv run python scripts/build_nifty_universe.py        # regenerate the PIT universe CSV (gitignored)
uv run python scripts/run_phase0.py --end 2024-12-31 # the validated run → reports/phase0_report.md
```
Engine low-level defaults were left neutral (minvar / monthly / no-refresh) so the test-suite stays
green; the *application* layer (run_phase0) carries the validated defaults.

**What's proven vs not:** the strategy edge is validated as far as *simulation* can go (walk-forward +
2025-26 holdout + shrink beats 1/N). What remains is **live-only** validation that no simulator can
replace — data-feed integrity, real fills/slippage, FIFO-vs-broker tax reconciliation, the
human-in-the-loop process, and certainty of no look-ahead (we found one look-ahead bug already). That
is the unskippable forward paper run; it can be *de-risked* fast (replay the production code over
history; validate FIFO vs a real Zerodha Tax P&L) and run *in parallel* with the build, but the
forward calendar time itself (pipeline survives N days + ≥1 volatility event) cannot be simulated away.

_(Superseded — those original "three candidate moves" are done: branch pushed/merged, Stage-1
founder-as-user build + paper clock live, QUBO/QAOA built. The active plan is the advisor-first one
above. The tax-alpha whitepaper remains a good resume capstone once the advisor exists.)_

**Read-me-first docs:** `reports/PHASE0_VERDICT.md` (full evidence chain + verdict), `STRATEGY.md`
(market scan, regulatory reality, 4-stage industry-ready plan), `PLAN.md` (technical track).
Experiment scripts: `walkforward.py`, `calibrate_gate.py`, `holdout_2025.py`, `exp_breadth.py`,
`exp_frequency_lookback.py`, `build_nifty_universe.py`.

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
uv run python scripts/advisor.py deploy 50000      # tax-smart advice (sell / raise-cash / deploy)
uv run --extra dashboard streamlit run scripts/dashboard_app.py   # the live web dashboard
```

All four gates (ruff, ruff-format, mypy strict, pytest) must pass before committing.

## Architecture (the funnel)

```
data/         price panel (yfinance→Parquet), point-in-time universe, Screener fundamentals
factors/      momentum, volatility, liquidity (0a) + value, quality, dividend (0b); regime; scoring
alloc/        Ledoit-Wolf+EWMA covariance conditioning → scipy sector allocator → scipy optimizer
accounting/   FIFO tax lots + Zerodha costs + capital-gains tax   (reused live; Portfolio.to_state persists a book)
backtest/     walk-forward engine, portfolio accountant, baselines, metrics, report; decision.py = shared decide_rebalance
live/         Kite auth + replay harness + paper book (PaperBook) + dashboard renderer + advisor.py (tax-smart layer, crit 10) + holdings.py (live reader) + tradebook.py (Console CSV → dated FIFO, crit 4)
scripts/      run_phase0, paper, advisor (CLI), dashboard_app (Streamlit, `dashboard` extra), build_nifty_universe, experiments
config.py     every tunable parameter (Q_alpha.md §16) in one place
              (the research track — QUBO/QAOA §15 + planned regime/agentic — lives in the separate Q_Alpha_Research repo)
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
2 ✅ | 3 ✅ PIT universe built (Phase A) | 4 🟡 reconstruction built (tradebook replay → dated FIFO,
`tradebook.py`); reconciliation vs real Zerodha **Tax P&L** still needs a real SELL + the Tax P&L parser |
5 ❌ corp-actions (Phase 1) | 6 ⏳ paper clock STARTED 2026-06-12, accumulating (3–6 mo, unskippable) |
7 ✅ | 8 ✅ (dynamic rule) | 9 🟡 pipeline built, needs the live run | 10 ✅ deterministic tax-smart
advisor + live dashboard built (`advisor.py`, `dashboard_app.py`)**. Phase A cleared survivorship (3)
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
  (AUM-gated ₹50L+; now in the `Q_Alpha_Research` repo). Discipline held: it cleared the "beat 1/N
  walk-forward net of cost+tax" bar.
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
- **Size-aware slippage — ✅ DONE (2026-06-17).** Replaced the flat 0.2% with the **square-root law**
  `slippage = impact_k·σ_daily·√(value/ADV)` (spec §13): new `accounting/slippage.py`
  (`SquareRootSlippage`/`FlatSlippage`, `square_root_impact_pct`, tested), a `slippage_model` on
  `Portfolio` used in `_sell`/`_buy`/`_affordable_qty`, and `run_backtest(dynamic_slippage=True)` which
  sets a **causal as-of** per-rebalance ADV+vol snapshot (no look-ahead). Config in `CostConfig`
  (`impact_k=1.0`, floor 2bps, cap 2%). At k=1 the law equals the old 0.2% exactly at the §3.3
  order-size cap (1% of ADV, 2% daily vol), so it's a principled generalisation. **`run_phase0`
  defaults it ON** (`--no-dynamic-slippage` reverts). **Honest Phase-0 impact (PIT, annual, shrink,
  end 2024): headline barely moves — GO holds, Sharpe 1.13→1.14, CAGR ~18.2→18.3%, maxDD −25.2 flat,
  still beats Nifty TRI + 1/N — but charged cost DROPS ₹22.2k→₹9.5k** because the strategy trades
  small fractions of ADV in deep large-caps, so realistic impact is *below* the flat 0.2%. The model's
  teeth are for the **Nifty 100–200 expansion**, where thin mid-caps in size get charged more — the
  gate/optimiser then avoid them. Slippage is an execution *cost*, not portfolio risk.
- **Benchmark fairness.** Move to **Nifty 50 TRI** (total-return, free from niftyindices.com) — raises
  the bar ~1.5%/yr; the strategy still clears it.
- **BSE→NSE canonical-ticker robustness — ✅ DONE (2026-06-17).** A holding/trade is keyed by ISIN in
  demat (exchange-agnostic), and NSE is our single source of truth (panel/universe/factors/slippage)
  and the liquid venue. So `live/holdings.py` `to_ticker(symbol, exchange)` → **`canonical_ticker(symbol)`**
  that always resolves to `.NS` (a BSE INFY buy tracks as `INFY.NS`); `Holding.exchange` keeps the real
  venue for the live `ltp()` call. `tradebook.py` uses it too (a BSE leg + its NSE counterpart reconcile
  to one lot). Deliberately did **NOT** build full dual-exchange (NSE+BSE) calibration — same companies,
  thinner BSE book, Sensex⊂Nifty, BSE-only = illiquid small-caps → complexity tax, zero alpha, bloats
  the clean repo. Tests in `test_holdings.py` (BSE→.NS, exchange preserved). 107 tests green.
- **§4.6 gate tax-date bug — ✅ FIXED (2026-06-17).** `decision._net_benefit_ok` dry-ran the gate's
  cost/tax estimate at wall-clock `date.today()` instead of the rebalance `as_of`, so in a historical
  backtest every lot looked long-term → STCG under-estimated as LTCG → the gate traded too readily.
  Now threads `as_of` (live, `as_of`≈today, so also correct). **Validated headline unaffected**
  (force_refresh short-circuits the gate); only non-force-refresh `tax_aware` runs (older Phase A
  monthly/quarterly tables, `calibrate_gate`) would shift slightly if re-run — qualitative conclusions
  hold. 106 tests green.
- **Tax-engine validation (criterion 4).** Validate the FIFO engine against a real **Zerodha Console →
  Reports → Tax P&L** export (user action). **Note:** LTCG *loss* set-off isn't implemented
  (documented Phase-0 deferral) — it will surface in this reconciliation, so fix before reconciling.
- **Risk-tolerance reckoning.** Backtest the full **50/25/25** pool structure (not 100% core) to see
  the blended drawdown, then confirm the real tolerance (long-only equity ≈ -30% in crashes; a hard
  ≤20% implies a hedging overlay = a v2 feature).

## Iron rules (don't violate)

- Do **not** auto-tune parameters to manufacture a GO — that defeats Phase 0. Validate out-of-sample.
- Keep all four gates green (ruff, ruff-format, mypy strict, pytest) before every commit.
- Surface honest caveats in the report; never let a survivor-only universe silently earn a GO.
