# CLAUDE.md

Guidance for Claude Code (and humans) working in this repo. **Rewritten 2026-09-08 from scratch.**

The previous version was itself a from-scratch rewrite on 2026-09-04, at 328 lines, done because the
file had accreted fifteen months of session log. Four days of patching took it to 615 lines with
headings that contradicted their own content — one said *"the build is closed"* above text explaining
it was not, another said *"this is not a bug to fix"* above the description of the bug being fixed.

The same rule applies again, and it is the point of this file: **describe what is true, not what
happened.** History is in git and in `reports/`.

---

## 🛑 Read first

**₹5,00,000 of real money is in the user's Zerodha account** (since 2026-08-27): ₹1,00,000 opening
basket across 8 names, then ₹50,000/month. **He places every order himself. Nothing here has ever
auto-traded and nothing ever will.** Verified: zero call sites place an order.

**He invested before the system's own gate opened, knowingly, with the evidence in front of him.**
Do not re-litigate that decision. Do not soften a red because money is committed. The framing he was
given and which still stands: *plan at the index's ~11–12%, treat the backtest's excess as unproven
upside, size the first year as tuition.*

**Nothing authorizes a GO.** `AUTHORIZING_PAIR` is `None` and every criterion reads ⚪ CANNOT ASSESS.
That is deliberate, not a countdown. Never describe this system as validated for real money.

### The user

Not a trader and does not want to become one. He wants the system to do the research and hand him
one bounded decision. He wants to understand the maths as it is built (formula → example → why), not
to analyse earnings reports himself. **[OPERATING.md](OPERATING.md) is the page he runs this from** —
read it before proposing any change.

---

## The failure mode of this codebase

**Every serious defect found here has been the same defect: a number labelled as something it is
not.** Not arithmetic errors — the arithmetic is almost always right. The *label* is wrong, or the
*input* is wrong, on a surface where the label becomes an order.

| Said | Was |
|---|---|
| "ahead by ₹4,01,677 (+444%)" | ₹1,677 (+1.2%) — parked SIP cash counted as performance |
| "Deploy ₹100,000" | a ₹5,97,418 basket — 84% of the opening position in one stock |
| `BASELINE_EW`, the equal-weight fund | NIFTYBEES minus a fee — *easier* than the do-nothing baseline |
| "the hedge costs 21.5% of ×286.2 terminal wealth" | ×8.4 — 13 years of deposits compounded as returns |
| "worst fall −34.9%, drawdown matches the index" | **−47.5%**, eleven points *deeper* than the index |
| a veto citing a source URL | a stock **quote page**, evidencing nothing |
| `NIFTY_LOT_SIZE = 75` | 65 — stale three days after its own "verify this" comment |
| "hedge available: 8 lot(s), one lot ₹17,923" | one lot is ₹17.9 **lakh** — an ETF price read as the index |
| "703 tests green", in this file | **678** — a progress line counted by eye, then quoted in three PRs |
| a shadow report reading `EXECUTE` over the screen's basket | **alphabetical, one share each**, funded by a budget the screen never saw |
| the anchor order, 393 units for ₹108,365.82 | left **₹0.18** to pay ~₹325 of charges — it could not have filled |
| "25 of 25 filings read" | **25 of 30** — the cap sliced the window, then counted the slice |
| a benchmark window with no data, reported `0.0%` | unmeasured. Flat and unknown are not the same market |
| "Clear" on the buy screen | **nobody had read that company's filings** |
| "The build is closed" | four defects were found that same day |

**Passing tests have caught almost none of them.** Unit tests verify that a function works. These are
failures of *integration* (the right data reaching that function), *methodology* (the function
answering the right question), and *operation* (the scheduled process actually running).

### Four rules that follow

1. **When you fix a defect, grep for every other caller of the thing you fixed.** Three times a
   correct fix was applied at one call site and reasoned about as if applied to a concept.
2. **A test that asserts a source line pins that line's bug in place.** Assert the *property*.
3. **When a number looks wrong in your own scratch run, chase it before explaining it away.**
4. **Test the caller, not only the function.** Eleven tests passed while the scheduled caller fed
   `propose()` alphabetically ordered one-share baskets, because every test supplied good data. A
   test suite is also a caller: "no production caller" is not the same as "unused".

