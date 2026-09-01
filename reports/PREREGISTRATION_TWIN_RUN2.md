# Pre-registration — twin forward run 2

**Recorded 2026-08-30. AMENDED 2026-08-30/31, before the window opened and before any *valid*
in-window mark existed — see §0b.** The evaluation window opens **2026-09-01**
(`twin.EVALUATION_START`) and closes twelve months later.

**Why the 1st and not the 31st.** The cron ran on 2026-08-31 against the *old* code — the mis-wired
`BASELINE_EW` and the raw-value statistic — and committed a row. Opening the window on a day whose
only observation was computed against the wrong bar would place a known-bad row inside the registered
evidence. Both rows now on file (2026-08-30, 2026-08-31) are therefore **pre-window**, retained as the
state-at-registration record and excluded from the statistic. The cost is one day. Nothing below may change while it runs. A change to any of it is a new run,
re-registered, exactly as forward run 1 was voided rather than amended.

**This is an amendment, not a voiding.** Forward run 1 was voided because it had *accrued marks*
under rules that turned out to be wrong. This document was written and corrected on the same day, with
zero in-window observations in between. Nothing has been discarded because nothing had yet been
measured.

Fake money only. The real Zerodha account is the state source and is never traded.

---

## Why an amendment was needed at all

An external review of the system on 2026-08-29/30, checked against the code, found four defects in
the measurement layer. Three of them would have made the twelve months ahead unreadable:

1. **The GO gate could not open.** `BACKTEST_NOISE_FLOOR = ₹84,11,106` was the p95 of 60 no-skill
   draws estimated over **thirteen years, ₹78.5 lakh of contributions, against NIFTYBEES**. It was
   then applied to a **₹3 lakh book, over twelve months, against the equal-weight fund**. Mismatched
   in scale, in horizon and in benchmark: it asked a ₹3 lakh book to beat luck by ₹84 lakh. Starting
   the clock with it would have spent a year to reach a guaranteed non-answer.
2. **The AI ablation was starved.** `Market.ai_verdicts` was wired into `runner._deploy` by PR-8 and
   then **never populated by the twin cron** — `scripts/twin.py:_market()` constructed `Market`
   without it, so `policy.use_ai and market.ai_verdicts` was False on every book, every day.
   TWIN_FULL and TWIN_NO_AI were byte-identical **by construction** (all four twins held 15 lots and
   ₹400.72140625000265 of cash on 2026-08-30). `TWIN_FULL − TWIN_NO_AI` could only ever have read
   ₹0, and in August 2027 that ₹0 would have looked like a finding about the AI. No test asserted
   that the ablation differentiated anything, which is why it survived review.
3. **No history of any book existed.** `data/twin/marks.json` is written with `write_text` and holds
   exactly one day; `books.json` is likewise a snapshot. Every run destroyed the previous day. Twelve
   months would have arrived as a terminal value and nothing else — every path-dependent question
   (worst drawdown, volatility of the gap, when the books diverged) permanently *unaskable*. Unlike
   every other defect on the list, this one was deleting evidence rather than mis-reading it.

---

## 0b. Amendment, 2026-08-30 — four defects found before the window opened

A second review checked the merged code rather than the plan, and found four things that would have
made the registered run meaningless. All four are fixed; the amendment is recorded here because the
fixes change what §1–§3 say.

**1. `BASELINE_EW` was not equal-weight.** `scripts/twin.py` passed `market.index_close` — the
NIFTYBEES series — to *both* `baseline_mark` and `ew_fund_mark`. `BASELINE_EW` was therefore
**cap-weighted NIFTYBEES minus a 0.41% fee**, which is strictly *easier* to beat than the `BASELINE`
sitting beside it (₹3,04,027 against ₹3,04,289 on 2026-08-30). Since `TWIN_FULL vs BASELINE_EW` is
the only comparison that opens the gate, the gate was measuring the wrong thing in the wrong
direction, and the entire reason for gating against a fund rather than an index was defeated by one
argument. Now built from `equal_weight_pit` on the point-in-time Nifty-50 panel. A missing panel
yields **no `BASELINE_EW` mark at all** rather than a borrowed one.

**2. The statistic was not scale-free.** `G = ln(V_FULL / V_EW)` on raw book values was described as
invariant to the SIP. It is not — identical contributions dilute a ratio rather than cancelling in
it: `ln(110/100) = 0.0953` but `ln(210/200) = 0.0488`, with nothing having happened in the market.
Twelve monthly deposits would have walked the statistic steadily toward zero. The test that "proved"
scale-freeness multiplied two finished marks by ten, which is invariance under *multiplicative*
scaling — not what a deposit does. Both legs are now **unitized NAVs**, which are contribution-invariant
by construction.

