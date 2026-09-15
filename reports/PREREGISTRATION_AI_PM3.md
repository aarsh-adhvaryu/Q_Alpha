# Pre-registration — AI-PM-3: the investor as an agent

**Registered 2026-09-15, before any AI-PM-3 review of a real book.** Sections 1–6 are frozen once the
start date in section 7 is filled in; corrections go in a dated section at the bottom. AI-PM-2's
record is not relabelled: the paper book is one continuous book, and every decision carries the
version that made it.

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
- **No rule sells.** Sales come only from reduce or exit intentions with a reason.
- Compared by `scripts/agent.py compare`: capital deployed, cash, names, effective names, largest name
  and sector, traded value, costs and tax. Switching the live book to the expanding rules is a later
  registration, after that comparison.

## 6. Resumability

Receipts are written before they are parsed; the journal (`data/twin/agent/journal.jsonl`) records
attention, review, confirmation and queue per evening; decision, logbook, intention and scope rows are
keyed by the review digest. A rerun after an interruption at any step makes no model call already
answered, queues nothing twice and writes no record twice (tested).

## 7. Start

**Start date: not set.** `agent.Registration.start` is `None`, so AI-PM-2 runs SYSTEM.

AI-PM-3 starts the trading evening after all of these hold, and the date is then written here and in
`agent.Registration.start` in the same commit:

1. Phases 3, 4 and 5 are merged and `scripts/graph.py ingest` has run on the real archive.
2. `scripts/agent.py scenarios --model claude-sonnet-5` passes every scenario.
3. `scripts/agent.py shadow-review` has run once on real data, and its receipt has been read by a person.
4. AI-PM-2 has no order waiting to fill.
