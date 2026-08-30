# Pre-registration — twin forward run 2

**Recorded 2026-08-30, before the run accrued its first mark.** The evaluation window opens
**Monday 2026-08-31** and closes **2026-08-31 + 12 months**. Nothing below may change while it runs.
A change to any of it is a new run, re-registered, exactly as forward run 1 was voided rather than
amended.

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

## 1. The gating statistic — **log relative wealth**

Exactly one comparison gates: `TWIN_FULL` vs `BASELINE_EW`, the purchasable equal-weight fund net of
its fee. The ablations are diagnostics and can never open the gate.

$$G_{12} \;=\; \ln\!\left(\frac{V_{\text{TWIN\_FULL},\,12}}{V_{\text{BASELINE\_EW},\,12}}\right)$$

Every book receives **identical cash flows** (`assert_identical_flows`), so the flows cancel in the
ratio and what remains is the selection difference. Chosen over a difference of two XIRRs because it
needs no root-finding, cannot fail to converge on a lumpy SIP, and is additive across sub-periods.

**It is scale-free**, which is the property the retired rupee floor lacked: the monthly SIP may grow
the book by any factor and $G$ is unmoved. Asserted by
`test_the_gating_statistic_is_scale_free`.

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
* the **equal-weight fund net of its fee** as the benchmark leg;
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
  name kept, so an outage degrades TWIN_FULL to *exactly* TWIN_NO_AI, never to an empty book.

**Frozen for the run:** model `claude-haiku-4-5`, search tool `web_search_20250305`, prompt version
`PR-8`. A model or prompt change is a second treatment and would make this run 3.

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
