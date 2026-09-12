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

**Nothing authorizes a GO, and there is no longer a gate to open.** It was deleted on 2026-09-12:
six criteria graded a verdict that needed two hundred years of data to arrive, and six criteria
reading ⚪ CANNOT ASSESS for ever is a surface that teaches its reader to stop looking. Nothing
here is validated. Never describe this system as validated for real money.

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
| "12 high-materiality negative items" | **4** — the reader counted lines in an append-only log, not events at their current revision |
| a step that failed, having left yesterday's report standing | **zero bytes** — `write_text` truncates before it encodes, so the failure destroyed what it was replacing |
| "The build is closed" | four defects were found that same day |
| an evidence step recorded `done` after 216s | **zero coverage rows, zero events** — "nothing to cover" returning 0 |
| a refused model call, counted as a clean read | **unread**. `("", {})` parsed as a filing with no bad news in it |
| coverage saying 128 documents read | **no events, no receipts** — an `elif` discarded them when another batch failed |
| a 30-day veto window, dropping 10 names of 10 | **7 events, not 233** — it read *when we filed the paper*, not when the event happened |
| `mypy src scripts`, green | **vacuous over `qalpha.*`** — `ignore_missing_imports` resolved our own package to `Any` |

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
- **All four gates green before every commit**: `ruff`, `ruff format`, `mypy --strict src scripts`,
  `pytest`. **`src` alone is not the gate.** It was until 2026-09-11, and `scripts/` — where every
  entry point lives — was the one part of this repo nothing verified. Two live defects shipped
  through that hole: `atomic.write_text(..., encoding="utf-8")`, which failed the twin step on
  every run, and `_log_applied` handed bare tuples where it reads `.amount`, an AttributeError
  waiting in the deposit path. `mypy_path = "src"` in `pyproject.toml` is what makes checking
  `scripts/` real — without it `ignore_missing_imports` resolves the whole `qalpha` package to
  `Any` from outside `src/` and the check passes while verifying nothing.
- **Always branch + PR.** The harness blocks self-merges; the user clicks merge.

---

## What is true today (2026-09-08)

**66 live modules · 1,423 tests green + 1 xfail** (counted, not estimated — see the
table above for what happens when a progress line is counted by eye). **There is no cron.** `paper.yml` was deleted on
2026-09-10 and its five steps moved to `live/daily.py`, which runs them on the user's desktop when
he presses the button. The record from 2026-09-01 to that date was produced by the cron and stands;
everything after it is produced locally.

### One book, and it starts deciding on 2026-09-14

| Book | What it is |
|---|---|
| `SYSTEM` | the whole thing deciding for itself — screen, evidence, governor, §4.7 exits, costs, tax |
| `BASELINE_EW` | the Nifty-50 equal-weight index fund, charged 0.41%/yr. **The bar** |
| `BASELINE` | NIFTYBEES, bought and held. The do-nothing floor, never the bar |
| `REAL` | the user's tradebook replayed — what he actually did |

**`SYSTEM` is seeded as a copy of `REAL`.** It holds exactly what he holds, follows the tradebook
until `EVALUATION_START = 2026-09-14`, and only then begins to choose. Two books from one state
means every later difference is **a decision**, not a different starting point. Verified on
registration day: `SYSTEM − REAL = ₹0`. Registered in `reports/PREREGISTRATION_SYSTEM.md`, written
two days before the window opened.

**It was nine books and a GO gate until 2026-09-12.** Three ablations asked which component earns
its keep — harder than the question we already cannot answer. `CORE_V1` was a second clock for a
second unfinishable experiment. And the gate graded six criteria toward a verdict needing two
hundred years: `AUTHORIZING_PAIR` was `None` and would have stayed `None`. Six criteria reading
⚪ CANNOT ASSESS for ever is not honesty, it is a surface that teaches its reader to stop looking.
~1,700 net lines deleted.

> **A twelve-month result, in either direction, is consistent with chance.** The edge over this
> benchmark is **0.42%/yr** against **5.3%/yr** of drift. That is not a caveat to add afterwards —
> it is the finding, and it is why the corpus matters more than this book. Full detail in
> `reports/NULL_MATCHED.md`.

### The evidence spine — reads filings and headlines, decides nothing

Runs daily **before** the twin. Fetches and archives NSE's regulatory-indicator file (`REG1_IND`,
which carries the P/E>50 caution) and each candidate's corporate announcements, downloads the
filings, hashes them, extracts their text, and puts them through the model.

