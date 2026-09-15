# Q-Alpha

**An AI that invests a paper portfolio of large Indian companies on its own — and a record honest
enough to tell whether it is any good.**

Its book starts as a copy of the user's real Zerodha holdings, taken from his tradebook. Each trading
evening it reads the day's prices, the companies' filings and the headlines, reviews every holding
and a short list of candidates, and decides to hold, buy or sell. The trades happen on paper. Its
losses are its own. The horizon is years, not days.

**Nothing here places a real order, and nothing ever will.** If the paper record shows it works, the
user may act on its recommendations in his own account, by hand, as his own decision.

This file is the whole project: what it is, how to run it, what it has learned, the maths it uses,
and what gets built next. Development rules are in [CLAUDE.md](CLAUDE.md). Past versions of every
plan and report are in git history.

---

## 1. Where it stands — 2026-09-15

| | |
|---|---|
| **Working** | The evening run: prices → filings → headlines → filed results → four paper books marked against two index funds. Tax-exact FIFO accounting. Resumes where it stopped. |
| **The investor** | **AI-PM-3**, the only one (`live/agent.py`), registered in [reports/PREREGISTRATION_AI_PM3.md](reports/PREREGISTRATION_AI_PM3.md). AI-PM-1 and AI-PM-2 were retired on 2026-09-15 without making a decision. |
| **Start date** | **Not set.** Until it is, `SYSTEM` mirrors the user's holdings and nothing decides. It is set once the checks in the registration's §7 pass. |
| **Proven edge** | None. See §6. |

---

## 2. How to use it

1. **Double-click Q-Alpha** on the desktop. The black window *is* the app; closing it stops it. It
   runs the evening by itself and opens `http://127.0.0.1:8787/`, which narrates the run and reloads
   when it finishes.
2. **Read the page**: the four books, what `SYSTEM` holds, which filings were read, and what went
   wrong, if anything. A failed step says so in words; it is never hidden.
3. **After you trade in your real account, drop the tradebook export into `data/tradebooks/`.**
   Zerodha Console → Reports → Tradebook → CSV. It must reach back to your first trade
   (2026-06-15); overlapping exports are safe — duplicates are removed by trade id.

That is all. There is no broker login. Missing two days costs the two days, not the work: the next
run resumes what it had not finished.

**Check a tax figure by hand the first time you sell something complicated.** The engine has matched
a real Zerodha Tax P&L exactly once — a single lot, short-term, no loss (§6).

---

## 3. What runs each evening

```
prices     yfinance → data/historical/*.parquet   (watchlist, Nifty-50 point-in-time, NIFTYBEES)
  ↓
scope      SYSTEM's holdings + the 8 names furthest below their 1-year high     live/screen.py
  ↓
filings    NSE announcements for those names → archive the bytes → extract events,
           each with a quote checked against the archived document              scripts/evidence.py
  ↓
headlines  4 market feeds + one Google News search per name → archive → map → read   scripts/news.py
  ↓
results    each company's filed quarterly results, both NSE feeds → check → store  scripts/financials.py
  ↓
graph      everything read tonight → the knowledge graph ($0)              scripts/graph.py ingest
  ↓
books      credit flows → fill yesterday's orders → the investor reviews → mark   scripts/twin.py
  ↓
page       data/session/qalpha.html, served by live/server.py
```

Each step is recorded in `data/session/ledger.jsonl` — one journal, holding both the steps and the
evening's own summary — against a digest of its inputs (date, names, price panel bytes, extraction
version). Finished work is not redone; changed inputs make it pending; a failure is recorded and the
evening continues.

**The run knows what day it is.** The world is dated by the session its prices come from. On a
Saturday, or on Ganesh Chaturthi, the page says the exchange was closed and no review is asked for.
A *trading* day with no closing prices is a failure — something did not download — and says so.

