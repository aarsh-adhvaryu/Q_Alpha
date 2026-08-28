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
   Zerodha tradebook (uploaded)                  ┌─ REAL      your orders, your judgement
            │                                    │            (advisor-assisted, manual)
            ▼                                    │
   FIFO ledger + dated lots ──► cash flows ──────┼─ TWIN-AI   full system, autonomous, AI selector
   (buys, sells, SIP instalments)                │
            │                                    ├─ TWIN-DET  full system, autonomous, no AI
            │                                    │
            └────────────────────────────────────┴─ BASELINE  NIFTYBEES, do nothing
```

**Four books. Identical cash flows. Four decision-makers.** Every book receives the same rupees on the
same days — derived from your actual tradebook — so the only difference is who decides. That isolates
exactly three questions:

| Comparison | Answers |
|---|---|
| TWIN-DET − BASELINE | Does the system beat doing nothing? |
| TWIN-AI − TWIN-DET | Does the AI add anything? (one treatment, as before) |
| TWIN-DET − REAL | Does autonomy beat your judgement? |

The third is the one that has never existed, and it is the one that decides whether autonomy should
ever graduate toward the real account. **It is reported, never gated** — it is information about you,
not a pass/fail on the system.

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
| 3 | TWIN-DET vs BASELINE | XIRR gap **exceeds the Monte-Carlo noise floor** (§5) net of cost + tax | A gap smaller than the noise is not a result |
| 4 | Tax reconciled | ≥ one **multi-lot or LTCG** sale matched to the Zerodha Tax P&L | Exactly one sell has ever been reconciled: single-lot, all-STCG, no loss |
| 5 | Corporate action reconciled | ≥ one applied live and matched to the broker | Never done. Demerger is not even modelled yet (§6) |
| 6 | Data integrity | Tradebook reconciles to broker holdings; no unexplained price gaps ungated | Off-market credits and demerger steps both break the ledger silently |

**Reported alongside, never gated:** TWIN-AI − TWIN-DET, TWIN-DET − REAL, and the delivered vs
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

## 5. Monte Carlo — what it is for, and what it is not

You asked for Monte Carlo / GBM to improve the advisor. **It cannot do that, and using it that way
would be the most dangerous thing in this plan.** GBM assumes lognormal returns with constant
volatility: no fat tails, no volatility clustering, no regimes — precisely the features that decide
whether a strategy survives. Simulating from GBM and tuning against it produces a system fitted to a
market that does not exist.

**What simulation is genuinely for here, and what it will be used for:**

1. **The noise floor (criterion 3).** Block-bootstrap the historical return panel (preserving fat
   tails and autocorrelation, which GBM discards), replay the full system on each path, and take the
   distribution of TWIN-DET − BASELINE. **The 95th percentile of that distribution under a null of
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

## 7. Open — needs your answer

**"Freezing the assets — what to freeze, how much to freeze."** My reading, alongside hedging, is
**de-risking: move some fraction out of equity into cash when risk is elevated, and hold it there.**
If that is right, the design questions are: what triggers it (the fragility gauge? drawdown? the
regime model?), what fraction, and what brings it back. If you meant something else — locking specific
lots from being sold, or ring-fencing cash from deployment — say so; they are different features.

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
| 3 | **Autonomy** | Hedge, de-risk, exits, rebalance running unattended on the twin, every decision logged with its reason |
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
