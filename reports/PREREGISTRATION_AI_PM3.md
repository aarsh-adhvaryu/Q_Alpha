# Pre-registration — AI-PM-3: the investor as an agent

**Registered 2026-09-15, before any AI-PM-3 review of a real book.** Sections 1–6 are frozen once the
start date in section 7 is filled in; corrections go in a dated section at the bottom. The paper
book is one continuous book, and every decision carries the version that made it.

**AI-PM-3 is the only investor.** AI-PM-1 and AI-PM-2 were retired on 2026-09-15 before either made a
decision (their registrations are in git history). "AI-PM-2" below names the design this one changes
and the original purchase limits, which the live book keeps.

## 1. What changes from AI-PM-2

| | AI-PM-2 | AI-PM-3 |
|---|---|---|
| Who is reviewed | every holding and 8 candidates, every evening | names code flags (section 3); every holding weekly |
| What the model returns | HOLD / BUY / SELL with share counts | intentions: open / add / hold / reduce / exit, conviction, desired share of the book, reason, thesis, what would prove it wrong |
| Who sizes | the model, cut by code | code only (`live/sizing.py`) |
| What it sees | packet | the same packet, restricted to names under review, plus quant cards, graph connections with quotes, attention triggers |
| Research tools | 4 document tools, once | the same 4 plus 6 graph tools, once, 6 requests in total |
| Models | `claude-sonnet-5` | decider and confirmer, section 4 |
| A second book | none | a shadow book sizing the same intentions under the expanding rules (section 5) |

Unchanged: the model proposes and code disposes; long-only; fills at the next session's close from a
real close with volume; INCOMPLETE is never HOLD; receipts hold everything the model saw.

## 2. The packet

Portfolio (all holdings, cash, weights, tax position); `under_review`; `not_reviewed_tonight` with each
name's last recorded decision; `attention` (every trigger with the ids it may be cited by);
`must_address_this_week`; candidates in scope; prices, exchange flags, verified events, coverage and
filed results for names under review; a quant card per name (`live/quant.py`, QUANT-1); graph coverage
and one-hop connections per name (`live/graph.py`, GRAPH-1); memory and scorecard; the live sizing
rules and this month's remaining allowance; costs.

## 3. Attention (`live/attention.py`)

A name is reviewed when any of these fired since its last review: a high-materiality verified event;
a filed quarterly result; a move of at least 2σ of its own daily volatility; P/E at or beyond its own
3-year 10th/90th percentile; evidence recorded as contradicting its thesis, or a close below the level
the investor stated would prove the thesis wrong; a high-materiality event at a company it supplies
(found through the graph; exposure from the disclosed revenue share, or MISSING); name above 22% or
sector above 32% of the book; its filings not read tonight. Portfolio level: a failed evening step;
cash above 25% of the book for two consecutive months while candidates exist.

**Full review** of every holding and all candidates: Fridays; whenever seven days have passed since
the last; whenever a portfolio-level trigger fires; on the first evening. A holding not reviewed keeps
its last decision record and is shown as "not reviewed tonight: no trigger".

## 4. Models and money

- **Decider** (triggered reviews): `claude-sonnet-5`.
- **Confirmer** (every open and every exit before sizing; runs full reviews): `claude-sonnet-5`. When
  the decider is the confirmer, its own decision stands and the record says so.
- An unconfirmed open is not sized; an unconfirmed exit is held. A confirmation that did not arrive is
  not a yes.
- Every call is reserved in the decisions partition of the monthly cap before it is made.
- **Replacing the decider** with a cheaper model (local Qwen3.5-9B, DeepSeek V4 Pro, or another) is a
  new registration, allowed only after that model passes every scenario in SCENARIOS-1
  (`scripts/agent.py scenarios`) and its agreement with the confirmer on the same scenarios is reported.
  Passing rules a model in; it does not show decision quality.

## 5. Sizing

- **Live book:** `CURRENT_SIZING` — AI-PM-2's limits: 8 names, 20% name and 30% sector for purchases,
  ₹50,000 a month, no rollover.
- **Shadow book:** `EXPAND_SIZING` — tiers core 8–12%, standard 4–6%, starter 2–3%; new position at
  least ₹15,000 or not opened; up to 40 names (new purchases only); purchases of a name above 20% or a
  sector above 30% pause; allowance `A(m) = min(carry + ₹50,000, ₹1,00,000)` less purchases and queued
  buys, counted from the month the shadow is seeded. Seeded as a copy of SYSTEM on AI-PM-3's first
  evening. Its orders fill at the same session the live book's would.
- Both books check traded volume, affordability including charges, purchase limits and caps again
  at the fill price. The shadow receives subsequent external cash flows once and interprets the
  same intentions against its own holdings. Each book receives dividends and splits on its own
  eligible holdings, with ex-date actions before that session's trades.