**The model extracts, it does not judge.** It reports what a document says; deterministic policy
decides what that means. Every event carries a verbatim quote **checked against the archived bytes** —
a quote that is not in the document is discarded and counted. It cannot introduce a name it was not
given a document for, and cannot attribute a real quote to the wrong company.

Extractor version **EX-3**. EX-1 asked for "material events" and never said material *to whom*, so
77 of 193 came back `high` — "revenue up 10%", "EBITDA grew 8%" — and a high event triggers `WATCH`,
which skips a name. **Good news rejected candidates.** EX-2 defines materiality as *concern to someone
who owns the shares*. `pretrade` acts only on the current version, so EX-1 rows stay on file and
cannot act.

The reader is **`claude-sonnet-5`**, chosen by measurement under a rule fixed before the numbers
existed (`reports/READER_COMPARISON_EX3.md`). **Two readers agree on 22% of findings** — the reader
substantially determines the event stream, which is the whole reason the label names it.

**~25–29% of even the winning reader's quotes fail verification, and they are not fabrications.**
Documents were re-read passage by passage: every failure was a true statement that is not a
contiguous verbatim span — clauses joined across a sentence, a summary built from real fragments,
and one case where PDF extraction had split a word so the *archive* was wrong, not the model. The
guard works; its cost is **recall**, biased against documents with poor text extraction. **The
corpus under-counts events, systematically. Absence in it is not evidence of no event.**

**Both repairs were tried and both were rejected on measurement** (`reports/EX4_PROMPT_NEGATIVE.md`).
A graded "close enough" threshold died before costing anything: coverage of the failing passages runs
continuously 0.59→0.96 with no gap to cut at, so any threshold is a tuned parameter buying
paraphrase-as-quotation. Tightening the prompt was built as EX-4, measured paired on 220 identical
filings, and **lost on both axes — 155 events kept against 200, and 34.9% discarded against 25.1%.**
Reverted.

> **A sample small enough to be cheap was large enough to be confidently wrong.** EX-4 looked like a
> 40% improvement on 120 documents and reversed sign on 220. Round-robin sampling reaches only each
> name's first few filings at small sizes, and those are short and formulaic. **Reader and prompt
> comparisons here use ≥220 documents and quote the sample size beside every rate.**

**EX-3 changed no instruction. It made the reader part of the label** (2026-09-11). A version now
means "these instructions, read by `corpus_reader()`" — and a row from any other model satisfies
nothing: not `_seen_before`, not the extraction receipt, not `filings_read` on the buy screen, not a
`pretrade` flag. **A row with no reader recorded does not match**, because every such row predates
the field and was read by whatever was configured that evening. That is the mixture the label
exists to prevent: two models disagree on one filing the way two analysts do, and this repo already
records the smaller version of it — the same snippet labelled differently in different batches by
one model at temperature zero. It cost ~1,135 documents of completed reading, which is the price of
the corpus being one thing. Registered in `reports/PREREGISTRATION_EX3_CORPUS.md`.

**`live/news.py` does the same for headlines (`NEWS-1`).** Four market RSS feeds plus one Google News
search per in-scope name, archived with provenance **before** anything parses them; the alias table
in `data/universes/nifty100_aliases.csv` decides which company an item is about, and the model cannot
widen that. Only a verified, current-version item that is **both `high` and `negative`** raises a
flag, and a flag is `WATCH` — news can never `BLOCK`, asserted in `pretrade.assess_candidate`.
Rules and first-run findings: `reports/PREREGISTRATION_NEWS_V1.md`.

Three things it is careful about, each learned on the first archived run:

- **An item is a report, not an event.** Nine outlets carried one Meghalaya court order about
  SHREECEM. Every surface that prints the count says what it counts; clustering would mean inventing
  a similarity score, which the registration forbids.
- **The same snippet is labelled differently in different batches.** Temperature is zero, but the
  batch is part of the prompt. Labels are stable within a run and not across one. Recorded as a
  limit of the method, not re-prompted until the answers agree.
- **A batch is limited by what the REPLY can hold**, not by the context — 60 headlines in one call
  came back cut off at `max_tokens`, which counts as a failed read. Capped at 20 items.

### What reaches the user

Under the basket on the page, `live/flags.py` prints what the exchange and the filings say about
those exact names, linked to the filing. **Flags, never vetoes** — there is no path from it back into
selection or sizing.

