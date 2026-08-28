# CLAUDE.md

Guidance for Claude Code (and humans) working in this repo.

## 🛑 READ FIRST — REAL MONEY IS IN THE ACCOUNT (2026-08-27)

**₹5,00,000 has been transferred to the user's real Zerodha account.** The plan he decided on:
**₹1,00,000 opening basket across 8 names, then ₹50,000/month SIP.** He places every order himself;
nothing here has ever auto-traded and nothing ever will.

**He is investing BEFORE the system's own gate opened, knowingly.** The deterministic GO scorecard
read **NOT YET** on audit day — 3 of 5 criteria amber:

| Criterion | Reading (2026-08-24) |
|---|---|
| Track length | 50 of 63 trading days |
| **Volatility event withstood** | **never** — worst in-window Nifty pullback −2.2%, gate needs ≤ −10% |
| Forward vs benchmark | paper book **+0.3% vs Nifty +3.3%** — trailing by 3.1pp |
| Drawdown behaviour | 🟢 market-driven, within tolerance |
| Data integrity | 🟢 dense, largest gap 4 days |

The System book also sat **behind** plain NIFTYBEES buy-and-hold on its (very short) run. **Do not
re-litigate his decision** — it was made with all of the above in front of him, and the honest framing
he was given is: *plan at the index's ~11–12%, treat the backtest's 16.4% as unproven upside, and
size the first year as tuition.* **The gate has not opened. Never describe the system as validated
for real money, and never soften the scorecard to make him feel better about money already committed.**

### The pre-flight audit found FIVE defects, and they are all one defect

**Full write-up: [reports/PREFLIGHT_AUDIT.md](reports/PREFLIGHT_AUDIT.md)** — findings with reproduced
numbers, the process lesson, and the recommendation given.

Every one was a **number labelled as something it is not**, on a surface where the label becomes an
order. None was caught by 481 passing tests, because each is a figure reported *about* the machinery
rather than the machinery's own arithmetic. **This is the failure mode of this codebase — a resuming
session should hunt for exactly this shape.**