**Model calls are budgeted before they are made** (`live/spend.py`). Every priced call reserves its
worst-case cost in `data/spend/ledger.jsonl` first and runs only if the month's settled spend plus
open reservations stays under the cap (`spend_cap_usd`, $15 by default). Reading and backfills can
never use the part kept for decisions (`spend_decisions_reserve_usd`, $6). When the reply arrives the
reservation is settled at the real token count. A budget reached, an account out of credit, or a
model that is not the registered one makes the step **not run** — a review becomes INCOMPLETE, never
a HOLD, and a reading run stops with its documents still unread. Local models cost nothing but must
have their weights pinned (`scripts/models.py pin <tag>`) before they may read for the corpus; the
reader comparison below records the digest it measured instead, because pinning follows measurement.

---

## 4. The four books

Every book receives **the same rupees on the same days**, taken from the **broker's ledger** — the
dated deposits and withdrawals themselves (`data/twin/funding.json`, imported by
`reconcile_account.py --import`). They differ only in what they did with the money.

**Cash is part of the answer.** The books were once funded by what the tradebook showed *spent on
shares*, so ₹2,01,117 sitting in the account existed in no book and not investing it cost nothing.
Now every book starts with the full ₹5,05,686. The baselines put all of it into their fund on the
day it arrives; the investor may only spend ₹50,000 a month, so it will hold cash for months. That
cuts both ways and is meant to: holding cash while the index falls is a real gain, and holding it
while the index rises is a real cost. Both now show.

| Book | What it is |
|---|---|
| `SYSTEM` | The AI investor's paper book. Seeded as an exact copy of `REAL`. |
| `REAL` | The user's own trades, replayed. |
| `BASELINE_EW` | The same money in a Nifty-50 **equal-weight** index fund, net of its 0.41% fee. **The bar.** |
| `BASELINE` | The same money in NIFTYBEES, bought and held. The do-nothing floor. |

`BASELINE_EW` is the bar because most of what once looked like an edge over the cap-weighted index
turned out to be the equal-weight premium — which anyone can buy in five minutes.

**Dividends.** The baselines are marked on adjusted (total-return) series, so their dividends are
reinvested for them. The twin's holdings are marked on raw closes, so its dividends have to be
credited explicitly, on the ex-date, or the bar wins on arithmetic alone. They are
(`corporate_actions.py --import`), and each is cross-checked against the price panel's own
adjustment factor before it is applied. Between the first trade and 2026-09-11 the book earned
₹0 of them: everything but the starter position was bought on 2026-08-28, after every ex-date.

**Names the bar cannot price.** Seven Nifty-50 members have no price in the panel at all —
TATAMOTORS (symbol retired at the 2025 demerger; the watchlist names its successor, TMPV), HDFC, CAIRN, IDFC, JPASSOCIAT, LTIM, STER. They
were always excluded from the equal weighting; now they are named on every run rather than silently
missing, so "the fifty" is never quietly forty-nine. A member that stops being priced mid-life makes
the day's level **unknown** rather than ₹0 or its last price.

A gap between books is **descriptive**. One book over months is mostly timing and luck.

---

## 5. The investor — what is being built

### AI-PM-3: the investor

Registered in [reports/PREREGISTRATION_AI_PM3.md](reports/PREREGISTRATION_AI_PM3.md); it decides for
`SYSTEM` from the start date in its §7, which is also `live/twin.EVALUATION_START` — the one start date.

- **Attention first** (`live/attention.py`): each evening code flags what changed — a high-materiality
  event, new results, a 2σ move, a valuation extreme, a contradicted thesis, trouble at a customer it
  supplies, concentration, a missing feed, idle cash. Only flagged names are reviewed; every holding
  weekly. A name not reviewed is shown as "not reviewed tonight: no trigger", never a fresh HOLD.
- **Sees** for the names under review: verified filing and headline events; a year of prices; each
  company's own filed quarterly results as published by that date; a quant card; graph connections
  with quotes; its own memory. **May ask once** for up to 6 read-only look-ups (`live/tools.py`, graph
  tools).