Below that, `live/twinpanel.py` prints the record: the eight model books, both tracks against the
equal-weight fund, the six gate criteria, the account against the same money in the index, and a
capability register saying what each part has earned. It **computes nothing** — every figure is read
from the file that produced it (`data/twin/history.jsonl`, `data/twin/gate.json`,
`reports/NULL_MATCHED.json`, `track_record`), because a number invented on a display surface is how
every labelling defect here has started.

The two gaps against the fund are **in different units from different start dates and can disagree
in sign** — today `core_v1` reads +₹5,389 and G −0.0023 on the same comparison, because the rupee
figure runs from the first cash flow and G from the registered window. Both are shown, both are
labelled, and the rupee one is never the criterion.

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

Double-click **Q-Alpha** → a console window opens and stays open (**it is the app**; closing it
stops the server) → it runs the evening itself and opens `http://127.0.0.1:8787/`, which narrates the
run and reloads when it finishes → if it says Kite was not reachable, press **Log in to Zerodha** on
the page (the session expires ~6am IST, so most days it will ask) → read **Today's basket**, sized to
the ₹50,000 allowance and never to the whole balance → place every order yourself in Kite,
**CNC/delivery, no stop-loss, no target** → **drop the tradebook export into `data/tradebooks/`**
afterwards (de-duped on Zerodha trade ids, so overlapping ranges are safe). Money for future
instalments **stays in the broker account**; the page holds it back and says so.

**The export must cover the first trade (2026-06-15).** It is the only source of cash flows for every
book, and one that starts later replays `REAL` short — every twin then reads as beating the user by
the lots it left out. `twin.partial_export_reason` refuses instead; the empty-tradebook check cannot
see this, because one row is not zero rows.

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
              console (UTF-8 before anything prints) · atomic (a failed write keeps the old file)
              advisor · deploy (the buy screen) · position_health · price_integrity · cooling_off
              satellite · governor · hedge · nav · twin · runner · policy · go_gate
              verdicts (AI-V2: keep/drop as a RULE over verified events — nothing is asked)
              ai_brief · track_record · measures · safety · scan · notify · auth · client
              twinpanel (the record on the page: books · tracks · gate · what is trusted)
              holdings · tradebook(+store) · taxpnl · ticker
              evidence (NSE regulatory indicators) · announcements (filings + provenance)
              news (headlines: fetch · archive · map · read — flags only, never a veto)
              extraction (the model reports what a filing says) · pretrade (may we buy this?)
              pipeline (rank → skip → anchor → one outcome) · flags (what the user sees)
scripts/      local_run.py (the click — the only entry point) · twin.py · evidence.py (the spine)
              paper.py · advisor.py · ocr_scans.py · backtest_* · exp_*
config.py     every tunable parameter in one place
```

**Conventions.** Money is `Decimal` everywhere it touches accounting, never float. No look-ahead ever
— historical reads go through `PriceData.as_of(date)`; fundamentals carry a 90-day effective lag; a
test fails on look-ahead. Reuse before adding. Reference the spec by section (`§4.6`) in comments.

**Two rules the first real run taught, on 2026-09-11:**

- **`live/console.use_utf8()` first, in every entry point.** Windows falls back to cp1252 when
  stdout is a pipe, and `uv run` pipes its child. The `mark` step died on a `₹`. A rule that every
  print must remember to be ASCII is a rule the next print will break; the stream is fixed instead.
- **`live/atomic.write_text` for anything a later run or a person reads.** `Path.write_text` opens
  (truncating) and *then* encodes, so that same failure left `reports/paper_dashboard.md` **empty**.
  `save_parquet` learned this on 2026-09-07; the markdown and JSON writers had not, and one of them
  holds the paper book.

**Nothing runs unattended.** `live/daily.py` holds the step list the cron used to hold — prices →
mark the model book → **filings** → **headlines** → twin → brief — and runs it when the user presses
*Run the evening*. A step may declare `needs_any`: the brief runs with a local model **or** a cloud
key, because requiring the key alone would skip work this machine can do. Three properties make that a replacement rather than a regression:

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
uv run mypy src scripts                                # scripts too — see Iron rules
uv run python scripts/local_run.py                     # THE entry point: pipeline → page
uv run python scripts/evidence.py daily                # the evidence spine (shadow)
uv run python scripts/evidence.py backfill --workers 8 # the corpus, once, in the cloud
uv run python scripts/evidence.py compare-readers      # which model should read it (measures)
uv run python scripts/news.py daily                    # the headlines (archive → map → read)
uv run python scripts/news.py daily --dry-run          # archive only; read nothing
uv run python scripts/run_phase0.py                    # the validated backtest
uv run python scripts/ocr_scans.py --dry-run           # scanned filings with no text layer
uv run python scripts/local_run.py --app               # the app: buttons, live progress, tokens
uv run python scripts/local_run.py --app --autorun     # what the desktop click runs
uv run python scripts/local_run.py --no-pipeline       # decide only, on research already on disk
uv run python scripts/local_run.py --force             # re-run steps the ledger calls done
uv run python scripts/local_run.py --login             # refresh the Kite session first
Q-Alpha.bat                                            # the desktop shortcut points at this file
```

