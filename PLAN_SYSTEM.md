# PLAN_SYSTEM — Q-Alpha as a constrained autonomous portfolio manager

**Written 2026-08-31.** This supersedes the incremental plans as the *target architecture*. It is not
a rewrite: 22,624 lines and 40 live modules already exist, the accounting engine reconciles to the
paise, and the twin is accruing daily. What is missing is not components. It is the **spine** that
turns them into one decision, and the **evidence** that makes the decision trustworthy.

---

## 1. The product, in one sentence

> Q-Alpha performs the research, rejects the noise, sizes the position, checks it against a mandate,
> and hands the user **one** of three things per day. The user is not a trader and must not become one.

```
NO_ACTION        nothing cleared the bar. Here is what was examined.
EXECUTE          one bounded order, pre-checked, ready to place.
HUMAN_REQUIRED   something is ambiguous or a guard tripped. No trade placed.
```

Everything else in this document exists to make those three outputs honest.

**The VBL case is the specification.** The user bought VBL; Kite's own nudge said don't; Q-Alpha would
have *encouraged* it, because the deploy screen ranks names by how far they sit below their 1-year
high and VBL is −23.8% off its. §4.7 rated it WATCH, not BREAKING. The system was not neutral on that
trade — it was on the wrong side, holding out a number that looked like a discount. No amount of
additional price mathematics fixes that. **The system must read things that are not prices.**

---

## 2. What already exists (compose, do not rebuild)

| Layer | Modules | State |
|---|---|---|
| Accounting | `tax_lots` `costs` `capital_gains` `corporate_actions` `slippage` | **Reconciled to ₹0.00** vs a real Zerodha Tax P&L. Frozen (rule (a)). |
| Engine | `engine` `decision` `strategy` `portfolio` `baselines` `metrics` `significance` `runstore` | Validated in-sample; OOS contested (§8). |
| Factors / alloc | `momentum` `volatility` `liquidity` `fundamental` `score` `regime` · `conditioning` `optimizer` `sectors` | Built. |
| Screen | `deploy` `position_health` `price_integrity` `cooling_off` | Live. **Never backtested OOS.** |
| Advisor | `advisor` (sell / raise-cash / deploy / harvest) | Live, tax-exact, §70 set-off. |
| Broker | `auth` `client` `holdings` `tradebook(+store)` `taxpnl` `instruments` `basket` `ticker` | Live, manual execution. |
| Forward | `twin` `runner` `policy` `go_gate` `nav` `verdicts` `track_record` `measures` | Run 2 window opens 2026-09-01. |
| Guards | `safety` `scan` `notify` `runlog` | Live, fail-loud. |
| AI | `ai_brief` `verdicts` | Veto-only, citation-required, fake money. |
| Regime | `hedge` `fragility` `drawdown` `defensive` | **Signal-only — moves no money.** |

**Roughly 80% of the machinery is present.** What follows is mostly wiring, evidence, and one new
data spine.

---

## 3. Architecture — six layers, one direction of authority

Authority flows **down only**. No layer may override the one below it.

```
  L5  ORCHESTRATOR      one output/day, immutable decision packet
       |
  L4  RISK GOVERNOR     deterministic. can VETO anything. cannot be overridden.
       |
  L3  PORTFOLIO         sizing, tax, optimizer, hedge, regime
       |
  L2  OPPORTUNITY       deterministic screen + event candidates. proposes only.
       |
  L1  EVIDENCE          filings, exchange lists, news → structured events
       |
  L0  DATA SPINE        collection, provenance, freshness, hashes
```

### L0 — Data spine

Every stored value carries an envelope. This is not bureaucracy: **every defect in this repo's history
has been a value whose label did not match what it was.**

```
value · instrument · as_of_market_time · retrieved_at · source
raw_or_adjusted · dataset_hash · calculation_version · freshness_status
```

Sources, by cadence:

