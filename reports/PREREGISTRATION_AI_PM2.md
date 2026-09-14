# Pre-registration — AI-PM-2

**Registered 2026-09-14, before the first review.** AI-PM-1 was registered on 2026-09-13 and
**never made a real decision**: its record is one shadow review, and shadow runs are not the book.
Between its registration and its start date the packet gained the companies' own filed financial
statements, which this project's own definition makes a new version. Rather than run AI-PM-1 for one
evening and supersede it, AI-PM-1 is closed with an empty record and AI-PM-2 starts in its place.

The books are continuous. The version label is not.

---

## 1. What is being claimed

That a language model, given a bounded packet of evidence and a fixed mandate, can manage a
long-only Indian equity portfolio at least as well as buying an equal-weight index fund.

Nothing here is a claim that it *will*. This is a forward record designed so that a negative result
is as readable as a positive one, and so that neither can be reinterpreted afterwards.

## 2. The investor

| | |
|---|---|
| Version | **AI-PM-2** |
| Model | `claude-sonnet-5`, pinned by id. A different model is a different treatment. |
| Filing reader | `claude-sonnet-5` under EX-3; headlines under NEWS-1. Pinned into the corpus label. |
| Cadence | One review per trading evening, after 17:00 IST, on that day's close. |
| Horizon | Years. Holding is a decision. |
| Start | **2026-09-15**, the first session on or after the registered start of 2026-09-14 (Ganesh Chaturthi). |

## 3. The mandate

Held in code at `src/qalpha/live/mandate.py` and written into **every receipt**, so a record can
always say which limits produced it.

| Limit | Value | Why |
|---|---|---|
| Names | at most 8 | A book it can actually have read the filings of. |
| Per name | 20% of total value **on purchase** | Concentration is the point; unbounded concentration is not. |
| Per sector | 30% of total value **on purchase** | One macro shock must not be able to take the book. |
| Drift band | +2 points | A cap that forces a sale on a price move pays capital-gains tax to undo a gain. Drift is shown, never forced. |
| Purchases | ₹50,000 per calendar month | The user's own instalment. Selling is never limited by it; freed cash does not raise it. |
| Direction | long only | No borrow, no short, no leverage, no instrument but listed equity. |

**Code disposes.** The model returns typed decisions; deterministic code enforces every line above,
plus affordability including costs and evidence coverage, and may cut or cancel an order with a
stated reason. The model never touches state.

## 4. What the model sees

One packet per review, saved whole with its reply as a receipt:

- every holding and up to 8 candidates (held + the cheapest by pullback, from the Nifty-50 watchlist);
- each name's close, a year of monthly adjusted closes, one-year return, pullback from its high;
- the exchange's surveillance flags;
- up to 6 verified filing/news events per name, with the coverage that produced them — including
  what was filed and **could not** be read;
- **new in AI-PM-2:** the company's own filed quarterly results — revenue, costs, margins, EPS —
  from the Ind-AS XBRL it filed with the exchange, restricted to filings **disseminated on or before
  the review's date**, with growth and margin computed by code, and with their age stated;
- the portfolio's cash, weights, lot-level tax position and monthly budget;
- the mandate above;
- its own memory: the notes it wrote in earlier reviews and a scorecard code computes from its past
  decisions — labelled as beliefs and results, **never as evidence**.

**It may ask for more, once.** Before deciding it may request up to 6 read-only look-ups over the
same archives (`src/qalpha/live/tools.py`): more filings for a name, every filed quarter, one metric
across several names, or a finer price history. Every tool is limited to the review's own date and
to the names already in front of it. The answers are appended to the packet and therefore to the
receipt, and the second reply must decide. There is no third pass.

## 5. What is recorded

- **Receipt** per review: packet, reply, model, version, usage, timestamp, digest.
- **Decision** per name: action, quantities requested and accepted, reason, thesis, `invalidate_if`,
  cited evidence ids, the price it saw.
- **Logbook**: what the model wrote about each name and the portfolio, in its words.
- **Fills**: at the **next** session's raw close with positive volume. Never at a close the decision
  had already seen.
- **INCOMPLETE is never HOLD.** No key, a refused or truncated reply, unparseable JSON, a holding
  left out, an unread holding, a changed model — the review did not happen and the page says so.

## 6. How it will be judged

`scripts/evaluate.py`, one command over immutable inputs, three separate tests:

1. **Operation** — did it run as registered? Pass/fail, judgeable immediately.
2. **Decision quality** — were decisions made properly, independent of whether they paid?
3. **Outcome** — unitized NAV against `BASELINE_EW`. **Needs roughly three years.** Below 60
   observations the harness prints no figure at all, because a figure printed there would be read.

**The bar is `BASELINE_EW`** — a point-in-time equal-weight Nifty-50 fund, charged 0.41%/yr. Not
NIFTYBEES, which is the do-nothing floor.

**There is no gate and nothing to tune.** A negative result requires no code change to report.

## 7. Known limits, stated before the start

- **The financials are stale.** The exchange's results archive currently ends at the December 2024
  quarter for these names, roughly 20 months behind the price panel. The packet says so per name, in
  words, and the evaluation harness names this as a confound. Any effect of financials on decisions
  is entangled with their age.
- **Banks have none.** Nine watchlist banks file under a taxonomy with no `RevenueFromOperations`
  tag. They are shown as **unknown**, explicitly not as weak.
- **25 filed quarters do not reconcile** against their own internal identities and are not fed.
- **No point-in-time Nifty-100.** Candidate scope is the Nifty-50 universe, which is point-in-time.
- **Cash is a live confound.** The books hold ₹2,00,533 of real deposited cash that the ₹50,000
  monthly limit releases slowly, while the baselines are fully invested from day one. In a falling
  market that alone puts SYSTEM ahead. Every surface shows cash beside value for this reason.

## 8. Recorded outcomes

*(Append only, dated.)*

- **2026-09-14** — registered. No review has run under AI-PM-2.
- **2026-09-14** — **dry run before the start, and three defects it found.** One shadow review on a
  copy of SYSTEM: 8 holdings held with filing-grounded reasons, one MARUTI buy proposed and
  **cancelled by code** ("already 8 names"). 32,564 input + 7,507 output tokens, about $0.21. The run
  exposed three things, all fixed before the first real review:
  1. The export guard compared the tradebook's first trade against the books' first *cash flow*.
     Once the books were funded from the ledger, the first flow became a deposit — and money sits in
     an account before it buys anything — so the guard refused a complete export. It now compares
     against a watermark of the earliest trade any export has shown, which is strictly tighter.
  2. The history row was stamped with the **calendar** date rather than the session its marks came
     from, so a holiday wrote Friday's marks under Monday's date: one observation duplicated, not
     two, in the series the evaluation harness counts. Rows are now dated by the session. The one
     mis-dated row written today was removed.
  3. The record page's "deciding for itself" banner keyed on the calendar too, and announced the
     start on the morning of a closed exchange while the book was still mirroring REAL.
  Separately, the refunding of 2026-09-14 left 16 history rows measuring the **old** funding basis
  (₹3,04,144) beside rows measuring the new one (₹5,05,686) — a 40% cliff in the chart that never
  happened. They are moved to `data/twin/history-before-refunding.jsonl`, kept and not deleted, and
  `twin.py refund` now does this itself. The registered window starts 2026-09-14, so no observation
  inside it is affected.
