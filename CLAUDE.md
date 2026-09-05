# CLAUDE.md

Guidance for Claude Code (and humans) working in this repo. **Rewritten 2026-09-04 from scratch** —
the previous version had accreted fifteen months of dated session logs and most of it was stale. This
file now describes *what is true*, not what happened. History lives in git and in `reports/`.

---

## 🛑 Read first

**₹5,00,000 of real money is in the user's Zerodha account** (since 2026-08-27): ₹1,00,000 opening
basket across 8 names, then ₹50,000/month. **He places every order himself. Nothing here has ever
auto-traded and nothing ever will.**

**He invested before the system's own gate opened, knowingly, with the evidence in front of him.**
Do not re-litigate that decision. Do not soften a red because money is committed. The honest framing
he was given and which still stands: *plan at the index's ~11–12%, treat the backtest's excess as
unproven upside, size the first year as tuition.*

**The GO gate is shut.** It reads **NOT YET, 0 of 12 months**, with four criteria at ⚪ CANNOT ASSESS
because nothing has checked them. Never describe this system as validated for real money.

### The user

Not a trader and does not want to become one. He wants a system that does the research and hands him
**one** of three things a day — `NO_ACTION`, `EXECUTE` (one bounded order to approve), or
`HUMAN_REQUIRED`. He wants to understand the maths as it is built (formula → example → why), not to
analyse earnings reports himself. Target architecture: **[PLAN_SYSTEM.md](PLAN_SYSTEM.md)**.

---

## The failure mode of this codebase

**Every serious defect found here has been the same defect: a number labelled as something it is
not.** Not arithmetic errors — the arithmetic is almost always right. The *label* is wrong, or the
*input* is wrong, on a surface where the label becomes an order.

Twenty-odd instances now. A few, so the shape is unmistakable:

| Said | Was |
|---|---|
| "ahead by ₹4,01,677 (+444%)" | ₹1,677 (+1.2%) — parked SIP cash counted as performance |
| "Deploy ₹100,000" | a ₹5,97,418 basket — 84% of the opening position in one stock |
| `BASELINE_EW`, the equal-weight fund | NIFTYBEES minus a fee — *easier* than the do-nothing baseline |
| "the hedge costs 21.5% of ×286.2 terminal wealth" | ×8.4 — the ×286 was 13 years of deposits compounded as returns |
| "worst fall −34.9%, drawdown matches the index" | **−47.5%**, eleven points *deeper* than the index |
| a veto citing a source URL | a stock **quote page**, evidencing nothing |
| `NIFTY_LOT_SIZE = 75` | 65 — stale three days after its own "verify this" comment was written |

**700+ passing tests have caught none of them.** Unit tests verify that a function works. These are
failures of *integration* (the right data reaching that function), *methodology* (the function
answering the right question), and *operation* (the scheduled process actually running). You need all
four and only one is cheap.

### Three rules that follow

1. **When you fix a defect, grep for every other caller of the thing you fixed.** Twice now a correct
   fix was applied at one call site and reasoned about as if applied to a concept.
2. **A test that asserts a source line pins that line's bug in place.** Assert the *property*. One
   test asserted the literal call that caused the +444% defect — the suite would have gone red if
   anyone had fixed it.
3. **When a number looks wrong in your own scratch run, chase it before explaining it away.** The
   ₹5,97,418 basket was hit during an audit, written off as a harness mistake, and moved past. It was
   both.

---

## Iron rules

- **Real money never auto-trades. The user places every order.** Outlives every gate here.
- **Rule (a): the validated backtest headline and its engine are frozen.** No change may touch
  `src/qalpha/{backtest, accounting, data, config}` for a live feature. Verify with
  `git diff --name-only main -- src/qalpha/backtest src/qalpha/accounting src/qalpha/data src/qalpha/config.py`
  — it must print nothing.
- **Unknown is never substituted.** Missing price ≠ previous price. Missing filing ≠ no bad news.
  Missing AI response ≠ approval. Absent null ≠ threshold of zero. Unknown produces
  `CANNOT ASSESS — NO ACTION`.
- **A number on a real-money surface must be labelled as the thing that was computed.**
- **Audit with idle cash in the portfolio.** A zeroed fixture hides an entire class of defect.
- **Never tune a parameter to manufacture a GO.**
- **Pre-registration before any experiment; negatives get published.**
- **Flag, don't veto** on the buy list — user decision, still standing. Selection stays deterministic.
- **All four gates green before every commit**: `ruff`, `ruff format`, `mypy --strict`, `pytest`.
- **Always branch + PR.** The harness blocks self-merges; the user clicks merge. Merging to `main`
  auto-deploys Streamlit.

