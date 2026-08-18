# Trust repair — the advisor, the page, and the experiment (planned 2026-08-17)

**Status: ALL EIGHT PRs BUILT (branches `trust-repair-pr1`…`pr8`, **429 tests, 0 skipped**, four gates
green on each). Tiers 1–4 closed. Forward run 1 is VOID and published; the study is re-seeded at
ground zero on 2026-08-18 and now tests the AI's per-name verdict as its single treatment.**

Companion to [PLAN_INTEGRATION_AUDIT.md](PLAN_INTEGRATION_AUDIT.md) (same day). That audit diagnosed
the **presentation** incoherence and the **experiment** confound, and its findings hold. This plan
carries them forward and adds **two defects in the buy recommendation itself** that it did not reach.

**The GO book (`data/paper/book.json`) is not touched by any item here.** Its 45-mark criterion-6
clock keeps running; the validated 18.2% headline and engine stay frozen. Rule (a) is intact
throughout.

## Context

The dashboard told the user to put ₹100,000 into VEDL, TRENT, IRFC, HDFCLIFE and ITC — names in
visible decline — while an AI brief on the same page analysed six entirely different stocks, and two
panels showed ₹400,000 and ₹200,724 against two apparently contradictory baselines. His verdict:
*"i am unable to trust the advisor for now."*

Answers to what he asked:
- **Two books.** The GO book is ₹2L funded once on 2026-06-12, never topped up. The System book is
  ₹2L core + ₹2L of dashboard Add-money (₹150k on 12 Jul, ₹50k on 3 Aug). Structurally disjoint.
- **Two baselines.** There is only **one**. Both `+0.98%` and `+3.92%` are the same NIFTYBEES
  adj-close series over windows 28 days apart, during which Nifty rose 2.7%. No contradiction — no
  labels.
- **"So many plots."** Only **two charts** exist. The clutter is **eight return numbers on four
  bases over two windows**, none labelled.

## What is actually wrong

### Tier 1 — the buy recommendation (why trust broke)

**T1.1 Corporate actions read as discounts.** `cheapness_scores` ([deploy.py:100](src/qalpha/live/deploy.py))
is `max(0, 1 − price / 1y_high)` over `adj_close` — yfinance *Adj Close*
([ingest.py:46,72](src/qalpha/data/ingest.py)), corrected for splits and dividends, **never for
demergers or spinoffs**. Exactly two names in the 95-name watchlist have an unexplained one-day
collapse (VEDL −64.9% on 2026-04-30; TRENT −33.0% on 2026-01-01) and they rank **#1 and #2** on
cheapness, taking **44.4%** of the ₹100k deploy. The phantom discount persists for a full year.
[corporate_actions_feed.py](src/qalpha/live/corporate_actions_feed.py) detects only splits and
dividends — precisely what `adj_close` already handles.

**T1.2 The advisor contradicts its own breakdown detector.** `position_health()`
([position_health.py:114](src/qalpha/live/position_health.py)) is the §4.7 idiosyncratic-breakdown
test. Run over the five recommended names on the same panel and date: VEDL 🔴, IRFC 🔴, HDFCLIFE 🔴,
ITC 🔴, TRENT 🟢. **Four of five are names the system would flag for exit if they were held.** It runs
over `portfolio.positions()` only ([dashboard_app.py:490,547](scripts/dashboard_app.py)) and is never
pointed at candidates. `deploy.py` imports no factor module, no volume, no fundamentals
([deploy.py:31-34](src/qalpha/live/deploy.py)).

**T1.3 The safety gate checks the wrong panel.** `assess_advice_inputs`
([dashboard_app.py:311-313](scripts/dashboard_app.py)) validates the **core PIT panel** for names you
*own*. The buy list is priced off `data/historical/prices_watchlist.parquet`
([dashboard_app.py:1150-1174](scripts/dashboard_app.py)), whose freshness is not in `SafetyReport`; it
tolerates ~4 trading days of staleness and its refresh runs `check=False`
([dashboard_app.py:1139-1147](scripts/dashboard_app.py)), so a failed download silently serves stale
prices.

