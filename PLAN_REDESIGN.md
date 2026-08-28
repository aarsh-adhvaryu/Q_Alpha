# The redesign — one system, one repo, one honest test

**Decided 2026-08-28, the day real money went in.** Supersedes the GO scorecard, the System/Shadow
forward study, and the two-repo split. Nothing here is built yet; this is the pre-registration and
it is written **before** the first backtest, deliberately.

---

## 0. Why

The GO scorecard graded a paper book running the **validated funnel** — shrink-weighted, annual,
tax-aware rebalancing. **That is not the system in use.** The system in use is the deploy-into-weakness
advisor plus a health watch plus a hedge readout, which shares no selection code and no names with the
funnel behind the 18.2% headline. *Grading the thing you do not run, in order to authorise the thing
you do, is a category error.* Every criterion could have gone green without saying anything about the
money at risk.

Second, two repos guaranteed drift: the product could not import research, so anything research proved
could never be the thing that runs, and anything the product ran was never what research tested.

---

## 1. Architecture — the digital twin

**The real Zerodha account is the state source. A fake-money twin is the autonomous system. Nothing
autonomous ever touches Zerodha.**

```
   Zerodha tradebook (uploaded)
            │
            ▼                              HEADLINE
   FIFO ledger + dated lots                ┌─ TWIN-FULL   everything on, AI agentic, integrated
            │                              │       │
            ▼                              │       ├─ TWIN −AI      ablation: the AI's contribution
   cash flows ─────────────────────────────┤       ├─ TWIN −HEDGE   ablation: the hedge's
   (buys, sells, SIP instalments)          │       └─ TWIN −EXITS   ablation: the exits'
            │                              │
            │                              ├─ BASELINE    NIFTYBEES, do nothing
            └──────────────────────────────┴─ REAL        your orders, your judgement
```

**One integrated system as the headline; one-factor-removed ablations below it.** Every book receives
the same rupees on the same days, derived from your actual tradebook, so the only difference is who
decides. Each ablation removes **exactly one factor** from TWIN-FULL, so every gap is attributable to
one thing:

| Comparison | Answers | Gates? |
|---|---|---|
| **TWIN-FULL − BASELINE** | **Does the system beat doing nothing?** | **YES — criterion 3** |
| TWIN-FULL − (TWIN −AI) | What did the AI contribute? | no — descriptive |
| TWIN-FULL − (TWIN −HEDGE) | What did the hedge contribute? | no — descriptive |
| TWIN-FULL − (TWIN −EXITS) | What did the exits contribute? | no — descriptive |
| TWIN-FULL − REAL | Does autonomy beat your judgement? | no — descriptive |

**⚠️ Only the headline gates, and this is load-bearing.** Four comparisons at 95% confidence throw a
false positive roughly one run in five. If an ablation can also open the gate, the gate eventually
opens on noise. Ablations inform; they never authorise. The same rule voided forward run 1.

TWIN-FULL − REAL has never been asked before. It decides whether autonomy should ever graduate toward
the real account — **reported, never gated**: it is information about you, not a pass/fail on the
system.

### What the AI may do (the agentic boundary)

The AI is **integrated into doing**, not advising: on the twin it may act on **selection** (keep/drop
from the deterministic candidate set), **sizing** (how much of available cash now vs held), **timing**
(deploy or wait), **the hedge** (on/off) and **calling an exit**.

It may **not**, enforced in code and asserted by test, exactly as PR-8: invent a name outside the
deterministic universe; breach the 20% name / 30% sector caps; or **fail closed** — no response, no
key, an unparseable reply or a refusal all fall back to the deterministic path, so an AI outage
degrades TWIN-FULL to TWIN −AI rather than to nothing.

*This deliberately reverses PR-8's retirement of the size tilt.* That retirement existed so the run
tested exactly one treatment; under the ablation design TWIN −AI isolates the AI's **total**
contribution however many levers it pulls, so the constraint is no longer needed.

**Money-weighted throughout (XIRR).** A monthly SIP is not present for the whole window, so a
start-to-end percentage is not a rate. This is `live/track_record.py`'s existing contract, extended to
four books.

### What "autonomous" means on the twin

The twin runs the whole system with no human in the loop: rebalance on the tax gate, §4.7 breakdown
exits, the drawdown exit (§4), hedge on/off, de-risking, corporate actions, SIP deployment. It logs
every decision with its reason. **The real account does none of this automatically** — you place every
order, and the advisor is the only thing you touch.