---

## What is true today (2026-09-04)

**23,169 lines · 42 live modules · 703 tests green.**

### The forward experiment — twin run 2

The only clean evidence route this system has. Window **opened 2026-09-01**, closes twelve months
later. Pre-registration: **[reports/PREREGISTRATION_TWIN_RUN2.md](reports/PREREGISTRATION_TWIN_RUN2.md)** —
frozen, amendments recorded before the window opened.

Seven books on **identical cash flows** from the user's real tradebook (`assert_identical_flows`):

| Book | 2026-09-03 | Note |
|---|---:|---|
| REAL | ₹3,01,643 | his own orders, replayed |
| TWIN_FULL | ₹2,96,359 | everything on |
| TWIN_NO_AI | ₹2,96,354 | **differs by ₹5 — the ablation is alive** |
| TWIN_NO_EXITS | ₹2,96,239 | |
| TWIN_NO_HEDGE | ₹2,96,359 | **identical to FULL — see below** |
| BASELINE_EW | ₹2,99,383 | PIT equal-weight fund, net fee — **the only gating comparison** |
| BASELINE | ₹3,00,984 | NIFTYBEES, reported never gating |

**The gating statistic** is log relative wealth of **unitized NAVs**:

$$G = \ln\frac{\mathrm{NAV}_{\text{TWIN\_FULL}}}{\mathrm{NAV}_{\text{BASELINE\_EW}}}$$

Raw book values are *not* contribution-invariant — identical deposits dilute a ratio rather than
cancelling in it ($\ln(110/100)=0.095$ but $\ln(210/200)=0.049$), so a monthly SIP would walk the
statistic toward zero. Unitized NAVs are invariant by construction (`live/nav.py`).

`NULL_P95_LOG_REL_WEALTH` is **`None`** — the matched null has not been generated, so criterion 3
reads ⚪. Its specification is frozen; computing it later cannot be tuned to the result.

**The record is append-only.** `data/twin/history.jsonl` (one row/day: every book's value, net
invested, XIRR, the gate) and `data/twin/ai_verdicts.jsonl` (every AI attempt *and* verdict, with
`price_at_decision`, model, prompt version). Both refuse any write that would shrink the file. Before
these existed, `marks.json` was rewritten daily and no book had a history at all.

### The AI

Deterministic screen generates → **the AI may only veto** → deterministic code sizes and executes
survivors. Fake money only. Guards are structural, not prompted: it **cannot add a name**, **cannot
size anything**, **cannot fail closed** (any failure keeps the whole basket), **cannot act
unrecorded** (a failed provenance write discards the verdicts), and **cannot veto without a primary
citation**.

**First real veto: 2026-09-03, ADANIENSOL**, for "U.S. bribery charges against chairman" — citing a
**stock quote page**. The rule then in force checked that a URL was *present*, not that it *supported
the claim*. A veto now acts only on `nseindia.com` / `bseindia.com` / `sebi.gov.in` / `ibbi.gov.in` /
`mca.gov.in`. Reporting *about* a filing does not count. A demoted veto is recorded as a lead.

Model `claude-haiku-4-5`, prompt version `PR-8b`, **frozen for the run** — a model or prompt change is
a second treatment and would require re-registration.

### The hedge — signal only, and this is not a bug to fix

`runner._hedge` emits `HEDGE_ON`/`HEDGE_OFF` and **moves no money**, so `TWIN_FULL − TWIN_NO_HEDGE`
is **₹0 by construction** and is *never* evidence about hedging. This is not an oversight: one Nifty
futures contract is **65 index units** (verified 2026-09-04; NSE rebaselined at end-Dec 2025), so at
index ~27,574 one lot is **₹17.9L** of notional and hedging half a book needs

$$V_{\min} = \frac{\text{lot} \times \text{index}}{h} = ₹35.8\text{ lakh}$$

against a ₹3L book. `hedge_availability` reports this on every hedge decision, so the ₹0 is
*explained*. **Re-verify `NIFTY_LOT_SIZE` before quoting any rupee figure from it.**

### The pre-trade governor (Phase A, in flight)

- **`live/governor.py`** — sector concentration measured on the **resulting book**, not the basket.
  The 30% cap was applied to the names chosen *that round*; at slider 3–4 a 30% cap cannot bind
  (three names ⇒ one is 33%), so twelve individually-compliant SIP baskets compound to a **36.9%
  POWER** book. Kite nudges on holdings at 50%; our cap was stricter on paper and weaker in practice.