> **Assume your next feature ships with a labelling defect until someone else has looked.** That has
> been true of every feature added since 2026-09-05, without exception.

---

## Iron rules

- **Real money never auto-trades. The user places every order.** Outlives every gate here.
- **Rule (a): the validated backtest headline and its engine are frozen.** No change may touch
  `src/qalpha/{backtest, accounting, data, config}` for a live feature. Verify with
  `git diff --name-only main -- src/qalpha/backtest src/qalpha/accounting src/qalpha/data src/qalpha/config.py`
  — it must print nothing. One exception is on file: `save_parquet` was made atomic on 2026-09-07,
  a correctness fix to a writer, recorded rather than slipped in.
- **Unknown is never substituted.** Missing price ≠ previous price. Missing filing ≠ no bad news.
  Missing AI response ≠ approval. Absent null ≠ threshold of zero. Unread ≠ clean.
- **A number on a real-money surface must be labelled as the thing that was computed.**
- **Audit with idle cash AND holdings.** A zeroed fixture hides an entire class of defect — on an
  empty book any two-name basket is 47/53 by sector, so the governor fires on every clean day.
- **Never tune a parameter to manufacture a GO.**
- **Pre-registration before any experiment; negatives get published.**
- **Flag, don't veto** on the buy list. Selection stays deterministic and the decision stays his.
- **All four gates green before every commit**: `ruff`, `ruff format`, `mypy --strict`, `pytest`.
- **Always branch + PR.** The harness blocks self-merges; the user clicks merge.

---

## What is true today (2026-09-08)

**63 live modules · 1,223 tests green + 1 xfail** (counted, not estimated — see the
table above for what happens when a progress line is counted by eye). **There is no cron.** `paper.yml` was deleted on
2026-09-10 and its five steps moved to `live/daily.py`, which runs them on the user's desktop when
he presses the button. The record from 2026-09-01 to that date was produced by the cron and stands;
everything after it is produced locally.

### Two experiments run, and neither authorizes anything

| | Question | Pair | Window | Status |
|---|---|---|---|---|
| **run 2** | can the whole system beat the fund? | `TWIN_FULL` vs `BASELINE_EW` | 2026-09-01 → 2027-09-01 | operational rehearsal |
| **CORE_V1** | does the *screen* beat the fund? | `CORE_V1` vs `BASELINE_EW` | opened 2026-09-08 | descriptive track |

`AUTHORIZING_PAIR` is `None`. Both tracks record their own statistic under `tracks` in
`data/twin/history.jsonl`, each labelled by its own pair; the `gate` block is empty because nothing
authorizes. Set `AUTHORIZING_PAIR` only when that pair's question, statistic and matched null are all
frozen **before** its window opens.

**Run 2 is a rehearsal** because its treatment changed inside its own window: its first four days ran
under two different AI rules wearing one version label. Preserved in full, no row edited.

**`CORE_V1` is descriptive** because its matched null was withdrawn — see below.

### The matched null was generated and withdrawn

`NULL_P95_LOG_REL_WEALTH` is `None`. A value of 0.071877 was generated on 2026-09-06 from 2,000
draws and withdrawn hours later: it was matched to *a* specification, not to `CORE_V1`'s. The two
pre-registrations named different statistics (p95 of |G| vs of G), the gate is one-sided against a
two-sided bar (true α 2.32%, not 5%), the null diversified into ~50 of 51 index members while
`CORE_V1` holds a capped basket, and `CORE_V1` can sell while the null never does.

Measured p95(|G|) by basket size: **8 names 0.162 · 15 names 0.106 · the null's ~50 names 0.072.**
The bar was 1.5–2.3× too low, and too low is the direction that makes noise look like skill.

> **The qualitative finding survives and is the important one.** The backtest's edge over the gating
> benchmark is **0.42%/yr**; a 15-name basket drifts **5.3%/yr** against that fund for no reason. So
> a correctly matched bar is ~25× the edge, criterion 3 would fire about **1%** of the time if the
> edge were entirely real, and detecting it at 95% needs roughly **200 years**. A twelve-month
> superiority test cannot answer this question. Full detail in `reports/NULL_MATCHED.md`.

### The evidence spine — reads filings, decides nothing

