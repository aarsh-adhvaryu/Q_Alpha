# Forward run 1 (2026-07-10 → 2026-08-14) — VOID, published as a negative

**Verdict: this run cannot answer the question it was registered to ask.** Not "the AI didn't help" —
something weaker and more important: **the instrument could not measure it.** Recorded here in full,
per the repo rule that pre-registered work is published whatever it says.

## What it reported

| Book | Value | Profit | Return (vs money put in) |
|---|---:|---:|---:|
| System (AI-paced) | ₹408,135 | ₹8,135 | +2.03% |
| Shadow (AI off) | ₹406,594 | ₹6,594 | +1.65% |
| Baseline (NIFTYBEES) | ₹403,900 | ₹3,900 | +0.97% |

**System − Shadow = ₹1,541** — the headline "did the AI help?" number. **Do not cite it.**

## Why it is void

### 1. The two books were not twins

The pre-registration says the AI tilt changes deploy **size only**. It did not.

| | System | Shadow |
|---|---:|---:|
| Names held | 32 | 28 |
| Shared | 26 | 26 |
| Held by one book only | 6 | 2 |

Two mechanisms turned a size difference into a composition difference. `max_name_fraction` filters
candidates on `price ≤ amount × 0.20`, so a smaller deploy sees a **smaller universe**; and
whole-share rounding drops different names at different scales. Each book also sized against its
*own* existing holdings. Six weeks of that compounded into **two different funds**, and the
difference between two different funds is not an ablation of the AI.

**Scale check:** the signal is **₹1,541**. One day of whole-share rounding noise is **₹1,964**. The
thing being measured is smaller than the measurement error.

### 2. Both books were contaminated by price artifacts

Both held names bought on discounts that did not exist — `adj_close` corrects splits and dividends but
never demergers, so a corporate action read as a 65% crash (see `PLAN_TRUST_REPAIR.md` T1.1):

| | System | Shadow |
|---|---:|---:|
| VEDL.NS | 69 sh | 57 sh |
| TRENT.NS | 6 sh | 5 sh |

At the point of the audit these two names took **44.4%** of a ₹100,000 recommendation. Both books
therefore accrued on a basket selected partly by a data defect, and — note — in *different
quantities*, which is the first problem again.

### 3. A third, quieter one: cash drag exceeded the signal

Measured on money contributed the System book returned +2.03%; on capital actually deployed, +2.73%.
The **0.70pp** gap is undeployed cash. That gap is **larger than the System−Shadow difference** the
study exists to detect, and the two books held different amounts of idle cash.

## What was salvaged

Nothing about the AI. Three things about the design, all now fixed:

1. **Composition must be fixed by construction, not hoped for.** Forward run 2 computes the day's
   basket **once at a fixed notional against an empty book**; both books execute that same ticker
   set, and a name is dropped only if it rounds below one share in *both*. Only quantities differ.
2. **The data feeding selection must be guarded before the run starts**, not after — hence PR-2's
   price-continuity guard landing before any re-seed.
3. **A difference smaller than the noise floor is not a result.** Rounding noise is now something the
   design controls rather than something the reader has to know about.

## What is untouched

The **validated ₹2L GO book** (`data/paper/book.json`) and its criterion-6 clock are not affected by
any of this and never were — it runs the validated engine on an annual cadence and shares no code
path with the deploy screen. Pillar 1 keeps accruing on its existing marks. Rule (a) intact.

## Data

Archived under `data/autopilot/archive/forward_run_1_*/` — books, track record, ledger, flows and
state exactly as they stood at the freeze. Nothing deleted.
