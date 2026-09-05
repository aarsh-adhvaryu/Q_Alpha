# Pre-registration — PreTradeAssessment v1

**Frozen 2026-09-05, BEFORE `live/pretrade.py` was written.**

The rules are written first because the alternative is to build the combiner, run it on the current
basket, and adopt whatever it says as correct. That is selecting on the outcome, and this project has
done it twice already: `shrink` was chosen on the holdout, and `live/valuation.py` was built for VBL
without ever being run against VBL.

---

## 1. What this object is

One question, per candidate, answered before any order is sized:

> **May Q-Alpha buy this stock?**

It is **not** a view on whether the stock will go up. It combines what the exchange publishes with
what verified filings say, and reports one state plus the evidence behind it.

## 2. The five states, and the precedence between them

| State | Meaning | Effect |
|---|---|---|
| `BLOCK` | a hard, deterministic exchange condition | excluded, no human needed |
| `UNKNOWN` | a required feed failed, or is stale | `HUMAN_REQUIRED` |
| `WATCH` | evidence exists and is advisory | `HUMAN_REQUIRED` |
| `PASS` | every consulted dimension is clear | eligible for the screen |
| `NOT_COVERED` | this version does not evaluate that dimension | reported, never state-changing |

**Precedence: `BLOCK` > `UNKNOWN` > `WATCH` > `PASS`.**

`UNKNOWN` outranks `WATCH` deliberately. A known warning is a thing you can read and weigh; an
unmeasured dimension is not, and the more dangerous of the two is the one nobody looked at. Both
route to a human, so the ordering only decides what the report leads with — but it must lead with
the gap, not the finding.

## 3. Extracted events may never BLOCK. This is the load-bearing rule.

A verified quote proves the document **contains that sentence**. It does not prove the model
classified it correctly, judged its materiality correctly, or read it in context. The verification
guard tests the citation, not the reasoning.

So:

- **Only the exchange's own deterministic conditions produce `BLOCK`** — suspension, trade-to-trade
  series, ASM/GSM stage ≥ 2, active insolvency. Those are facts NSE publishes as lists, not
  readings of prose.
- **A verified extracted event produces at most `WATCH`.**
- An **unverified** event produces nothing at all. It is counted and reported, never acted on.

No engine inherits another's authority. A language model that reads filings has not earned the
right to veto a trade, and giving it one because its citation checked out would be exactly the
mistake the citation check was built to prevent.

## 4. Which events reach `WATCH`

| Materiality | Verified | Effect |
|---|---|---|
| `high` | yes | `WATCH` |
| `medium` / `low` | yes | listed in the report, **state unchanged** |
| any | no | counted as unverified, **state unchanged** |

Materiality is the model's own label. It is allowed to raise a flag for a human and nothing more.

## 5. Dimensions in v1

**Consulted** — a failure or staleness here is `UNKNOWN`:
1. Exchange regulatory indicators (`REG1_IND`, via `live/evidence.py`)
2. Corporate announcements for the name (via `live/announcements.py` + `live/extraction.py`)

**`NOT_COVERED`** — named explicitly so silence is never read as approval:
fundamentals · earnings quality · debt and cash flow · promoter pledges · related-party transactions
· auditor changes · liquidity and ADV · settled-cash and duplicate-order checks (those belong to the
governor, not here)

## 6. Coverage floor, and why it exists

If **every** consulted dimension were allowed to return `NOT_COVERED`, the object would answer `PASS`
having looked at nothing. So:

> **A `PASS` requires at least the exchange-indicator dimension to have been consulted successfully.**
> If it was not, the state is `UNKNOWN`, never `PASS`.

The announcement dimension may legitimately be empty — a name can simply have filed nothing in the
window — and an empty result there is `PASS` for that dimension, not `UNKNOWN`. Distinguishing
"filed nothing" from "we did not look" is the whole reason the fetch reports coverage separately.

## 7. What this does not do

- It does not rank, score or size. It answers eligibility only.
- It is **not wired into any decision path** in this version. `CORE_V1` is untouched by design; its
  clock resets only on a screen change and this is not one.
- It does not consult liquidity, settled cash or duplicate orders. Those are the governor's.

## 8. Expected outcomes — FROZEN before implementation

Applied to the basket the live screen recommends today, using the archived 2026-08-27 exchange file:

| # | Fixture | Expected |
|---|---|---|
| 1 | `JIOFIN` — carries the P/E > 50 caution | `WATCH` |
| 2 | `VBL` — clear on that date, no high-materiality event | `PASS` |
| 3 | a name at ASM stage ≥ 2 | `BLOCK` |
| 4 | exchange file missing | `UNKNOWN`, even if announcements were clean |
| 5 | a high-materiality **verified** event on an otherwise clear name | `WATCH` |
| 6 | a high-materiality **unverified** event on an otherwise clear name | `PASS`, with the count reported |

Fixture 6 is the one that matters. If an unverified event can move the state, the verification guard
is decorative.