Runs daily **before** the twin. Fetches and archives NSE's regulatory-indicator file (`REG1_IND`,
which carries the P/E>50 caution) and each candidate's corporate announcements, downloads the
filings, hashes them, extracts their text, and puts them through the model.

**The model extracts, it does not judge.** It reports what a document says; deterministic policy
decides what that means. Every event carries a verbatim quote **checked against the archived bytes** —
a quote that is not in the document is discarded and counted. It cannot introduce a name it was not
given a document for, and cannot attribute a real quote to the wrong company.

Extractor version **EX-2**. EX-1 asked for "material events" and never said material *to whom*, so 77
of 193 came back `high` — "revenue up 10%", "EBITDA grew 8%" — and a high event triggers `WATCH`,
which skips a name. **Good news rejected candidates.** EX-2 defines materiality as *concern to someone
who owns the shares*. `pretrade` acts only on the current version, so EX-1 rows stay on file and
cannot act.

### What reaches the user

Under the basket on the page, `live/flags.py` prints what the exchange and the filings say about
those exact names, linked to the filing. **Flags, never vetoes** — there is no path from it back into
selection or sizing.

A name is "clear" only when the exchange passes **and** a complete, current-version, recent coverage
row says its filings were read. Anything else prints *"Filings NOT read — that is a gap, not a clean
bill."* This was wrong for two days and is the fifteenth entry in the table above.

### The decision loop

`live/pipeline.py` walks the screen's ranking, skips what does not clear, and puts the remainder in an
anchor (`NIFTYBEES`) so cash is never idle. `HUMAN_REQUIRED` is reserved for the **account or the
feed** — an unpriced holding, a wholly dead evidence feed, a broker mismatch. Never "I could not read
one filing".

A rejected name is **not** backfilled with the next stock: that needs a screen re-run at a different
basket size, and a screen asked for a different number of names is a different screen. The anchor is
the replacement.

The governor **filters, it does not stop** — and its 30% sector cap applies only once the book spans
≥4 sectors, because below that it is arithmetically unsatisfiable and rejects everything.

**It is exercised by the golden-day replay and by the daily shadow run. It does not touch the
local run's buy surface** (`scripts/local_run.py`), which calls the screen directly.

---

## What is proven, and what is not

**Proven:**
- The FIFO/cost/tax engine reconciles to **₹0.00** against a real Zerodha Tax P&L (one sale:
  single-lot, all-STCG, no loss).
- Trading less beat trading more, net of cost and tax, across walk-forward sub-periods.
- Equal-weighting explains most of the apparent edge over the cap-weighted index.
- Selling to manage risk **loses to the tax** — the §4.7 exits finished ₹74.8 lakh behind
  buy-and-hold over 13 years and paid ₹13.3 lakh in tax to do it.

**Not proven — state these plainly whenever the numbers come up:**
- **The headline is not out-of-sample.** `shrink` was selected by requiring it to beat 1/N *on the
  2025–26 holdout* (`scripts/exp_breadth.py:104`), which spends the holdout. `README.md` §5 now shows
  gate 1 as 🔴 with the reasoning inline.
- **The screen the real money runs has never been backtested out-of-sample at all.**
- **Its worst backtested fall is −47.5%**, against the index's −36.3%. He runs it with no stop-loss.
- **"Tax-aware execution" overstates what runs.** `force_refresh=True` short-circuits the §4.6
  net-benefit gate (`decision.py:183`), so tax is *charged* but the gate never decides.
- **`weighting="score"` silently collapses to equal weight** via `_cap_renorm`, so `exp_breadth`
  tested five variants, not six.
- **Sharpe assumes rf = 0.** Immaterial to the comparison, inflated as an absolute number.
- **The reports do not reproduce day to day.** Until input hashes are pinned, treat every rupee
  figure as good to about half a percent.
- **Most of the tax engine has never met a broker statement** — multi-lot, LTCG, loss set-off and
  §112A are unit-tested and unconfirmed. **The first such real sale must be reconciled afterwards.**
- **No corporate action has ever been reconciled live.** This is the likeliest thing to bite first.
- **Nobody has watched this system fall.** Every live day so far has been calm.

---

## The operating contract

