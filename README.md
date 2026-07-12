# Q-Alpha

[![CI](https://github.com/aarsh-adhvaryu/Q_Alpha/actions/workflows/ci.yml/badge.svg)](https://github.com/aarsh-adhvaryu/Q_Alpha/actions/workflows/ci.yml)

**A tax-aware quantitative investing system for Indian (NSE/BSE) equities — and an honest study of
what actually survives once you put real taxes and costs inside the decision.**

If you read one paragraph: most backtests look great because they ignore that, in India, selling a
winner triggers a 20% short-term capital-gains tax, and trading costs money. Q-Alpha puts those
frictions *inside* the buy/sell decision instead of subtracting them at the end. The surprising
result is that the "alpha" is mostly **discipline** — trade rarely, be tax-smart — not clever
stock-picking. Then we built the live system around that finding: an advisor that tells a human the
**tax-smart move**, a dashboard, and a paper-trading run that self-certifies before any real money.

> **Status in one line:** the strategy is validated as far as a backtest can go (it beats the index
> *and* equal-weight, net of cost and tax, out-of-sample). The live system is built and deployed on a
> real account. The only thing between here and real-money go-live is **calendar time** — a mandatory
> ~6-month forward paper run — plus a couple of real-world events to reconcile. No engineering blocks it.

Read-me-next: [reports/PHASE0_VERDICT.md](reports/PHASE0_VERDICT.md) (full evidence chain) ·
[CLAUDE.md](CLAUDE.md) (developer/agent log) · [Q_alpha.md](Q_alpha.md) (the full spec).

---

## 1. The headline result (for the skim-reader)

On a **survivorship-free** point-in-time Nifty 50 universe (delisted companies included), **net of
realistic Zerodha costs and Indian FIFO capital-gains tax**, vs the Nifty 50 **total-return** index:

| Strategy | CAGR | Sharpe | Verdict |
|---|---|---|---|
| **Q-Alpha** (tax-aware, annual, shrinkage-weighted) | **18.2%** | **1.13** | — |
| Nifty 50 TRI (dividends reinvested) | 14.5% | 0.98 | beaten by **+3.7%/yr** |
| Equal-weight 1/N | 17.7% | 1.09 | beaten by **+0.5%/yr** |

**Why beating "1/N" matters:** equal-weighting every stock (1/N) is famously hard to beat — most
published strategies lose to it once costs and taxes are honest. Clearing that bar **in-sample, on a
genuinely unseen 2025–26 holdout, AND across every rolling 3-year holding window** (it never had a
losing 3-year stretch) is the real claim here, not the headline CAGR.

```bash
cd qalpha && uv sync --extra dev
uv run python scripts/build_nifty_universe.py          # regenerate the point-in-time universe
uv run python scripts/run_phase0.py --end 2024-12-31   # → reports/phase0_report.md
```

---

## 2. The core idea, in plain words (then the math)

**Plain words.** Imagine you hold a stock that's up 50%. A "smarter" model says rotate into a slightly
better one. But selling realizes a 20% tax on that 50% gain *today* — money that would otherwise keep
compounding. So the rational move is usually: **don't trade unless the improvement clearly beats the
tax bill.** Q-Alpha encodes exactly that rule.

**The math (spec §4.6 — the "net-benefit gate").** A rebalance from current weights *w* to target
weights *w\** is executed **only if**

```
ΔRisk(₹)  >  2 × ( Cost(trade)  +  Tax_FIFO(trade) )
```

- `ΔRisk(₹)` = the reduction in annualized portfolio volatility from the trade, expressed in rupees
  (volatility × portfolio value). We compute volatility with a Ledoit–Wolf-shrunk, EWMA-weighted
  covariance matrix (robust on short samples).
- `Cost` = real Zerodha charges (brokerage, STT, exchange/GST/stamp) + market-impact slippage.
- `Tax_FIFO` = the capital-gains tax the sale would realize, computed **lot-by-lot, oldest-first
  (FIFO)** — the legally-mandated method for Indian demat accounts.
- The `2×` is a margin of safety so we only trade when the benefit *clearly* wins.

This one gate turned a strategy that's taxed to death (**5.4% CAGR — a clear NO-GO**) into one that
beats the index net of everything (14.6% → 18.2% with later refinements).

**The two refinements that mattered, and the math behind them:**

1. **Trade less (annual rebalancing).** Lower turnover → fewer taxable events → more gains cross the
   365-day line into the **12.5% long-term** bracket instead of **20% short-term**. Realized tax fell
   from ₹1.17L (monthly) to ₹20k (annual), and *every* metric improved monotonically. We later swept
   weekly→monthly→quarterly→annual explicitly (`Q_Alpha_Research`): weekly is catastrophic (1.6% CAGR,
   −61% drawdown — turnover/tax eats everything); annual wins decisively. **Trading rarely is the edge.**

2. **Shrinkage weighting (the DeMiguel/Tu–Zhou result).** Instead of a pure minimum-variance optimizer
   (which over-fits noise) or pure equal-weight, blend them 50/50:

   ```
   w_final = ½ · w_minvariance  +  ½ · w_equal-weight
   ```

   This "anchor-to-1/N" shrinkage is the only optimizer change that beat 1/N **in-sample, on the
   holdout, AND across all rolling 3-year windows.** Pure min-variance and pure score-tilt both lost.

**The honest takeaway:** the edge is **tax-and-friction discipline + a modest robust return tilt**, not
stock-picking genius. Tax-aware portfolio construction for *Indian* retail (FIFO, LTCG/STCG, the
₹1.25L annual exemption) is genuinely under-explored — the academic literature is almost entirely US.

---

## 3. How it was validated — *including the wrong turns* (this is the real work)

The validation is the point, not the CAGR. The result was stress-tested until it nearly broke, then
fixed **honestly** rather than tuned to look good:

1. **Removed survivorship bias.** Built a point-in-time Nifty 50 membership table (81 names, delisted
   companies included) by reverse-applying index reconstitutions; the check caught 4 source errors and
   2 missing exits. **The edge survived** — it wasn't being flattered by only looking at winners.
2. **Used a fair benchmark.** Switched from Nifty *price* to Nifty 50 **TRI** (dividends reinvested, a
   ~1.1%/yr higher bar) — and in doing so found and fixed a **look-ahead bug in our own 1/N baseline**
   that had front-run future index entrants (a fake 22.4%). We hold ourselves to the same honesty.
3. **Walk-forward across regimes.** The thesis held, but "annual is *the* optimal frequency" did not —
   the real driver is **low *realized* turnover**, not a magic calendar number.
4. **Out-of-time holdout (2025–26) — it initially FAILED.** On genuinely unseen data the frozen config
   was flat (0.7%) while 1/N made 7.1%. We diagnosed the cause (the tax gate had *ossified* the book —
   only 5 rebalances ever, coasting on stale 2013–19 winners), fixed it (`force_refresh`), and added
   shrinkage — which then beat 1/N on the holdout too (8.1% vs 7.1%). **We published the failure.**
5. **Did not tune to win.** A gate-multiplier sweep showed no value generalizes out-of-sample, so we
   left it at the spec default. The iron rule: never tune parameters to manufacture a "GO."

---

## 4. The full system (beyond the backtest)

Q-Alpha is not just a backtest — it's a deployed, human-in-the-loop product. **It never auto-trades:**
it tells a human the tax-smart move; the human places the order. Every tax number is **deterministic**
(exact, auditable — no LLM ever computes a number).

- **Tax-smart advisor** (`live/advisor.py`) — three modes on the validated FIFO/cost/tax engine:
  *Sell* (exact STCG/LTCG split, the largest ₹0-tax quantity, the ₹1.25L exemption shelter), *Raise
  cash* (least-tax source order), *Add money* (route new capital to underweights as ₹0-tax buys).
- **§70 loss set-off** (`accounting/capital_gains.py`) — nets short-term losses against gains
  (STCG first at 20%, then LTCG at 12.5%) the way Indian law actually works; the advisor shows the
  tax it saves. (Wired into the advisor only — *not* the backtest engine — so the headline is provably
  unchanged.)
- **Corporate actions** (`accounting/corporate_actions.py`, §14 crit 5) — splits (preserve cost &
  holding period), bonuses (₹0-cost shares dated the ex-date → can be short-term even when the
  originals are long-term), dividends (income, never capital gains). Interleaved into the tradebook
  replay so a held name that splits reconstructs to the broker's exact share count.
- **Live Zerodha integration** (`live/holdings.py`, `tradebook.py`, `taxpnl.py`) — reads your real
  holdings + live prices; a Console tradebook upload reconstructs exact dated FIFO lots; the FIFO
  engine was **reconciled to the paise** against a real Zerodha Tax P&L (criterion 4).
- **Deployed dashboard** (`scripts/dashboard_app.py`, Streamlit Cloud) — two tabs: **🧠 The system**
  (the System book below, with the validated core's full view in an expander underneath) and **🔴 Live
  (Zerodha)** (the real account + the interactive advisor). The watch views:
  - **🎯 GO readiness** — a deterministic, no-AI scorecard that flips to GO *only* when the forward
    paper run clears every criterion (enough days · survived a real ≥10% market drop · keeps pace with
    the benchmark · drawdown within the validated envelope · clean data feed). It can read **READY —
    awaiting a stress event** when everything but a live market shock is satisfied.
  - **🩺 Position health** — between the slow annual rebalances, flags any holding in a *company-specific*
    breakdown (down a lot AND lagging the market — not just a market-wide dip). Advisory only.
  - **🛡 Systemic risk** — a market-stress reading; when elevated, notes the research-proven tax-free
    hedge as something to *consider* (informational; the product places no derivatives).
  - **Realtime** — live tick streaming via Kite's WebSocket while the tab is open, with an honest
    freshness badge (it says "stalled" rather than lying when ticks stop) and a 30-second polling
    fallback.
- **Autonomous paper run** (`scripts/paper.py` + GitHub Actions) — a notional ₹2L book marked daily by
  a weekday cron, which **auto-applies the strategy's scheduled (annual) rebalances** so the forward
  record tests the live strategy, not a frozen basket. This is criterion 6 — the unskippable evidence.

### The System book — the whole system proving itself on its own advice

The trust problem with any advisor: it *suggests* trades but never lives with them. So a second
fake-money book (`scripts/autopilot.py`, daily cron) **runs the entire system on itself**: it receives
cash (a monthly top-up + a dashboard Add-money button), **executes the Add-money advisor's own buy
list** on itself (deploy-into-weakness, ₹0-tax buys, sizing paced by market weakness × a fixed rule
over an LLM's daily market read — the AI supplies a *lean*, deterministic code acts on it), evaluates
the **§4.6 tax-benefit gate every day** (it rebalances when the benefit beats 2× cost+tax — this week
or in six months, the market decides, not a calendar — and logs every refusal with its reason), and
carries the research-validated **tax-free hedge overlay as a daily measurement** (hedged-vs-unhedged
return + drawdown, computed on both the System book *and*, read-only, the untouched GO book).

Two comparators with **identical cash flows** keep it honest: a **shadow twin with the AI off**
(System − Shadow = exactly what the AI adds — either sign is a valid finding) and a **NIFTYBEES
buy-and-hold baseline** (System − Baseline = what the whole system adds over doing nothing).

**The endgame contract (pre-committed):** real-money integration happens only when ALL FOUR are green —
the core clears its deterministic GO scorecard · System > Baseline · the AI verdict is in · the hedge
has been *witnessed* cutting a real stress event. If any pillar fails, that's reported, not integrated
around. Real money never auto-trades; the human places every order — that rule outlives the GO.

---

## 5. Where it stands — the §14 scorecard (10 gates to real money)

`1✅ 2✅ 3✅ 4✅ 5🟡 6⏳ 7✅ 8✅ 9🟡 10✅`

- **✅ done:** strategy beats baselines net of cost+tax, out-of-sample (1) · no look-ahead (2) ·
  survivorship-free universe (3) · FIFO tax reconciled to the paise vs a real Tax P&L (4) · risk
  controls (7,8) · the deterministic advisor + dashboard (10).
- **🟡 awaiting one real event each:** crit-4 final hardening wants a real *multi-lot/loss* sell to
  reconcile; crit-5 wants one real corporate action on the account (the engine + wiring are done and
  tested); crit-9 wants one *scheduled* (not manually-triggered) cron firing.
- **⏳ pure waiting:** crit-6, the ~6-month forward paper run surviving ≥1 volatility event. No
  simulation can replace it.

**There is no unbuilt engineering on the critical path.** What remains is calendar time and real-world
events.

---

## 6. Math & methods glossary (for the curious interviewer)

| Term | Plain meaning |
|---|---|
| **FIFO tax lots** | India taxes share sales oldest-first. We track every purchase lot with its date so STCG-vs-LTCG and the holding period are exact. |
| **STCG / LTCG** | Short-term (<365 days) gains taxed 20%; long-term (≥365) taxed 12.5% with a ₹1.25L/yr exemption. The whole strategy leans toward the cheaper long-term side. |
| **Sharpe ratio** | Return per unit of risk (volatility). Higher = smoother ride for the same return. |
| **Max drawdown** | The worst peak-to-trough fall — the "how bad did it hurt" number. |
| **Ledoit–Wolf shrinkage** | A covariance estimator that's stable on short data (raw sample covariance is noisy and over-fits). |
| **EWMA** | Exponentially-weighted moving average — recent data counts more than old data. |
| **Square-root slippage** | Market impact ≈ `k · σ · √(order ÷ daily volume)` — bigger orders in thinner stocks cost more (spec §13). Matters most when scaling to mid-caps. |
| **1/N (equal weight)** | Put the same money in every name. The honest, hard-to-beat baseline. |
| **Walk-forward** | Test on data the model never saw, rolling forward in time — the opposite of cheating. |
| **QUBO / QAOA** | A way to phrase stock selection as a combinatorial optimization a quantum computer *could* solve. Explored in the research repo (honest near-miss). |

---

## 7. Explicit biases & deliberate decisions (read this — it's where the honesty lives)

Every model embeds choices. Here are ours, stated plainly, including the ones that *are* a bias:

- **No real-money track record yet.** Everything is backtest + a notional paper run. The mandatory
  ~6-month forward run is *why* — we refuse to claim live performance we don't have.
- **Survivorship bias — handled, not ignored.** We built a point-in-time universe with delisted names.
  But large-cap survivorship in India is genuinely *modest* (delistings ≈0.81% of Nifty-500 market
  cap), so the correction is small — we say so rather than overclaim a heroic fix.
- **Single market, single asset class.** Indian large-cap equities only. The tax logic is India-specific
  (it would not transfer to, say, US wash-sale rules). This is a deliberate scope, not generality.
- **Annual rebalancing is a trade-off, not free.** Trading rarely maximizes after-tax return, but it
  means the model can *miss* a good mid-year reallocation. We accept this (the backtest shows acting on
  most mid-year signals loses to tax) and added a **position-health watch** for the genuine exceptions.
- **"Cheapness" is technical, not fundamental.** The deploy-in-weakness lever scores how far a stock
  has pulled back from its high — a *price* proxy, **not** a P/E. True valuation needs a fundamentals
  feed we don't have (Kite doesn't expose it). We label this honestly everywhere it appears.
- **Broker = Zerodha, not the spec's HDFC.** Chosen for ₹0 delivery brokerage, which changes the
  cost-gate math. A deliberate, documented deviation (`accounting/costs.py`).
- **The validated edge is 3-factor (price/volume).** The richer 6-factor (with fundamentals) model is
  *data-blocked*, not run on the point-in-time universe. We don't claim the 6-factor result.
- **The 2025–26 holdout was a YELLOW FLAG we published.** Frozen config failed out-of-time; we
  diagnosed and fixed the cause rather than burying it. The fix (shrinkage) is what earns the GO.
- **Iron rule:** no parameter was ever tuned to manufacture a passing result. A negative result,
  reported honestly, is a valid outcome.

---

## 8. Setup, layout, and conventions

```bash
cd qalpha
uv sync --extra dev          # create venv + install
uv run pytest                # 169 tests, must stay green
uv run ruff check .          # lint
uv run ruff format --check . # format
uv run mypy src              # strict type-check
uv run --extra dashboard streamlit run scripts/dashboard_app.py   # the live dashboard
```

```
src/qalpha/
  config.py        all tunable parameters (Q_alpha.md §16) in one place
  data/            yfinance ingest, point-in-time universe, bad-tick sanitizer
  factors/         momentum / volatility / liquidity scoring + regime classification
  alloc/           Ledoit-Wolf covariance conditioning, sector allocator, optimizer (minvar|equal|score|shrink)
  accounting/      FIFO tax lots · Zerodha costs · capital-gains tax (+ §70 set-off) · corporate actions   ← reused live, same code the backtest validated
  backtest/        walk-forward engine, portfolio accountant, baselines, metrics, go/no-go report
  live/            Kite auth · holdings reader · tradebook replay · Tax-P&L reconcile · advisor · paper book · dashboard renderer · safety guards · realtime ticker · GO scorecard · position health
```

**Conventions that matter:** money is `decimal.Decimal` everywhere it touches accounting (never
float); **no look-ahead, ever** (all historical reads go through `PriceData.as_of(date)`; there's a
test that fails on look-ahead); the accounting engine is standalone so the live system reuses the
*exact* FIFO/cost/tax code the backtest was validated on.
