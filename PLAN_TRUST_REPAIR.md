# Trust repair — the advisor, the page, and the experiment (planned 2026-08-17)

**Status: PR-1 BUILT (branch `trust-repair-pr1`, four gates green, 321 tests). PR-2 … PR-8 planned,
user-approved scope, not yet implemented.**

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

### PR-2 · Price-continuity guard (fixes T1.1, T1.3)
New `src/qalpha/live/price_integrity.py`:
- `unexplained_gaps(prices, tickers, as_of, *, threshold=0.25, lookback=365)` → per-ticker one-day
  returns beyond threshold **not** matched by a split/dividend from
  `corporate_actions_feed.corporate_actions_from_series` (reused, not reimplemented).
- A flagged name is excluded from `cheapness_scores` until its 1-year high is re-based to the post-gap
  window, and is reported on the advice object so the UI can say why.
- Extend `safety.assess_advice_inputs` ([safety.py:137-158](src/qalpha/live/safety.py)) to take the
  **watchlist** panel as well as the core panel; make `_download_watchlist_panel` surface a banner on
  failure instead of silently serving stale prices.
- Tests: VEDL/TRENT fixtures assert both drop out of the top of the ranking; a genuine −30% slide with
  no gap must still rank.

### PR-3 · Candidate health flag, and restore the buy surfaces (fixes T1.2, T1.4, T1.5)
User's decision: **flag, not veto** — the list still shows the same names, with the system's own
verdict beside each.
- Call `position_health()` over **candidates** as well as holdings; carry each name's level on
  `DeployAdvice`. Render 🔴/🟠/🟢 beside every recommended name with its 6-month return and
  excess-vs-median.
- Re-cap sectors *after* `head(max_names)` ([deploy.py:156-158](src/qalpha/live/deploy.py)) so the
  delivered basket carries the constraint the code claims.
- Reframe on screen: this is an **unvalidated technical screen, not the 18.2% strategy**. Say it in
  [README.md](README.md) §7 too — the existing note says "technical, not P/E" but never says "never
  tested against a baseline".
- Rewrite [test_deploy.py:66-71](tests/test_deploy.py) so the drawdown ordering is asserted
  *alongside* the health flag rather than as the sole property.
- Restore the PR-1 surfaces.

### PR-4 · Label every number (fixes T2.1–T2.4)
- Every return gets its **basis and window** on screen. Add `start_date` to `baseline_book.json`;
  print both windows wherever two books appear.
- Show the System book's +2.03% and +2.73% together, labelled *contributed* and *deployed*, with the
  gap named as cash drag.
- The GO book reports **one** headline; the other two bases move behind a "how this is measured" note.
- Equity tile → "Book value (incl. cash)", or subtract cash. Make the tile and the chart beneath it
  read the same source (T2.3).
- Collapse the AI narrative to the `SIGNAL:` line plus the tilt it produced (T2.5) — superseded by
  PR-8 if the name-verdict experiment ships.

### PR-5 · Cross-surface consistency tests (fixes T3.3)
The gap that let all of this pass 316 green tests.
- Assert that any two surfaces reporting the same book agree, or differ only by a named, tested
  quantity (the ₹611.92 day-one cost; the cash-drag gap).
- Commit a small fixture price panel so [test_dashboard_app.py](tests/test_dashboard_app.py) **runs in
  CI** instead of skipping.
- Add a freshness assertion for the Tab-1 sources (`autopilot_dashboard.md`, `system_track.csv`,
  `ai_brief.md`) — currently entirely ungated.

### PR-6 · Accounting integrity (fixes T3.1, T3.2, T3.4)
- Reconcile the ₹240,500 log drift: make `manual_injections.json` append-once keyed on the queue
  entry's id, backfill a correction record, turn `_report_log_drift` from a print into a loud
  dashboard banner.
- Close the `pending_injections.json` race: the runner claims entries by id and clears **only what it
  applied**, rather than truncating the file.
- Delete the dead files and state keys.

### PR-7 · Re-seed the experiment from today (user's Q3)
*"what if we start from the ground zero day 1 from today … before window gets removed"* — correct
instinct, and cheaper than it sounds: **re-seeding System/Shadow does not touch the GO book's clock.**
Depends on PR-2 and PR-3 — re-seeding first would rebuy the artifacts.
- **Archive, don't delete.** Freeze the 2026-07-10 → present run as a disclosed, confounded first
  result and publish it as a negative, per repo rule. Its data stays committed.
- Re-seed System / Shadow / Baseline at ground zero on the day this lands, identical cash flows.
- **Fixed-notional baskets:** compute the basket once at a fixed notional, then scale executed
  quantities. Composition identical by construction; only size differs. This is what makes
  System − Shadow an ablation rather than a comparison of two funds.