Double-click **Q-Alpha** → it runs on this machine and opens one page → if it says Kite was not
reachable, run once with `--login` (the session expires ~6am IST, so most days it will ask) → read
**Today's basket**, sized to the ₹50,000 allowance and never to the whole balance → place every order
yourself in Kite, **CNC/delivery, no stop-loss, no target** → **drop the tradebook export into
`data/tradebooks/`** afterwards (de-duped on Zerodha trade ids, so overlapping ranges are safe).
Money for future instalments **stays in the broker account**; the page holds it back and says so.

**No stop-loss, and it is load-bearing:** the screen buys names that are *down*, so a stop sells
exactly what it just bought, realises a loss, triggers tax, and fires on ordinary volatility. The exit
is the §4.7 breakdown test, which distinguishes a name-specific fall from the market falling.

---

## Architecture

```
data/         yfinance→Parquet panel (atomic writes) · point-in-time universes · fundamentals
factors/      momentum · volatility · liquidity (+ value · quality · dividend) · regime · scoring
alloc/        Ledoit-Wolf+EWMA conditioning → sector allocator → optimizer
accounting/   FIFO lots · Zerodha costs · capital gains (§70 · §74 · §112A · cess) · corporate
              actions · slippage.  FROZEN (rule (a)); reused live so both paths share one engine
backtest/     walk-forward engine · portfolio · baselines · metrics · significance · runstore
              decision.py = the shared decide_rebalance the live runner also calls
live/         account (the reconciled account) · session (snapshot + resume) · seed (one common
              start) · commitments (what it already decided) · mandate (the limits, once)
              report (the HTML page) · ui (how a number looks, never what it is)
              advisor · deploy (the buy screen) · position_health · price_integrity · cooling_off
              satellite · governor · hedge · nav · twin · runner · policy · go_gate · verdicts
              ai_brief · track_record · measures · safety · scan · notify · auth · client
              holdings · tradebook(+store) · taxpnl · ticker
              evidence (NSE regulatory indicators) · announcements (filings + provenance)
              extraction (the model reports what a filing says) · pretrade (may we buy this?)
              pipeline (rank → skip → anchor → one outcome) · flags (what the user sees)
scripts/      local_run.py (the click — the only entry point) · twin.py · evidence.py (the spine)
              paper.py · advisor.py · exp_null.py · backtest_* · exp_*
config.py     every tunable parameter in one place
```

**Conventions.** Money is `Decimal` everywhere it touches accounting, never float. No look-ahead ever
— historical reads go through `PriceData.as_of(date)`; fundamentals carry a 90-day effective lag; a
test fails on look-ahead. Reuse before adding. Reference the spec by section (`§4.6`) in comments.

**Nothing runs unattended.** `live/daily.py` holds the step list the cron used to hold — prices →
mark the model book → **evidence spine** → twin → brief — and runs it when the user presses *Run the
evening*. Three properties make that a replacement rather than a regression:

- **A failed step is recorded and the run continues.** The cron was fail-soft too; the problem was
  that it was fail-*silent*. A failure here is written to `data/session/ledger.jsonl` and printed on
  the page.
- **Finished work is not redone.** Completion is keyed to `InputSnapshot.research_digest()` — the
  date, the names, the price panel, the extraction version. Not cash and not the budget, because a
  proposal lowering the remaining allowance must not invalidate every filing the run just read.
- **A skip is not a completion.** A step missing its credential is reported and left pending, so it
  runs the day the credential arrives.

`tests/test_evidence_durability.py` fails if any workflow with a `schedule:` reappears.

---

## Commands

```bash
uv sync --extra dev
uv run pytest                                          # must stay green
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run python scripts/local_run.py                     # THE entry point: pipeline → page
uv run python scripts/evidence.py daily                # the evidence spine (shadow)
uv run python scripts/run_phase0.py                    # the validated backtest
uv run python scripts/exp_null.py --draws 2000         # the matched null
uv run python scripts/local_run.py --app               # the app: buttons, live progress, tokens
uv run python scripts/local_run.py --no-pipeline       # decide only, on research already on disk
uv run python scripts/local_run.py --force             # re-run steps the ledger calls done
uv run python scripts/local_run.py --login             # refresh the Kite session first
./qalpha.sh                                            # the same thing, from the desktop launcher
```