**It runs natively on Windows, from `D:\Q-Alpha`.** Moved off WSL on 2026-09-10. Python,
`uv`, git and Ollama are all on the Windows side; the desktop shortcut points straight at
`Q-Alpha.bat` in the repo, and `%~dp0` is the repo — so there is no path to bake, no copy step and
no installer. The bridge that existed before (a launcher inside `\\wsl$\<distro>\...`, a path that
only exists while WSL is running, copied out by a script that had to be re-run whenever the distro
or repo moved) was all cost of living in the wrong filesystem, and went with it.

The move also fixed the local model for free: Ollama runs on Windows and binds the Windows side's
loopback, which WSL — a separate network namespace — could never reach. `QALPHA_LOCAL_MODEL` now
works with no configuration at all.

**There is no hosting, and the only server is the one the click starts.** Streamlit, its 2,498-line
app, its config, `requirements.txt` and the whole `deploy/` hosting tree were removed on 2026-09-09.
What runs now is `live/server.py`: Python's own `http.server` on 127.0.0.1 only, started by the
launcher with `--autorun` so the click *runs the evening* rather than serving the last run's page,
and stopped by closing its window. It writes `data/session/qalpha.html` and inlines it. `live/ui.py`
survived the move without one edit to a component, because it had never been allowed to know what was
rendering it.

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
| `QALPHA_LOCAL_MODEL` | reads filings **on this machine**. Must be a tag the server actually lists; a name with nothing listening — or a name the server does not have — does NOT fall back to the cloud, by design, so it turns reading off rather than on. Recipe: `ollama create qwen3-8b-32k -f docs/ollama/Modelfile.qwen3-8b-32k` |
| `QALPHA_LOCAL_MODEL_CONTEXT` | what that model was **built** with (32768 for the above). It states the window, it cannot set it: the OpenAI-compatible route has nowhere to send `num_ctx`, which is why the Modelfile is committed |
| `ANTHROPIC_API_KEY` | filings in the cloud, and the web-searched brief (`BRIEF-1`). **No nightly step requires it:** with a local model the brief is written here from the headlines the evening archived (`BRIEF-2-local`), citing an item id per claim. The EX-3 corpus backfill *does* require it, and `uv sync --extra ai` — the SDK is an optional extra |
| `QALPHA_CORPUS_READER` | **optional.** Names the model EX-3 rows must come from, overriding `claude-haiku-4-5`. It names the corpus, so a run under it cannot be mistaken for a run under the default |
| `GIST_TOKEN` | **optional.** A private-gist tradebook store, for whoever keeps one. Unset, the twin reads `data/tradebooks/` — the same folder the page reads and the one OPERATING.md names |

A missing one is never an error: the run degrades to a named absence and says which figures it
therefore cannot confirm.

---

## Open work

**The system ran end to end on the user's desk for the first time on 2026-09-11**, and it found two
defects in its own plumbing (both fixed and in the table above). The product operates. What is not
established is whether its *choices* are worth anything, and that is now the whole of the work.

### What the measurement actually says

`reports/SCREEN_OOS_FIRST_READ.md` tested the live ranking over 163 months on a point-in-time
universe. Every interval includes zero and the screen picks winners in half of all months:

| Basket | Annualised spread vs 1/N | t | 95% CI |
|---:|---:|---:|---|
| 8 | +2.65% | 0.60 | includes zero |
| 15 | +1.45% | 0.54 | includes zero |

**Survivorship bias on the universe the money actually runs on is worth ~3.8 points a year** — more
than the entire signal. So the honest position is not "the rule fails"; it is **"the rule has never
been measured on a clean universe, and the measurement that would settle it is blocked on one data
task."**

### The next four things, in this order

1. **Fill `NEXT_50_CHANGES` in `scripts/build_nifty100_pit.py`.** It is an empty list and the script
   **refuses to write anything** while it is — correctly. Until point-in-time Nifty-100 membership
   exists, no result computed on `nifty100_watchlist.csv` means anything, because today's members
   applied to the past is worth more than the effect being measured. Source: NSE's Next-50
   reconstitution circulars. This is bounded data entry, not research.