| Cadence | What | Cost |
|---|---|---|
| Daily (post-close) | EOD OHLCV, instrument master, corporate actions, **index membership** | free |
| Daily | **Exchange lists**: T2T segment, suspension circulars, IRP, rights entitlements | free |
| 15–60 min, market hours | **NSE/BSE corporate announcements** for held + watchlist names | free |
| Same day | Price-shock detection on holdings (−8% day) | free |
| **Never** | Tick-by-tick storage | — |

**Storage: keep what works.** Append-only JSONL + Parquet in git is already proven — `history.jsonl`
survived its first real cron on 2026-08-31 and committed. Postgres is deferred until a persistent
local node exists and there is a reason. *Do not* introduce a database because the architecture
diagram looks better with one.

**Reproducibility:** every panel gets a recorded hash. The Phase-4 audit showed identical code on a
re-downloaded panel moves the exits leg by ₹6.8 lakh. Until inputs are pinned, no rupee figure in any
report is reproducible to better than half a percent, and reports must say so.

### L1 — Evidence engine

Zerodha's nudge taxonomy is the specification, and its lesson is that **seven of eight checks are
lookups, not judgments**:

| Check | Mechanism | Needs AI? |
|---|---|---|
| T2T segment | exchange list | no |
| Insolvency (IRP) | exchange / IBBI | no |
| Suspension pending | exchange circular | no |
| Rights entitlement | instrument type | no |
| Illiquid (<₹100cr) | market cap | no |
| Corporate action | `corporate_actions_feed` + `price_integrity` — **built** | no |
| Sector concentration | our own book + sectors — **data already held** | no |
| Governance / news | filings + reporting | **yes** |

So the veto layer is mostly a **deterministic pre-trade check**, and the LLM handles one residual
class. This inverts the earlier design and is much cheaper and far more testable.