- **Intentions, sized by code** (`live/agent.py`, `live/sizing.py`): open / add / hold / reduce / exit
  with conviction and desired share of the book, a reason, a thesis and what would prove it wrong.
  The live book sizes them under the original limits (8 names, 20% a name, 30% a sector, ₹50,000 a
  month); a shadow book sizes the same intentions under the expanding rules, for comparison.
- **Two models**: a decider reviews; a confirmer must confirm every new position and every exit.
- **Fills** at the **next** trading session's close, never at a price the decision had already seen.
- **Incomplete is never HOLD.** No reply, a truncated reply or a citation that is not the company's
  own means the review did not happen, and the page says so.
- **Memory:** a logbook the model writes each review and a scorecard code computes from its past
  decisions — fed into the next review, labelled as its own earlier beliefs and results.
- **Scenario suite** (`live/scenarios.py`): fixed situations that rule a cheaper decision model in or
  out before it may replace the registered one.
- **Resumes at any step** without a second model call, a second order or a second record.

### What a "version" means

A version is a fixed description of the investor: model, prompt, what it is shown, what tools it
has, how fills work, its limits. **The paper book is one continuous book across versions**; every
decision is stamped with the version that made it. Nothing is reset — versioning stops a better-informed investor's results being
credited to an earlier one.

### The build order

Each step is its own registered version. Training or a knowledge graph comes only if a measured gap
calls for it.

| Step | What | Done when |
|---|---|---|
| **A. Accounts** ✓ | Deposits and withdrawals as explicit flows, from the broker's ledger. Dividends as dated cash on the ex-date, each cross-checked against the price panel's own adjustment before any book receives it. Splits and bonuses through the replay, checked by the share count against the broker's statement. | Done: `tests/test_accounting_scenario.py` runs one book through a deposit, a dividend, a split, a partial sale with tax, an unpriced holding and a restart, and reconciles with no manual edit. |
| **B. Company facts** ✓ | The companies' own filed quarterly results, from both of the exchange's feeds — the old results feed (to Dec 2024) and SEBI's Integrated Filing feed (2025 on) — keyed by the time each was published; banks read under the banking taxonomy (interest earned, provisions, NPAs); growth and margin computed by code; refreshed every evening, and a re-import is byte-identical. | Done: every filing is checked against its own statement's identities and refused if it does not add up; a filing is invisible to a packet dated before it was published, a restatement supersedes only from its own date, a full year is never stored as a quarter, and a fetch never deletes a stored filing — all pinned by tests. `financials.py` prints the counts. |
| **C. Mandate** ✓ | One versioned mandate (`live/mandate.py`): every limit in one place, read by the manager, stated in the prompt, and written into every receipt. | Done: the prompt's numbers are asserted to be the numbers code enforces, a mandate file that sets an unknown field is refused rather than silently ignored, and the whole mandate is in the packet. |
| **D. Research tools** ✓ | Four read-only look-ups (`live/tools.py`) the investor may ask for **once**, before deciding: more filings, every filed quarter, one metric across names, a finer price history. Answers join the packet and the receipt. | Done: every tool is bounded by the review's own date and by the names in front of it; requests beyond the limit are refused out loud; research surfaces archived ids and never mints one, so a citation earned by research is checked like any other. |
| **E. Evaluation** ✓ | `scripts/evaluate.py` — one command, immutable inputs, three separate tests, no gate. It prints **no outcome figure** below 60 observations, and names what it cannot measure. | Done. Point-in-time Nifty-100 is **still unsourced and stays that way**: `NEXT_50_CHANGES` is empty, and filling it from today's constituents would look complete while reintroducing ~3.8%/yr of survivorship bias. The harness reports that as a named limit. |
| **F. Training** | **Not started, and not justified.** Training needs a *measured* deficiency, and there is no record yet to measure one in — zero real reviews. The standard is written down below so it cannot be lowered later. | Would need: a deficiency visible in the evaluation harness across enough reviews to be a pattern rather than a run; a frozen baseline; and the trained version beating that baseline on data neither saw. Until all three exist, this stays at not-started. |

### Data to collect