2. **Replay the policy the money runs, not the ranking.** `exp_screen_oos.py` tests monthly
   rankings. The live policy is buy-and-hold with a ₹50,000 monthly allowance, the §4.7 exits, the
   sector cap, costs and tax. Those are different strategies and only one of them is being run.
3. **Build the historical filing corpus.** **It is the only route to evidence that does not need
   centuries.** A portfolio over twelve months is *one* observation of a small signal inside large
   noise — that is where the 200-year figure comes from. The same information at the *event* level
   is thousands of observations, and an event study can reach significance in months of work.

   The machinery is built, registered and the reader is chosen (2026-09-11). The corpus itself is
   **not built yet**. `compare-readers` ran on 150 filings across 22 names: Haiku discarded 59% of
   its own quotes as not in the document against Sonnet's 29%, and found 59 events to Sonnet's 109 —
   half the findings at twice the miss rate — so rule 1 of the registration picked
   **`claude-sonnet-5`**. Projected from that run's measured throughput: **~2,100 documents in about
   30 minutes at eight workers, ~$38 at list.** Against ~84 evening runs on the local path.
   `uv sync --extra dev --extra ai` — `--extra ai` alone drops ruff and mypy.

   **The local reader is not obsolete and the choice was not free.** It reads the nightly 10-day
   window for nothing and sends nothing anywhere; the corpus goes to the cloud because eighty-four
   evenings is not a schedule. Both cannot feed one corpus — see EX-3 above.
4. **The predictive question has a first answer, and it is a null** (`ES-1`, 2026-09-12,
   `reports/PREREGISTRATION_EVENT_STUDY.md`). After a verified high-materiality veto-shaped filing
   event, mean abnormal return over 20 trading days is **−0.62%, t = −0.77** clustered by name; the
   per-name test reads **t = −0.22**. Every horizon includes zero. **`AI-V2`'s drop rule is
   unsupported** — it is still running, and that is now an explicit choice rather than a default
   nobody examined.

   Three details the headline hides. The **5-day sign is positive** (+0.68%): if anything the names
   drift up just after the events the rule drops them for. The **60-day figure is clustering** —
   −3.61% pooled, **−0.09% per name**, which is the artefact the registration named in advance.
   And **conditioning adds nothing**: every event day unconditionally gives −0.54% against the
   subset's −0.62%, a difference of 8 basis points on a standard error many times that.

   **The sample is the finding.** 4,252 events collapse to 463 name-days and the primary test rests
   on **61**. Fifteen large caps over one year cannot produce more. A real answer needs the
   point-in-time universe — item 1, still an empty list — because this corpus holds only names that
   are here today, and survivorship biases it *toward* making them look good after bad news.

5. **Then, and only then, ask the predictive question properly.** *Given what was knowable on a date, does a
   model over events plus price context beat the price-only screen?* Train on early years, test on
   late years nobody looked at, measure after costs. **Nothing in this repo learns that mapping
   today** — the AI reads and reports; deterministic policy decides. That gap is real and it is not
   hidden: `AI-V2` is a rule over verified events, not a predictor, and it is registered as such.

### Standing constraints on all four

- **Pre-register first.** Every one of these is an experiment, and this project has twice adopted a
  result as the expected value after seeing it.
- **Never tune until an old backtest looks good.** That fits historical noise, and at this effect
  size noise is most of what there is.
- The realistic prize is not a large edge. It is (i) knowing whether the rule works at all,
  (ii) avoiding the blow-ups, and (iii) the levers already proven here — cost, tax, and staying
  invested. Those beat most retail behaviour. They do not beat an index fund by construction.

### Still open, unchanged

- **The gate question.** The superiority test cannot be answered (`reports/NULL_MATCHED.md`). The
  honest options remain: abandon it in writing, or re-register as non-inferiority. Leaving it
  ambiguous invites someone to install a null later and retroactively authorize a window that
  started before it was settled. **The user has not chosen.**
- **Letting a headline drop a name** is `AI-V2.1` and needs its own registration.
- **Deferred, none of it breaking:** dataset hashes so reports reproduce · raw prices for execution
  and FIFO basis · date-dependent tax rates · `_cap_renorm` · durable off-repo document storage.
- **Never without a separate registered experiment:** mid/small-cap, IPO, F&O. **No engine inherits
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