- **`live/valuation.py`** — current P/E and market cap, threshold **the exchange's own P/E > 50**.
  A check, never a factor: it does not re-rank or re-select.

---

## What is proven, and what is not

**Proven:**
- The FIFO/cost/tax engine reconciles to **₹0.00** against a real Zerodha Tax P&L (one sale:
  single-lot, all-STCG, no loss).
- Trading less beat trading more, net of cost and tax, across walk-forward sub-periods.
- Equal-weighting explains most of the apparent edge over the cap-weighted index.
- Selling to manage risk **loses to the tax** — the §4.7 exits finished ₹74.8 lakh behind
  buy-and-hold over 13 years and paid ₹13.3 lakh in tax to do it.

**Not proven — state these plainly whenever the numbers come up:**
- **The headline is not out-of-sample.** `shrink` was selected by requiring it to beat 1/N *on the
  2025–26 holdout* (`scripts/exp_breadth.py:104`), which makes the holdout validation data. README §5
  still claims `✅ out-of-sample` for gate 1. **That claim is wrong and should be corrected.**
- **The screen the real money runs has never been backtested out-of-sample at all.**
  `advise_deploy_into_weakness` shares no selection code with the validated funnel.
- **The screen's worst backtested fall is −47.5%, deeper than the index's −36.3%** (peak 2018-01-08 →
  COVID trough 2020-03-23). The extra return is bought with extra risk. He runs it with no stop-loss.
- **"Tax-aware execution" overstates what runs.** `force_refresh=True` short-circuits the §4.6
  net-benefit gate, so tax is *charged* but the gate never decides. Low turnover comes from the
  annual cadence.
- **`weighting="score"` silently collapses to equal weight** — `_cap_renorm` clips 0–100 scores to a
  0.20 cap before normalising. So `exp_breadth` tested five variants, not six.
- **Sharpe assumes rf = 0.** Immaterial to the comparison (the benchmark is computed the same way),
  inflated as an absolute number.
- **The reports do not reproduce day to day.** Identical code on a re-downloaded panel moved the
  Phase-4 exits leg by ₹6.8 lakh. Until input hashes are pinned, treat every rupee figure as good to
  about half a percent.
- **Most of the tax engine has never met a broker statement** — multi-lot, LTCG, loss set-off and
  §112A are unit-tested and unconfirmed. **The first such real sale must be reconciled afterwards.**
- **No corporate action has ever been reconciled live.**
- **Nobody has watched this system fall.** Every live day so far has been calm.

---

## The operating contract the user actually runs

Open dashboard → Kite login (daily, one tap — there is **no** compliant unattended token) →
**Add money, type the amount** (a hard budget) → **slider 8 for the opening ₹1,00,000, 3–4 for the
monthly ₹50,000** → place every order himself in Kite, **CNC/delivery, no stop-loss, no target** →
**upload the tradebook after every batch** (Console → Reports → Tradebook; de-duped on Zerodha trade
IDs, so overlapping ranges are safe). Money for future instalments **stays in the broker account**.

**No stop-loss, and it is load-bearing:** the screen buys names that are *down*, so a stop sells
exactly what it just bought, realises a loss, triggers tax, and fires on ordinary volatility. The exit
is the §4.7 breakdown test, which distinguishes a name-specific fall from the market falling. A stop
cannot. *If* a news/catalyst sleeve is ever built it gets its own stops — a catalyst thesis
invalidates in days — but that is a separate sleeve with a separate mandate, never a rule applied to
the core.

---

## Architecture

```
data/         yfinance→Parquet panel · point-in-time universes · Screener fundamentals
factors/      momentum · volatility · liquidity (+ value · quality · dividend) · regime · scoring
alloc/        Ledoit-Wolf+EWMA conditioning → sector allocator → optimizer
accounting/   FIFO lots · Zerodha costs · capital gains (§70 · §74 · §112A · cess) · corporate actions
              · slippage.  FROZEN (rule (a)); reused live so the live path and backtest share one engine
backtest/     walk-forward engine · portfolio · baselines · metrics · significance · runstore
              decision.py = the shared decide_rebalance the live runner also calls
live/         advisor (sell/raise-cash/deploy/harvest) · deploy (the buy screen) · position_health
              price_integrity · cooling_off · satellite · valuation · governor · hedge · nav
              twin · runner · policy · go_gate · verdicts · ai_brief · track_record · measures
              safety · scan · notify · auth · client · holdings · tradebook(+store) · taxpnl · ticker
scripts/      twin.py (the cron) · paper.py · advisor.py · dashboard_app.py · backtest_* · exp_*
config.py     every tunable parameter in one place
```

