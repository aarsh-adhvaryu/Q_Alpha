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

- **Financials lag results season, not years.** Results are read from both the exchange's old
  results feed (to December 2024) and SEBI's Integrated Filing feed (2025 on), so a name's newest
  quarter is the newest one it has filed — about six weeks after a quarter ends. Each packet states
  every figure's age in words.
- **Banks are read under the banking taxonomy.** "Revenue" for a bank is interest earned, and the
  packet adds net interest income, provisions and NPA ratios. A consolidated bank filing leaves NPA
  ratios blank; they are shown as not reported, never as zero.
- **Filed quarters that do not add up against their own statement are refused** and named, not fed.
- **Candidates must have had their filings read.** A cheap name whose filings nobody has read is
  listed as not shown, with the reason, rather than put in front of the investor unread.
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
- **2026-09-14** — **a test wrote to the live record.** Teaching `twin.py refund` to set old-basis
  history aside made its test run that path against the real `data/twin/history.jsonl`, and the
  full test suite emptied it. Nothing was lost — the rows are moved, never deleted — and all three
  ledger-basis rows were restored from the set-aside file. `cmd_refund` now takes the history path,
  the test passes its own, and the test suite fingerprints the 2,934 files that make up the record
  (books, history, the investor's records, evidence logs, financials) before and after the session
  and fails if any changed. The suite runs green with it in place.
- **2026-09-14** — **the three data limits in §7 are closed, before the first review.**
  1. *Stale financials.* The latest quarter for every name was December 2024 because SEBI's
     Integrated Filing moved results to a different exchange feed in 2025. Both feeds are now read;
     the new filings carry the same Ind-AS tags under an `in-capmkt:` prefix. TCS's newest quarter
     becomes June 2026, filed 9 July 2026.
  2. *Banks.* Read under the banking taxonomy: revenue is interest earned; net interest income,
     provisions and NPA ratios are added; a consolidated filing's blank (0) NPA is shown as not
     reported. Bank statements are checked with their own identity (operating profit less provisions
     equals PBT) and refused if they do not add up.
  3. *TATAMOTORS.* The candidate watchlist names TMPV, the listing that continues the company after
     the 2025 demerger. The point-in-time index membership is unchanged; its switch date is unsourced.
  Also: a period longer than 100 days is never stored as a quarter. These change what the packet
  contains, so they are part of AI-PM-2 **only if merged and imported before the first review on
  2026-09-15**; after it, the same change would be a new version. Six candidates still have unread
  filings and are shown to the investor as not shown, with the reason, until a backfill reads them.