---

## 2. The new GO gate

Replaces §14's criterion set. **All must hold; no criterion may be softened to reach a GO.**

| # | Criterion | Bar | Why this bar |
|---|---|---|---|
| 1 | Track length | **≥ 12 months** of real cash flows | Below this the comparison is dominated by entry timing, not selection — `MIN_MONTHS_FOR_A_VERDICT`, the same bar that voided forward run 1 |
| 2 | Volatility event | ≥ one **−10%** Nifty drawdown inside the window | Nobody has watched this system fall. Unchanged from the old gate, and still the criterion most likely to block |
| 3 | **TWIN-FULL** vs BASELINE | XIRR gap **exceeds the Monte-Carlo noise floor** (§5) net of cost + tax | A gap smaller than the noise is not a result. **The only comparison that gates** — ablations are descriptive |
| 4 | Tax reconciled | ≥ one **multi-lot or LTCG** sale matched to the Zerodha Tax P&L | Exactly one sell has ever been reconciled: single-lot, all-STCG, no loss |
| 5 | Corporate action reconciled | ≥ one applied live and matched to the broker | Never done. Demerger is not even modelled yet (§6) |
| 6 | Data integrity | Tradebook reconciles to broker holdings; no unexplained price gaps ungated | Off-market credits and demerger steps both break the ledger silently |

**Reported alongside, never gated:** all three ablations, TWIN-FULL − REAL, and the delivered vs
advertised sector/name caps.

---

## 3. What is archived

**Full reset, per decision 2026-08-28.** Archived under `data/archive/2026-08-28/` with a written
verdict, exactly as forward run 1 was:

- The ₹2L GO paper book (`data/paper/book.json`, start 2026-06-12, ~50 marks)
- Forward run 2 System/Shadow/Baseline (re-seeded 2026-08-18)
- The old GO scorecard and its dashboard tab

**These are published as evidence, not deleted.** The honest verdict on both: *the instrument was
measuring the wrong thing*, not *the strategy failed*. Neither ran long enough to say anything either
way, and criterion 2 never fired in any of them.

⚠️ **Cost of the reset, stated plainly:** forward evidence returns to zero on the day money went in,
and criterion 1 cannot be met before **August 2027**. That is the price of measuring the right thing.

---

## 4. The drawdown exit ("sell before too much loss")

Currently **absent by design** — CLAUDE.md argues a stop is load-bearing to omit, because the screen
buys names that are down, so a stop sells what it just bought, realises a loss, triggers tax, and
fires constantly on normal volatility. That argument is a hypothesis, not a measurement.

**Decision: backtest it, expose it as an option on the advisor, let the twin self-test it live.**

- **Backtest** as a pre-registered variant over the SIP window, against the §4.7 breakdown test alone.
  Measured net of cost **and tax** — a stop that wins gross and loses net is a losing rule.
- **Advisor**: an opt-in toggle. It reports "this position is down X% — consider exiting" and prices
  the exact tax. It never sells.
- **Twin**: TWIN-DET runs it live. If the backtest says it hurts, the twin still runs it, and the
  disagreement between backtest and forward is itself a finding.

Pre-registered thresholds, fixed now so they cannot be fitted later: exit at **−20%** from entry on a
name whose §4.7 test also reads breaking; **−30%** unconditionally. One variant, not a grid.

---

## 4a. Selling: least tax, and the gate that decides whether to sell at all

**₹0 tax is a special case, not the objective.** Zero exists only on loss lots and on long-term gains
inside the ₹1.25L exemption — for this account, nothing until **August 2027**. A rule gated on ₹0
would be a sell rule that cannot fire.

**Two separate mechanisms, both kept:**

1. **Whether to sell at all — the §4.6 net-benefit gate.** Trade only when the benefit exceeds cost +
   tax. This is the larger lever by far: it is what produced **18.5% against 15.2%**, and it is the
   reason low realised turnover is the validated edge. Every autonomous sell on the twin passes it.
2. **How to sell, once decided — least tax.** `advise_raise_cash` ranks by tax-per-rupee, takes the
   free portion first (loss lots, then LTCG inside the exemption), then the cheapest taxed lots, and
   states the ITR figure. Rebuilt on the ITR basis 2026-08-28.

Least tax is *execution*. The gate is *decision*. Confusing the two is how a system talks itself into
turnover it cannot afford.