**There is no dashboard and no server.** Streamlit, its 2,498-line app, its config, `requirements.txt`
and the whole `deploy/` hosting tree were removed on 2026-09-09. The system runs on this machine when
you click it, writes `data/session/qalpha.html`, and stops. `live/ui.py` survived the move without
one edit to a component, because it had never been allowed to know what was rendering it.

**Auditing a live surface offline** — no Kite login, no server. The account *shape* is the point:
**idle cash and holdings together**, because a zeroed portfolio hides an entire defect class. See
`tests/test_golden_day.py` for the full chain asserted to the paisa.

**Refreshing prices.** `live/daily.py`'s `prices` step refreshes every panel a run reads —
the screen's watchlist panel, the book's panel, and the benchmark — from `live/panels.py`, which
names each file once and pairs it with the universe it is built from. Call that, not
`scripts/paper.py refresh`, which still touches only the book's panel.

This warning previously said to call three things by hand, and that was the bug rather than the
workaround: **Refresh market data** re-pulled the book's panel while the gate checked the screen's,
so the staleness block could not be cleared by pressing the button that exists to clear it. Fixed
2026-09-10; `tests/test_panel_freshness_coupling.py` fails if a gated panel is not one the refresh
writes, or if any live module spells a panel path as a literal again.

**Secrets** live in `.env` at the repo root, and nowhere else now that there are no Actions.

| | |
|---|---|
| `KITE_API_KEY` · `KITE_API_SECRET` | holdings, cash, prices; the secret only at login |
| `QALPHA_LOCAL_MODEL` | reads filings **on this machine**. Set it only once a server answers — a name set with nothing listening does NOT fall back to the cloud, by design, so it turns reading off rather than on |
| `ANTHROPIC_API_KEY` | filings in the cloud, and the web-searched brief (which has no local substitute) |
| `GIST_TOKEN` | the tradebook store. Without it the twin cannot read the tradebook and **correctly refuses to run** |

A missing one is never an error: the run degrades to a named absence and says which figures it
therefore cannot confirm.

---

## Open work

**The build is not closed and saying so was itself a defect.** But there is no queue of features
here, and adding one is not the default. The list below is short on purpose.

1. **Nothing.** The system runs, the flags reach the buy screen, and the record accrues. The correct
   next action is usually to let it run.
2. **If the user asks for the AI to do more:** the live twin veto is still the web-search one whose
   source rule checks only a hostname. `extraction.py` is the safer design and does not feed it.
   Replacing it is a treatment change and needs registering.
3. **If the user asks about the experiments:** the superiority question cannot be answered (see the
   null). The honest options are to abandon it in writing, or re-register as non-inferiority. Leaving
   it ambiguous invites someone to install a null later and retroactively authorize a window that
   started before it was settled.
4. **Deferred, none of it breaking:** dataset hashes so reports reproduce · raw prices for execution
   and FIFO basis · date-dependent tax rates · `_cap_renorm` · durable off-repo document storage.
5. **Never without a separate registered experiment:** mid/small-cap, IPO, F&O. **No engine inherits
   another's authority.**

### Do not disturb

`EVALUATION_START`, `CORE_EVALUATION_START`, the screen's parameters, and `BASELINE_EW`'s
construction. Changing any of them restarts a twelve-month clock. The AI and evidence layers version
**independently** and may change freely — that separation is the reason improvements no longer reset
the experiment, which was the mechanism that kept this project further from evidence the closer it
got.

---

## Reading order for a new session

**[OPERATING.md](OPERATING.md)** (what the user actually does) → this file →
**[reports/NULL_MATCHED.md](reports/NULL_MATCHED.md)** (why the gate cannot open) →
**[PLAN_SYSTEM.md](PLAN_SYSTEM.md)** (target architecture) → `README.md` → `Q_alpha.md` (the spec).

`PLAN_REDESIGN.md` and `PLAN_TRUST_REPAIR.md` look like stale planning and are not: six source files
cite them **by section** as the reason a design is what it is. Do not delete them.

`../Q_Alpha_Research` is the **archive** — the hedge forward run and the published negatives (QUBO
×2, HMM overlay, LPPLS). Dormant since 2026-08-29. The product does not import from it.

> Q-Alpha never asks to be trusted. It shows enough evidence that the decision can be checked — and
> it refuses to act when it cannot.