| Dataset | Why | Source |
|---|---|---|
| A year of filings for candidates nobody has read (now IRFC, ITC, HDFCLIFE, GODREJCP, HDFCBANK, IOC, TMPV) | A candidate whose filings are unread is not shown to the investor | `scripts/evidence.py backfill --only … --workers 8` — about $2 a name; the evening prints the exact command |
| Tax P&L, every quarter with a sale | Re-reconcile tax on multi-lot, long-term and loss cases | Zerodha Console, from the user |
| Dividend and corporate-action statements | Check the vendor's dividend record against the broker's | Zerodha Console, from the user |
| Point-in-time Nifty-100 membership | Step E | NSE Next-50 circulars → `scripts/build_nifty100_pit.py` |

Private account files go in `data/account/` and are never committed.

### The knowledge graph and quant cards (built; not yet in the evening)

What Q-Alpha retrieves is kept, connected, and dated, so the investor can follow a chain — two
holdings that supply the same customer — instead of re-reading a year of filings.

- **The record is an append-only log** (`data/graph/assertions.jsonl`, `live/graph.py`); Neo4j is a
  projection rebuilt from it (`live/graph_neo4j.py`), so a correction can never rewrite history.
- **Every assertion is DISCLOSED** (document hash + verbatim quote), **COMPUTED** (inputs + code
  version), **INFERRED** (model + confidence, never returned as a fact) **or MISSING** (a known gap).
- **Two time axes:** when a fact applied, and when Q-Alpha knew it. A restatement filed today leaves
  yesterday's answer exactly as it was — tested.
- **Filled at $0** from what is on disk (`scripts/graph.py ingest`): filing and headline events,
  filed results, the investor's decisions and theses. Connections between companies (supplier,
  owner, subsidiary, competitor, related party) are read by a model from filings
  (`scripts/graph.py relations`), kept only with a verbatim quote. Ratings, board and shareholding
  feeds are not ingested yet and show as MISSING.
- **Quant cards** (`live/quant.py`): trailing P/E against its own three-year point-in-time range,
  growth, margin trend, bank ratios, volatility, drawdown, beta to NIFTYBEES, correlation with the
  book, and what adding ₹15,000 would do to the book's volatility. Measurements, not signals.

### Sizing that expands (built; runs on a shadow book first)

The investor will state **intentions** — open, add, hold, reduce or exit; conviction; desired share
of the book; why — and code turns them into orders for each book (`live/sizing.py`).

- **Selling is decided, never forced.** Every rule limits purchases. A name that drifts from 20% to
  28% on price is not sold; buying it pauses and it is flagged for review.
- **Depth:** positions aim at a conviction tier — core 8–12%, standard 4–6%, starter 2–3% of the book.
- **Breadth:** new names up to 40; a new position opens at ₹15,000 or more, or not at all. Neither
  rule ever sells an existing position.
- **Rollover:** `A(m) = min(unspent last month + ₹50,000, ₹1,00,000)`, less purchases and queued buys.
  The allowance limits buying; it is not cash, and cash never expires.
- **Tested before use:** the live book keeps AI-PM-2's limits (`CURRENT_SIZING`); a shadow book
  applies `EXPAND_SIZING` to the same intentions, and the two are compared on capital deployed, idle
  cash, names, effective names, concentration, turnover and tax.

### Which reader, at what cost — EX-5 (built, not yet run)

Reading every filing with `claude-sonnet-5` ran the API key dry. EX-5 measures, on 150 fixed archived
filings, whether a local model on this laptop or a cheaper API reads well enough, and which routine
notices (trading-window closures, newspaper copies, ESOP allotments) can be skipped without hiding
anything material. Registered in
[reports/PREREGISTRATION_EX5_READERS.md](reports/PREREGISTRATION_EX5_READERS.md) before any run.

- **The reference** is Opus 5's complete readings plus every candidate's claim that Opus judged
  true — **checked by the user**: 20 documents read end to end, 25 of the judge's verdicts. If the
  reference missed more than 10% of what the user found, nothing is selected.