## 4b. The hedge — what it is for, and why it is twin-only for years

**The purpose:** in a crash, the two ways not to lose are selling and hedging, and Indian tax decides
which works. Selling realises 20% STCG to avoid a loss that mostly recovers — the research HMM
sell-overlay tested exactly this and **lost**. Hedging keeps every share (₹0 capital gains) and shorts
index futures at ratio `h` (0.5) of book value while the stress gauge is elevated. Measured on the
validated book: **COVID drawdown ≈ −25% → −10% with ~no return given up.** *The tax is always the
killer; hedge, don't sell.*

**It is not free:** 0.03%/side, 0.05% monthly roll, and **30% F&O business-income tax on hedge
gains** — F&O is business income in India, not capital gains, and `hedge.py` models this. Cheaper
than selling, not costless.

### ⚠️ It cannot be placed on the real account for years — lot size

`apply_futures_hedge` uses `notional = h * pv`, a **continuous fraction of book value: no lot size, no
margin**. Correct for a fake-money twin; not how futures trade.

| | |
|---|---|
| Nifty futures lot size | **75** |
| One lot notional at Nifty ~25,500 | **≈ ₹19.1 lakh** (margin ~₹2.5L) |
| Equity book, 2026-08-28 | ~₹3,00,000 |
| Hedge wanted at h=0.5 | ₹1,50,000 |
| **Smallest purchasable hedge** | **₹19,10,000 — 12.7× the hedge, 6.4× the book** |

Real-account feasibility begins at **~₹19L** (h=1.0) or **~₹38L** (h=0.5) — roughly **2 and 4 years**
at ₹50,000/month. Options are the realistic small-account alternative (premium, not margin) but are a
different instrument with different behaviour; `hedge.py` models futures only. Not built now.

**Therefore: hedge is TWIN-ONLY, and that is the point, not a limitation.** The twin can carry a
fractional notional the real account cannot, so it is the only place this can be tested at current
size — and by the time the book can place the trade, there would be years of evidence. The `−HEDGE`
ablation (§1) measures its contribution; criterion 2 (a −10% event) is what makes the measurement
mean anything.

**Two standing caveats:** the gauge is **coincident, not predictive** — it fires at 15% drawdown, so
it caps the back half of a fall rather than dodging it. And it has **never been witnessed firing**
(endgame pillar 4, still zero).

## 4b-i. Can the hedge scale down to a ₹3L book? No — and cash is the only thing that can

**Asked 2026-08-28:** *"what if we scale the hedge for our scale, dynamic with the portfolio?"*

**No derivative scales below ~₹15L notional in India.** SEBI raised the minimum index-derivative
contract size to **₹15 lakh** in October 2024, explicitly to keep small retail out of F&O. The floor
binds every instrument, so it is not a futures-specific problem to route around:

| Instrument | Lot | Notional (current levels) |
|---|---|---|
| Nifty futures **and options** | 75 | ≈ ₹19.1L |
| BankNifty | 30 | ≈ ₹17.1L |
| FinNifty | 65 | ≈ ₹17.5L |
| MidcpNifty | 120 | ≈ ₹15.6L |
| Sensex | 20 | ≈ ₹16.6L |

**Options were the obvious escape and they do not survive the arithmetic.** Delta-sizing normally
gives fractional exposure and gamma scales the hedge up as the market falls — precisely the dynamic
behaviour wanted. But one put still controls ₹19.1L and the premium is paid on that whole notional: a
5% OTM monthly put is roughly **₹9,000–13,500 ≈ 3–4.5% of a ₹3L book, per month**. The portfolio would
be paid away hedging it.

### The one hedge that scales: not deploying

Withholding a contribution has **no minimum size, no margin, no premium and no tax**. It is infinitely
divisible and works identically at ₹3L and ₹3Cr. It is also the user's original "freeze the assets"
idea in the form that works — *trimming* means selling and is taxed (§7); *withholding new money*
reduces exposure with no taxable event at all.

**⚠️ It contradicts a rule already in production, and that conflict is the point.** The buy screen's
pre-committed policy is *deploy 50% of idle cash on elevated weakness, 100% on deep* — buy harder as
the market falls. Cash-withholding says hold back when stress is elevated. One is a mean-reversion
bet, the other a trend bet; **they cannot both be right**, and only the first has ever been tested.

**Therefore, as a hedge-family ablation on the twin (descriptive, never gating — §1):**

