# Pre-registration — AI-PM-1: the investor's first version

**Written 2026-09-13, before any review has run on the book.** The start date is set in a separate,
dated change once the conditions in §5 hold; nothing here may be edited after that date except §7.

## 1. The question

Can a pinned language model, given verified filings, headlines, prices, its own notes and hard limits
enforced by code, run a paper portfolio of large Indian companies well enough to be worth continuing —
measured operationally, by the quality of its decisions, and (slowly) by outcome against a fund
anyone can buy?

## 2. The investor, fixed

| | |
|---|---|
| Version | `AI-PM-1` — `src/qalpha/live/manager.py` at the commit that sets the start date |
| Model | `claude-sonnet-5`, over the API. Any other model is a different version. |
| Book | `SYSTEM`, seeded as an exact copy of `REAL` (the user's tradebook), continuous across versions |
| Reviews | One per trading evening, on that session's close, after 17:00 IST |
| Scope | Every holding + the 8 non-held watchlist names furthest below their 1-year high (`screen.candidates`). A pullback is not a valuation, and the prompt says so. |
| Packet | Holdings with cost, weight, long-term status and anything over the drift band; candidates; close and 13 monthly adjusted closes per name; NSE surveillance flags; up to 6 verified filing/headline events per name (EX-3 / NEWS-1, corpus reader, knowable on the date); its own last 3 notes per name and 3 portfolio notes from earlier evenings; a scorecard of its last 20 decisions; the limits; cost and tax summary. **No financial statements** — that is AI-PM-2. |
| Reply | JSON: a portfolio note, and per name HOLD/BUY/SELL, whole-number quantity, reason, thesis, invalidate-if, cited ids, note |
| Code enforces **on buys** | Long-only · at most 8 names after buying · a purchase may take a name to 20% and a sector to 30% of value including cash · cash including costs · every holding reviewed · every cited id real and for that ticker · sells before buys |
| Drift | A position that appreciates past the cap is **not** a breach: up to 22% (name) / 32% (sector) needs no action. Above the band the investor is told, and decides — trimming realises tax, and selling to manage risk has been measured here as losing to it. Code never forces a sale. |
| Fills | At the first session after the decision (read from the benchmark's bars), at that session's raw close, only with positive volume; limits re-checked with that day's prices. A missing quote keeps the order waiting and blocks the next review. |
| Costs and tax | The existing Zerodha cost model and FIFO capital-gains engine |
| Records | `data/twin/manager/`: receipts (packet + reply + usage), decisions, fills, logbook, scorecard |

## 3. What counts as a review that did not happen

No key · model refusal · reply cut off · reply not JSON · a holding not reviewed · a cited id that is
not that company's · an order for a name neither held nor shown · a sell above what is held · a held
name whose filings are not read · a held name with no close · orders still waiting · a different model.
Each is recorded as **incomplete**, changes no book, and is never a HOLD.

## 4. Comparison

`SYSTEM` against `BASELINE_EW` (Nifty-50 equal-weight, 0.41% fee), `BASELINE` (NIFTYBEES) and `REAL`, same
flows, same days. Relative wealth by unitized NAV from the start date. No annualized rate under a year.

## 5. Start conditions — all must hold

1. This version is merged.
2. Every held name's filings are read (INFY, MUTHOOTFIN, TATAPOWER, WIPRO were not on 2026-09-13).
3. One shadow review (`scripts/twin.py shadow`) has completed on real data, and its receipt has been
   read by a person.

The start date is then the next trading day, set in `EVALUATION_START` by a dated change.

## 6. What may be claimed

**May:** what it did, why (its receipts), what it cost, and how the book moved against the funds — as a
description.

**May not:** that it has skill. One book over months is dominated by timing and luck; the old screen's
edge would have needed ~200 years to tell from chance. **Nothing here authorizes real money.** A
twelve-month anniversary is not a verdict.

## 7. Recorded outcomes

*(Append only, dated.)*

- **2026-09-13** — registered. No review has run on `SYSTEM`.
- **2026-09-13** — **amended before the start date, at the user's instruction.** The 20% and 30%
  caps become limits on **purchases**, with a 2-point drift band above them. The first shadow review
  trimmed two holdings (TATAPOWER 21.4%, VBL 20.9%) that had merely appreciated; a rule that forces a
  sale on price drift pays capital-gains tax to undo a gain, which is the trade this repository has
  already measured as a loser. Buying stays capped; drift is shown, never acted on by code.
- **2026-09-13** — **shadow review run and read** (start condition 3). 8 holdings reviewed on
  2026-09-11's close: 5 HOLD citing specific filings, 3 trims. 25,020 input + 10,217 output tokens.
  Records in `data/twin/manager/shadow/`. Start conditions 1 and 2 are not yet met.