*Confirmed on re-run 2026-08-17:* the committed watchlist panel's last date is **2026-07-10 — 38
calendar days old**. The Streamlit host re-downloads on a 6h TTL, so this is not proof the live
surface is 5 weeks stale; it is proof that a panel this old produces a confident, unbannered buy list
whenever that download fails. PR-2 must check the **host's** panel date, not just the committed one.

**T1.4 Guards that do not bind.** `max_sector_weight=0.30` is inert (largest sector is 10.4% of raw
weight, and it is applied *before* `head(max_names)` at [deploy.py:132-158](src/qalpha/live/deploy.py)
with no re-check). `max_name_fraction=0.20` is a share-price ceiling, not a quality filter.
[test_deploy.py:66-71](tests/test_deploy.py) *asserts* that a deeper fall earns a larger position.

**T1.5 The rule was never validated.** No backtest references `advise_deploy_into_weakness` or
`cheapness_scores`. `run_phase0.py`, `walkforward.py`, `holdout_2025.py`, `exp_breadth.py` all
exercise the factor funnel ([strategy.py:65-100](src/qalpha/backtest/strategy.py)), a disjoint
selection path. The 18.2% headline applies to no name on the buy list; the GO book holds APOLLOHOSP,
ASIANPAINT, BEL, NTPC, SUNPHARMA — **zero overlap**.

### Tier 2 — measurement coherence

**T2.1 One baseline, presented as two.** Same NIFTYBEES adj-close series
([paper.py:63-74](scripts/paper.py), reused at [autopilot.py:127-139](scripts/autopilot.py)) over
windows 28 days apart. `baseline_book.json` has **no `start_date` field** — the window is recoverable
only from `system_track.csv` row 1.

**T2.2 Eight return numbers, four bases, two windows, no labels.** The GO book alone shows three
(+0.36% vs `starting_capital`; +1.3% and +1.26% vs the first equity mark ₹199,388.08) — the ₹611.92
of day-one trading cost sits between the denominators. The System book shows +2.03% (money-weighted
on contributions) eleven lines above +2.73% (flow-stripped, deployed capital); the 0.70pp gap is cash
drag, and it is larger than the AI effect being measured.

**T2.3 One book, two numbers, same screen.** `_paper_overview`
([dashboard_app.py:867](scripts/dashboard_app.py)) re-marks equity live against the host panel; the
chart directly beneath (`:1355`), the GO scorecard (`:470`) and the freshness panel (`:288`) all read
the cron-committed `book.equity_curve`. The "Equity" tile is inclusive of cash and sits beside a
separate "Cash" tile.

**T2.4 Only two charts exist.** `system_track.csv` → return %; `book.json` → rupees. The perceived
clutter is the unlabelled numbers, not chart count.

**T2.5 The AI narrative has no consumer.** [ai_brief.py:79-86](src/qalpha/live/ai_brief.py) asks for
per-name analysis; the machine contract (`:92-96`) is one `SIGNAL:` line with **no ticker field**. The
only parser ([autopilot.py:35-38](src/qalpha/live/autopilot.py)) yields five scalars → `signal_tilt` →
deploy *size*, in the fake book only. On the real-money surface the tilt is rendered and discarded
([dashboard_app.py:1258-1303](scripts/dashboard_app.py)). ~57.6k input tokens/day, rendered directly
under an unrelated buy list.

### Tier 3 — integrity and hygiene

**T3.1** `manual_injections.json` totals **₹440,500** against ₹200,000 actually credited — drift
**₹240,500** from duplicate entries ([autopilot.py:433-441](src/qalpha/live/autopilot.py)).
`state.json` is authoritative; [autopilot.py:253-257](scripts/autopilot.py) only prints a warning.

**T3.2** `pending_injections.json` has two writers on two machines with no lock — the Streamlit host
([dashboard_app.py:67-117](scripts/dashboard_app.py)) and the Actions runner (`clear_pending`,
[autopilot.py:551](scripts/autopilot.py)). A deposit queued between `load_pending()` (`:544`) and
`clear_pending()` (`:551`) is **destroyed unread** — the same failure family as the ₹50k lost in July.

**T3.3 Nothing tests cross-surface agreement.** 316 tests, all green, and none compares two panels
reporting the same book. [test_dashboard_app.py](tests/test_dashboard_app.py) is `skipif`'d on a
gitignored price panel, so **it never runs in CI**. `paper.yml` runs no tests and commits `[skip ci]`.