1. **A stale benchmark graded the GO scorecard, silently** (#72). `paper.py daily` refreshes the
   benchmark; `paper.py refresh` refreshes prices and **not** the benchmark. A 70-day-stale copy read
   the worst Nifty pullback as **0.0%** instead of −2.2% (so the hard volatility gate reported a calm
   market when the truth was *no data*) and flattered the strategy by 2.3 points. Now
   `_benchmark_covers` refuses to grade and names the fix.
2. **`universe_breaking_rate` was 0.0 by construction** (#72) — measured over the universe *after* the
   breakdown filter removed the very names it counts, so the sentence that makes the health table
   interpretable never rendered. Real rate on the live watchlist: **20.4%**.
3. **The 30% sector cap breaches below six names** (#72) — 33.9% at five, **50.0% at three**. Below ~6
   names the cap is *arithmetically unreachable* (five equal names ⇒ one is 20% ⇒ any two in a sector
   is 40%). Unfixable by clamping, so it is **disclosed**: the delivered mix is shown and flagged.
4. **The deploy heading named `amount` while the basket spent `cash + amount`** (#73). A ₹5,00,000
   broker balance and ₹1,00,000 typed produced a **₹5,97,418** basket under a "Deploy ₹100,000.00"
   heading. **The user was one click from a 64-share HCLTECH order that should have been 11** — 84% of
   his opening position in one stock. The arithmetic was right and documented; the label was not.
5. **The Equity tile was `market_value`, which includes cash** (#74). With the SIP money parked, it
   read **₹5,00,000 of "Equity" against ₹0 of stock**; after the opening basket, ₹6,00,877 where the
   shares are worth ₹1,00,693.

**⚠️ A process lesson worth more than the fixes.** Defect 4 was hit *during the audit itself* — a test
run produced a ₹1.99 lakh basket on a ₹1 lakh deploy, it was written off as a harness mistake, and the
session moved on. It was both. **When a number looks wrong in your own scratch run, chase it before
explaining it away.**

### What shipped (all merged, 503 tests, 0 skipped)

- **#71 `live/track_record.py`** — the forward instrument. Your tradebook → dated cash flows → the
  **same rupees on the same days** replayed into NIFTYBEES → both legs marked today, with an **XIRR**
  (money-weighted; a monthly SIP is not present for the whole window, so a start-to-end percentage is
  not a rate). Honesty properties are the tests: it **must be able to say "behind by ₹X"**; under
  `MIN_MONTHS_FOR_A_VERDICT = 12` it refuses a verdict and says the gap is entry timing; the index leg
  is priced **at or before** each trade; a sell larger than the index sleeve floors at zero and flags.
- **#72** the three audit fixes above.
- **#73 `advise_deploy(..., spend_idle_cash=)`** — the typed amount is now a **hard budget** on the
  real-money surface, with a checkbox to opt back in. **Library default stays `True`** (the autopilot
  depends on idle cash being deployed). Targets size on `holdings_value + budget`, so a large parked
  balance cannot skew positions. *Why a switch and not a smarter default:* **a broker balance is not
  self-describing** — cash for next month's instalment and cash awaiting deployment are
  indistinguishable from inside the advisor. Only the user knows.
- **#74 `live/dashboard.py:account_overview`** — Equity (shares only) · Cash / available margin (% of
  account, explicitly *not* Equity) · Unrealised P&L against what was actually paid. Imported from the
  user's Claude Design project, whose own figures state the contract (₹1,91,312 + ₹7,335 = ₹1,98,647).
  A day's move is **withheld unless every holding has a previous close**; an unpriced holding is
  **named in a banner**, never valued at zero.

### Standing limitations — true on the first order, not fixable by more code

- **Nobody has watched this system fall.** Every live day so far has been calm.
- **The buy screen has one backtest behind it** (16.4% vs 11.8%, 13y SIP), its concentrated variants
  lean on a survivorship-flattered watchlist, and **every guard protecting that result was written in
  the month before the money went in**.
- **Most of the tax engine has never met a broker statement.** Exactly one sell reconciled: single-lot,
  all-STCG, no loss (₹25.25, Δ ₹0.00). Multi-lot / LTCG / loss set-off / exemption are unit-tested and
  unconfirmed. The page warns when a sale touches them — **that sale must be reconciled afterwards**.
- **No corporate action has ever been reconciled live** (criterion 5).

### The operating contract the user actually runs

Open dashboard → Kite login (daily) → **Add money, type the amount** (it is now a hard budget) →
**slider 8 for the opening ₹1,00,000; 3–4 for the monthly ₹50,000** (stickiness dominates the SIP — at
sliders 3, 4 and 6 the top-ups are *identical* and add zero new names; 12 sprawls to 13 names) → place
every order himself in Kite, **CNC/delivery, no stop-loss, no target** → **upload the tradebook after
every batch** (Console → Reports → Tradebook; de-duped on Zerodha trade IDs, so overlapping ranges are
safe). Money for future instalments **stays in the broker account** — he explicitly refused a
transfer-in/transfer-out chore, which is why #73 exists.

**No stop-loss, and this is load-bearing:** the screen buys names that are *down*, so a stop sells
exactly what it just bought, realizes a loss, triggers tax, and fires constantly on normal volatility.
The exit rule is the §4.7 breakdown test, which distinguishes a name-specific fall from the market
falling. A stop-loss cannot.

## ✅ DONE — THE FINAL AUDIT, ALL SIX FIXED (2026-08-28)

**Full write-up: [reports/FINAL_AUDIT.md](reports/FINAL_AUDIT.md).** Branch `telegram-guard-parity`.
**522 tests, 0 skipped; ruff + format + mypy green.**

**Six defects, all the same defect again** — a number labelled as something it is not, on a surface
where the label becomes an order. 503 passing tests caught none of them. All six are now fixed.

| # | Surface | Said | Truth |
|---|---|---|---|
| 1 | Track record (#71) | "ahead by **₹4,01,677**" (+444.2%) | ahead by **₹1,677** (+1.2%) |
| 2 | Raise cash | "₹620 tax" | **₹9,570** — Sell tab said ₹32,754 for the same shares |
| 3 | Raise cash | "Raises ₹3,92,610.50" | ₹3,91,675.88, and ₹7,389 short of the ask |
| 4 | Holdings table | HCLTECH "3.3%" | **17.8%**; column summed to 18.6% |
| 5 | `position_health` | VEDL "−59%, breaking down" | a demerger step: **+2%** since it |
| 6 | Telegram scan | "VEDL −65% off high" | −22% once re-based |

**#1 was the worst and was pinned in place by a test.**
`test_the_track_record_is_on_the_real_money_page` asserted the literal string
`track_record(trades, portfolio.market_value(prices), ...)` — the suite would have gone **red** if
anyone had fixed it. `market_value` is cash + holdings, and the benchmark leg is built from traded
rupees alone, so ₹4L of parked SIP money read as pure outperformance on the one panel whose asserted
property is that it *must be able to say "behind by ₹X"*. Now `holdings_value`; the test forbids
`market_value(` by name and a behavioural test marks the same book both ways.

**#2 was two tax engines on one book.** `advise_raise_cash` costed its plan on the frozen backtest
engine (no §70 set-off, no §112A, **no §2(42A) 12-calendar-month correction**) and bolted cess on at
the end. It now runs the Sell tab's path: boundary-corrected lots, one `net_capital_gains_tax` over
the **whole plan** (tax is not attributable per order — §70 nets across names), redraw-until-met, and
**re-costed as the merged orders the user actually places**. Under-quote is now ₹0.00 at every level,
asserted by replaying the plan through the Sell tab's engine. The tab also finally shows the
unverified-branch warning and the "NOT long-term yet" demotion.

**#5 fixed the last unguarded consumer of `adj_close`.** `position_health` takes
`rebase_from`/`exclude` on the same default-off contract PR-2 gave `cheapness_scores`; the
cross-sectional median is computed **after** re-basing; the note no longer claims "~6mo" for a
shorter window. Every live caller routes through it — dashboards via one `_guarded_health` helper.

**Rule (a) holds, provably:** `git diff --name-only` touches **no** file under
`src/qalpha/{backtest, accounting, data, config}`. Every new guard defaults to off, so the SIP
backtest's own `position_health` call is bit-for-bit unchanged (asserted by test).

### The process lesson — second time running

> **When you fix a defect, grep for every other caller of the thing you fixed.**

#74 separated shares from cash in `account_overview` — `market_value` had two other live callers, and
#1 was merged in the same fortnight. PR-2 guarded `cheapness_scores` — `adj_close` had two other
unguarded consumers. Both fixes were correct; both were applied at one call site and reasoned about
as if applied to a concept. Corollary from #1: **a test that asserts a source line pins that line's
bug in place** — assert the property.

**⚠️ `scripts/paper.py refresh` refreshes neither the benchmark nor the watchlist panel.** Call
`_refresh_benchmark()` and `build_nifty100_watchlist.py --prices` too, or you audit stale data.

### Left open, deliberately

- The tradebook panel captions `result.realized_tax` as "realized capital-gains tax to date" — the
  backtest engine's figure, not the ITR number, unlabelled as an estimate. A caption on history, not
  an input to an order.
- `_liquidation_efficiency` still ranks each holding against the **full** remaining FY exemption in
  isolation, so the source *ordering* is a documented heuristic. The quoted tax is exact.
- The System tab's book comparison (fake money, captioned as such).
- **Nothing is merged to `main`** — this branch, and the earlier `docs-real-money` commit.

**The first multi-lot or LTCG sale must be reconciled against the Zerodha Tax P&L afterwards.** There
is now one tax path instead of two, but it is still the path that has met exactly one broker
statement (single-lot, all-STCG, no loss, ₹25.25, Δ ₹0.00). Code cannot close that; a reconciliation
can.

## ✅ CLOSED — TRUST REPAIR (2026-08-17, all eight PRs merged)

**The user audited the live dashboard and said: *"i am unable to trust the advisor for now."* He is
right, and the reasons are now documented and scoped. The full plan is
[PLAN_TRUST_REPAIR.md](PLAN_TRUST_REPAIR.md) — **ALL EIGHT PRs BUILT** (branches
`trust-repair-pr1`…`pr8`). Tiers 1–4 closed. 429 tests, 0 skipped.
Companion audit (same day, presentation + experiment side): [PLAN_INTEGRATION_AUDIT.md](PLAN_INTEGRATION_AUDIT.md).
All eight merged; nothing here is queued.** The *method* is what still matters: every defect was a
number the user could see, reconciled against the code that produced it.**

**PR-1 (done): the buy list is OFF the real-money surface.** One flag —
`live/dashboard.py:BUY_ADVICE_ON_REAL_MONEY = False` — gates the Add-money buy list, the zero-typing
auto PM brief, and the "deploy idle cash" checklist item; the Add-money tab now renders a notice
naming both defects. Every renderer stays wired behind the flag, so **PR-3 restores the surfaces by
flipping one constant, not by rewriting anything.** Sell / Raise cash are untouched (validated
FIFO/tax engine). Four gates green, 321 tests. **Do not flip the flag back until PR-2 (price
continuity guard) and PR-3 (candidate health flag) are both merged.**

**PR-2 (done): corporate actions no longer read as discounts.** New `live/price_integrity.py` —
`unexplained_gaps` finds one-day steps that no split/dividend explains (the feed is *injected*, never
fetched, so the guard is pure and costs no network call). The fix is a **re-base, not a veto**: a
flagged name's 1-year high is measured from its gap day, so it keeps a correct reading.
`cheapness_scores` gained `rebase_from`/`no_tilt`, both **default-off** — existing callers are
bit-for-bit unchanged. Measured on the live watchlist: VEDL 65.4%→**23.1%**, TRENT 47.4%→**13.2%**,
their combined share of a ₹100k deploy **44.4%→5.8%**. Also closes T1.3: `watchlist_freshness_guard` +
`SafetyReport.buy_advice_safe` (a narrowing of `safe_to_advise`, non-blocking so it never silences
Sell/Raise cash), and `_download_watchlist_panel` now reports failure instead of silently serving the
previous panel. 343 tests. **Rule (a) verified: no backtest path imports `live/deploy.py` or
`price_integrity.py` — the validated funnel is untouched.** ⚠️ `scripts/autopilot.py` uses the same
advisor, so System/Shadow *future* deploys are corrected while their existing lots still hold the
artifacts — the confound PR-7's re-seed clears.

**Two defects in the buy recommendation, both new this session, both real-money-facing:**
1. **Corporate actions read as discounts.** `cheapness_scores` (`live/deploy.py:100`) uses yfinance
   `adj_close`, which corrects splits + dividends but **never demergers**. Exactly two of 95
   watchlist names have an unexplained one-day collapse (VEDL −64.9% on 2026-04-30, TRENT −33.0% on
   2026-01-01) and they rank **#1 and #2** on cheapness — **44.4% of a ₹100k deploy chases two price
   artifacts**, and the phantom discount persists a full year.
2. **The advisor contradicts its own detector.** `position_health()` (the §4.7 idiosyncratic-breakdown
   test) rates **4 of the 5 names the advisor recommended** as 🔴 breaking down — VEDL, IRFC, HDFCLIFE,
   ITC. It runs over *holdings* only and is never pointed at *candidates*. Same panel, same day,
   opposite verdicts. This — not missing sentiment — is why it recommends falling knives.

Also established: **the buy rule has never been backtested** (no script references
`advise_deploy_into_weakness`); it shares **zero** selection code and **zero** names with the
validated funnel that the 18.2% headline describes. There is only **one** baseline, not two (`+0.98%`
and `+3.92%` are the same NIFTYBEES series 28 days apart) and only **two** charts — the "clutter" is
eight unlabelled return numbers on four bases. `manual_injections.json` over-counts contributions by
**₹240,500**; `pending_injections.json` still has a two-machine write race that can destroy a queued
deposit (same family as the ₹50k lost in July). **316 tests green and not one compares two panels
reporting the same book** — which is why none of this was caught.

**User decisions locked 2026-08-17 (do not re-litigate):**
- **Flag, don't veto.** Add the continuity guard + show `position_health`'s 🔴 beside each recommended
  name. Selection stays deterministic and unchanged.
- **Pull the buy list off the real-money surface NOW** (PR-1), restore it only once guarded (PR-3).
  Sell / Raise cash stay live — they run on the validated FIFO/tax engine.
- **Re-seed System/Shadow from ground zero** rather than pick a fallback; archive the confounded
  2026-07-10 → 08-17 run as a published negative. **This does NOT touch the GO book's clock.**
- **The AI graduates to name-level verdicts** (PR-8) — math generates candidates, AI returns keep/drop
  on a **~1-year horizon**, math sizes and executes. ⚠️ This makes the LLM a **selector**, changing
  locked discipline #3 — it is **fake-money only** until a positive verdict, is pre-registered, and
  the AI can never add a name outside the deterministic universe. **Real money never auto-trades.**


**PR-3 (done): the advisor now consults the detector it ships with; buy surfaces restored.**
`position_health()` runs over **candidates**, and every recommended name carries its verdict into
`WeaknessDeployAdvice.candidate_health` → `candidate_health_note()` → `render()`. **Flag, not veto** —
a 🔴 name stays in the basket and is still bought, asserted by test so a later "helpful" veto cannot
creep in. **On the live panel it is 13 of 15, not the 4 of 5 the audit found**, so the note carries the
**universe base rate** (27% of the watchlist is breaking → the basket is **3.2× more concentrated**)
— that ratio, not the raw count, is the interpretable number. ⚠️ Caveat for a future session: with the
cross-sectional median at +0.4%, `DefensiveConfig`'s two conditions collapse into roughly one ("down
more than ~10%"), so 🔴 is weaker evidence than its two-condition design implies until the §6.2
walk-forward threshold calibration happens. **T1.4 fixed:** `_cap_sectors` is re-applied after
`head(max_names)` — the old order let the delivered basket breach the cap it advertised at **every
slider setting below ~13** (at 5 names: **80.1% IT**; at 8: 50.7%; at 12: 34.3% — all now ≤30%). At the
default 15 it was already compliant, which is why nothing caught it. **T1.5 on screen:**
`buy_advice_scope_note()` says "never backtested, shares nothing with the 18.2% funnel" on every
render, and README §7 gained a matching bias bullet. `BUY_ADVICE_ON_REAL_MONEY = True`; the tab has
three states (kill-switch off / prices failed PR-2's guard / live) and the kill-switch notice no
longer cites the fixed defects as its reason. 353 tests.


**PR-4 (done): every number carries its basis and its window.** The fix is **a vocabulary, not new
arithmetic** — every number the audit found was correct, just unlabelled. New `live/measures.py`:
`ReturnMeasure` cannot render without a basis and a window; `BASES` names the four denominators in
use (contributed · deployed · starting capital · first mark). **T2.1:** `Book.start_date` stamped on
first funding + serialised; `baseline_book.json` backfilled to `2026-07-10` (its window was
recoverable only from `system_track.csv` row 1). **T2.2:** one headline per book — the GO book leads
with the **stricter** basis (vs ₹200,000 starting capital, which counts the ₹611.92 day-one cost
against it); the first-mark basis moved behind an "ℹ️ How this is measured" expander. The System
report names the **+0.70pp** contributed-vs-deployed gap as **cash drag** and notes it is larger than
the System−Shadow effect being measured. **T2.3:** the tile now reads the **cron-committed curve**
(same source as the chart/scorecard/freshness panel); live drift shows as a separate labelled line.
Tile → "Book value (incl. cash)" + "of which cash". **T2.5:** `ai_signal_summary()` leads with the
`SIGNAL:` line + the multiplier it produced and states the contract has **no ticker field**; prose
moved behind a nested expander. Two books on one screen now get `window_mismatch_note`. 370 tests.


**PR-5 (done): cross-surface tests, and the dashboard module actually runs in CI.**
`tests/test_cross_surface.py` (16 tests) asserts relationships **between** artifacts — two surfaces
reporting one book agree, or differ by a *named, tested* quantity (the ₹611.92 day-one cost is
asserted as an identity: one basis is reconstructed from the other). The load-bearing one is not "is
+2.03% right" but "does anything explain the +2.73% eleven lines below it". They read only committed
files — no market data, no network. **⚠️ The plan's T3.3 diagnosis was incomplete:** the gitignored
panel was one blocker, but `ci.yml` ran `uv sync --extra dev` which **never installed streamlit**, so
`importorskip` skipped the module in CI regardless. Now installs `--extra dashboard`, and **CI fails
on any skip at all** (a skip reads as a pass in the summary). `test_dashboard_app.py` runs against a
generated `dashboard_sandbox` fixture rather than a committed market-data panel — verified by passing
the full suite with every `.parquet` moved off disk. Tab-1's three cron-written sources
(`system_track.csv`, `autopilot_dashboard.md`, `ai_brief.md`) were rendered with **no freshness check
whatsoever**; now gated by `source_freshness`. **393 tests, 0 skipped** (was 316 with a silently
skipped dashboard module).


**PR-6 (done): the Add-money queue can no longer lose a deposit; the log reconciles.**
**T3.2** had *two* ways to destroy money, not one: `apply_pending` truncated the queue on read (so a
deposit queued mid-run vanished — the ₹50k-in-July family), **and** it cleared ~180 lines before
`save_state`, so any crash in the deploy/gate/mark pipeline emptied the queue with the money never
credited. That second window is far wider. Now entries are **claimed by id** (`entry_id()` hashes
legacy entries deterministically), `apply_pending` never clears, and the runner calls
`clear_applied()` **after** persistence — it re-reads and writes back everything it did not claim.
**T3.1:** `log_manual_injection` is **append-once keyed on the entry id** (the cron re-logging each
pass was the root cause); the ₹240,500 is repaired by an **appended signed correction**, never a
deletion — `manual_log_drift(Decimal("200000"))` now returns **0**. Drift also renders as a dashboard
banner (`injection_drift_markdown`) leading with "Your money is fine" — it always was; `state.json`
is authoritative. **T3.4:** the three dead files are **archived, not deleted**
(`data/autopilot/archive/` + README) — they are a frozen pre-registered experiment's evidence, and
this repo archives rather than removes those. ⚠️ `reports/{paper_dashboard.md, paper_equity.csv}`
are **not** dead (paper.py writes them, paper.yml commits them, PR-5's tests read them, research
mission-control fetches them) — the plan was wrong there; left alone. 404 tests.


**PR-7 (done): forward run 1 is VOID and published; run 2 seeded at ground zero 2026-08-18.**
⚠️ **The System/Shadow/Baseline experiment restarted — do not compare anything to pre-2026-08-18
numbers.** The **GO book was not touched**: `data/paper/book.json` is byte-identical (md5 unchanged,
45 marks, start 2026-06-12) and pillar 1 kept accruing. **T4.1 fixed:** the day's basket is computed
**once at a fixed ₹100,000 notional against an empty book** (`_reference_basket`), scaled per book
(`scaled_basket`, truncating — `Portfolio.buy` is cash-capped so rounding up would silently shrink),
and a name is dropped only if it rounds below one share in **both** books (`common_basket`). Verified
live: System @₹50k → 15 names, Shadow @₹40k → 14, executed intersection **14 identical tickers**,
quantities differing. **T4.2 fixed:** both books are empty and byte-identical at ground zero; VEDL and
TRENT (69/57 and 6/5 in run 1) are gone. Run 1 is archived under
`data/autopilot/archive/forward_run_1_*/` and written up in
[reports/FORWARD_RUN_1_VOID.md](reports/FORWARD_RUN_1_VOID.md) — its System − Shadow of ₹1,541 sat
under ₹1,964 of one day's rounding noise, so the honest verdict is *"the instrument could not
measure it"*, not *"the AI didn't help"*. **Second prereg amendment recorded before run 2 accrued a
mark**, adding the bar run 1 lacked: a System − Shadow difference is reportable only if it exceeds
the run's cumulative rounding-noise scale. `scripts/autopilot.py reseed [--as-of DATE]` is the
command; it also clears the stale scoreboard. 415 tests.


**PR-8 (done): the AI is now a per-name SELECTOR — ⚠️ locked discipline #3 changed, fake money only.**
Math generates candidates → the AI returns keep/drop on a **~1-year horizon** → math sizes and
executes survivors. **Real money never auto-trades — untouched.** Three guards, enforced in code and
tested, not prompted: it **cannot add a name** (`parse_verdicts` discards anything outside the
deterministic universe), **cannot size anything** (`survivors` filters, never rescales — survivors keep
the fixed-notional quantities Shadow uses), and **cannot fail closed** (no verdict/key/response, a
refusal, an unparseable line → the name is **kept**, i.e. exactly the Shadow book). New `VERDICT:`
line-per-name contract; `SIGNAL:` untouched. **The deploy-size tilt is RETIRED** — both books deploy
the same amount, forced by the acceptance criterion (stubbed keep-everything ⇒ byte-identical
baskets), so run 3 tests exactly one treatment. **Model stays `claude-haiku-4-5` + `web_search_20250305`
and is now a pre-registered parameter — do NOT change it mid-run** (a model swap is a second
treatment; that would be run 4, re-registered). **Third prereg amendment** recorded before run 3
accrued a mark, adding: if the AI drops no names, the result is *"no verdicts issued"*, not *"the AI
didn't help"*. Verdict sheet archived daily to `reports/ai_verdicts.md`. 429 tests.

**PR-71 (branch `track-record`): the system can now be caught failing — on the user's own money.**
The Live tab reported equity, cash, holdings and realized tax: four *states*, not one *result*. It
could not say whether any of it was working. The backtest cannot answer that either — it measures a
strategy over 2013–2026, never *your* holdings on *your* dates. New `live/track_record.py` closes
that: your Zerodha tradebook becomes dated cash flows, the **same rupees on the same days** are
replayed into NIFTYBEES, and both legs are marked today and reported side by side with an **XIRR**
(money-weighted — a ₹50k SIP is not present for the whole window, so a start-to-end percentage is
not a rate). Rendered in a Live-tab expander, read-only, fail-soft.

**The honesty properties are the tests, not the arithmetic:** the panel must be able to say
**"behind by ₹X"** (asserted — a surface that can only report good news is marketing); under
`MIN_MONTHS_FOR_A_VERDICT = 12` it says the gap is *entry timing, not selection* and refuses a
verdict (the same bar that voided forward run 1); the index leg is priced **at or before** each trade
so no future price enters; a sell larger than the index sleeve floors units at zero and **flags**
rather than silently going short. Both columns carry a basis and a window via PR-4's `ReturnMeasure`.
Charges (~0.1%) are in neither column and the panel says so. **481 tests, 0 skipped.**

**⚠️ The backtest is NOT wired into any cron, deliberately.** Re-running it monthly adds one month to
thirteen years and answers the same question. What runs forward is this panel plus the existing daily
cron. **The 16.4% backtest figure is not a forecast** — plan at the index's ~11–12% and treat the
excess as unproven upside until this panel has a year of real data.

**Rule (a) is intact and stays intact: the GO book (`data/paper/book.json`), the validated engine and
the 18.2% headline are untouched by every item in the plan.**

## 📜 HISTORY — the July 2026 handoff (SUPERSEDED — see the top of this file)

> ⚠️ **Written 2026-07-21, when the user was going hands-off for ~6 months on fake money. That is no
> longer the situation: real money went in on 2026-08-27 and he is operating the system weekly.** The
> mechanics below (cron, secrets, Kite reality, cost facts) are still accurate and useful. The framing
> — "hands-off", "silence means healthy", "the GO ping" — is not. Do not take instructions from it.

**The system is live, autonomous, and mid-test. The user is hands-off for ~6 months** (Telegram pings
him; silence = healthy). If you are a fresh session, this block is your orientation — read it, then
the ENDGAME CONTRACT below, then skim the dated blocks only as needed.

**➕ TAX ENGINE COMPLETED TO REAL-LIFE ACCURACY (2026-07-27, advisor/reconcile layer only — rule (a)
intact, engine + 18.3% headline provably unchanged; re-ran the canonical backtest to confirm).** The
advisor's quoted sell tax is now the real ITR figure: correct 20%/12.5% + ₹1.25L exemption + §70
intra-year set-off + **§74 8-AY loss carry-forward** (`net_capital_gains_tax` now threads brought-
forward STCL/LTCL chronologically, oldest-first, expiring past 8 AYs) + **4% Health & Education Cess**
(`TaxConfig.cess_rate`; effective 20.8%/13%) + **§112A grandfathering** (`grandfathered_cost_of_
acquisition`/`apply_grandfathering`, pre-1-Feb-2018 lots re-costed to 31-Jan-2018 FMV via an optional
`advise_sell(grandfather_fmv=…)` map; unpriced pre-2018 lots are flagged, kept on conservative actual
cost). **The frozen backtest engine (`compute_sell`) stays cess-free / actual-cost — never touched.**
Also: a **LTCG-safe** column (safe minimal holding date per line) in the paper-report + Streamlit
Paper/Live holdings tables (`dashboard.ltcg_safe_sell_note`). **Deliberately NOT modelled** (need the
user's total income / a different tax head — out of a CG advisor's scope): surcharge, dividend-income
tax, F&O business-income (the hedge is fake-money). **User confirmed he holds nothing pre-2018 →
grandfathering is inert for his live book (pure passthrough); no 31-Jan-2018 FMV table needed.** Gates
green (286 tests). This closes every code-fixable tax item — nothing tax-shaped remains on the path.

**🔧 OPS/UX HARDENING (2026-07-28, all merged; gates green — 294 tests).** Three reliability fixes so
the live surfaces don't silently lose the user's data/money:
1. **Persistent cumulative tradebook.** The Live-tab tradebook upload was session-only (re-upload the
   whole history on every restart). Now it keeps ONE master, de-duplicated by Zerodha `trade_id`
   (composite fallback), in a **private gist** (`live/gist_store.py` + `live/tradebook_store.py`): the
   user just **stacks new exports**. Robust across reboots via **auto-discovery** — `find_gist_id`
   locates the gist by filename so the **token alone** re-loads the master (pinning `TRADEBOOK_GIST_ID`
   is an optional fast-path); a "Download combined tradebook" button is the always-available fallback.
   Own master CSV round-trips without re-`canonical_ticker` (no `.NS.NS`). **Real trades never touch the
   public repo.** Needs a `GIST_TOKEN` (gist scope) — falls back to `GITHUB_TOKEN`.
2. **Add-money made fail-loud + a visible pending queue.** Root cause of a lost ₹50k top-up: with no
   working `GITHUB_TOKEN` (contents:write) the Add-money button fell back to a soft warning and the
   deposit never reached `pending_injections.json`, so the System book stayed at ₹350k. Now: a red
   up-front banner when the token is missing, a hard "❌ NOT saved" on failure, and a **pending-queue
   panel** (`_fetch_pending_injections`, authoritative repo read) so a top-up is *seen* landing and
   clearing. (User has since set a working token — an Add-money queue commit is on `main`.)
3. **Auto ₹50k monthly top-up REMOVED (per user).** Funding is **manual only** — he adds money via the
   dashboard when he opens it; it still credits all three books equally, so the A/B stays fair. The
   `autodeposit` toggle/CLI + `MONTHLY_DEPOSIT` are gone; the frozen A/B/C `scheduled_injection` prereg
   record is left untouched (not on the live path).

**Secrets checklist (Streamlit):** `GITHUB_TOKEN` = contents:write on the repo (Add-money + pending) ·
`GIST_TOKEN` = gist scope (tradebook; or one token with **both** repo-contents + gist, set as
`GITHUB_TOKEN`, and drop `GIST_TOKEN`) · `KITE_*` + `APP_PASSWORD` (Live tab) · `ANTHROPIC_API_KEY` +
`TELEGRAM_*` on repo Actions. **Docs finalized this session** — README §4/§6/§7/§9 + this block.

**Read order for a new session:** this block → 🏁 THE ENDGAME CONTRACT → the 2026-07-11/12 blocks
(unification · System book) → README.md (the front door). The research repo
(`../Q_Alpha_Research`) is the **archive** (hedge forward run + published negatives incl. QUBO ×2);
its CLAUDE.md explains itself.

**What runs without anyone (weekday cron `paper.yml`, 12:23 UTC, verified green):** prices refresh →
₹2L GO book marked (criterion-6 evidence) → Telegram opportunity scan → AI brief (Haiku+web-search →
`reports/ai_brief.md`, emits the `SIGNAL:` line) → System book (`scripts/autopilot.py daily`: apply
queued Add-money (manual only — the auto monthly ₹50k top-up was REMOVED 2026-07-28 per the user;
he adds money himself when he opens the app) → AI-paced deploys → daily §4.6 gate evaluation →
hedge overlay measured on System AND GO books) → everything committed. State lives in
`data/autopilot/*` + `data/paper/{book,adaptive_book,shadow_book}.json`; reports in `reports/*.md`.

**Where the run stood at handoff (2026-07-21, 8 marks — treat as stale, re-pull):** System +0.37% ·
Shadow +0.25% · Baseline +0.02% (all on ₹3.5L contributed; AI ahead by noise-level ₹431 — DO NOT
over-claim). GO book ₹~2.01L, 25+/63 days, NOT YET (Δ vs Nifty ≈ −2%, red line −3% — the number to
watch). Hedge off (gauge ~0.5 < τ0.7). First deploy resolutions land **~2026-08-07** (hit-rate table
starts filling); **the user funds the books manually via the dashboard** (no auto monthly refill —
removed 2026-07-28).

**Locked disciplines a new session must NOT undo:**
1. **Rule (a):** the validated 18.2% backtest headline + engine are frozen; never tune to a GO; the
   LLM never computes a number for the validated path.
2. **The clean ₹2L GO book (`data/paper/book.json`) is the control** — never trade it off-schedule,
   never add the hedge TO it (measure-only), never restart its clock.
3. **AI is informational-only on real-money surfaces** (PR #45, user-enforced): the AI-paced sizing
   option was REMOVED from the Zerodha Add-money advisor; it graduates back ONLY on a positive
   System-vs-Shadow verdict per the contract. Do not re-add it early.
4. **Real money never auto-trades; the user places every order.** Outlives the GO.
5. **Pre-registration before any new experiment; negatives get published.**

**User context (matters for advice):** he may build a REAL manual book during the test (possibly
₹10L+, incl. IPOs). That's fine and by design — the advisor is source-agnostic (works on any
holdings); remind him to **upload the Zerodha Console tradebook CSV** for exact dated-lot tax (raw
holdings are undated → conservative STCG assumption; IPO allotments are off-market credits and may
stay undated). At GO, a pre-existing manual book is **converged, never liquidated**: new-money
routing to target + §4.6-gated consolidation + least-tax sells. His picks' returns are his own — the
18.2% claim applies to the model's strategy only.

**Operational facts (don't re-debug):** AI-brief input tokens swing ~20k–50k/day with the news cycle
(web-search results bill as input; server-side loop re-reads context) — ~₹4–8/day is NORMAL, only
investigate >80k. Secrets: `ANTHROPIC_API_KEY` + `TELEGRAM_*` on repo Actions; `GITHUB_TOKEN`
(classic, repo scope, no expiry) + `KITE_*` + `APP_PASSWORD` in Streamlit secrets — GitHub secrets
are write-only, never try to read them. Streamlit app may nap after ~a week idle (viewer only — data
accrues in git regardless; wake with a click). Kite login is daily-manual and only needed for the
Live tab. Merging to `main` auto-deploys Streamlit; always branch + PR (the harness blocks
self-merges — the user clicks merge).

**When the GO ping comes:** verdict = ALL FOUR pillars of the ENDGAME CONTRACT below, then the
integration step it defines. If any pillar fails, report honestly; never integrate around a red.

## 📜 HISTORY — unification (2026-07-11)

> ⚠️ Not current state; kept for *why* the system is one product with three engines.

**The live system is now ONE system in this product repo.** The user's audit verdict: the pieces felt
fragmented (two repos, an invisible wallet, a fetched "Research" tab). Decision (his call): **unify the
live system into the product, break the *organizational* separation, keep the *validation* one.** Two
iron rules were untangled — **(a) the validated 18.2% headline stays provably unchanged; never tune to
manufacture a GO → SACRED, kept.** **(b) two repos / product-never-imports-research → relaxed.**

**Built on branch `unify-live-system` (not yet merged):**
- **Auto-pilot moved in, native.** `src/qalpha/live/autopilot.py` (the fake-money A/B/C core — was the
  research forward study) + `scripts/autopilot.py` (daily runner: fund wallet → deploy via
  `advise_deploy_into_weakness` **imported directly**, A no-AI · B AI-tilted · C buy-and-hold → resolve
  vs Nifty → write `data/autopilot/*` + `reports/autopilot_dashboard.md`). Idempotent per day. Pre-reg
  at `docs/PREREGISTRATION_autopilot.md`.
- **AI brief moved in, quarantined.** `src/qalpha/live/ai_brief.py` + `scripts/ai_brief.py` (Haiku +
  web-search, context-only). It is the **optional `ai` extra** — the engine/factors/backtest/CI never
  import it; its only machine consumer is Book B, which acts on the `SIGNAL` line via a fixed rule. So
  the product stays deterministic where it must be; **rule (a) intact** (AI never computes a number for
  the validated engine).
- **Dashboard = one screen, three tabs:** 📄 Paper book · 🔴 Live (Zerodha) · **🤖 Auto-pilot** (native;
  replaced the fetched Research tab). The Auto-pilot tab has a **wallet with an Add-money button** + a
  **toggleable ₹50k monthly auto-top-up** (the user's confusion — "where do I add money" — is fixed;
  every deposit hits all three books equally so the A/B/C verdict stays fair), the "did it work / did
  the AI help" scoreboard, and today's AI brief.
- **Cron:** `paper.yml` now runs the AI brief + auto-pilot (fail-soft) after the daily mark and commits
  their data. **⚠️ ACTION NEEDED (user):** add **`ANTHROPIC_API_KEY`** to THIS repo's Actions secrets
  (only the research repo had it) — else the brief silently skips and Book B just runs neutral.
- **Research is now the archive:** the hedge forward run + the finished dead-ends (quantum/LPPLS/HMM).
  Its cron no longer runs the AI brief or the study (they live here now). The product no longer fetches
  research over HTTP. Gates green (product 234 tests; ruff/format/mypy). Nothing here trades — fake
  money only; real Zerodha stays 100% manual.

**Auto-pilot follow-ups (2026-07-11, branch `autopilot-trades-rebalance`):** three user-requested
additions, all fake-money, rule (a) intact.
- **Add-money persistence.** The dashboard (Streamlit Cloud) and the cron (GitHub Actions) are
  different machines, so the button used to write only the session. Now it queues the deposit to the
  repo's `data/autopilot/pending_injections.json` via the **GitHub Contents API**; the runner
  (`autopilot.apply_pending`) applies + clears it, staying the sole writer of `books.json`. **⚠️ needs a
  `GITHUB_TOKEN`** (fine-grained, contents:write on Q_Alpha) in the app's **Streamlit secrets** (+
  optional `GITHUB_REPO`, defaults to `aarsh-adhvaryu/Q_Alpha`). No token → the button falls back to a
  session-only add with a loud warning.
- **Show the trades.** The Auto-pilot tab now has a per-book holdings + last-buy panel.
- **Smart-rebalance experiment book.** A 4th fake book (`data/paper/adaptive_book.json`, ₹2L,
  `StrategyParams.rebalance_freq="ADAPTIVE"`): runs the validated core strategy but **evaluates every
  run and rebalances only when the §4.6 tax-benefit gate clears** — self-timed, not annual, not
  forced-frequent (the user's ask: "a smart one that doesn't lose money"). Run by the auto-pilot runner
  (`_run_adaptive_book`, fail-soft), tracked in `adaptive_track.csv`, shown in a "🏁 All engines,
  side-by-side" table (validated ₹2L annual core + smart-rebalance + A/B/C wallet books, each vs Nifty).
  **NEVER the validated GO book** (`data/paper/book.json`) — a separate book, headline untouched.

**Unified advisor + hedge (2026-07-11, branch `unified-advisor-hedge`):** the "one coherent system" pass.
- **Add-money = math + AI.** The Add-money advisor (Live + Paper) now surfaces the AI's market read and
  applies the same `signal_tilt` Book B uses to suggest *how much* of the idle cash to deploy now vs
  hold as dry powder (a tranche by market-weakness × AI lean). **Names + tax stay 100% deterministic;
  the AI never picks a stock or computes a number.** "Deploy all now (time-in-market)" is the honest
  default; the AI-paced option is offered with a market-timing caveat. Idle cash = demat cash (injected
  or freed by a sell). The auto-pilot's Book B forward-tests whether acting on the AI actually helps.
- **Hedge promoted from research → `src/qalpha/live/hedge.py`** (`stress_gauge` [drawdown→[0,1], the
  product-native gauge; the cross-asset fragility gauge stays the research upgrade path] + `hedge_active`
  + `apply_futures_hedge`, the validated tax-free short-futures overlay; `tests/test_hedge.py` incl.
  no-look-ahead). Wired into the auto-pilot as a **downside-protection overlay on the smart-rebalance
  book** (`_run_hedge_overlay`, stateless/recomputed, τ≥0.7 h=0.5) → shows hedged-vs-unhedged return +
  **drawdown** in the Auto-pilot dashboard. **Fake money — never a real F&O trade.** *Why this and not
  "sell defensively":* selling to dodge a drawdown was tested (research HMM overlay) and LOST to the
  capital-gains tax; the hedge keeps the shares (₹0 CG tax) and cuts the crash. Coincident gauge → in a
  calm window it stays off and curves match; its value shows only in a real stress event.
- **Plots:** an "all engines" return-% line chart in the Auto-pilot tab (A/B/C + smart-rebalance).
- Gates green (241 tests). Rule (a) intact throughout (AI never the calculator; validated headline +
  ₹2L GO book untouched; the hedge/auto-pilot are fake-money experiments).

**THE SYSTEM BOOK (2026-07-12, branch `system-book`) — the closed trust loop.** The user's demand:
*"I can only trust the advisor if it takes the decision AND acts on it — no paperbook, no autopilot
separate, all in one; the optimizer must handle the real world, not just a scheduled time."* Built:
- **ONE fake-money book runs the entire system on its own advice** (`scripts/autopilot.py`, fully
  rewritten): cash in (monthly ₹50k + Add-money queue) → **AI-paced deploys into weakness** (the exact
  Add-money advice, executed on itself; `signal_tilt` sizes it) → **§4.6 tax-gated adaptive rebalance
  evaluated EVERY day** (trades only when worth the tax — it may later consolidate opportunistic buys
  into the core target, again only when worth the tax) → **hedge overlay readout** (flow-adjusted).
  The System book = the former smart-rebalance book upgraded in place (`data/paper/adaptive_book.json`,
  its ₹2L history carries over).
- **Two comparators, identical cash flows:** `data/paper/shadow_book.json` (cloned at first run; AI
  OFF → System−Shadow = the AI's added value) and `data/autopilot/baseline_book.json` (NIFTYBEES
  buy-and-hold → System−Baseline = the system's value over doing nothing). The A/B/C wallet books are
  **FROZEN** (prereg carries a disclosed amendment note; same questions, now asked of the full system).
- **Dashboard = TWO tabs:** 🧠 **The system** (wallet + Add-money, scoreboard from
  `reports/autopilot_dashboard.md`, race chart from `data/autopilot/system_track.csv`, per-book
  holdings, AI brief expander, and the **validated ₹2L core-GO view unchanged in an expander
  underneath**) · 🔴 **Live (Zerodha)** (unchanged; the human places every order).
- **Load-bearing valuation detail:** the system book holds core + watchlist names, so it's valued on a
  **merged panel** (`_merge_panels`, everything ffilled — causal) — an index/session mismatch between
  panels must never silently drop a holding's mark (found in smoke: a stale core panel cratered equity
  −88% until the ffill fix). Money-weighted returns: wallet→book deploys are logged as flows
  (`data/autopilot/system_flows.json`) and stripped from the curve before hedge/return math.
- The clean ₹2L GO book (`data/paper/book.json`) is **untouched** — still the criterion-6 evidence.
  Rule (a) intact: AI paces size only; the engine computes everything. Gates green;
  cmd_daily smoke-tested end-to-end locally (deploys executed, gate refused a same-day rebalance with
  its reason logged, idempotent re-run). Follow-up (#42): the hedge overlay is also **measured
  read-only on the GO book's committed curve** — protection evidence accrues on both books without
  touching the criterion-6 gate.

## 🏁 THE ENDGAME CONTRACT (locked with the user 2026-07-12 — read before any "GO" work)

**The user is walking away for ~6 months; the system runs itself** (weekday cron: mark GO book → AI
brief → System book deploy/gate/hedge → commit; funding is manual Add-money (no auto monthly
top-up — removed 2026-07-28); Telegram pings him on
weakness escalation, GO flip, guard/pipeline failure — silence means healthy). His words: *"if the
system does go green, it should be ALL — the AI, the paperbook, the hedge, all working — then after
that we integrate to the final usable system."*

**"Green" therefore means ALL FOUR, not just criterion-6:**
1. **Core GO** — the validated ₹2L book clears the deterministic §14 scorecard (track length,
   volatility event withstood, vs benchmark, drawdown behaviour, data integrity).
2. **System > Baseline** — the System book beats the same-cash-flow NIFTYBEES baseline over the run
   (the whole system adds value over doing nothing).
3. **AI verdict** — System vs Shadow answers "did the AI help?" **Either answer is a valid result**:
   keep the AI nudge in the final system only if it added value net; drop it without ceremony if it
   didn't.
4. **Hedge witnessed** — ≥1 real stress event where the measured overlay cut the drawdown on both
   books (the gauge firing + protection visible, not just theory).

**Then — and only then — the integration step:** promote the proven pieces into the final usable
system for his REAL account: the advisor (Sell/Raise = math, Add-money = math + whichever AI verdict
survived) sizing against his actual demat cash, the hedge as a dashboard-prompted **manual** F&O
decision, and auto-invest remaining fake-only unless he explicitly decides otherwise then. **Real
money never auto-trades; he places every order — that rule outlives the GO.** If any pillar fails
(NO-GO, System < Baseline, hedge never tested), report it honestly and do NOT integrate around it.

## 📜 HISTORY — the Ops Layer (2026-07-11)

**Everything below this block is the older working log; this block is what's true now.** The
**"Daily-Driver Ops Layer"** in [PLAN_OPS_LAYER.md](PLAN_OPS_LAYER.md) is **built and its product half
is merged + live.** Four gates green; the paper cron pushes daily.

**MERGED to `main` (product side of the Ops Layer):**
- **PR-1 (#33) — Telegram notification spine + daily opportunity scan.** `src/qalpha/live/notify.py`
  (stdlib `urllib` Telegram sender, **fail-soft**: missing config/error → `False`, never raises),
  `src/qalpha/live/scan.py` (pure edge-triggered `evaluate` — weakness escalation w/ tranche policy,
  easing w/ 3-scan hysteresis, rebalance-due, GO flip, guard-failure, Monday digest; `AlertState`
  JSON), `scripts/scan_alerts.py` (runs in the paper cron after the daily mark; `--test` /
  `--force-digest` / `--pipeline-failed`). `paper.yml` wired + `if: failure()` alert +
  `data/paper/alert_state.json` committed. Verified live to the user's phone.
- **PR-2 (#34) — capital-aware auto buy-brief + two real bug fixes.** `DeployPolicyConfig` in
  `config.py` (idle_cash_floor ₹5000, tranches 50%/100%, max_names 15); `live/dashboard.py`
  `live_pm_brief_markdown` + `watchlist_is_stale`; `dashboard_app.py` auto PM brief on the Live tab
  (zero typing, gated by `assess_advice_inputs`). **Bug fixes:** the live advisor was fed the watchlist
  `adj_close.mean()` as the "index" instead of the real Nifty TRI (now threaded through); `_watchlist`
  was cached forever → added 6h ttl + stale re-download. Namespaced advisor widget keys (paper/live).
- **Dashboard plain-English clarity (#35).** `live/dashboard.py` `plain_summary_markdown` /
  `performance_read` (ahead/behind/tracking vs Nifty) / `glossary_markdown`; wired into
  `dashboard_app.py` (In-plain-English banner atop the Paper tab + good/bad caption under the metrics +
  a "Jargon" expander). **Presentation only — engine/headline untouched. Merging it auto-deployed to
  the user's Streamlit Cloud dashboard (live on his phone).**

**Telegram bot @qalphastocks_bot** (chat_id 8936117519); repo Actions secrets `TELEGRAM_BOT_TOKEN` /
`TELEGRAM_CHAT_ID` set. The weekday paper cron now marks the book AND pushes edge-triggered alerts.

**The research repo carries the rest of the Ops Layer + new work (see its CLAUDE.md):** PR-3 hedge-flip
alert + PR-4 daily AI market brief (Haiku 4.5, context-only) merged & live on the hedge cron; a
whole-system integration layer (`system_check` + `mission_control_app`) + a Streamlit deploy fix; and a
**pre-registered A/B/C "did it work?" forward study** (WIP on branch `forward-study`). **The product
never imports research** — integration is via committed data (the research mission-control *fetches*
this repo's public `reports/paper_dashboard.md`; it does not import). **This repo's clean ₹2L paper GO
run is deliberately UNTOUCHED by any of the ops/AI/study work** — so a real-money GO stays credible.

**Iron rules reaffirmed with the user (2026-07-11):** Zerodha = **execution + funding only**, he places
every real order; **real money NEVER auto-trades** (auto-invest is fake-money/paper only, to build
trust); the LLM is **context-only, never the calculator or the validator of the math**; keep the
validated 18.2% headline provably unchanged. §14 scorecard unchanged (crit-6 forward paper run + a
volatility event remain the calendar blockers).

## 📜 HISTORY — hardening + deployment (2026-06-19)

**⏭️ QUEUED NEXT BUILD (2026-07-08, planned + user-approved scope, NOT yet implemented):** the
**"Daily-Driver Ops Layer"** — full plan in [PLAN_OPS_LAYER.md](PLAN_OPS_LAYER.md) (execute it
PR-by-PR next session). Why: the user's audit verdict — everything analytical exists but the system
is 100% pull-based (zero outbound notification in either repo; idle cash shown but never acted on;
buy advisor needs typed amount + button; weakness/hedge/GO signals computed only when the dashboard
is opened). Four PRs, all in `live/`+`scripts/`+workflows (engine/headline provably untouched, never
auto-trades): **PR-1** Telegram spine + edge-triggered daily opportunity scan in the paper cron
(weakness escalation w/ tranche policy, rebalance due, GO flip, guard/pipeline failure + Monday
digest; hysteresis on de-escalation); **PR-2** capital-aware auto buy-brief on Live-tab login
(`fetch_available_cash` → `advise_deploy_into_weakness`, zero typing) + `DeployPolicyConfig`
(pre-committed tranches: 50% idle on elevated, 100% on deep) + two real bug fixes (live advisor fed
watchlist-mean instead of the real index @ dashboard_app.py:615; `_watchlist` cached forever →
stale); **PR-3** (research repo) hedge-flip Telegram alert; **PR-4** (research repo) daily AI market
brief — Opus 4.8 + web-search tool, min-token config (effort=low, max_tokens=1500, max 4 searches,
~₹4–8/day), **context-only/never a signal**, satellite-sleeve framing for discretionary ideas.
Deferred by user decision: private cash-snapshot repo (PR-5). User decisions locked 2026-07-08:
Telegram · events+Monday digest · dashboard-only cash sizing · AI brief daily on Opus 4.8. Both
crons verified alive (daily marks through 2026-07-07 on both repos' origin/main).

**For the full, interviewer-level overview read [README.md](README.md) — it now carries the complete
story (plain-language + the math + an explicit "biases & decisions" section).** This CLAUDE.md is the
detailed *working log* below; the README is the front door.

**Where we are:** Phase 0 (backtest validation) is **complete and defensible** — 18.2% CAGR / Sharpe
1.13, beats Nifty 50 TRI *and* 1/N net of cost+tax, in-sample + on the 2025–26 holdout + every rolling
3y window. The **live system is built and deployed** on the user's real Zerodha account via Streamlit
Cloud: deterministic tax-smart advisor (sell / raise-cash / deploy), §70 loss set-off, corporate
actions, live holdings + tradebook reconciliation (crit-4 reconciled to the paise), a notional paper
book that **auto-runs and self-certifies**, and four watch tabs (🎯 GO readiness · 🩺 position health ·
🛡 systemic risk · realtime ticks). **Both repos green** (qalpha 169 tests, research 28; ruff/format/
mypy/pytest all pass).

**§14 scorecard: `1✅ 2✅ 3✅ 4✅ 5🟡 6⏳ 7✅ 8✅ 9🟡 10✅`.** No unbuilt engineering on the critical
path. What remains is **calendar + real-world events**: crit-6 (the ~6-month forward paper run + ≥1
volatility event, unskippable) · crit-4/5 (reconcile one real multi-lot/loss sell + one real corporate
action — engines done & tested) · crit-9 (observe one *scheduled* cron firing; dispatch already proven
green). The system **never auto-trades** — it advises; the human places the order.

**Iron rules still hold:** no tuning to manufacture a GO · all four gates green before commit · money is
`Decimal` · no look-ahead · keep the validated headline provably unchanged (new tax features are wired
into the advisor/live layer, never the backtest engine). The research track lives in the separate
`Q_Alpha_Research` repo and the product **never imports from it**.

The dated working log below is the full history (every decision, fix, and dead-end) — skim it for *why*
something is the way it is; trust this block + the README for *what is true now*.

---

## What this is

Q-Alpha — a quantitative wealth-management system for Indian (NSE/BSE) equities. The full system
architecture is specified in [Q_alpha.md](Q_alpha.md) (v3.1). The codebase is built **phase by
phase**; the spec mandates that **Phase 0 (strategy validation by backtest) must beat baselines
after costs and taxes before any production infrastructure is built**.

**Current state: Phase 0 COMPLETE + live build well underway — all on `main`.** Beyond the validated
Phase-0 GO, the repo now has the live layer (Kite auth, replay harness), a running **paper-trading
book** (notional, started 2026-06-12) with a **dashboard + autonomous daily pipeline**. The
**research track (quantum QUBO/QAOA, + planned regime/bubble & agentic work) now lives in a separate
repo** — `github.com/aarsh-adhvaryu/Q_Alpha_Research` — which imports this engine as a dependency, so
this repo stays product-clean. See the "NEXT SESSION" block for the active plan (a
deterministic tax-smart advisor + a live Zerodha-wired dashboard). Phase-0 evidence:
`reports/PHASE0_VERDICT.md`. The original headline (6-factor, 24 survivors, vs Nifty *price*)
was stress-tested through two fairness fixes (point-in-time universe + TRI benchmark) and an
out-of-sample walk-forward; the edge survived once rebalancing slowed to low turnover. §14 gates
**1 ✅ (OOS) · 2 ✅ · 3 ✅**; criteria 4-10 are Phases 1-6 (infra/broker/paper-trading) — the
real-money GO is still months away. The 6-factor PIT run is data-blocked (fundamentals for ~75 names
incl. dead ones) but is *not* a GO-blocker. **⚠️ But the 2025-26 out-of-time HOLDOUT
(`scripts/holdout_2025.py`) is a YELLOW FLAG:** frozen config on genuinely unseen data was flat
(0.7% vs TRI 0.6%) and **trailed 1/N badly (7.1%) with worse drawdown** — the alpha did NOT
generalize. Root cause: the §4.6 tax gate **froze rebalancing after 2019** (only 5 rebalances ever),
so the in-sample 18.5% was largely stale 2013-19 winners riding the 2020-24 bull. Low power (17.5mo,
flat market) so not proof of failure, but not confirmation either. **Ossification fixed**
(`run_backtest(force_refresh=True)`: scheduled rebalance always executes, band-limited): un-froze the
book (5→13 rebalances), **neutral in-sample** (18.4 vs 18.5) and **fixed holdout drawdown −24→−13%**
— but holdout return still flat (1.1%) and still trails 1/N (7.1%). So ossification was a real flaw
(→ `force_refresh` should be the production default) but NOT the reason alpha was absent OOS.
**Then Track A SOLVED it (`scripts/exp_breadth.py`):** the literature's anchor-to-1/N shrinkage —
`weighting="shrink"` (½ min-var + ½ equal over the picks) — **beats 1/N in-sample (18.3 vs 17.7),
on the holdout (8.1 vs 7.1), AND across rolling 3y holds** (dominates every percentile, worst-3y
+3.6% vs 1/N −8.7%, ≥1/N in 67%). First optimiser change to clear the iron-rule bar *and* survive
the out-of-time holdout. So the edge is BOTH the tax engine AND a modest robust 1/N-anchored return
tilt — not pure index-tracking after all. No DB / broker / dashboard yet. CI green.

## 📜 HISTORY — the June 2026 hardening/autonomy sprints

> ⚠️ Not a queued build. The work described here shipped long ago; kept for the reasoning.

**✅ HARDENING SPRINT (2026-06-19) — every *code-fixable* GO blocker closed; what remains is calendar
time + a couple of real trades, not engineering.** The user's brief: "solve every problem so the only
thing left is waiting 3–6 months." Five things shipped (both repos' four gates green — qalpha 144
tests, research 23):
- **Realtime tick-streaming — Stage-2 SOLVED, session-scoped** (`src/qalpha/live/ticker.py`,
  `tests/test_ticker.py`). *Why:* Stage-2 looked impossible on Streamlit Cloud because a 24/7 socket
  dies on idle-sleep — but realtime is only needed **while the user is watching**. So the `KiteTicker`
  socket's lifetime is tied to the **browser session** (parked in `st.session_state`): on login a
  background thread opens the socket, subscribes to the held instruments, and pushes ticks into a
  thread-safe `TickStore` the fragment reads; when the session ends the thread stops. Wired into the
  live view as a **best-effort overlay** — any failure (no creds/socket) silently falls back to the
  30s `ltp()` polling, so it can never break the working page. `KiteTicker` is lazy-imported so the
  pure `TickStore`/`resolve_tokens` are unit-tested. **Cannot be verified in the agent sandbox (no
  socket/creds) → user verifies on the box** (established pattern). `🔴 streaming` vs `⏱ polling` badge.
- **Hedge promoted to product as a READ-ONLY watch tab** ("🛡 Systemic risk" sidebar view;
  `live/dashboard.py:systemic_risk_markdown` + tests). *Why:* the user reversed the earlier "keep the
  hedge in research" decision and asked for "just a tab where I watch, no action, like the paper
  money." Shows the systemic-risk level (🟢/🟠/🔴 from Nifty drawdown vs 1y high) and, when elevated,
  notes the research-proven tax-free futures hedge "would suggest *considering* a hedge" — **purely
  informational, never trades, no derivatives placed.** *How (iron rule intact):* uses the
  **product-side** `deploy.py:market_weakness` signal, **does NOT import research** (`The product never
  imports from here`). The richer cross-asset fragility gauge stays in research as the upgrade path.
- **Fail-loud system-safety guards** (`live/safety.py`, `tests/test_safety.py`). *Why:* the user asked
  to "remove all problems that can cause a loss from a system failure." Key insight: **the system never
  auto-trades**, so a system failure can only lose money by **showing wrong data the user acts on**.
  So the fix is fail-loud guards — `price_freshness_guard` (stale feed), `price_completeness_guard`
  (a held name with no/zero quote that would be silently dropped from the tax/cash math),
  `broker_session_guard` (dead/expired token) → `assess_advice_inputs`/`SafetyReport`. The dashboard
  advisor is now **gated** (`dashboard_app.py:_advisor_with_safety`): bad inputs **withhold the
  recommendation behind a banner** instead of computing on them.
- **STCG/LTCG loss set-off** (`accounting/capital_gains.py:net_capital_gains_tax`/`net_tax_total`,
  tests in `test_capital_gains.py`) — the real **criterion-4 correctness gap**. Full §70 rules: STCL
  sets off against STCG first (20%) then LTCG (12.5%); LTCL against LTCG only; ₹1.25L exemption on the
  net LTCG; carry-forward reported (8-AY carry not applied — Phase-0 deferral). *Why additive:* it is a
  **pure FY-aggregation function wired ONLY into the advisor** (`advise_sell` now nets loss lots
  against gain lots and shows the `setoff_saving`) **+ reconciliation — deliberately NOT into
  `compute_sell`/the backtest engine**, so the validated 18.2% headline is **provably unchanged**.
  Residual: cross-event FY netting + carry-forward still deferred.
- **hedge.py open-episode tax bug FIXED** (research repo — see its CLAUDE.md). Optimistic edge case,
  no published number affected, fixed for correctness + test.

**✅ AUTONOMY SPRINT (2026-06-19, branch `hardening-sprint` then continued) — the paper run now executes
itself and self-certifies.** User's brief: "I can't code every time / no AI / all from the dashboard /
if it works in ~5 months it should provide a GO."
- **Paper rebalance-cadence gate + auto-apply — a real bug fixed** (`live/paper.py`,
  `scripts/paper.py`, `tests/test_paper.py`). The live path had **no rebalance schedule**:
  `decide_rebalance` returns `execute=True` every call when `force_refresh` is on, and the daily cron
  called it daily → the dashboard proposed a full ~40% rebalance EVERY day ("drift 41%" nag), and
  auto-applying it would have churned the book daily and destroyed the validated low-turnover tax edge.
  (The backtest avoids this only because its loop calls `decide_rebalance` *solely* on annual
  `_rebalance_dates`.) Fix: `PaperBook.scheduled_rebalance_due(as_of)` = the online mirror of
  `_rebalance_dates` — a rebalance is due only when `as_of` enters a new annual period; `plan()` HOLDS
  between scheduled dates. `paper.py daily` now **auto-applies** a scheduled, actionable plan to the
  NOTIONAL book (zero real money; the gate guarantees ~once a year, never daily) so criterion-6 tests
  the live strategy, not a frozen June basket. **Engine untouched → headline unchanged.**
- **Deterministic GO scorecard + "🎯 GO readiness" dashboard tab** (`live/go_scorecard.py`,
  `tests/test_go_scorecard.py`, wired into `live/dashboard.py:go_readiness_markdown` + `dashboard_app`).
  A real multi-criterion verdict (NOT a countdown), pure arithmetic, **no LLM/no judgement**: flips to
  GO the moment the evidence clears (earlier than 6mo if it does), NO-GO if the strategy misbehaves.
  Criteria, all must be 🟢: **track-length power floor** (~3mo, a floor not a date) · **volatility-event
  withstood** (HARD gate — must survive a ≥10% Nifty pullback in-window; a calm curve can't earn a GO) ·
  **forward vs benchmark net** (red = NO-GO) · **drawdown behaviour** within the backtest envelope ·
  **data integrity** (dense marks). On the real book today: **NOT YET** (4/63 days, no vol event yet).

**What's left after this sprint (NOT code — this is the honest GO picture):** (a) **calendar,
irreducible** — criterion 6, the ~6-month forward paper run surviving ≥1 volatility event; (b) **one
real-world event each (days, user-triggered)** — criterion 4 final hardening needs *one* real
multi-lot/loss/LTCG sell + its Tax P&L to reconcile against the new set-off code; criterion 9 needs
*one* observed scheduled-cron firing (dispatch ≠ cron); (c) **still open** — criterion 5 corporate
actions (not started); (d) **data-blocked, off the critical path** — fundamentals/value factor + PIT
Nifty-100/200 membership. **Nothing here is committed yet** (offer the user a branch per repo).

**✅ DEPLOYED & LIVE (2026-06-18) — the dashboard runs on Streamlit Community Cloud, on the user's REAL
Zerodha account, from his phone.** This is the headline state. AWS was abandoned mid-attempt (EC2
security-group / SSH / IAM / status-checks = a beginner wall; `deploy/DEPLOY_AWS_BEGINNER.md` +
`DEPLOY.md` Docker path kept as portable fallbacks, `DEPLOY_LIGHTNING.md` too). **Streamlit Cloud won**
(deploy straight from the public GitHub repo, no server/SSH/Docker, free, `…streamlit.app` URL,
auto-redeploys on every `main` push so the daily paper cron keeps it fresh): `deploy/DEPLOY_STREAMLIT.md`,
root `requirements.txt` (`-e .` + streamlit). The user funded the account; the **Live Zerodha view shows
his real holding (INFY ×5)** with live `ltp()`.
- **What the deployed dashboard does (all from one screen, PRs #17–#22):** password gate (`APP_PASSWORD`);
  paper-run **freshness panel** (`live/dashboard.py:paper_freshness`); **in-app Kite credentials form**
  (`_ensure_kite_credentials` — enter api_key/secret in the UI, no `.env`) + **one-tap login**
  (`request_token` captured from Kite's redirect via `st.query_params`); **auto-refresh** (`st.fragment
  run_every=30`); **self-bootstraps** the gitignored price panels on a fresh host (`_ensure_data` →
  `paper.py daily` for prices **and** benchmark; `_watchlist()` lazily downloads the Nifty-100 panel);
  Streamlit-secrets→env **bridge** (`_bridge_secrets`). Advisor tabs: **Sell** (exact tax) · **Raise
  cash** (least-tax order) · **Add money** = the **buy side** — wired to `advise_deploy_into_weakness`
  (Nifty-100, diversified, cheapness-tilted, **₹0-tax buys**) with a **"spread across N stocks" slider**
  (`max_names`, default 15) so the user dials concentration↔diversification (he flagged 43×1-share was
  over-diversified). Tradebook-CSV upload → exact dated tax. **Only the order placement stays in Kite
  (by design).**
- **Honest gaps surfaced live (worth knowing next session):** (1) the tax advisor is *trivial* on a
  1-tiny-holding-at-a-loss account — it earns its keep with a real multi-name book; (2) "cheap" = a
  **technical** pullback proxy, not fundamental P/E (data-blocked); (3) the **deploy advisor on the live
  account** uses the watchlist panel, not the model funnel target. **Kite reality (locked):** daily
  one-tap login; **no** compliant unattended token (auto-TOTP declined). **Streamlit gotcha seen:** after
  a code merge the app can hot-reload the page but keep an **old imported module** in memory → spurious
  `TypeError` → fix is **Manage app → Reboot** (forces a clean re-import).
- **✅ SUPERSEDED (2026-06-19) — Stage-2 true tick-streaming BUILT, session-scoped** (`live/ticker.py`).
  The old blocker ("Streamlit Cloud sleeps → kills a 24/7 socket") was dissolved by tying the
  `KiteTicker` socket to the **browser session** (lives only while the tab is open — exactly when
  realtime is needed), not to a 24/7 server. No paid always-on host required. **User verifies the live
  socket on the box.** Also now done: the research fragility gauge promoted as a **read-only "🛡 Systemic
  risk" advisory tab** (product-side signal, no research import). Still deferred: fundamentals/value factor.

**Next session = brainstorming, not a queued build.** Everything below is current. **All PRs are
merged** — the earlier "#10 then #11 awaiting manual merge" note is resolved: #10 `cleanups` merged,
#11 `tradebook-upload` re-landed as **#12** (merged), plus #13/#14/#15. Nothing is pending.

**✅ CRITERION 4 RECONCILED (2026-06-18) — the FIFO engine matches the real Zerodha Tax P&L to the
paise.** The user made a **real SELL** (HDFCBANK 5 @ ₹790.50 on 17 Jun, bought on BSE / sold on NSE),
exported the Console **Tax P&L** (`data/taxpnl-…xlsx`) + **Tradebook** (`data/tradebook-…csv`), and
the reconciliation now runs end-to-end: new **`src/qalpha/live/taxpnl.py`** (`parse_taxpnl` +
`reconcile_gross`), **`scripts/reconcile_taxpnl.py`** → `reports/crit4_reconciliation.md`, tests in
`tests/test_taxpnl.py`; `ReplayResult` gained `realized_gains`. **Gross realized P&L (zero-cost replay)
== Zerodha STCG ₹25.25, Δ ₹0.00** — proves FIFO lot-matching + STCG/LTCG classification + the BSE-buy/
NSE-sell ISIN merge are correct. Our **net** taxable gain sits below gross by our modelled deductible
transfer charges (DP charge dominant, ₹14.36 ≈ Zerodha's ₹15.34 "Other Credits & Debits"; STT
correctly excluded) → STCG tax ₹2.18. Caveat: a tiny, single-sell, all-STCG case — it validates the
*plumbing* exactly; a multi-lot / LTCG / loss-set-off case will exercise more (LTCG loss set-off still
unimplemented — fix before a sell that triggers it). **§14 criterion 4 → ✅.**

**On `main` (9 PRs merged, 2026-06-13):** Phase 0 (validated GO) + a **live layer** (`src/qalpha/live/`:
Kite auth, replay harness, shared `decide_rebalance`) + a **paper-trading runner** (`scripts/paper.py`,
notional ₹2L book started 2026-06-12, 5 holdings) + a **dashboard + autonomous daily GitHub Actions
pipeline** (`paper.yml`) + the **deterministic tax-smart advisor** + a **live Streamlit dashboard**.
(The quantum research track was moved to the separate `Q_Alpha_Research` repo.) Four gates green.

**🏁 FINALIZATION (2026-06-18) — Nifty-100 deploy-in-weakness, the manual-investor solution.** The
user's real need: diversify + find better entries; Nifty-50 large-caps are rarely cheap outside a
crash, so the *opportunity set* must widen to Nifty 100. Built (branch `nifty100-advisor-deploy`):
**`scripts/build_nifty100_watchlist.py` → `data/universes/nifty100_watchlist.csv`** (96 current names
+ sectors — a *forward-looking* watchlist, so survivorship is irrelevant: it lists what's investable
*today*, not a backtest universe); **`src/qalpha/live/deploy.py`** (tested) — three deterministic
price-based layers on top of the validated `advise_deploy` (₹0-tax greedy buys): (1) `market_weakness`
(index drawdown from 1y high → normal/elevated/deep "when to deploy more" advisory; a self-contained
signal — the richer research **fragility gauge** is the upgrade path), (2) `cheapness_scores` (pullback
below each name's 1y high — a **technical** out-of-favour proxy, *honestly NOT* fundamental P/E, which
stays data-blocked), (3) `deploy_target` (diversified equal-weight + sector-capped water-filling, tilted
to cheaper names) → `advise_deploy_into_weakness`. CLI: **`advisor.py deploy-weakness AMOUNT [--tilt]`**.
`tests/test_deploy.py`. **This is the tax-free "buy cheap, diversify" lever** — new money only, ₹0
capital-gains tax. **Honest framing locked in:** the *validated backtested strategy* default stays
Nifty 50 (no proven alpha from breadth — see the research breadth/QUBO findings); this widens only the
*manual investor's* opportunity set, which the advisor/tax engine already serve on any holdings.
**Watchlist prices — INGESTED (verified working):** `build_nifty100_watchlist.py --prices` downloads
the 96 names → `data/historical/prices_watchlist.parquet` (95/96 priced; only retired TATAMOTORS.NS
fails); `deploy-weakness` loads that panel so it actually sees the full Nifty 100 incl. the Next-50
midcaps (62/96 → **95/96**; the missing midcaps were the whole point). Also added an **anti-dominance
guard** (`max_name_fraction=0.20`): drops a name whose single share exceeds that fraction of the deploy,
so a pricey share (e.g. SHREECEM ₹24,825) can't swallow a small ₹50k deploy — it now spreads across
~14 names. **"Closed" = build-complete
v1; the real-money GO remains gated by the unskippable forward paper run** (criterion 6) — that calendar
time cannot be compressed. QUBO/breadth stay in research; the fragility-gauge promotion (as a read-only
"systemic risk" advisory) is the clean next integration if revisited.

**🚀 DEPLOY STAGE 1 (2026-06-18) — phone-accessible hosted dashboard.** User wants a URL on his phone,
always-on, realtime, with the paper-run shown (not trusted). Built (`deploy/`: Dockerfile +
entrypoint.sh [bootstraps the gitignored price panels on first boot] + docker-compose.yml + DEPLOY.md
[AWS EC2-free-tier / Lightsail step-by-step, security-group-to-own-IP, Caddy HTTPS option]). Dashboard
gains: **password gate** (`APP_PASSWORD` env, open if unset for local dev), **paper-run freshness panel**
(`live/dashboard.py:paper_freshness` + test — weekday-aware stale flag, the "see it's alive" piece),
**phone one-tap Kite login** (captures the `request_token` from Kite's redirect via `st.query_params`,
paste fallback — no CLI), and **auto-refresh** (`st.fragment(run_every=30)` on the live view →
near-realtime ltp). **Kite reality (locked):** the daily session needs a one-tap human login — there is
NO compliant fully-unattended token (declined auto-TOTP as ToS-violating/insecure). **Can't verify a
live server here** (sandbox blocks ports; no AWS/Kite creds) → AppTest-smoke + pure-fn tests only; user
verifies on the box. **✅ STAGE 2 NOW BUILT (2026-06-19, `live/ticker.py`): true tick-streaming via Kite
`KiteTicker`** — a background thread → thread-safe `TickStore` → fragment reads it, exactly as planned,
but **session-scoped** (socket lives with the browser session, not a 24/7 host) so it needs no always-on
server; best-effort overlay over the 30s polling. Built here, **verified on the box** (no live socket in
the sandbox). Stage-1 auto-refresh is the pre-connect fallback.
**HOSTING = LIGHTNING AI (user's choice, `deploy/DEPLOY_LIGHTNING.md`)** — we're already in a Lightning
Studio (repo+data present), so the Streamlit plugin gives a 1-click public URL; **auto-start** = always-
on, pay-per-use (idle-sleep + cold-start). Caveat: auto-start's idle-off is fine for Stage-1 auto-refresh
but **kills a Stage-2 always-on WebSocket** → true-ticks need a persistent Studio (continuous credits) or
the AWS free-tier box. Lightning note: the GH-Actions paper cron commits to GitHub, so the Studio app
needs a periodic `git pull` for the freshness panel to show fresh marks. The Docker/AWS scaffold
(`deploy/DEPLOY.md`) stays as the portable any-VPS path.

**⭐ USER MADE FIRST REAL TRADES (2026-06-13):** funded YHK037, **HDFCBANK BUY 5 @₹785.45 COMPLETE**
(CNC/delivery), INFY BUY 5 still OPEN/pending; cash ₹445.75. **A same-day delivery buy sits in
`positions()` day-book, NOT `holdings()`** (→ T+1 it lands in `holdings()` as `t1_quantity`), so
`--source live` (which reads `holdings()`) shows EMPTY until tomorrow. Possible quick win:
also read `positions()` for same-day visibility (offered, not built). Kite token expires daily
~06:00 IST → re-mint `python -m qalpha.live.auth --manual`. **Streamlit server can't run in the agent
harness** (sandbox kills port-binding, exit 144); the user runs it + forwards port 8501 via VSCode
PORTS. I verify rendering with Streamlit `AppTest` (in-process, no socket).

**🎯 USER'S VISION + AGREED NEXT PLAN (the active direction — build this):** the user trades **manually
(all his own decisions)** and wants an **advisor + proper live web dashboard wired to his REAL Zerodha
account** — it reads his holdings (`kite.holdings()`) + live prices, reflects every trade *he* makes,
and tells him the **tax-smart move**. It NEVER auto-executes. Tax math is **deterministic** (exact/
auditable — NOT an LLM computing numbers; an LLM "concierge" that routes NL questions to the engine is
an optional *later* flourish, never the calculator). **Build order:**
1. ✅ **DONE — Deterministic tax-smart advisor** (= §14 criterion 10, the recommendation layer):
   `src/qalpha/live/advisor.py`. Three modes, all on the validated FIFO/cost/tax engine (no LLM, no
   second formula), source-agnostic (takes a `Portfolio`): `advise_sell` (STCG/LTCG split, exact tax,
   exemption shelter, largest ₹0-tax quantity, wait-out-365 flag), `advise_raise_cash` (least-tax
   source order — losers/long-term first — vs naive pro-rata), `advise_deploy` (route new money to
   underweights, buys-only ₹0 tax, vs a taxable full rebalance). CLI `scripts/advisor.py`
   (`sell`/`raise-cash`/`deploy`). `Portfolio` gained `clone()`, public `sell()`/`buy()`,
   `preview_sell()`. Tests `tests/test_advisor.py`.
2. ✅ **DONE — Live web dashboard** (Streamlit): `scripts/dashboard_app.py` — equity vs Nifty 50 TRI,
   holdings, today's recommendation, and the advisor as interactive tabs. Read-only (never trades).
   Source = paper book now → `kite.holdings()` later (the `_load` seam). `streamlit` is an optional
   **`dashboard`** extra (UI-only, not in CI/pipeline). Run: `uv run --extra dashboard streamlit run
   scripts/dashboard_app.py`. `AppTest` smoke test skips dev-only (CI) / without on-disk data.
3. ✅ **DONE — Live Zerodha holdings reader** (PR #10): `src/qalpha/live/holdings.py` reads
   `kite.holdings()` + `ltp()` + `margins()` into the same `Portfolio`. Source swap is a sidebar toggle
   (dashboard) / `--source live` (CLI). **Caveat:** `holdings()` has no purchase dates → undated lots
   (tax short-term-assumed) flagged via `LiveHoldings.lots_dated`/`.tax_caveat`.
4. ✅ **DONE — Tradebook upload → exact dated tax** (PR #11, the criterion-4 reconstruction half):
   `src/qalpha/live/tradebook.py` (`parse_tradebook` path-or-file, `replay_tradebook`→`ReplayResult`,
   `reconcile_positions`). Dashboard Live view has an `st.file_uploader`; upload the Console tradebook
   CSV → exact dated FIFO lots + realized tax + holdings reconciliation; advisor uses the accurate book.
**Trust gate** before real-money reliance: **criterion 4** = reconcile our realized tax vs the real
Zerodha **Tax P&L** export. **✅ DONE (2026-06-18)** — real SELL made, Tax P&L parser built, gross
reconciles to the paise (₹25.25 STCG, Δ ₹0.00); see the crit-4 block above + `reports/
crit4_reconciliation.md`. Remaining hardening: a multi-lot/LTCG/loss case (this one was single-lot,
all-STCG) and LTCG loss set-off. **Parked (declined/deferred):** auto-execution, LLM-for-numbers,
Monte Carlo, GPU, more quantum.

**✅ PAPER CRON FIXED (2026-06-15, PR [#14](https://github.com/aarsh-adhvaryu/Q_Alpha/pull/14), merged).** Root cause of the never-firing
schedule: `cron: "0 12"` was the **top of the hour** — GitHub throttles/silently-drops on-the-hour
scheduled workflows under load. Moved to `"23 12 * * 1-5"` (off-hour). Proved the pipeline works
end-to-end via a manual `workflow_dispatch` run (green; it marked the book + pushed the track record,
commit `1a799e1`). First scheduled firing expected next weekday 12:23 UTC — **still verify it fires
on schedule** (dispatch ≠ cron). The job itself was always sound; only the trigger timing was broken.

**🅿️ PARKED VISION (2026-06-15, user said "do later") — autonomous system + Nifty 100–200.** The
user wants the product to become **autonomous data→scoring→recommendation, human approves + trades
manually** (never auto-executes — already the design). Daily data refresh + a weekly decision/advisor
run (two cron cadences; the `paper.yml` skeleton already does the no-AI-in-loop pattern). Scale the
universe **5 → Nifty 100–200** (user's chosen scope). Two findings that reshape this:
1. **Kite Connect API does NOT expose fundamentals/Tijori** (verified vs kite.trade/docs/connect/v3:
   categories are auth/orders/GTT/alerts/portfolio/quotes/WebSocket/historical-candles/MF/margin — no
   fundamentals). Tijori on Zerodha is the **consumer Kite UI only**; programmatic Tijori = its own
   **separate paid API**. So fundamentals can't ride the existing Kite integration.
2. **The validated edge is 3-factor (price/volume) — it needs ZERO fundamentals.** So scaling to
   Nifty 100–200 is **data-cheap** (price history via yfinance + the bad-tick sanitizer; no data
   deal). Fundamentals/6-factor stays the *optional later* enhancement (only then weigh Tijori-API vs
   NSE/BSE-filings parsing). **Critical path for the expansion (a fresh, pre-registered Phase-0 pass —
   the Nifty-50 result does NOT auto-transfer):** (a) extend the PIT universe 50→~200 via
   `build_nifty_universe.py`; (b) add the **square-root slippage law** `impact≈k·σ·√(value/ADV)`
   *before* trusting mid-cap numbers (flat 0.2% is too optimistic off large-caps — see §13 / the
   open-threads slippage item); (c) re-validate 3-factor net cost+tax, walk-forward, **vs 1/N**. Run
   as a **validation experiment**; promote the new universe into the product default **only after it
   clears the bar** (keep qalpha pristine — see the research-untouched rule). **Trap to avoid:** a
   "weekly decision" cadence must NOT loosen the §4.6 gate — weekly *monitoring* is fine, but actual
   trades must stay rare (low realized turnover is the validated edge).
   - **▶ STAGE-1 BREADTH SCREEN DONE (2026-06-18) — INCONCLUSIVE, and instructively so.** Pre-reg
     `reports/PREREGISTRATION_universe.md`; `scripts/build_static_universe.py` (current Nifty-100,
     98 names) + `scripts/exp_universe_breadth.py` (parameterized walk-forward on a **separate** price
     cache → validated panel untouched) → `reports/universe_breadth_findings.md`. Ran the validated
     config (annual·shrink·force_refresh·dynamic-slippage) on a **static current-constituents** Nifty
     100. Result: strategy 16.4% CAGR / Sharpe 1.06 (≈ its clean PIT-50 18.2%/1.13, **no visible
     breadth bonus**), but "loses to 1/N by −9.9pt." **The −9.9pt is an artifact:** 1/N on a static
     survivorship-biased universe (26.3% CAGR — implausible) is the *largest* survivorship beneficiary
     (buy-and-hold-all-future-survivors), so it inflates **more** than a point-in-time factor strategy
     → the gap is contaminated, not a real loss. **Methodological lesson: never benchmark vs 1/N on a
     survivorship-biased universe; a static screen cannot adjudicate breadth.** Did NOT run Nifty 200
     (same contamination → motion, not evidence). **The only valid path = Stage 2: a real PIT
     Nifty-100/200 membership (NSE reconstitution circulars / niftyindices) — the data-blocked piece.**
     Given no visible bonus even with the survivorship tailwind, the EV of that data effort is modest;
     **keep the product at the validated Nifty 50** unless/until Stage-2 data is sourced. Not a
     next-week item.

**🧠 OTHER OPEN THREADS** — same-day `positions()` reading; crit-4 hardening (multi-lot/LTCG/loss
case + LTCG loss set-off — the single-sell gross reconciliation is ✅ done); corporate-actions (crit 5);
the tax-alpha whitepaper; LLM "concierge"
routing NL → the deterministic engine; an equity-curve chart + dashboard screenshot in the README
(the only "last-mile" polish for resume-readiness — repo is otherwise resume-ready: 100 tests green,
CI green, honest README). Let the user steer.

**The validated config is now the default** of `scripts/run_phase0.py` (no args needed):
PIT universe + **Nifty 50 TRI** benchmark + **annual** rebalance + **`weighting=shrink`** (½ min-var +
½ equal, the anchor-to-1/N edge) + **`force_refresh=True`** (anti-ossification) + §4.6 gate 2.0 + band
0.10. Reproduce the headline (**18.2% CAGR / Sharpe 1.13 / GO**, beats Nifty TRI 14.5% and 1/N 17.7%):
```bash
uv run python scripts/build_nifty_universe.py        # regenerate the PIT universe CSV (gitignored)
uv run python scripts/run_phase0.py --end 2024-12-31 # the validated run → reports/phase0_report.md
```
Engine low-level defaults were left neutral (minvar / monthly / no-refresh) so the test-suite stays
green; the *application* layer (run_phase0) carries the validated defaults.

**What's proven vs not:** the strategy edge is validated as far as *simulation* can go (walk-forward +
2025-26 holdout + shrink beats 1/N). What remains is **live-only** validation that no simulator can
replace — data-feed integrity, real fills/slippage, FIFO-vs-broker tax reconciliation, the
human-in-the-loop process, and certainty of no look-ahead (we found one look-ahead bug already). That
is the unskippable forward paper run; it can be *de-risked* fast (replay the production code over
history; validate FIFO vs a real Zerodha Tax P&L) and run *in parallel* with the build, but the
forward calendar time itself (pipeline survives N days + ≥1 volatility event) cannot be simulated away.

_(Superseded — those original "three candidate moves" are done: branch pushed/merged, Stage-1
founder-as-user build + paper clock live, QUBO/QAOA built. The active plan is the advisor-first one
above. The tax-alpha whitepaper remains a good resume capstone once the advisor exists.)_

**Read-me-first docs:** `reports/PHASE0_VERDICT.md` (full evidence chain + verdict), `STRATEGY.md`
(market scan, regulatory reality, 4-stage industry-ready plan), `PLAN.md` (technical track).
Experiment scripts: `walkforward.py`, `calibrate_gate.py`, `holdout_2025.py`, `exp_breadth.py`,
`exp_frequency_lookback.py`, `build_nifty_universe.py`.

### Original static result (Phase 0b, 2012–2024, net of cost + tax) — vs Nifty *price*
| | final ₹ (from ₹2L) | CAGR | Sharpe | max abs DD |
|---|---|---|---|---|
| Q-Alpha (6-factor, tax-aware) | 1,412,776 | 16.6% | 1.06 | -34.5% |
| Nifty 50 (price) | 992,378 | 13.4% | 0.85 | -38.4% |
| Equal-weight 1/N | 1,579,511 | 17.7% | 1.09 | -35.6% |

### Phase A: survivorship-free universe + fair Nifty 50 **TRI** benchmark (3-factor, fully reproducible)
The six-factor model can't yet be run on the PIT universe (needs fundamentals for ~75 names; only 7
of 25 Screener files are even in the repo), so the clean A/B is on the **3-factor (0a)** model:
| run | universe | CAGR | Sharpe | max DD | cost+tax | vs Nifty 50 TRI (14.5%, 0.98) |
|---|---|---|---|---|---|---|
| static-0a | 24 survivors | 14.6% | 0.98 | -33.6% | ₹10k | CONDITIONAL (ties Sharpe) |
| **PIT-0a** | **76, dead names in** | **15.2%** | **0.92** | **-28.1%** | **₹165k** | **NO-GO (loses Sharpe)** |
| 1/N (PIT, frictionless) | — | 17.7% | 1.06 | -39.0% | 0 | — |

Honest read: **survivorship bias was *not* inflating the edge** — fixing it actually *raised* return
(14.6→15.2%) and cut drawdown. At **monthly** rebalancing the strategy loses Sharpe vs TRI because
turnover/tax explodes (₹2.7k→₹117k) — the §4.6 gate at 2.0 is far too lenient at this universe size.

### Phase A follow-up: **rebalance frequency** is the single biggest lever (PIT-0a vs TRI, net cost+tax)
| rebalance | # rebal | tax | CAGR | Sharpe | maxDD | verdict |
|---|---|---|---|---|---|---|
| Monthly | 47 | ₹117k | 15.2% | 0.92 | -28.1% | NO-GO (loses Sharpe) |
| Quarterly | 22 | ₹76k | 16.7% | 1.04 | -24.6% | GO |
| **Annual** | **5** | **₹20k** | **18.5%** | **1.13** | **-24.1%** | **GO — beats TRI *and* 1/N** |

**Trading less improves *every* metric monotonically** in the full window. Mechanism is durable:
lower tax (LTCG not STCG, fewer events) + less noise-trading + tax savings compounding. Frequency is
a CLI knob (`run_phase0.py --rebalance M|Q|Y`). Reports: `reports/phase0_pit_report.md` (monthly),
`reports/phase0_pit_annual_report.md` (annual), `reports/phase0_static0a_report.md` (static/TRI).

### WALK-FORWARD VALIDATED (`scripts/walkforward.py`) — thesis holds OOS; frequency is *not* a magic number
Two out-of-sample views on the PIT universe, net cost+tax:
- **Rolling 3-yr holding periods (every entry day):** Annual dominates the *whole distribution* —
  worst-ever 3y **+4.4%** (never a losing 3y stretch) vs Monthly +2.6%, Nifty-TRI **−2.9%**, 1/N
  **−8.7%**. Annual ≥ TRI in **93%** of holds, ≥ 1/N in **69%**, ≥ Monthly in 70%. Best downside of
  any option — the consumer-relevant headline ("even if you started at the worst time…").
- **3 independent sub-period backtests (distinct regimes):** Annual **beat both TRI and 1/N in all
  three** windows (vs 1/N: +4.8, +2.4, +6.9). BUT the M<Q<Y ranking is **not** monotonic OOS —
  Monthly won 2015-21 (its gate suppressed trades → low realized turnover anyway), Quarterly was
  erratic (great 2012-18, *lost* to benchmarks 2018-24 when it under-traded to ₹0 tax).
- **Refined, validated conclusion:** the driver is **low *realized* turnover, not the nominal
  frequency** — annual achieves it structurally, the §4.6 gate achieves it adaptively; both win,
  pure-monthly-churn loses, and zero-turnover (stuck) also loses. So: **"trade less, tax-aware,
  beats index + 1/N net of friction" is validated OOS**; "annual is *the* optimal frequency" is not
  — annual/quarterly is the robust *zone*, pick by the tax/Sharpe trade-off, don't over-fit the point.

## Key decisions (deviations from the spec, deliberate)

- **Broker = Zerodha (Kite Connect), not HDFC.** Notably ₹0 delivery brokerage, which changes the
  cost-gate math. Cost constants live in `src/qalpha/accounting/costs.py`.
- **Tax-aware optimizer** (`run_backtest(tax_aware=True)`): the spec's §4.6 net-benefit gate done
  properly — a rebalance is suppressed unless its annual risk reduction (₹) beats 2× its real
  cost + FIFO capital-gains tax. This is the core edge: friction is modelled *inside* the decision,
  not bolted on. It turned a NO-GO (5.4% CAGR, taxed to death) into beating Nifty 50 net (14.6%).
- The **accounting engine** (`src/qalpha/accounting/`) is standalone so the future live decision
  engine reuses the exact same FIFO/cost/tax code.
- **Dynamic drawdown control** (`src/qalpha/backtest/drawdown.py`, spec §0 amended): the flat
  "20% = FULL FREEZE" was *replaced* (evidence: it misfires almost only at crash bottoms). New rule
  is market-relative — absolute DD → defensive posture; **adaptive excess-DD vs benchmark** (beyond
  the strategy's own 95th-pct, sustained ≥60d) → strategy-failure halt; catastrophic (~-40%) →
  human alert. The spec is a *proposal we improve*, not scripture — amend it when evidence warrants.

## Commands

```bash
uv sync --extra dev                       # set up venv + deps
uv run pytest                             # tests (must stay green)
uv run ruff check . && uv run ruff format --check .   # lint + format
uv run mypy src                           # strict type-check
uv run python scripts/run_phase0.py       # run the backtest + print go/no-go report
uv run python -m qalpha.data.ingest --tickers TCS INFY --start 2012-01-01   # pull prices
uv run python -m qalpha.data.fundamentals --raw data/fundamentals/raw       # ingest Screener xlsx
uv run python scripts/advisor.py deploy 50000      # tax-smart advice (sell / raise-cash / deploy)
uv run --extra dashboard streamlit run scripts/dashboard_app.py   # the live web dashboard
```

**The audit recipe** — how the pre-flight audit reproduced every live surface offline, no Kite login
and no Streamlit server. Copy this shape; the account state is the part that matters.

```python
import sys; sys.path.insert(0, "scripts")
from datetime import date
from decimal import Decimal
import pandas as pd
from paper import _load_benchmark_series, _refresh_benchmark   # refresh() does NOT do the benchmark
from qalpha.config import Config
from qalpha.data.prices import PriceData
from qalpha.backtest.portfolio import Portfolio
from qalpha.live.deploy import advise_deploy_into_weakness

cfg = Config()
prices = PriceData.from_long(pd.read_parquet("data/historical/prices_watchlist.parquet"))
wl = pd.read_csv("data/universes/nifty100_watchlist.csv")
sector_of = dict(zip(wl["ticker"], wl["sector"]))
watchlist = [t for t in wl["ticker"] if t in prices.tickers]

# ⚠️ The account shape is the whole point: idle cash AND holdings. A zeroed portfolio hides
#    four of the five defects found in August 2026.
pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal("500000"))
advice = advise_deploy_into_weakness(
    pf, Decimal("100000"), watchlist, sector_of, prices,
    _load_benchmark_series(), date.today(), max_names=8, spend_idle_cash=False,
)
print(advice.render())          # then check every rendered figure against what the code summed
```

Refresh both panels before auditing anything:
```bash
uv run python scripts/build_nifty100_watchlist.py --prices    # watchlist panel
uv run python -c "import sys;sys.path.insert(0,'scripts');from paper import _refresh_benchmark;_refresh_benchmark()"
```

All four gates (ruff, ruff-format, mypy strict, pytest) must pass before committing.

## Architecture (the funnel)

```
data/         price panel (yfinance→Parquet), point-in-time universe, Screener fundamentals
factors/      momentum, volatility, liquidity (0a) + value, quality, dividend (0b); regime; scoring
alloc/        Ledoit-Wolf+EWMA covariance conditioning → scipy sector allocator → scipy optimizer
accounting/   FIFO tax lots + Zerodha costs + capital-gains tax + corporate_actions (split/bonus/dividend, crit 5)   (reused live; Portfolio.to_state persists a book)
backtest/     walk-forward engine, portfolio accountant, baselines, metrics, report; decision.py = shared decide_rebalance
live/         Kite auth · replay · paper book · dashboard renderer (+ account_overview tiles, systemic_risk_markdown) · advisor.py (tax-smart layer, crit 10; §70 set-off; `spend_idle_cash` budget) · deploy.py (the buy screen: weakness → cheapness → health filter → sector cap) · holdings.py · tradebook.py + tradebook_store.py + gist_store.py (Console CSV → dated FIFO, crit 4, private-gist master) · taxpnl.py · safety.py (fail-loud guards) · ticker.py (session-scoped realtime) · **price_integrity.py** (demerger/bad-print guard) · **position_health.py** (§4.7 breakdown test, now a filter) · **cooling_off.py** (names the user deliberately exited) · **measures.py** (a basis + window on every number) · **track_record.py** (the real account vs the same money in the index, XIRR) · go_scorecard.py (deterministic GO verdict; refuses to grade on a stale benchmark) · autopilot.py · ai_brief.py · hedge.py · notify.py · scan.py
scripts/      run_phase0, paper, advisor (CLI), dashboard_app (Streamlit, `dashboard` extra), build_nifty_universe, experiments
config.py     every tunable parameter (Q_alpha.md §16) in one place
              (the research track — QUBO/QAOA §15 + planned regime/agentic — lives in the separate Q_Alpha_Research repo)
```

Data flow each rebalance: `as_of` slice (no look-ahead) → liquidity gate → factor scores under the
regime's weights → top-N selection → sector allocator → portfolio optimizer → tax-aware execution.

## Conventions

- **Money is `decimal.Decimal`** everywhere it touches accounting; never float (spec §5.2). Factor
  / covariance math uses numpy float64.
- **No look-ahead, ever.** All historical reads go through `PriceData.as_of(date)`; fundamentals
  carry an `effective_date = report_date + 90d` lag. There is a test that fails on look-ahead.
- **Reuse before adding.** The sector-percentile ranker, cost engine, and FIFO ledger are shared;
  prefer extending them. Match the surrounding style; keep functions typed (mypy strict).
- Reference the spec by section (e.g. "§4.6") in comments so code maps back to the architecture.
- Phase 0a (3 price/volume factors) runs without fundamentals; Phase 0b (6 factors) activates when
  Screener exports are present in `data/fundamentals/raw/`. The scorer renormalises over whatever
  factors exist, so the same code path serves both.

## Path to a real GO — §14 scorecard

"GO" = the spec's §14 (10 criteria, all true before real money), spanning Phase 0 → Phase 6.
Status: **1 ✅ walk-forward validated (low-turnover 3-factor PIT beats TRI in 93% of 3y holds & beat
TRI+1/N in all 3 independent sub-periods, best downside; the *thesis* holds OOS though not a magic
frequency — see Phase A) |
2 ✅ | 3 ✅ PIT universe built (Phase A) | 4 ✅ **reconciled to the paise (2026-06-18)** — real SELL +
Tax P&L parser (`taxpnl.py`); gross == Zerodha STCG ₹25.25 (`reports/crit4_reconciliation.md`).
**§70 loss set-off now implemented (2026-06-19, `net_capital_gains_tax`, advisor/reconcile only — not
the engine, headline preserved).** Remaining hardening needs a *real* multi-lot/LTCG/loss sell + Tax
P&L to reconcile the new netting; 8-AY carry-forward still deferred |
5 🟡 corp-actions ENGINE + live wiring done, tax-correct (2026-06-19, `accounting/corporate_actions.py`
+ `FIFOLedger.apply_split/apply_bonus`, `Portfolio.apply_corporate_action`, detector
`live/corporate_actions_feed.py`, **interleaved into `tradebook.replay_tradebook` so a held name that
splits/bonuses reshapes its lots at the ex-date** + reconciles): splits preserve cost+holding-period,
bonus = ₹0-cost lots at the ex-date (→ STCG even when originals are LTCG), dividends = income cash. 10
tests incl. end-to-end through the replay. Remaining: reconcile ONE real corporate action on the account |
6 ⏳ paper clock STARTED 2026-06-12, accumulating (3–6 mo, unskippable) |
7 ✅ | 8 ✅ (dynamic rule) | 9 🟡 pipeline built, needs the live run | 10 ✅ deterministic tax-smart
advisor + live dashboard built (`advisor.py`, `dashboard_app.py`)**. Phase A cleared survivorship (3)
and — once rebalancing slowed to annual — re-cleared criterion 1 on the *fair* test. Remaining for a
defensible Phase-0 GO: **walk-forward validation** of the rebalance frequency (don't trust one
bull-heavy window), then optionally the 6-factor PIT run. The *real-money GO* remains months away,
gated by a mandatory paper-trading run.

## Brainstorming / open threads (what we're actively deciding)

- **Survivorship-free universe — DONE (Phase A).** Built `data/universes/nifty50_membership.csv`
  (point-in-time Nifty 50, 2012–24, dead names included) via `scripts/build_nifty_universe.py`
  (reverse-apply from current set, validated — caught 4 Wikipedia errors + 2 missing exits). Wired
  `run_phase0.py --universe-csv`. Also fixed a **look-ahead bug in the 1/N baseline** (it front-ran
  future index entrants → fake 22.4%; now `equal_weight_pit` respects membership) and added a fair
  **Nifty 50 TRI** benchmark (`--benchmark NIFTYBEES.NS`, adj-close = divs reinvested) + a §5.1
  yfinance bad-tick sanitizer. Finding: survivorship wasn't flattering the edge, but vs TRI the
  3-factor model loses Sharpe (see status table). **Blocker for the real verdict: fundamentals for
  the ~75 PIT names** (a Screener-ingest data task, like the original 0b) to run 6-factor-on-PIT.
  Large-cap survivorship bias is genuinely *modest* (delistings ≈0.81% of Nifty-500 mcap) — confirmed.
- **"A better optimizer" — DONE: shrinkage hybrid (`weighting="shrink"`).** ½ min-var + ½ equal-weight
  over the picks (DeMiguel/Tu-Zhou anchor-to-1/N) is the validated winner — beats 1/N in-sample, on
  the 2025-26 holdout, and across rolling 3y holds (dominates every percentile). `select_and_weight`
  now supports `minvar|equal|score|shrink`; engine takes `weighting=` + `n_stocks_override=`. Pure
  broad-equal and score-tilt LOST (dilute/concentrate) — only the principled blend won. **Remaining
  optimizer ideas:** HRP/NCO (another robust route), and QUBO/VQE as the §15 research showcase
  (AUM-gated ₹50L+; now in the `Q_Alpha_Research` repo). Discipline held: it cleared the "beat 1/N
  walk-forward net of cost+tax" bar.
- **Defensive engine — two modes tested (`run_backtest(defensive=...|governance_events=...)`).**
  (1) *Price-based* idiosyncratic-drawdown exit (§3.6, `defensive.py:idiosyncratic_exit_flags`):
  on the annual core it cuts drawdown (-24%→-19%) and plugs the 2022 hole (-10%→+11%) but costs
  ~3pts CAGR (18.5→15.6) and *raises* tax (₹20k→₹46k) by whipsawing blue-chips (RELIANCE, ITC,
  MARUTI…) that recover — Sharpe ~flat (1.13→1.11), so it trades return for drawdown, not a free
  win. (2) *Event-driven* governance freeze (§3.11, `defensive.py:GovernanceEvents`, seed
  `data/events/governance_events.csv`): surgical by construction (only ever touches a broken
  business), but a **backtest no-op here** — the momentum/quality factors already never bought
  Yes Bank / Zee (collapsing momentum → never selected). Lesson: the opportunistic engine already
  does most of the defending; event-defence's real value is per-position risk control + a
  human-escalation trigger, and it's gated on a full historical event feed. Also fixed a real
  engine bug surfaced here: idle settled cash was locked out of redeployment by the §4.6 variance
  gate (cash→stocks looks like a risk rise) — now idle cash above the no-trade band always deploys
  (§2.9 fresh-capital routing), which also benefits real capital injections.
- **§4.6 gate multiplier — OOS-calibrated, verdict: DON'T tune it (`scripts/calibrate_gate.py`).**
  Swept {1,2,3,5} at monthly across the 3 sub-periods: **no value generalizes** (best flips
  1.0/3.0/2.0 by window) and turnover is a *knife-edge* (mult 2.0→47 rebalances/₹117k, 3.0→4/₹13k);
  monthly+gate loses to 1/N in ~half the windows. The robust turnover lever is **structural
  frequency (annual)**, not the multiplier — kept at spec default 2.0. (Iron rule: did not tune to
  manufacture a GO.) Side effect found+fixed: idle-cash redeploy lockout (monthly full 15.2→16.7%).
- **Size-aware slippage — ✅ DONE (2026-06-17).** Replaced the flat 0.2% with the **square-root law**
  `slippage = impact_k·σ_daily·√(value/ADV)` (spec §13): new `accounting/slippage.py`
  (`SquareRootSlippage`/`FlatSlippage`, `square_root_impact_pct`, tested), a `slippage_model` on
  `Portfolio` used in `_sell`/`_buy`/`_affordable_qty`, and `run_backtest(dynamic_slippage=True)` which
  sets a **causal as-of** per-rebalance ADV+vol snapshot (no look-ahead). Config in `CostConfig`
  (`impact_k=1.0`, floor 2bps, cap 2%). At k=1 the law equals the old 0.2% exactly at the §3.3
  order-size cap (1% of ADV, 2% daily vol), so it's a principled generalisation. **`run_phase0`
  defaults it ON** (`--no-dynamic-slippage` reverts). **Honest Phase-0 impact (PIT, annual, shrink,
  end 2024): headline barely moves — GO holds, Sharpe 1.13→1.14, CAGR ~18.2→18.3%, maxDD −25.2 flat,
  still beats Nifty TRI + 1/N — but charged cost DROPS ₹22.2k→₹9.5k** because the strategy trades
  small fractions of ADV in deep large-caps, so realistic impact is *below* the flat 0.2%. The model's
  teeth are for the **Nifty 100–200 expansion**, where thin mid-caps in size get charged more — the
  gate/optimiser then avoid them. Slippage is an execution *cost*, not portfolio risk.
- **Benchmark fairness.** Move to **Nifty 50 TRI** (total-return, free from niftyindices.com) — raises
  the bar ~1.5%/yr; the strategy still clears it.
- **BSE→NSE canonical-ticker robustness — ✅ DONE (2026-06-17).** A holding/trade is keyed by ISIN in
  demat (exchange-agnostic), and NSE is our single source of truth (panel/universe/factors/slippage)
  and the liquid venue. So `live/holdings.py` `to_ticker(symbol, exchange)` → **`canonical_ticker(symbol)`**
  that always resolves to `.NS` (a BSE INFY buy tracks as `INFY.NS`); `Holding.exchange` keeps the real
  venue for the live `ltp()` call. `tradebook.py` uses it too (a BSE leg + its NSE counterpart reconcile
  to one lot). Deliberately did **NOT** build full dual-exchange (NSE+BSE) calibration — same companies,
  thinner BSE book, Sensex⊂Nifty, BSE-only = illiquid small-caps → complexity tax, zero alpha, bloats
  the clean repo. Tests in `test_holdings.py` (BSE→.NS, exchange preserved). 107 tests green.
- **§4.6 gate tax-date bug — ✅ FIXED (2026-06-17).** `decision._net_benefit_ok` dry-ran the gate's
  cost/tax estimate at wall-clock `date.today()` instead of the rebalance `as_of`, so in a historical
  backtest every lot looked long-term → STCG under-estimated as LTCG → the gate traded too readily.
  Now threads `as_of` (live, `as_of`≈today, so also correct). **Validated headline unaffected**
  (force_refresh short-circuits the gate); only non-force-refresh `tax_aware` runs (older Phase A
  monthly/quarterly tables, `calibrate_gate`) would shift slightly if re-run — qualitative conclusions
  hold. 106 tests green.
- **Tax-engine validation (criterion 4) — ✅ DONE (2026-06-18).** FIFO engine reconciled vs the real
  **Zerodha Console → Tax P&L** export: gross == ₹25.25 STCG to the paise (`taxpnl.py`,
  `scripts/reconcile_taxpnl.py`, `reports/crit4_reconciliation.md`). The first sell was a single
  STCG gain (no loss), so loss set-off wasn't exercised. **✅ §70 loss set-off now IMPLEMENTED
  (2026-06-19, `net_capital_gains_tax`/`net_tax_total`):** STCL→STCG then LTCG, LTCL→LTCG only,
  exemption on net, carry-forward reported (8-AY carry not applied). Additive — wired into the advisor
  (`advise_sell` nets losses + shows `setoff_saving`) + reconcile only, NOT the backtest engine, so the
  headline is unchanged. **Still needs a *real* multi-lot/LTCG/loss sell + Tax P&L to reconcile the netting.**
- **Risk-tolerance reckoning.** Backtest the full **50/25/25** pool structure (not 100% core) to see
  the blended drawdown, then confirm the real tolerance (long-only equity ≈ -30% in crashes; a hard
  ≤20% implies a hedging overlay = a v2 feature).

## Iron rules (don't violate)

- **Real money never auto-trades. The user places every order.** Outlives every gate in this repo.
- **A number on a real-money surface must be labelled as the thing that was computed.** Five separate
  defects in August 2026 were all this one mistake, and one of them nearly became a 64-share order.
  When a figure reaches a screen, check what its label claims against what the code summed.
- **Audit with idle cash in the portfolio.** Four of those five only appear when `portfolio.cash > 0`.
  A zeroed fixture is why 481 tests missed them.
- **The GO gate is not open. Never call the system validated for real money**, and never soften a red
  because money is already committed.
- Do **not** auto-tune parameters to manufacture a GO — that defeats Phase 0. Validate out-of-sample.
- Keep all four gates green (ruff, ruff-format, mypy strict, pytest) before every commit.
- Surface honest caveats in the report; never let a survivor-only universe silently earn a GO.