**Event schema** (the AI's only job is to fill this from a document, never to decide):

```
ticker · event_type · event_occurred_at · became_public_at · primary_source_url
materiality (vs revenue/mcap) · novelty · horizon · direction · extracted_facts
contradictions · verification_status · model · prompt_version · retrieved_at
```

**Rules, already enforced in code as of 2026-08-30:** an uncited claim is ignored; a DROP without a
source URL is demoted to KEEP; a verdict whose provenance row fails to write does not act; the model
being unavailable degrades to the deterministic system, never to an empty book.

**Event classes ranked by whether a statistical model is even possible** (from the power calculation:
n ≈ 43 independent events minimum, inflated 3–5× for cross-sectional clustering):

| Class | Events available, 13y | Verdict |
|---|---|---|
| Earnings / guidance surprise | 50 × 4 × 13 ≈ **2,600** | Model it. |
| Management change | 100–150 | Marginal. |
| Contract win | 65–200, wildly heterogeneous | **Veto-shaped, not alpha-shaped.** |
| Governance, auditor, pledge, SEBI | sparse, lumpy | **Veto only.** Never fit a model. |

An auditor resignation does not need a model to be worth acting on. It needs to be *seen*.

### L2 — Opportunity engine

Proposes. Never sizes, never executes.

- **Existing:** the deterministic weakness/cheapness/health screen. Unchanged.
- **Added:** event candidates — earnings surprise only, and only once the historical corpus exists.
- **Removed from the buy path:** nothing. The screen stays the generator; events become a *filter*
  and, later, a second generator with its own registered experiment.

### L3 — Portfolio

Sizing (`advise_deploy`), tax (`advisor`, §70, §112A), optimizer (`shrink`), corporate actions.
All built. Two open items:

- **Hedge: RESOLVED 2026-08-31 — the ₹0 is now explained, not accidental.** `runner._hedge` still
  moves no money, and `TWIN_FULL − TWIN_NO_HEDGE` is still ₹0 by construction. Wiring
  `apply_futures_hedge` in as-is would have replaced that with a worse number: it models a
  *continuous* notional, so it would have simulated **0.16 of a futures contract**, and fractions of
  a contract do not exist. Instead `hedge_availability` reports at **whole-lot granularity**, and
  every hedge decision now carries it. At index 25,000 one contract is ₹18.75L of exposure, so
  hedging half a book needs **V_min = lot × index / h = ₹37.5L** — an order of magnitude above the
  current ₹3L book. The overlay is therefore not "untested", it is **not purchasable**, and the
  system says so with the threshold at which that changes. Re-verify `NIFTY_LOT_SIZE` against NSE
  contract specs before quoting any rupee figure from it.
- **Crash / fall behaviour** already exists as `market_weakness` and `stress_gauge`. What is missing
  is that they *gate deployment* — a "deep" regime should change the tranche, which `scan.py` knows
  and the twin does not act on.

### L4 — Risk governor

**The most important new component.** Deterministic, separately testable, and it can veto anything.

Rules, taken verbatim from the operating contract already agreed — the change is that they move from
prose in `CLAUDE.md` to an object with a `veto()` method:

```
settled cash only                       limit orders only
1% ADV cap                              min ADV ₹50L core / ₹25L tactical
≤20% single name                        ≤30% sector — MEASURED ON THE BOOK, not the basket
core capital never funds tactical       no order after the cutoff
net benefit must clear cost + tax       duplicate-order prevention
stale input → refuse, never assume      kill switch
human approval (Stages 1–2)             post-order reconciliation
```

**The sector rule is a live defect, and probably the VBL nudge.** The 30% cap is applied to
`deploy_target` over the names selected *that round*. At slider 3–4 — the documented monthly SIP
setting — the cap is arithmetically unreachable: with three names one is 33%, so any two in a sector
is 67%. Twelve individually-"compliant" monthly baskets can compound into a book that is half one
sector, and nothing in the system ever looks at the cumulative mix. Kite does, at 50%. **Our cap is
stricter on paper and weaker in practice, because it constrains the wrong denominator.**

**Stops:** core keeps **no stop-loss** — it buys weakness, so a stop sells what it just bought, and
Phase 4 measured that at ₹74.8 lakh behind buy-and-hold plus ₹13.3 lakh of tax. The exit is the §4.7
breakdown test (idiosyncratic, relative to peers) plus event evidence. A tactical/news sleeve, *if*
built, gets its own stops because a catalyst thesis invalidates in days — but that is a separate
sleeve with a separate mandate, never a rule applied to the core.

### L5 — Orchestrator

Produces exactly one output per day and one **immutable decision packet**:

```
decision_id · timestamp · code_commit · eligible_universe · dataset_hashes
portfolio_before · signals · events + citations · constraints_applied
candidates_rejected + reasons · recommended_quantities · expected_cost_and_tax
risk_before/after · invalidation_conditions · approval · order_result · portfolio_after
```

**Given that packet and the same commit, the recommendation must reproduce exactly.** If it cannot,
it was not auditable and must not have been actionable.

---

## 4. Compute — where things run, and why

| Where | Runs | Never runs |
|---|---|---|
| **GitHub Actions** (always-on, stateless) | collection, commits, deterministic daily mark, twin, alerts | anything needing GPU or a persistent socket |
| **Laptop CPU** (intermittent) | decision run, reconciliation, dashboards | anything safety-critical while it is off |
| **Laptop GPU** (RTX 5070 Ti, batch) | historical filing corpus → event DB, embeddings, Monte Carlo, heavy backtests | the daily loop |
| **Streamlit** | read-only surfaces | order placement |
| **Kite** | execution + state source | autonomous trading |

**The honest latency requirement.** For a one-year-hold book, "real-time" matters for **detection**,
not execution — orders are placed by hand the next morning regardless. So:

- Filings poll at 15–60 min: **yes**, this is where asymmetric information lives.
- Same-day price-shock flag on holdings: **yes**.
- Tick stream: **no**, unless a tactical sleeve is later approved.

**The GPU's real job is the corpus, not the day.** ~15 candidates/day through Haiku costs pennies and
needs no GPU. Turning thousands of historical filings into a structured event database — so *"what
happened after comparable events"* becomes answerable — is genuinely GPU-shaped and runs when the
laptop is on.

**Trading safety must never depend on the GPU or an LLM being reachable.** If the laptop is off, the
deterministic system continues and the AI queue waits.

**Kite's daily login is not a limitation to engineer around.** It is the one moment a human
necessarily touches the system each day, which makes it the natural home for the exception queue:
log in, see `NO_ACTION` or approve one bounded order. That *is* the Stage-2 product, and it needs
almost none of this infrastructure to exist.

---

## 5. The ML question, answered honestly

Asked: LLM, MLP, NN, RL — whatever is needed. The honest answer is that most of it is **not yet
supportable by the data**, and saying so is worth more than shipping a model that overfits.

| Method | Verdict | Reason |
|---|---|---|
| **LLM (document → structured event)** | **Yes, now.** | Reading filings is genuinely a language task. Already shipped in veto form. |
| **Deterministic lookups** | **Yes, now.** | Seven of Zerodha's eight nudges. No model needed at all. |
| **Event study / GLM on earnings** | **Yes, once the corpus exists.** | n ≈ 2,600 clears the power bar. Start linear; a NN is not the bottleneck. |
| **Monte Carlo / bootstrap** | **Yes, for sizing and drawdown.** | Already partly built (`significance.noise_floor`). Answers "how much can this lose". |
| **MLP / NN for return prediction** | **No.** | 13 years of monthly data on 50 names. This is the classic overfit trap and the repo has already published two negatives (QUBO ×2). |
| **Reinforcement learning** | **No, and not close.** | ~156 monthly periods — and they are not independent. Perhaps **5 genuinely independent macro regimes**. Deep RL needs thousands of episodes. It would memorise one path through history. |

**What would change these verdicts:** a corpus of point-in-time events with matured outcomes, and a
forward record long enough that a model can be evaluated out-of-sample without touching the data it
was fitted on. Both are Phase D+ work. Neither is a reason to delay Phases A–C.

---

## 6. Trust — the contract

Three invariants, applied everywhere, not just at the gate:

**1. Unknown is never substituted.** Missing price ≠ previous price. Missing filing ≠ no bad news.
Missing AI response ≠ approval. Absent null ≠ threshold of zero. Unknown produces
`CANNOT ASSESS — NO ACTION`. The GO gate does this now; the rest of the system must.

**2. Every number carries provenance.** See L0.

**3. Every decision replays.** See L5.

**Trust is per-component, never global.** A tax engine reconciled to ₹0.00 grants no authority to an
untested IPO model. The dashboard carries a capability register:

| Component | Honest state | What would earn trust |
|---|---|---|
| FIFO / cost / tax | partially verified | multi-lot + LTCG + corporate action reconciled to Zerodha |
| Data ingestion | partial | exchange cross-checks, freshness, hashes |
| Core screen | **in-sample only** | clean OOS + forward vs the investable baseline |
| Optimizer | research | stable under input perturbation and real costs |
| AI veto | experimental | source-backed vetoes, enough matured cases, positive shadow evidence |
| Hedge | **signal only** | real notional, P&L, margin, expiry |
| Executor | manual approval | reconciliation, idempotence, kill switch |

**Passing tests are necessary and insufficient.** 677 tests did not catch: the equal-weight benchmark
receiving NIFTYBEES; a statistic that was not contribution-invariant; a clock counting from the wrong
day; a cron that would have destroyed its own history. Four correctness levels, and unit tests reach
one:

| Level | Failure seen |
|---|---|
| Unit | — (all green) |
| **Integration** | `BASELINE_EW` got NIFTYBEES |
| **Methodological** | the statistic answered the wrong question |
| **Operational** | the cron would have thrown the record away |

**Therefore the golden-day replay is not optional and comes early** — one fixture simulating a
complete market day (data arrival → filings → recommendation → governor → approval → fake execution →
costs → mark → reconciliation) asserting the final portfolio exactly. It is the only test shape that
catches integration and operational defects, and it constrains everything built after it.

---

## 7. Phases — ordered by evidence, not ambition

### Phase A — The governor and the gaps it closes

1. ✅ **Sector concentration measured on the book**, not the basket (`live/governor.py`). Twelve
   individually-compliant SIP baskets at slider 4 compound into a **36.9% POWER** book; the governor
   flags 4 of those 12 months.
2. ✅ **Valuation caution** (`live/valuation.py`) — the VBL gap. The nudge was *"Scrip PE is greater
   than 50"*, and the screen ranks names **by** how far they fell, so a −38% fall from a P/E-80
   valuation reads as a discount. Current P/E is one API call; only *historical point-in-time*
   fundamentals are blocked. Threshold is the exchange's own, so nothing is invented.
3. ✅ **Hedge availability** at whole-lot granularity (`live/hedge.py`).
4. `Mandate` object + `RiskGovernor.veto()` — the rules of §L4 moved from prose to code. *(next)*
5. **Golden-day replay** proving the governor cannot be bypassed. *(next)*

*Why first: built from decisions already made, needs no new data, and converts conventions into
invariants. A governor nobody can prove is unbypassable is prose again.*

### Phase B — The evidence spine

4. Exchange-list collector (T2T, IRP, suspension, RE, market cap) → deterministic pre-trade checks.
5. NSE/BSE corporate-announcement poll for held + watchlist names.
6. Point the AI veto at **filings** rather than general web search.
7. `EvidenceEnvelope` on every stored value; dataset hashes recorded.

*Why second: this is the layer that would have said something about VBL.*

### Phase C — The spine

8. Decision packets, immutable and replayable.
9. Orchestrator → one `NO_ACTION` / `EXECUTE` / `HUMAN_REQUIRED` per day.
10. Heartbeats + automatic safe shutdown: stale essential input ⇒ observation continues, recommendation
    and execution stop.
12. Capability register on the dashboard.

### Phase D — Evidence that is still owed

13. **The matched null** (≥1,000 draws) — criterion 3 reads ⚪ until it exists. Spec frozen.
14. **README correction**: gate 1 claims `✅ out-of-sample` for a configuration selected *on* the
    holdout. It is in-sample. This is a ten-minute fix and the claim most likely to over-authorise
    capital.
15. `force_refresh` relabel: tax is charged, but the §4.6 gate never decides.
16. Raw prices for execution and FIFO basis; date-dependent tax rates; `_cap_renorm`.

### Phase E — New engines, each a separate registered experiment

17. Historical filing corpus (GPU batch) → event database.
18. Earnings-surprise event study — the only class with the sample size.
19. Mid/small-cap, IPO, F&O — each starts in shadow mode with its own point-in-time universe and its
    own graduation gate. **No engine inherits another's authority.**

### Autonomy ladder

| Stage | Q-Alpha does | User does |
|---|---|---|
| 1 | all research, paper book | reads exceptions |
| 2 | generates the exact limit order | one-tap approve |
| 3 | executes graduated strategies inside capital limits | monitors |
| 4 | everything inside the mandate | Kite login, capital, rule changes, ambiguous corporate actions, kill switch |

A new model, sleeve or strategy **cannot grant itself authority**. It re-enters at Stage 1.

---

## 8. What is still not true, stated plainly

- **The core screen has no clean out-of-sample evidence.** `shrink` was selected by requiring it to
  beat 1/N *on the 2025–26 holdout* (`exp_breadth.py:104`), so the holdout is validation data. The
  deploy-into-weakness screen the real money actually runs has never been backtested out-of-sample at
  all. **The forward twin is now the only clean route**, and it opens 2026-09-01.
- **The screen's worst backtested fall is −47.5%, deeper than the index's −36.3%.** The extra return
  is bought with extra risk. Corrected 2026-08-30.
- **The GO gate is shut and reads 6 of 6 criteria not green.**
- **Real money never auto-trades.** This rule outlives every gate in this repo.

> Q-Alpha never asks to be trusted. It shows enough evidence that the decision can be checked —
> and it refuses to act when it cannot.