| Variant | Feasible at ₹3L? | Tests |
|---|---|---|
| `−HEDGE` | — | the futures overlay's contribution (real from ~₹19L) |
| `+CASHHOLD` | **yes, today** | withhold deployment while the gauge is elevated |
| `+DEPLOYHARDER` | **yes, today** (current behaviour) | the existing pre-committed tranche policy |

`+CASHHOLD` vs `+DEPLOYHARDER` is the cleanest question in the whole design: two opposite,
pre-committed responses to the same signal, on identical cash flows, settled by data rather than by
argument. **Both are implementable on the real account immediately** — unlike every other hedge — so
whichever wins is directly actionable rather than parked until ₹19L.

## 4c. Cash flows — the tradebook is the only source

**There is no SIP schedule.** The user invests whatever amount he chooses, places it in Zerodha, and
uploads the tradebook; those trades become the dated cash flows every book receives. No book is ever
funded on a calendar.

This is load-bearing for the comparison: **all five books must see the same rupees on the same days**,
so the only difference between them is who decides. A scheduled injection that the real account did
not actually receive would silently break that, which is the flaw that voided forward run 1's
predecessor. The tradebook is the single source of truth; if it says nothing arrived, nothing arrived.

## 5. Monte Carlo — what it is for, and what it is not

You asked for Monte Carlo / GBM to improve the advisor. **It cannot do that, and using it that way
would be the most dangerous thing in this plan.** GBM assumes lognormal returns with constant
volatility: no fat tails, no volatility clustering, no regimes — precisely the features that decide
whether a strategy survives. Simulating from GBM and tuning against it produces a system fitted to a
market that does not exist.

**What simulation is genuinely for here, and what it will be used for:**

1. **The noise floor (criterion 3).** Block-bootstrap the historical return panel (preserving fat
   tails and autocorrelation, which GBM discards), replay the full system on each path, and take the
   distribution of TWIN-FULL − BASELINE. **The 95th percentile of that distribution under a null of
   "no skill" is the bar the live gap must clear.** This is the single most valuable thing simulation
   gives you, and the current design has no equivalent — forward run 1 was voided precisely because
   nobody knew how big a difference had to be to mean something.
2. **Drawdown expectation.** What does the worst 5% of paths look like? That is what you should be
   sized for, not the mean.
3. **Position sizing and freeze thresholds** (§7).

**Method: block bootstrap, not GBM.** Stationary bootstrap with expected block length ~20 trading
days. GBM is available for comparison only, and its results are never used to set a parameter.

---

## 6. What must be backtested, and what is already known

| Component | Status | Action |
|---|---|---|
| Factor funnel (18.2%) | ✅ validated, in-sample + holdout + rolling 3y | Untouched. Rule (a) still holds |
| Buy screen (SIP) | ✅ backtested 2026-08-20: **+209.7% vs NIFTYBEES +126.3%** | ⚠️ The live screen still says *"never backtested"* — stale label, fix immediately |
| §4.7 breakdown exit | ❌ never backtested as an exit rule | §6.2 walk-forward threshold calibration — the two conditions currently collapse into roughly one |
| Drawdown exit | ❌ does not exist | §4 |
| Hedge overlay | ⚠️ backtested in research, never integrated | Move into the product, re-run inside the composite |
| Rebalance timeline | ⚠️ `rebalance_freq="ME"` + tax gate vs the headline's annual | Re-test the cadence **inside** the composite, not standalone |
| Optimizer / sector alloc | ⚠️ tested standalone | Re-test inside the composite |
| Composite (all of it) | ❌ **never** | The main event |

**The composite is the point.** Every component above has been measured alone. None has been measured
together, which is the only configuration that has ever been run with money.

**Pre-registration discipline:** one variant per question, thresholds fixed in this document before the
first run, negatives published. The temptation to tune until it looks good is now materially stronger
because real money rides on the answer — that is exactly when the discipline matters.

---

## 7. Position-level dip management — RESOLVED: no trim, harvest losses instead

**Asked for:** *"there won't be huge crashes all the time, but there will be things affecting smaller
parts of it — understand the dips, handle the current assets wisely, buying a few stocks of a company
or selling, such that it doesn't affect much in the dip but helps in the rise."* That is harvesting the
rebalancing premium at position level: add on weakness, trim on strength.

**Decision (2026-08-28): the add half is kept and already exists; the trim half is NOT built.**

**The decisive reason: the SIP is already the rebalancing mechanism, and it is free.**