**3. The clock counted from the wrong day.** `months` came from the earliest flow on file —
2026-06-15, two trades that predate the experiment — so a window registered to open on 2026-08-31
would have reported "12 months" around June 2027, two months early and partly on unregistered
evidence. `EVALUATION_START` is now explicit and immutable, and criterion 2's drawdown window starts
there too.

**4. Two gate inputs were invented greens.** `tradebook_reconciles=True` and
`unguarded_price_gaps=0` were hard-coded, asserting a clean reconciliation and a clean feed that
nothing had checked — this repo's signature defect (a number labelled as something it is not) sitting
inside the gate itself. All four evidence inputs are now `None` → ⚪ CANNOT ASSESS, which blocks a GO
exactly as a red does while saying honestly that nobody looked. The gate consequently reads **6 of 6
criteria not green** at T=0, where it previously read 5 of 6 with a fabricated 🟢.

**Also corrected:** the T=0 history row had a hand-entered `start` of 2026-08-27 that contradicted
`books.json` (2026-06-15). It was regenerated from book state rather than from memory.

**Declared, not fixed — `TWIN_NO_HEDGE` is not an ablation.** `runner._hedge` emits `HEDGE_ON`/
`HEDGE_OFF` decisions and moves no money; the overlay needs a futures position the real account
cannot hold below ~₹19L. `TWIN_FULL − TWIN_NO_HEDGE` is therefore **₹0 by construction** and is not
evidence about the hedge. It is retained as a *signal log* — when the gauge fired, and for how long.
Reporting it as a measured hedge effect in 2027 would repeat, in a third place, the defect that left
the AI ablation starved.

---

## 1. The gating statistic — **log relative wealth of unitized NAVs**

Exactly one comparison gates: `TWIN_FULL` vs `BASELINE_EW`, the purchasable equal-weight fund net of
its fee. The ablations are diagnostics and can never open the gate.

$$G_{12} \;=\; \ln\!\left(\frac{\mathrm{NAV}_{\text{TWIN\_FULL},\,12}}{\mathrm{NAV}_{\text{BASELINE\_EW},\,12}}\right)$$

Each NAV is **unitized** from `EVALUATION_START`: the book holds units, and a contribution buys new
units at the prevailing price rather than inflating that price. This is the arithmetic a fund uses to
quote a NAV while money flows in and out, and it is what makes the statistic invariant to the SIP.

**Raw book values are not**, which was the error corrected in §0b.2: identical contributions dilute a
ratio rather than cancelling in it — $\ln(110/100) = 0.0953$ but $\ln(210/200) = 0.0488$, with
nothing having happened in the market. Twelve monthly deposits would have walked the old statistic
steadily toward zero.

Chosen over a difference of two XIRRs because it needs no root-finding, cannot fail to converge on a
lumpy SIP, and is additive across sub-periods. Asserted by
`test_the_gating_statistic_survives_a_contribution`, which demonstrates the failure it replaces
before asserting the property it guarantees.

Each book's NAV is reconstructed from `data/twin/history.jsonl`, whose rows already carry every
book's `net_invested` — so a day's contribution is the day-on-day difference in that figure, and no
separate flow file can disagree with it.

Report it to a human as $e^{G}-1$. The rupee gap is still displayed, always as description, never as
the criterion.

## 2. The null — specification frozen, value not yet computed

`twin.NULL_P95_LOG_REL_WEALTH` is **`None`** as of this record, and `None` reads
**⚪ CANNOT ASSESS** — never a pass, and never a silent bar of zero. The specification is fixed here
and may not be changed once the window opens:

* 12-month windows drawn from point-in-time Nifty-50 history;
* the same initial-capital-to-SIP ratio, **₹3,00,000 + ₹50,000/month**;
* identical deposit dates for the strategy leg and the benchmark leg;
* random selection pushed through otherwise identical machinery — same costs, same tax, same
  whole-share rounding — so the null carries every friction the real book carries;
* the **equal-weight fund net of its fee** as the benchmark leg, built by `equal_weight_pit` on
  point-in-time membership — the same construction the live `BASELINE_EW` now uses (§0b.1);
* both legs converted to **unitized NAVs** before the ratio is taken, exactly as the live statistic
  is, so the null and the observation are the same quantity;
* p95 of $|G|$ over the draws; ≥1,000 draws.

Computing this value is the one outstanding task. It must be generated and committed **before the
window closes**, and its inputs are fixed by this document, so producing it later cannot be tuned to
the result.

## 3. The AI treatment — one lever, now actually connected

`scripts/twin.py:_ai_verdicts` asks the model about the basket **TWIN_FULL** is about to buy and
feeds the result into `Market.ai_verdicts`. TWIN_FULL applies it; TWIN_NO_AI ignores it. That is the
whole treatment and the only difference between those two books.