- **A reader qualifies** with high-materiality recall ≥ 0.85 (and ≥ 0.9 × the best), precision ≥ 0.85
  and ≥ 90% verbatim quotes. The cheapest qualifier wins.
- **Skipped filings are "routine, not read"**, never counted as read (`live/triage.py`). A rule that
  hides one high-materiality event is removed.

`scripts/readers.py` runs it step by step; the evening run is unchanged until a result is registered.

---

## 6. What is proven, and what is not

**Proven**

- The FIFO, cost and tax engine matched a real Zerodha Tax P&L **to ₹0.00** — one sale, single lot,
  short-term, no loss.
- **Trading less beat trading more**, net of cost and tax, in every walk-forward sub-period tested.
- **Equal-weighting explains most of the apparent edge** over the cap-weighted index.
- **Selling to manage risk loses to the tax**: rule-based exits finished ₹74.8 lakh behind
  buy-and-hold over 13 years and paid ₹13.3 lakh in tax doing it.

**Not proven — say so whenever a number comes up**

- **No strategy here has shown an edge over the equal-weight fund.** The old screen's best reading was
  ≈0.4–0.6%/yr against ~5%/yr of noise: separating that from luck at 95% needs roughly two hundred
  years of one portfolio. Twelve months, in either direction, is consistent with chance.
- **The AI investor has no record at all.**
- **Most of the tax engine has never met a broker statement**: multi-lot, long-term, loss set-off and
  §112A are unit-tested only.
- **No corporate action has been reconciled live.** The likeliest thing to go wrong first.
- **Nobody has watched this system through a market fall.**
- **The filing corpus under-counts events.** ~25–29% of the reader's quotes fail verbatim
  verification — true statements, not contiguous text — so absence of an event is not evidence of no
  event.

---

## 7. The experiment record

Everything measured on the way here. Full reports are in git at commit `53e2588`
(`git show 53e2588:reports/<file>`).

| Id | Question | Answer |
|---|---|---|
| Phase 0 | Does the factor optimizer beat 1/N net of cost and tax? | 18.2% headline, **not out-of-sample**: the winning setting was chosen on the holdout. |
| Phase 4 | Where did the screen's gap over NIFTYBEES come from? | **76% of it is the equal-weight premium.** Hence `BASELINE_EW` as the bar. |
| Screen OOS | Does "buy the biggest pullbacks" beat 1/N, 163 months? | 8 names +2.65%/yr, t = 0.60; every interval includes zero. |
| Null matched | How long to tell this edge from luck? | ~200 years of one portfolio. The GO gate was deleted. |
| PO-1 | The live rulebook over 14 years, point-in-time Nifty-50 | **−55%** against the equal-weight fund. |
| PO-2 | Which layer lost it? | Raw top-8 ranking +9.1% vs the fund; filling underweights −27%; exits −55%. |
| PL-1 | Four fixes, replayed through the real runner | Exits off +52.7% ships; breakdown-as-flag **rejected, −23.2%** (it reversed PO-2). Still −26.9% vs the fund. |
| WC-1 | Is money invested during deep drawdowns better? | Yes: median +30.3% vs the fund — but only in 11 of 177 months, ~7 episodes. |
| WC-2 / 2b | Can you save cash for those drawdowns? | Full period +12.2%; **both halves ≈ 0 or negative.** One alignment (COVID). No. |
| ES-1 | Do negative filing events predict falls? | 20 days: −0.62%, t = −0.77. **Null.** 61 name-days behind the primary test. |
| EX-3 reader | Which model reads filings? | `claude-sonnet-5`: 29% quotes discarded vs Haiku's 59%, twice the events. Readers agree on 22% of findings. |
| EX-4 | Does a tighter prompt fix unverifiable quotes? | **Worse**: 155 events vs 200, 34.9% discarded vs 25.1% (220 documents). Reverted. |
| EX-5 | Which reader is good enough at the lowest cost, and which filings need no reading? | **Built, not run.** Rule registered first. |
| AI-PM-1, AI-PM-2 | The first two investor versions: one review of every name each evening, share counts chosen by the model | **Retired 2026-09-15 before either made a decision** (one shadow review between them). Superseded by AI-PM-3; their registrations are in git history. |
| Forward run 1 | 6 weeks of paper trading | **Void**: flows were injected on a calendar the real account never had. |
| Research track | QUBO ×2, HMM regime overlay, LPPLS crash signal, futures hedge | All negative. Archived in `Q_Alpha_Research`. |