- Amendment recorded in [docs/PREREGISTRATION_autopilot.md](docs/PREREGISTRATION_autopilot.md) — the
  file already carries one amendment block; add a second. Never rewritten.
- Pillar 1 keeps accruing on the GO book's existing 45 marks.

### PR-8 · AI name-verdict experiment (user's Q4)
Same pre-registration amendment as PR-7; ships after it.

*"the AI recommends, the math runs it, if it is a no- then no, if it is a yes then yes … the watchlist
it gives should not just be of tomorrow, but based on a window say a year or so."*

The current study tilts deploy *size*, which is why noise swamped it. A per-name verdict is directly
measurable, and the re-seeded Shadow is the instrument.
- **Design:** math generates the candidate list (drawdown screen + continuity guard + health flag) →
  the AI returns a per-name keep/drop verdict on a **~1-year horizon** → math sizes and executes what
  survives, ₹0-tax, whole shares. The AI never computes a number, never sizes a position, and
  **cannot add a name outside the deterministic universe** — that keeps the opportunity set fixed and
  the ablation clean.
- **Prompt:** rewrite [ai_brief.py:63-98](src/qalpha/live/ai_brief.py) to ask for a one-year view of
  each candidate, not tomorrow's session. Score `SIGNAL.lean` on the horizon it was asked about.
- **Contract:** extend the `SIGNAL:` grammar with a per-name field — today it has none
  (`ai_brief.py:94`, `autopilot.py:36`), which is the mechanical reason the narrative reaches nothing.
- **Measurement:** System = candidates + AI verdict; Shadow = identical candidates, no verdict.
  System − Shadow then measures exactly "did the AI's name judgement help", with composition
  controlled.
- **⚠️ Scope change, stated plainly:** this makes the LLM a **selector**, which changes locked
  discipline #3 (AI is informational-only). It runs **fake money only**; it reaches the real-money
  advisor only on a positive verdict, per the endgame contract. **Real money never auto-trades — that
  rule is untouched.**

## Verification

Four gates on every PR: `ruff check` · `ruff format --check` · `mypy src` (strict) · `pytest -q`
(316 tests today). `paper.yml` commits `[skip ci]` and runs no tests, so CI must be exercised via PR.

Reproduce the two headline defects, before and after PR-2/PR-3:

```bash
# T1.1 — unexplained one-day gaps across the watchlist (expect VEDL, TRENT; expect none after PR-2)
uv run python -c "
import pandas as pd
df=pd.read_parquet('data/historical/prices_watchlist.parquet'); df['date']=pd.to_datetime(df['date'])
cut=df.date.max()-pd.Timedelta(days=365)
for t,g in df.groupby('ticker'):
    s=g.set_index('date')['adj_close'].sort_index(); s=s[s.index>=cut]
    m=s.pct_change()[lambda r: r<-0.25]
    if len(m): print(t,[(d.date(),round(100*v,1)) for d,v in m.items()])"

# T1.2 — the system's own verdict on its own buy list (expect 4x breaking today)
uv run python -c "
import pandas as pd
from qalpha.data.prices import PriceData
from qalpha.live.position_health import position_health
df=pd.read_parquet('data/historical/prices_watchlist.parquet')
p=PriceData.from_long(df); a=pd.to_datetime(df['date']).max().date()
for h in position_health(p.adj_close,['VEDL.NS','TRENT.NS','IRFC.NS','HDFCLIFE.NS','ITC.NS'],a).holdings:
    print(h.icon,h.ticker,h.level,f'{h.trailing_return:+.1%}',f'{h.excess_vs_market:+.1%}')"
```

- **PR-1:** `AppTest` smoke asserts the Live tab renders with no auto buy-brief and that Sell / Raise
  cash still work.
- **PR-2:** the gap script returns empty; a synthetic genuine slider still ranks; a failed watchlist
  download produces a banner, not silent stale prices.
- **PR-3:** the four 🔴 appear beside the names in the rendered advice; the delivered basket respects
  the sector cap after truncation.
- **PR-4/PR-5:** new consistency tests fail on `main` and pass after; `test_dashboard_app.py` reports
  as **run**, not skipped, in the CI log.
- **PR-6:** `manual_log_drift(Decimal('200000'))` returns `0` (it returns `240500` today); a deposit
  queued mid-run survives and is applied on the next run.
- **PR-7:** on the first two marks, System and Shadow hold **identical tickers** — the property whose
  absence voided the last six weeks.
- **PR-8:** with the AI stubbed to "keep everything", System and Shadow baskets must be
  byte-identical — proving the only difference the experiment can measure is the verdict itself.

End-to-end, after PR-3 and again after PR-7: run `scripts/autopilot.py daily` locally against the
committed state, confirm the idempotent re-run, and diff the rendered `reports/autopilot_dashboard.md`.