**T3.4 Dead weight.** `data/autopilot/{track.csv, adaptive_track.csv, books.json}` have no reader or
writer. `reports/{paper_dashboard.md, paper_equity.csv}` are generated and committed daily and read by
nothing in this repo. `state.json` still carries `monthly_autodeposit: true` after the feature was
removed 2026-07-28.

### Tier 4 — the experiment

**T4.1 System and Shadow are not twins.** 32 vs 28 names, 26 shared. The pre-registration says the
tilt changes *size only*; `max_name_fraction` and whole-share rounding make composition
amount-dependent, so six weeks compounded into two different funds. Signal ₹1,541 < one day of
rounding noise ₹1,964.

**T4.2 Both books already hold the artifact names** (System: VEDL 69, TRENT 6; Shadow: VEDL 57,
TRENT 5) — pillars 2 and 3 are accruing on a contaminated basket. **This is why the data fix must land
before any re-seed.**

**T4.3 Criterion 3's red line is inert** until 63 marks
([go_scorecard.py:251,186-192](src/qalpha/live/go_scorecard.py)) — at 45 marks it cannot go red
regardless of the gap.

## The plan — eight PRs

Order is load-bearing: **T1.1/T1.2 must land before the re-seed**, or the new run inherits the same
phantom discounts.

### PR-1 · Take the buy list off the real-money surface — ✅ BUILT
User's decision: *"until fix, it should be a part of the plan and removed from the dashboard, only
after the fix it gets back."*

Implemented as **one flag, not a deletion** — `dashboard.BUY_ADVICE_ON_REAL_MONEY = False`. Every
renderer stays wired behind it, so PR-3 restores the surfaces by flipping one constant.
- `dashboard.py` — the flag + `buy_advice_withheld_markdown()`, a notice that names both defects
  (with the two gap dates and the four 🔴 names) and states plainly that the rule is an unvalidated
  technical screen sharing nothing with the 18.2% funnel.
- `dashboard_app.py:331` — the `_auto_pm_brief` call is gated on the flag; the function is untouched.
- `_advisor_tabs` — the Add-money body moved verbatim into `_add_money_advisor()`, called only when
  the flag is on; otherwise the notice renders. **Sell** and **Raise cash** untouched.
- `next_actions()` gained `buy_advice_available` — the "Deploy idle cash → use **Add money**"
  checklist item was a pointer at advice the app now refuses to give. It reads *"Idle cash — buy plan
  withheld"* 🛑 instead, and says holding cash is the safe action.
- Tests: the flag's state and the notice's content are asserted in `test_dashboard_status.py`, which
  **runs in CI** (the AppTest module does not — see PR-5). Two AppTest cases render `_advisor_tabs`
  directly via `AppTest.from_string`, because the real advisor sits behind the Kite login gate that
  `AppTest` cannot pass: they assert the notice appears, no buy button and no AI read render, and the
  sell advisor still computes.
- Restored in PR-3. Nothing is deleted.

### PR-2 · Price-continuity guard (fixes T1.1, T1.3) — ✅ BUILT
New `src/qalpha/live/price_integrity.py`:
- `unexplained_gaps(prices, tickers, as_of, *, threshold=0.25, lookback=365, actions=None)` →
  per-ticker one-day returns beyond threshold **not** matched by a split/dividend from
  `corporate_actions_feed.corporate_actions_from_series` (reused, not reimplemented). The feed is
  **injected, never fetched** — the guard stays pure and adds no network call to a render. Both
  directions count (an unexplained *spike* corrupts the 1-year high too); only the **latest** gap per
  name is reported, since re-basing to it subsumes every earlier one.
- **Re-base, not veto.** A flagged name's 1-year high is recomputed from its gap day (the first price
  on the new basis), so it keeps a *correct* cheapness reading. Only when fewer than 20 post-gap
  marks exist does it fall back to 0 (untilted). `cheapness_scores` gained `rebase_from` / `no_tilt`,
  both defaulting to off — every existing caller's behaviour is bit-for-bit unchanged.