Each rebalance: `as_of` slice (no look-ahead) → liquidity gate → factor scores under the regime's
weights → top-N → sector allocator → optimizer → tax-aware execution.

**Conventions.** Money is `Decimal` everywhere it touches accounting, never float. No look-ahead ever
— historical reads go through `PriceData.as_of(date)`; fundamentals carry a 90-day effective lag; a
test fails on look-ahead. Reuse before adding. Reference the spec by section (`§4.6`) in comments.

**What runs unattended** — `paper.yml`, weekdays 12:23 UTC: refresh prices → mark the paper book →
Telegram scan → AI brief → twin (`scripts/twin.py daily`: sync flows → AI verdicts → step books →
mark → gate → append history) → commit → **postcondition that fails loudly if today's mark is not on
file**. Everything else is `continue-on-error`, so without that check a green run could accrue
nothing for months.

---

## Commands

```bash
uv sync --extra dev
uv run pytest                                          # must stay green
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run python scripts/twin.py daily                    # the cron entry point
uv run python scripts/run_phase0.py                    # the validated backtest
uv run --extra dashboard streamlit run scripts/dashboard_app.py
```

**Auditing a live surface offline** — no Kite login, no Streamlit server. The account *shape* is the
point: **idle cash and holdings together**, because a zeroed portfolio hides an entire defect class.

```python
import sys; sys.path.insert(0, "scripts")
from datetime import date
from decimal import Decimal
import pandas as pd
from paper import _load_benchmark_series
from qalpha.config import Config
from qalpha.data.ingest import load_parquet
from qalpha.backtest.portfolio import Portfolio
from qalpha.live.deploy import advise_deploy_into_weakness

cfg = Config()
prices = load_parquet("data/historical/prices_watchlist.parquet")
wl = pd.read_csv("data/universes/nifty100_watchlist.csv")
sector_of = dict(zip(wl["ticker"], wl["sector"]))
watchlist = [t for t in wl["ticker"] if t in prices.adj_close.columns]

pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal("500000"))   # ← idle cash AND holdings
advice = advise_deploy_into_weakness(
    pf, Decimal("100000"), watchlist, sector_of, prices,
    _load_benchmark_series(), date.today(), max_names=8, spend_idle_cash=False,
)
print(advice.render())     # then check every rendered figure against what the code summed
```

⚠️ `scripts/paper.py refresh` refreshes **neither** the benchmark nor the watchlist panel. Call
`_refresh_benchmark()` and `build_nifty100_watchlist.py --prices` too, or you audit stale data.

**Secrets.** Repo Actions: `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GIST_TOKEN`.
Streamlit: `GITHUB_TOKEN` (contents:write), `GIST_TOKEN`, `KITE_*`, `APP_PASSWORD`. GitHub secrets are
write-only — never try to read them. Without `GIST_TOKEN` the twin cannot read the tradebook and
**correctly refuses to run** rather than marking a book with no flows.

---

## Open work, in order

1. **Correct the README's out-of-sample claim** (gate 1). Ten minutes; the claim most likely to
   over-authorise capital.
2. **Generate the matched null** (≥1,000 draws, spec frozen). Criterion 3 reads ⚪ until it exists.
3. **`Mandate` + `RiskGovernor.veto()`** — the operating contract from prose into an object.
4. **One golden-day replay** — data arrival → filings → recommendation → governor → approval → fake
   execution → costs → mark → reconciliation, asserting the final portfolio exactly. The only test
   shape that catches integration and operational defects.
5. **Exchange evidence spine** — corporate announcements poll, T2T / IRP / suspension / RE lists.
   Point the AI veto at filings rather than web search.
6. Raw prices for execution and FIFO basis · date-dependent tax rates · `_cap_renorm` · dataset hashes.
7. Only then: mid/small-cap, IPO, F&O — each a separate registered experiment with its own
   point-in-time universe. **No engine inherits another's authority.**

---

## Reading order for a new session

This file → **[PLAN_SYSTEM.md](PLAN_SYSTEM.md)** (target architecture) →
**[reports/PREREGISTRATION_TWIN_RUN2.md](reports/PREREGISTRATION_TWIN_RUN2.md)** (what is frozen and
why) → `README.md` (the front door, and note the out-of-sample claim above) → `Q_alpha.md` (the spec).

`../Q_Alpha_Research` is the **archive** — the hedge forward run and the published negatives (QUBO
×2, HMM overlay, LPPLS). The product does not import from it.

> Q-Alpha never asks to be trusted. It shows enough evidence that the decision can be checked — and
> it refuses to act when it cannot.