- **No rule sells.** Sales come only from reduce or exit intentions with a reason.
- Compared by `scripts/agent.py compare`: capital deployed, cash, names, effective names, largest name
  and sector, traded value, costs and tax. Switching the live book to the expanding rules is a later
  registration, after that comparison.

## 6. Resumability

Receipts are written before they are parsed; the journal (`data/twin/agent/journal.jsonl`) records
attention, review, confirmation and queue per evening; decision, logbook, intention and scope rows are
keyed by the review digest. A rerun after an interruption at any step makes no model call already
answered successfully, queues nothing twice and writes no record twice (tested). Refused and
truncated receipts remain failures on retry. The queue journal restores orders after a crash before
the outer book save; each record file completes independently. A durable fill batch records the
before/after portfolio (including lot identities and tax state) before either the fill log or book
save, so recovery restores the same result without spending the allowance or applying tax again.

## 7. Start

**Start date: 2026-09-16.** Written here and in `twin.EVALUATION_START` in one commit on 2026-09-15,
before that evening. The first review is the evening of Wednesday 16 September; an order it queues
can first fill at Thursday 17 September's close. Sections 1–6 are now frozen for the first month.

AI-PM-3 starts the trading evening after all of these hold, and the date is then written here and in
`twin.EVALUATION_START` in the same commit, before that evening:

1. Phases 3, 4 and 5 are merged and `scripts/graph.py ingest` has run on the real archive.
2. `scripts/agent.py scenarios --model claude-sonnet-5` passes every scenario.
3. `scripts/agent.py shadow-review` has run once on real data, and its receipt has been read by a person.
4. SYSTEM has no order waiting to fill.

**How each held, 2026-09-15:**

1. Phases 3–5 merged (#155–#157), AI-PM-3 made the only investor (#162) with release fixes (#163,
   758 tests passed). `graph.py ingest` ran on the real archive: 16,166 assertion versions.
2. `agent.py scenarios --model claude-sonnet-5`: **5 of 5 passed** —
   `data/twin/agent/scenarios/claude-sonnet-5.json`.
3. `agent.py shadow-review` ran on real data — the close of 2026-09-11, the latest the panel held
   when it ran — a full Friday review of 8 holdings and 8 candidates, no research round, 104,216
   input and 14,371 output tokens. Receipt:
   `data/twin/agent/shadow-review/receipts/2026-09-11-review-d7a3e4861179c83191988fa5.json`.
   Intentions: reduce JIOFIN, TATAPOWER, VBL; add TCS, WIPRO; hold HCLTECH, INFY, MUTHOOTFIN. Every
   cited event exists in the packet, is dated on or before 2026-09-11, and its quote supports the
   reason. One wording overreach was noted: TATAPOWER's reason calls the SIAC award "fresh", while
   the cited filing says it was made in July 2025; the new fact is the 2026-09-10 headline. Read by
   the user before this date was merged.
4. SYSTEM's `pending` is `None`.

**Released code:** main at `8bb6375` (#163) plus this commit. Code, model ids, prompts and sizing
rules are frozen for the first month; prices, evidence, memory, holdings and records keep updating.

## 8. Corrections

*(Dated. Sections 1–6 are not edited after the start date is set.)*

- **2026-09-15, before any start** — found while retiring AI-PM-2, all fixed and tested:
  1. *The scorecard never showed AI-PM-3 a single one of its own decisions*: it counted only rows
     labelled AI-PM-2. It now counts every version's decisions and names the version on each row.
  2. *Filing events dated by the evening they were read.* 811 events have no event date and fell back
     to the reading date, so a filing published a year earlier and backfilled on 2026-09-12 looked like
     fresh news to the packet and to attention. They are dated by publication.
  3. *The `filings` research tool answered "0 verified events" to every request.*
  4. *A run cut between a fill and the book's save wrote the fill twice*, and the month's allowance is
     counted from that file.
  5. *The evaluation harness* counted AI-PM-2's receipt folder, where AI-PM-3 writes none, and never
     counted a purchase against the monthly limit.
  6. *One start date.* The evening run read AI-PM-2's start (2026-09-14) and would have run AI-PM-2
     tonight; AI-PM-3's start is now the only one.
- **2026-09-15, release checks before any start** — interrupted fills previously rebuilt a different
  portfolio after counting the saved purchase against its allowance; queued orders and partially
  written review records could be lost; cached failed replies could pass on retry. Recovery now
  restores the committed state. Fill costs fit inside the monthly allowance, both sizing books
  enforce their rules at fill time and receive later funding, and divergent holdings no longer
  invalidate the same investment intention. The daily path imports corporate actions for AI-held
  names and settles actions around missed-session fills; the shadow receives its own entitlements.
  Evaluation excludes HOLD from the count of reduced/cancelled trade intentions. These are
  correctness fixes before registration opens, not evidence of investment performance.