The guards are structural, not prompted, and are unchanged from PR-8:

* **cannot add a name** — `parse_verdicts` discards any ticker outside the deterministic universe;
* **cannot size anything** — survivors keep the quantities the screen computed;
* **cannot fail closed** — no `ai` extra, no key, a refusal, an unparseable line → empty map → every
  name kept, so an outage degrades TWIN_FULL to *exactly* TWIN_NO_AI, never to an empty book;
* **cannot veto without a citation** (added 2026-08-30) — a DROP whose `source=` is missing or is not
  a URL is **demoted to KEEP**. A veto evidenced only by a twelve-word reason cannot be told apart
  from a fabrication a year later, and telling those apart is the sole question this experiment
  exists to answer;
* **cannot act unrecorded** (added 2026-08-30) — if writing the provenance row fails, the whole
  verdict map is discarded and every name kept. A DROP that moves the book without a row explaining
  why is an unauditable treatment.

**What is logged, and why the confound is named rather than removed.** Every eligible day writes an
*attempt* row — `not_asked_cash_below_floor`, `not_asked_no_watchlist`, `error`,
`no_verdicts_parsed`, or `verdicts_recorded` — plus the model's raw response. Before this, four very
different days all produced no rows at all, and "the AI never got to speak" is not the same result as
"the AI looked and found nothing".

Dropped names are **not** replaced and survivors are **not** rescaled: the no-resize guard is a real
safety property and stays. The consequence is that `TWIN_FULL − TWIN_NO_AI` measures *the veto plus
the cash drag it causes*, not selection skill alone. That confound is not removed — it is **measured**:
the undeployed rupees are recorded on each attempt row, so the two can be separated afterwards instead
of being tangled forever.

**Power, stated in advance.** Twelve monthly deploys with zero to three drops each is a few dozen veto
events. That will not statistically establish alpha. This run is registered to produce an *operational*
result — a case library and a matured-veto hit rate — and a 2027 reader must not treat a
twelve-month portfolio gap as a verdict on the AI.

**Frozen for the run:** model `claude-haiku-4-5`, search tool `web_search_20250305`, prompt version
**`PR-8b`** — amended before the window opened to require a `source=` URL on every DROP. A model or prompt change is a second treatment and would make this run 3.

The model is asked only when TWIN_FULL's idle cash clears `idle_cash_floor` (₹5,000) — roughly when
a SIP lands, not daily. On 2026-08-30 TWIN_FULL holds ₹400.72, so no call is made.

**If the AI drops no names over the window, the result is "no verdicts issued", not "the AI did not
help".** Zero treatment events cannot estimate a treatment effect. The verdict log below is what
distinguishes those two readings, and a time counter alone cannot.

## 4. The record — append-only, and the only thing that accumulates

| File | One row per | Holds |
|---|---|---|
| `data/twin/history.jsonl` | day | every book's value, net invested, XIRR, start; the gating gap in rupees **and** in $G$; months elapsed; the gate verdict |
| `data/twin/ai_verdicts.jsonl` | day × ticker | call, confidence, reason, **price at decision**, model, prompt version |

Both are written atomically and **refuse any write that would leave the file shorter**. A same-day
re-run corrects that day's row rather than duplicating it; no other day is ever touched.

`price_at_decision` is load-bearing: with it, the counterfactual for a dropped name is a lookup
against any later price panel, and the AI question is answerable. Without it a DROP is an opinion
with no outcome attached.

These store the **inputs to every later statistic**, not the statistics. Drawdown, tracking error and
the significance of the gap are all recoverable from them — and recoverable *retroactively*, which is
the point.

## 5. What was NOT changed tonight, deliberately

The same review found real defects in the **backtest** layer: the SIP equity curve treats
contributions as returns (so the "hedge costs 21.5% of terminal wealth" figure and every Phase-4
drawdown are not yet trustworthy), residual cash is omitted from marks, execution and FIFO cost basis
run on adjusted rather than raw prices, capital-gains rates are applied flat across 2012–2026 rather
than by date, and `_cap_renorm` collapses `weighting="score"` to equal weight.

**None of these touch the forward record**, so none of them were rushed in the day before the clock
starts. They operate on data that still exists and can be recomputed at any time. They are the work
for the week after this run begins, and fixing them then voids nothing here.

---

**Status at T=0 (2026-08-30):** gate **NOT YET**, 5 of 6 criteria not green. TWIN_FULL is behind
BASELINE_EW by ₹514 (−0.17% relative wealth, G = −0.0017) — **descriptive only, 0 of 12 months**.
No verdict before the locked 12-month evaluation.