- Flags ride on `WeaknessDeployAdvice.price_gaps` and render via `price_gaps_note()`, so the advice
  explains itself instead of quietly changing its mind.
- `safety.watchlist_freshness_guard` + `assess_advice_inputs(watchlist=…, watchlist_download_ok=…)` →
  new `SafetyReport.buy_advice_safe`, a **narrowing** of `safe_to_advise` (never an escape hatch).
  Non-blocking by design: a stale *buy* panel must not veto Sell/Raise cash, which are priced off the
  core panel. `_download_watchlist_panel` now returns its exit status and `_watchlist` records it, so
  a failed refresh withholds buy advice instead of silently serving the previous panel.

**Measured effect on the live watchlist (2026-07-10 panel, ₹100,000, 15 names):**

| | cheapness before | cheapness after |
|---|---|---|
| VEDL.NS | 65.4% (rank #1) | **23.1%** |
| TRENT.NS | 47.4% (rank #2) | **13.2%** |

The top of the ranking becomes TCS · INFY · WIPRO · IRFC · HCLTECH · ITC — genuine decliners.
**VEDL + TRENT fall from 44.4% of the deploy to 5.8%**, and TRENT leaves the top-15 entirely. VEDL
stays, at a weight that reflects its *real* post-demerger pullback — the guard corrected a basis, it
did not blacklist a name.

- Tests (22 new): the ordering property (an artifact must not outrank a genuine decline — a guard
  that merely dropped volatile names would fail this), a genuine −60% grind is never flagged, a known
  split is *explained* and not reported, gaps aged out of the lookback are ignored, too-little-history
  falls back to zero, clean data leaves the delivered target byte-identical, and `buy_advice_safe` is
  false whenever `safe_to_advise` is.
- **Note for PR-7:** `scripts/autopilot.py` calls the same advisor, so the System/Shadow books' future
  deploys are corrected from here on — while their *existing* holdings still carry the artifacts
  (T4.2). That is precisely the confound the re-seed exists to clear.

### PR-3 · Candidate health flag, and restore the buy surfaces (fixes T1.2, T1.4, T1.5) — ✅ BUILT
User's decision: **flag, not veto** — the list still shows the same names, with the system's own
verdict beside each. Implemented exactly so: a 🔴 name stays in the basket and is still bought, with
its verdict rendered next to it (asserted by test, so a later "helpful" veto cannot creep in).

**T1.2 — the advisor now consults the detector it ships with.** `position_health()` runs over the
**candidate universe**, and every recommended name carries its level, 6-month return and
excess-vs-median into `WeaknessDeployAdvice.candidate_health` → `candidate_health_note()` → `render()`.

**The number is worse than the audit found. On the live panel it is 13 of 15, not 4 of 5.**
That table would be uninterpretable on its own — a pullback screen and a breakdown test look at the
same price fall, so *some* overlap is structural. So the note also carries the **universe base rate**:

> 13 of 15 recommended names are ones this system would flag for review-for-exit if you held them.
> For scale: **27% of the whole watchlist** is breaking down right now, so this basket is
> **3.2× more concentrated** in them than the universe it was drawn from.

That ratio is the honest statistic, and it is the one worth watching over time. A caveat that belongs
in the record: with the cross-sectional median at +0.4%, `DefensiveConfig`'s two conditions
(`abs_drawdown_exit=0.10` **and** `rel_underperf_exit=0.10`) currently collapse into roughly one — "is
it down more than ~10%". In a market with a median near zero the detector is less discriminating than
its two-condition design implies. Not a defect introduced here, but do not read 🔴 as a strong
independent signal until the thresholds get the §6.2 walk-forward calibration they were always
flagged as needing.

**T1.4 — the sector cap now binds on the basket actually delivered.** The water-filling was factored
into `_cap_sectors` and is applied **again after `head(max_names)`**. The old order constrained a
basket nobody was handed, and the top of a cheapness ranking is exactly where one sector clusters.
Measured on the live watchlist, largest sector before → after:

| names (the user's slider) | before | after |
|---|---|---|
| 5 | **80.1% IT** | 50.0% (cap infeasible at 5 names — degrades gracefully) |
| 8 | **50.7% IT** | 30.0% |
| 10 | **40.8% IT** | 30.0% |
| 12 | **34.3% IT** | 30.0% |
| 15 (default) | 27.7% | 27.7% — unchanged |

The slider runs 5–40 and explicitly invites concentration, so **every setting below ~13 silently broke
the 30% cap the code advertised.** At the default it was already compliant, which is why nothing
surfaced it.

**T1.5 — said on screen, every render.** `buy_advice_scope_note()` states what the screen is (a
deterministic technical screen, ₹0-tax, continuity-checked, health-flagged) and what it is not (never
backtested, no shared selection code or names with the 18.2% funnel, never measured against a
baseline). Added to [README.md](README.md) §7 as its own bias bullet — the existing "technical, not
P/E" line never said "never tested against a baseline".

**Surfaces restored.** `BUY_ADVICE_ON_REAL_MONEY = True`. The tab now has three distinct states:
switched off at the flag (kill-switch, kept working and tested), allowed but running on prices that
failed PR-2's guard, or live. The kill-switch notice was rewritten so it no longer cites the two
now-fixed defects as its reason — a notice that lies about why it is showing is its own trust failure.

**`test_deploy.py`'s drawdown assertion rewritten** per the plan: the ordering still holds (it is the
deliberate tilt), now paired with a companion test asserting the delivered basket carries the health
verdict, so "further down ⇒ buy more" can never again be the *whole* specification.

### PR-4 · Label every number (fixes T2.1–T2.5) — ✅ BUILT
The fix is **a vocabulary, not new arithmetic** — every number the audit found was correct.

**New `src/qalpha/live/measures.py`.** `ReturnMeasure` cannot render without a **basis** (what the
denominator is) and a **window** (over which dates); `BASES` names the four this system actually uses
— *money put in* · *capital actually invested* · *the notional starting capital* · *the book's first
equity mark*. Before this, the choice of denominator was implicit in whichever function happened to
compute the number. Plus `measures_table`, `cash_drag_note`, `window_mismatch_note`.

**T2.1 — the window is now in the book.** `Book.start_date`, stamped on first funding and serialised.
`baseline_book.json` had no such field, so its window was recoverable **only from `system_track.csv`
row 1** — backfilled to `2026-07-10` from exactly that source. A later top-up does not move it, and a
legacy book without the key still loads and does not have one invented.

**T2.2 — one headline per book; the rest behind a note.** The GO book's three numbers (+0.95% vs
starting capital, +1.26% vs the first mark) differ **only by the ₹611.92 of day-one trading cost that
sits between the denominators**. The headline is now the stricter basis — starting capital, which
counts that cost against the book — and an "ℹ️ How this is measured" expander carries the other with
the reason it differs. On the System book, the report names the **+0.70pp** gap between +2.03%
(contributed) and +2.73% (deployed) as **cash drag**, and says plainly that it is currently larger
than the System−Shadow difference the study is trying to measure.

**T2.3 — one book, one number.** The tile re-marked equity live against the host panel while the
chart beneath it, the GO scorecard and the freshness panel all read the cron-committed curve. The
tile now reads the **committed curve** — the book of record, since it is the criterion-6 evidence —
and any live drift is shown as a separate, labelled line rather than silently swapped in. Tile
renamed **"Book value (incl. cash)"**, beside **"of which cash"**.

**T2.4 — chart count was never the problem**, and the clutter it was mistaken for is now labelled.

**T2.5 — the AI narrative leads with what it actually does.** `ai_signal_summary()` renders the
`SIGNAL:` line and the one multiplier it produces, states that the contract has **no ticker field**,
and puts the prose behind a nested expander. Paragraphs of per-name analysis rendered under a buy
list are what made the brief read as *"the AI picked these"* — it cannot.

**Windows printed wherever two books appear.** The core-GO expander lives *inside* the System tab, so
two books with different funding histories and start dates 28 days apart sat on one screen with
nothing saying so. `window_mismatch_note` now says it, and adds that they are structurally separate
books. (A first cut of that helper dropped rows with no end date, which is every live book — it
rendered a dangling "— ." on the page. Fixed, with a test.)

Tests: 17 new. `test_measures.py` pins the vocabulary and both real confusions (one series/two
windows; one book/two bases). `test_dashboard_app.py` asserts the headline tile equals the committed
curve's last mark — a **cross-surface** assertion, the class of test T3.3 says does not exist yet.

### PR-5 · Cross-surface consistency tests (fixes T3.3) — ✅ BUILT
The gap that let all of this pass 316 green tests.

**New `tests/test_cross_surface.py` (16 tests).** These assert relationships *between* artifacts, not
the value of any one of them — every panel was individually correct and the page as a whole
contradicted itself, which is exactly what per-function coverage cannot see. Two surfaces reporting
the same book must agree, **or** differ by a named, tested quantity:
- `book.json` ⇄ `paper_dashboard.md` ⇄ `paper_equity.csv` — same mark, three renderings.
- The GO book's two bases differ by **exactly** the ₹611.92 day-one cost — one basis is
  *reconstructed* from the other, so the identity is asserted rather than the numbers memorised.
- `system_track.csv` ⇄ `autopilot_dashboard.md` for all three books; `profit = value − contributed`;
  the three books share one contribution history; System−Shadow is the subtraction it claims to be.
- **The assertion that would have caught the original defect:** not "is +2.03% right" (it was), but
  "does anything on this page explain why +2.73% appears eleven lines below it" (nothing did). Plus
  its converse — matching bases must *not* produce a quantified cash-drag claim.

These read only committed files, so they need no market data and no network.

*Design note:* label/window/cash-drag assertions render the report **fresh from committed data**
rather than reading the committed `.md`, which only regenerates when the cron fires — otherwise the
test would be measuring how recently the cron ran.

**`test_dashboard_app.py` now runs in CI.** The plan called for committing a fixture price panel;
generating one in a `dashboard_sandbox` fixture is strictly better — no market data enters the repo,
the panel cannot go stale relative to "today", and the prices are deterministic. Verified the way it
matters: **the full suite passes with every `.parquet` moved off disk.**

**⚠️ The plan's diagnosis of T3.3 was incomplete, and the missing half was the bigger one.** The
gitignored panel was only one blocker. `ci.yml` ran `uv sync --extra dev`, which **does not install
streamlit**, so `pytest.importorskip("streamlit")` skipped the module in CI *regardless of any
fixture*. Fixed by installing `--extra dashboard`. And because a skipped test reads as a passing one
in the summary line, CI now **fails on any skip at all** — the mechanism that hid this is closed, not
just this instance of it.

**Tab-1 freshness (was entirely ungated).** `source_freshness` / `sources_freshness_markdown` +
`_tab1_sources_panel`: the scoreboard, the track record and the AI brief are all cron-written files
that were rendered with no freshness check whatsoever, so a stopped cron would serve its last
successful numbers indefinitely with nothing on screen saying they were old.

**Result: 393 tests, 0 skipped** (was 316 with a silently-skipped dashboard module).

### PR-6 · Accounting integrity (fixes T3.1, T3.2, T3.4) — ✅ BUILT

**T3.2 — the queue could destroy a deposit, two ways.** `apply_pending` read the queue and truncated
it to `[]`; the books were persisted ~180 lines later at the end of `cmd_daily`. So:
1. a deposit queued by the dashboard **between the read and the truncate** was destroyed unread — the
   same failure family as the ₹50k lost in July; and
2. **any crash in the deploy/gate/mark pipeline** left the queue empty and the money never credited.
   That second window is much wider than the race and, as far as the queue is concerned, worse:
   applying a deposit twice is recoverable, silently dropping one is not.

Fixed by **claiming entries by id**. `entry_id()` derives a stable identity from the entry's own
fields (legacy entries queued before ids existed resolve to the same hash every time).
`apply_pending` no longer clears; the runner calls `clear_applied(applied)` **after** `save_state`,
which re-reads the file and writes back everything it did not claim. Anything queued mid-run survives
and is applied on the next pass — asserted by test, including the crash case.

**T3.1 — ₹240,500 of drift, reconciled without rewriting history.** Root cause: the cron re-logged
the same queued deposits on each pass (the duplicate pairs are visible minutes apart in the log).
`log_manual_injection` is now **append-once, keyed on the entry id**, and returns whether it wrote.
The repair is an appended **signed correction**, not a deletion — the erroneous rows are the evidence
of what the runner did, and an audit log you edit is not an audit log.
**`manual_log_drift(Decimal('200000'))` now returns `0`** (it returned `240500`), which is the plan's
acceptance criterion. `_report_log_drift` keeps its cron print, and the number now also appears as a
**dashboard banner** (`injection_drift_markdown`) that leads with *"Your money is fine"* — because it
was: `state.json` is authoritative and the books always held the right amount.

**T3.4 — archived, not deleted (a deliberate deviation from the plan).**
`data/autopilot/{track.csv, adaptive_track.csv, books.json}` have no reader or writer, but they are
the final state and track record of a **pre-registered experiment** frozen on 2026-07-12. This repo's
own rule is that pre-registered work is archived and published, never quietly removed — deleting a
superseded study's evidence is how a track record becomes a selection of its good runs. They move to
`data/autopilot/archive/` with a README explaining what they were. `monthly_autodeposit: true` is
dropped from `state.json` (feature removed 2026-07-28).

**⚠️ `reports/{paper_dashboard.md, paper_equity.csv}` are NOT dead and were not touched.** The plan
lists them as "read by nothing in this repo". They are written every run by `scripts/paper.py`,
committed by `paper.yml`, **read by PR-5's cross-surface tests**, and fetched over HTTP by the
research repo's mission-control. Deleting them would have broken all three.

### PR-7 · Re-seed the experiment from today (user's Q3) — ✅ BUILT
*"what if we start from the ground zero day 1 from today"* — and it did not touch the GO book's clock,
exactly as expected. `data/paper/book.json` is **byte-identical** before and after (md5 unchanged,
45 marks, start 2026-06-12). Pillar 1 never stopped accruing.

**T4.1 — fixed-notional baskets, so System − Shadow is an ablation.** The pre-registration said the
tilt changes size only; it did not, because each book called the advisor with its *own* portfolio and
its *own* amount. `max_name_fraction` filters candidates on `price ≤ amount × 0.20` (a smaller deploy
sees a smaller universe) and whole-share rounding drops different names at different scales.
Now: `_reference_basket()` computes the day's basket **once, at ₹100,000, against an empty book**;
`scaled_basket()` scales quantities per book (truncating — `Portfolio.buy` is cash-capped, so rounding
up would silently shrink and reintroduce the amount-dependence); `common_basket()` drops a name only
if it rounds below one share in **both** books, symmetrically. Verified on live data:

| | names | tickers |
|---|---|---|
| System @ ₹50,000 | 15 | — |
| Shadow @ ₹40,000 | 14 | — |
| **executed (intersection)** | **14** | **identical in both books**, quantities differ |

**T4.2 — re-seeded, with the artifacts gone.** `scripts/autopilot.py reseed` archives everything and
restarts at ground zero: System and Shadow **byte-identical and empty**, Baseline holding the same
₹400,000, all three on identical cash flows from 2026-08-18. Neither book holds VEDL or TRENT any
more (run 1 held 69/57 and 6/5 respectively, bought on phantom discounts).

**Archived, not deleted; published as a negative.**
[reports/FORWARD_RUN_1_VOID.md](reports/FORWARD_RUN_1_VOID.md) records what run 1 reported
(System − Shadow **₹1,541**, under one day's **₹1,964** of rounding noise) and why it is void. The
honest first result is not "the AI didn't help" but **"the instrument could not measure it"**. Books,
track record, ledger, flows and state are all under `data/autopilot/archive/forward_run_1_*/`.

**Pre-registration amended before run 2 accrued a single mark** — a *second* amendment block in
[docs/PREREGISTRATION_autopilot.md](docs/PREREGISTRATION_autopilot.md); nothing above it rewritten. It
adds a pre-committed bar the first run lacked: **a System − Shadow difference is reportable only if it
exceeds the run's cumulative rounding-noise scale**, otherwise it is reported as "no measurable
effect". Run 1's real failure was quoting a number smaller than its own error bar.

**The stale scoreboard is cleared too.** `reseed` rewrites `reports/autopilot_dashboard.md` to "run 2
has not started", because leaving the void run's numbers on the dashboard is the same
stale-artifact-presented-as-current failure the freshness work exists to prevent. PR-5's cross-surface
tests now assert *both* run states — with a track record they check agreement, without one they check
the scoreboard says so — rather than skipping, since CI now fails on any skip.

### PR-8 · AI name-verdict experiment (user's Q4) — ✅ BUILT
*"the AI recommends, the math runs it, if it is a no- then no, if it is a yes then yes … the watchlist
it gives should not just be of tomorrow, but based on a window say a year or so."*

**⚠️ This changes locked discipline #3** — the LLM now *selects*. It is the one deliberate exception,
**fake money only**, and its boundaries are enforced in code, not by prompt. Three guards, each tested:

1. **It cannot add a name.** `parse_verdicts` discards any ticker outside the deterministic universe
   it was handed. A model that invents RELIANCE or NVDA has those rows dropped before any code sees
   them. The opportunity set is fixed before the model is asked.
2. **It cannot size anything.** It returns keep/drop; `survivors` filters and never rescales. A
   surviving name is bought in exactly the quantity the fixed-notional basket assigned it — the same
   quantity Shadow buys.
3. **It cannot fail closed.** No verdict, no API key, a refusal, an exception, an unparseable line →
   the name is **kept**. Every failure mode degrades to exactly the Shadow book, never to an empty
   one. The deterministic screen is the floor; the model can only subtract from it.

**Contract.** A new `VERDICT:` line per name — `ticker` · `call` · `confidence` · `reason` —
deliberately *not* folded into `SIGNAL:`, which is one scalar for the whole index and has no ticker
field (the mechanical reason the narrative reached nothing, T2.5). `SIGNAL:` is untouched.

**The horizon is the change that matters.** The old prompt asked for a lean over the next 1–2 sessions
— a question about noise, scored against noise. `build_verdict_prompt` asks whether a name that is
*already* cheap and *already* flagged breaking is still a poor holding **a year out**, and points the
model at company-specific news a price screen cannot see (governance, regulatory action, accounting,
demerger effects, a broken end-market). *"It has fallen a lot"* is explicitly ruled out as a drop
reason — that is the screen's own selection criterion. Each candidate arrives with the deterministic
facts (re-based cheapness, §4.7 health, 6-month return) so the model reasons about news rather than
re-deriving numbers the engine owns.

**The deploy-size tilt is RETIRED** — both books now deploy the identical amount. This is *forced* by
the acceptance criterion: with the AI stubbed to keep everything the two baskets must be
byte-identical, which cannot hold while a tilt still moves one book's quantities. Run 3 therefore
tests **exactly one treatment**. Run 1's tilt result stands as published: unmeasurable.

**Model stays Claude Haiku 4.5 + web search** — now a *pre-registered parameter* that must not change
mid-run, since a model swap would be a second treatment. Haiku keeps the basic `web_search_20250305`
variant (the `_20260209` dynamic-filtering variant is Opus/Sonnet-tier only); `thinking`/`effort` do
not apply to Haiku and are correctly omitted.

**Third pre-registration amendment** recorded in
[docs/PREREGISTRATION_autopilot.md](docs/PREREGISTRATION_autopilot.md) before run 3 accrued a mark;
nothing above it rewritten. It adds one bar beyond amendment 2's noise floor: **if the AI drops no
names over the run, the result is "no verdicts issued", not "the AI didn't help"** — an untriggered
treatment is not a negative result.

Tests: 14 new, all guard-focused and network-free. The acceptance criterion —
`test_stubbed_to_keep_everything_the_two_baskets_are_identical` — asserts same tickers *and* same
quantities, which is what makes System − Shadow an ablation of the verdict rather than a comparison
of two differently-built portfolios.

## Verification

Four gates on every PR: `ruff check` · `ruff format --check` · `mypy src` (strict) · `pytest -q`.
**429 tests, 0 skipped** (was 316 with a silently-skipped dashboard module). CI now installs the
`dashboard` extra and **fails on any skip**.

**The GO book is byte-identical throughout all eight PRs** — md5 `ea9a45f4…`, start 2026-06-12, 45
marks. Rule (a) verified per PR: no backtest or factor path imports `live/deploy.py`,
`live/position_health.py`, `price_integrity.py`, or `ai_brief.py`.