---

## 8. Failures this project must not repeat

**Almost every serious defect here was a correct number with the wrong label**, or the right
function fed the wrong input. Passing unit tests caught almost none of them.

| It said | It was | The rule now |
|---|---|---|
| "ahead by ₹4,01,677 (+444%)" | ₹1,677 — parked cash counted as performance | Label every number as what was computed. |
| "Deploy ₹1,00,000" | a ₹5,97,418 basket, 84% in one stock | Test the caller with holdings **and** cash. |
| a backfill "running" | an API key with no credit left; nothing knew what had been spent | Reserve the worst case before every priced call; decisions keep their own share. |
| `BASELINE_EW`, the equal-weight fund | NIFTYBEES minus a fee | One definition per series; never reuse a neighbour's. |
| "worst fall −34.9%" | −47.5% — deposits hid the drawdown | Unitize before measuring a book money flows into. |
| "Clear" on the buy screen | nobody had read the filings | Unread is not clean. |
| "25 of 25 filings read" | 25 of 30 — the cap sliced the window | Count the eligible set before any cap. |
| a benchmark window with no data, `0.0%` | unmeasured | Unknown is never zero. |
| a refused model call | parsed as a filing with no bad news | A missing reply is not an answer. |
| "12 negative items" | 4 — lines in an append-only log, not events | Read the current revision, not the log. |
| a step that failed | left **zero bytes** where yesterday's report was | Atomic writes for anything read later. |
| an evidence step `done` after 216s | zero coverage — "nothing to do" returned 0 | Covering nothing is not success. |
| a veto citing a source | a stock quote page | A citation must be checked against the archived document. |
| a 30-day veto window | read the filing date, not the event date | Date events by when they happened. |
| alphabetical one-share baskets marked `EXECUTE` | the scheduled caller fed good code bad data | Test the production entry point, not only the function. |
| `mypy src scripts`, green | vacuous — the package resolved to `Any` | Verify the check checks something. |
| a fill at the close the decision had seen | look-ahead | Fill at a later session. |
| a model change mid-experiment | silently a different experiment | Pin models; a change is a new version. |
| "−53.0%/yr" on the page | three months annualized | No annual rate under a year of history. |

---

## 9. The maths

Formula → example → why. Section marks (§) in code comments refer to these headings; any other §
number in an older comment is the original spec, `git show 53e2588:Q_alpha.md`.

### FIFO lots (§2.7)

Every buy is a **lot** with its own date and price. A sale consumes the oldest lots first.

> Sell 6 TCS. Lot 1: 2 shares bought Jan 2025 — consumed fully, held over 365 days → long-term.
> Lot 2: 4 of 8 shares bought Aug 2025 → short-term. Tax is computed per lot.

*Why:* Indian demat accounts are FIFO by law; one average price per stock gets tax wrong.

### Costs (§4.6) — Zerodha delivery equity

| Charge | Rate |
|---|---|
| Brokerage | ₹0 |
| STT | 0.1% of turnover, buy and sell — **not deductible** from capital gains |
| Exchange transaction | 0.00297% |
| SEBI fee | 0.0001% |
| Stamp duty | 0.015%, buy side only |
| GST | 18% on (brokerage + exchange + SEBI) |
| DP charge | ₹13.50 per sell (the GST on it is not modelled) |
| Slippage | `k · σ_daily · √(trade value ÷ ADV)`, clamped to [0.02%, 2%]; 0.2% when size data is absent |

> ₹1,00,000 buy: STT ₹100, stamp ₹15, exchange ₹2.97, SEBI ₹0.10, GST ₹0.55 → ≈ ₹118.62 plus slippage.