| Lever | Redirectable per month | Tax |
|---|---|---|
| ₹50,000 SIP on a ₹3L book | **16.7% of the book** | **₹0** |
| ₹50,000 SIP on a ₹9L book (one year on) | **5.6%/month ≈ 67%/yr** | **₹0** |
| Trimming 5% of the book | 5%, once | 20% STCG on the gain |

New money moves more weight per month, tax-free, than any trim could. A name that runs to 25% is
de-concentrated by *not feeding it* — the SIP dilutes it without a single taxable event.

**Two supporting reasons.** (1) A continuous trim rule is mechanically the monthly row of the only
robust finding this repo has: monthly 15.2% / Sharpe 0.92 **NO-GO** against annual 18.5% / 1.13
beating TRI *and* 1/N, with every metric improving monotonically as turnover fell. The premium being
chased is 0.5–1.5%/yr **gross**, plausibly negative after 20% STCG and charges. (2) Under the ₹0-tax
constraint the user would want, it cannot fire at all before **August 2027** — every lot is short-term
until then, so only loss lots qualify. It would be a continuous trading mechanism switched off for its
first year.

**What is kept:** the add-on-dips half, which already exists — `advise_deploy_into_weakness` tilts new
money toward pulled-back names and tops up positions already held. Strengthening *how the SIP is
directed* is the real version of this idea, and it costs nothing.

**What is built instead: tax-loss harvesting.** §70 set-off and §74 eight-year carry-forward exist in
the tax computation; `capital_gains.py:137` calls harvesting itself "deferred past Phase 0", and no
surface ever says *"these positions are at a loss; realising them before 31 March banks a loss you can
carry forward eight years."* It is free (the sale is a loss), it is the one selling behaviour that
earns its turnover, and it is what the trim instinct should become.

**Sunset condition — this is "not yet", not "never".** Revisit trimming when the SIP falls below
**~1% of book value per month** (≈ a ₹50L book, roughly 2032 at ₹50,000/month). Past that the inflow
is no longer enough to rebalance with, and a trim starts to pay for itself.

---

## 8. Repo consolidation

**One product repo. Research becomes the place ideas live *before* they pass.**

| Moves into the product | Stays in research |
|---|---|
| Hedge (`exp_hedge*`, `hedge_paper`) | QUBO / quantum (unproven) |
| Regime + fragility gauge | LPPLS (unproven) |
| `system_check` → merged dashboard | Anything not yet through a pre-registered test |

**Graduation rule:** code moves into the product **only** when a pre-registered test on it passes.
Nothing in the product imports research — that stays true, but now it means something, because passing
is the only way across.

---

## 9. Phases

| # | Phase | Deliverable |
|---|---|---|
| 0 | **Pre-registration + archive** | This document; old books archived with verdicts; stale scope note fixed |
| 1 | **One repo** | Hedge + regime moved in, one engine, one test suite, CI green |
| 2 | **The twin** | Tradebook → real book → three parallel books on identical cash flows |
| 3 | **Autonomy** | Hedge, de-risk, exits, rebalance + **tax-loss harvesting** running unattended on the twin, every decision logged with its reason. **Twin-only until measured** — the advisor is unchanged, exactly as the AI selector was handled |
| 4 | **Backtest** | Bootstrap noise floor, drawdown-exit variant, rebalance cadence, optimizer, composite |
| 5 | **New GO gate** | Six criteria live; dashboard shows four books and the three gaps |
| 6 | **Frontend** | Decided *after* the engine is right — see below |

**Frontend, deferred deliberately.** Your engine is Python + pandas + parquet and your state is files
in git. Vercel is stateless serverless: it needs a persistent Python service, a database to replace
the file state, and a real callback + secret store for the daily Kite login. That is the correct
end-state architecture if this becomes a product, and it is weeks of work producing **zero new
investment insight**. Today's audit found six defects where a confident surface showed a wrong number.
A better-looking surface is the last thing that should move.

---

## 10. What does not change

- **Real money never auto-trades.** The twin is fake money. You place every real order. Reaffirmed,
  not relaxed — the autonomy lives entirely on the twin.
- **Rule (a):** the validated funnel and the 18.2% headline stay untouched and unimported by any of it.
- **Negatives get published.** Every archived book gets a written verdict.
- **The gate has not opened, and nothing here opens it.** This plan makes the test honest. It does not
  make the answer good.