### Tax (§4.6)

- **Short-term** (held < 365 days): 20%. **Long-term** (≥ 365 days): 12.5% above ₹1.25 lakh per
  financial year (April–March). **Cess** 4% on top: effectively 20.8% and 13%.
- **Set-off** (§70/§71): short-term losses offset any gain; long-term losses offset only long-term.
  **Carry-forward** (§74): 8 assessment years.
- **Grandfathering** (§55(2)(ac)): for equity bought before 2018-02-01, cost is
  `max(actual cost, min(price on 2018-01-31, sale value))` — old gains are sheltered, but no loss is
  manufactured.

> Sell for a ₹10,000 short-term gain: tax ₹2,000 + cess ₹80 = ₹2,080.

*Why:* tax is the largest cost of trading, and the one most often ignored.

### Money-weighted return (XIRR)

The annual rate `r` that makes `Σ flow_i / (1+r)^(t_i/365) + value_today / (1+r)^(T/365) = 0`,
with money in negative. **Withheld under a year of history** — three months annualized reads as a
disaster or a miracle.

### Unitized NAV and relative wealth

A deposit buys **units** at today's NAV instead of raising the price:
`units_new = units + deposit ÷ NAV`, `NAV = value ÷ units`.

> A ₹1,00,000 book gains 10% → ₹1,10,000. Add ₹1,00,000 to it and to a flat rival: raw ratio
> 2,10,000 / 2,00,000 = +5%. NAV ratio stays +10%.

Relative wealth between two books is `G = ln(NAV_A ÷ NAV_B)`. *Why:* deposits otherwise dilute every
lead and hide every drawdown.

### The equal-weight fund (`BASELINE_EW`)

On the last trading day of each month, split the fund's value equally across the names that were
Nifty-50 members **on that day** and had a price; hold units until the next month. The fund's fee is
charged continuously: `value × (1 − 0.41%)^years`.

*Why:* using today's members for the past would hold future winners before they joined the index.

### The candidate list (§ pullback)

`pullback = 1 − price_today ÷ highest price in the last 252 trading days`, floored at 0. A name whose
price series has an unexplained jump is measured only from after the jump; with too little history
since, it scores 0.

> High ₹1,000, today ₹750 → pullback 0.25.

*Why:* it narrows ~96 names to 8 the investor can read about. **A pullback is not a valuation**, and
the investor is told so.

### Evidence verification

A model-reported event is kept only if its quote appears **verbatim** in the archived bytes of the
document it cites, for a company it was given that document for. A row counts toward coverage only
if it was read by the named corpus reader at the current extraction version.

---

## 10. Layout

```
src/qalpha/
  accounting/  FIFO lots · costs · slippage · capital gains · corporate actions · Portfolio
  data/        price panels (yfinance → Parquet, atomic writes) · point-in-time universes
  live/        announcements · evidence · extraction · news · pretrade · localmodel   (reading)
               triage · readers · reference · reader_scoring     (EX-5: measuring the readers)
               sizing                                        (intentions → orders, per book)
               agent · attention · scenarios                 (AI-PM-3)
               spend · model_identity                        (what a model call may cost, and who answered)
               graph · graph_ingest · graph_neo4j · graph_tools · relations · quant   (knowledge)
               manager · evidence_log · decisions                                 (the investor)
               twin · flows · nav · benchmarks · tradebook · taxpnl · market · screen (books)
               daily · session · server · record · panels · progress · atomic · console (running)
scripts/       local_run (the app) · twin · evidence · news · reconcile_taxpnl · ocr_scans · readers · models · graph · agent
               build_nifty_universe · build_nifty100_watchlist · build_nifty100_pit
reports/       pre-registrations still in force
data/          evidence archive · twin books and history · universes · tradebooks (private)
```

```bash
uv sync --extra dev --extra ai
uv run python scripts/local_run.py --app --autorun      # what the desktop click runs
uv run ruff check . && uv run ruff format --check . && uv run mypy src scripts && uv run pytest
```
