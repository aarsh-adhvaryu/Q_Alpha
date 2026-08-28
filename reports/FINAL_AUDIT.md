# Final audit — the remaining real-money surfaces

**Audited 2026-08-28 against `main` (503 tests, 0 skipped), on prices and a benchmark refreshed the
same morning.** Commissioned by the brief at the top of `CLAUDE.md`: audit every real-money surface
the pre-flight audit did not reach, then report.

Surfaces covered: the **Sell tab** (`advise_sell`), the **Raise cash tab** (`advise_raise_cash`), the
**holdings table** (`_holdings_frame`), **position health**, the **track record panel** (#71), the
**tradebook reconciliation** panel, and the **Telegram opportunity scan** — which was not on the
brief's list and should have been, because it is the only surface that reaches the user without him
opening anything.

This repo publishes its negatives. This is one.

---

## 0. The headline

**Six defects. All six are the same defect the pre-flight audit found: a number labelled as something
it is not, on a surface where the label becomes an order.** None was caught by 503 passing tests, for
the same reason as last time — each is a figure reported *about* the machinery rather than the
machinery's own arithmetic.

Two of them are new instances of defects that were *fixed elsewhere in the same session that shipped
them*. That is the finding behind the findings, and §7 is about it.

| # | Surface | What it says | What is true | Fixed? |
|---|---|---|---|---|
| 1 | Track record (#71) | "You are **ahead by ₹4,01,677**" | ahead by **₹1,677** | ✅ |
| 2 | Raise cash | "₹620 tax" | **₹9,570** tax | ✅ |
| 3 | Raise cash | "Raises ₹3,92,610.50" | ₹3,91,675.88 | ✅ |
| 4 | Holdings table | HCLTECH "**3.3%**" weight | **17.8%** of the portfolio | ✅ |
| 5 | Position health | VEDL "−59%, breaking down" | a demerger step, ~−22% | ✅ |
| 6 | Telegram scan | "Most out of favour: **VEDL −65%**" | a demerger step, −22% | ✅ |

**All six are fixed.** #6 was the scope first agreed; the user then said *"start fixing the problems,
today investing starts"*, and #1–#5 followed. **522 tests, 0 skipped; ruff, format and mypy green.**
Rule (a) holds: `git diff --name-only` touches **no** file under `src/qalpha/{backtest,accounting,
data,config}` — the validated engine and the 18.2% headline are untouched, and every new guard
defaults to off so the SIP backtest's own `position_health` call is bit-for-bit unchanged.

---

## 1. The track record panel counts parked SIP cash as investment performance — **the serious one**

`scripts/dashboard_app.py:1562`

```python
record = track_record(trades, portfolio.market_value(prices), benchmark, as_of)
```

`market_value` is **cash + holdings**. `TrackRecord.value` is documented as *"what your holdings are
worth now"* and is compared against `benchmark_value` — what the **traded rupees** would be worth in
NIFTYBEES. The two columns are therefore on different bases: one includes ₹4,00,000 of SIP money
sitting idle at the broker, the other cannot.

Reproduced on the real account shape (₹1,00,000 opening basket placed 2026-08-27, ₹4,00,000 parked):

| | Panel renders today | Truth |
|---|---|---|
| Net money in | ₹90,280 | ₹90,280 |
| Worth today | **₹4,91,335** | ₹91,335 |
| Return | **+444.2%** | +1.2% |
| Verdict line | **"You are ahead by ₹4,01,677"** | "ahead by ₹1,677" |

**Why this is the worst finding in the audit.** PR-71's stated design property — asserted by its own
tests — is that the panel *must be able to say "behind by ₹X"*, because "a surface that can only
report good news is marketing". With cash in the account it **cannot say that**. Every ₹50,000 SIP
instalment that lands before it is deployed adds ₹50,000 of pure phantom outperformance. The one
instrument built to catch the system failing is the one instrument guaranteed to report success.

It is also **defect #74 verbatim** — the Equity tile that included cash — on a panel merged in the
same fortnight #74 was fixed. `account_overview` was taught to separate shares from cash; the
`market_value` call two hundred lines away was not.

**Fixed:** `portfolio.holdings_value(prices)`. The panel now reads **+1.2% · ahead by ₹1,677**.

⚠️ **A test was pinning the defect in place.** `test_the_track_record_is_on_the_real_money_page`
asserted the literal string `track_record(trades, portfolio.market_value(prices), benchmark, as_of)`
— so the suite would have failed had anyone fixed it. That is the sharpest illustration in this
report of why 503 green tests meant nothing here. It now asserts `holdings_value` *and forbids
`market_value(` by name*, and a behavioural test in `test_track_record.py` marks the same book both
ways and requires the shares-only reading to report the loss.

---

## 2. The Raise-cash tab quotes tax on a different engine than the Sell tab

`src/qalpha/live/advisor.py:372`

`advise_sell` computes the **real ITR figure**: §70 loss set-off, §112A grandfathering, the 4% cess,
and — critically — `apply_long_term_boundary`, the §2(42A) correction for the engine's `holding_days
>= 365` fast path.

`advise_raise_cash` costs its plan by summing `Portfolio.sell(...).tax`, the frozen **backtest**
tax, then bolts cess on at the end. That path applies none of the four. Its own docstring in
`capital_gains.py` says so: *"loss set-off … is a portfolio-level concern deferred past Phase 0."*

The dangerous direction is the boundary. A lot held **exactly 365 days** is long-term to the engine
and short-term to the law (§2(42A) needs *more than* twelve calendar months). Raise-cash treats it as
LTCG at 12.5%, shelters it under a ₹1.25L exemption it is not entitled to, and quotes near-zero.

Reproduced — one account, winners only, an ITC lot bought 2025-08-28 valued on 2026-08-28:

| Cash requested | Raise-cash quotes | True ITR liability | **Under-stated by** |
|---|---|---|---|
| ₹1,00,000 | ₹0.00 | ₹0.00 | ₹0.00 |
| ₹2,00,000 | ₹0.00 | ₹0.00 | ₹0.00 |
| ₹3,00,000 | ₹0.00 | ₹2,690.55 | **₹2,690.55** |
| ₹3,80,000 | ₹620.18 | ₹9,569.55 | **₹8,949.37** — 15× |

Take the *same* ITC shares to the Sell tab and it reports **₹1,57,472.65 of short-term gain**,
**₹32,754.31 of tax**, and warns: *"900 share(s) are NOT long-term yet, despite being held 365+
days."* Raise-cash says ₹620 and warns nothing. **Same book, same day, same shares, two answers.**

**Fixed.** `advise_raise_cash` now runs the same path as `advise_sell` — `apply_long_term_boundary`
on every consumed lot, then one `net_capital_gains_tax` over the **whole plan** (tax cannot be
attributed per order: §70 nets a loss in one name against a gain in another). Re-run of the table
above: the under-quote is **₹0.00 at every level**, asserted by a test that replays the plan's own
orders through the Sell tab's engine and demands equality. The panel now also carries the Sell tab's
`⚠️ N share(s) are NOT long-term yet` warning.

Two aggravating details on the same surface, **both also fixed**:

- **`_unverified_branch_warning` was wired into the Sell tab only** (`dashboard_app.py:1756`). The
  Raise-cash tab sells *multiple names across multiple lots by construction* — it exercises the
  multi-lot, LTCG, set-off and exemption branches every single time, and it was the one tab that
  never warned they are unreconciled. `RaiseCashAdvice` carried no `realized` field, so the helper
  would have no-opped even if called. It now carries `realized` and `ltcg_sheltered`, and the tab
  calls the same helper the Sell tab does.
- **`_liquidation_efficiency` ranked on the uncorrected tax**, so a lot held exactly 365 days ranked
  as the *cheapest* source when it is among the dearest. It now ranks boundary-corrected. It still
  costs each holding in isolation against the full remaining FY exemption, which several holdings
  cannot all use — so the **ordering remains a documented heuristic**. The quoted tax is not: it is
  computed on the executed plan as a whole.

---

## 3. "Raises ₹X for ₹Y tax" does not add up on its own panel

Same function. `smart_raised` accumulates `- rec.tax`, the **pre-cess** figure; `smart_tax` reports
`_add_cess(...)`, the **post-cess** figure. The cash line is netted against a smaller tax than the
line beneath it reports.

Reproduced — all-short-term winners, ₹4,00,000 requested:

```
gross proceeds                      : 417,270.00
charges                             :   1,293.93
tax the panel REPORTS  (with cess)  :  24,300.19
tax the panel SUBTRACTED (no cess)  :  23,365.57
gross − charges − reported tax      : 391,675.88   <- what you actually get
"Raises" figure shown to the user   : 392,610.50   <- what it says
OVER-STATED CASH                    :     934.62
```

The per-order **Tax column also fails to sum to the headline**: ₹15,195.15 + ₹8,170.42 = ₹23,365.57,
against ₹24,300.19 printed below it. Two numbers a user can add up by eye, on one screen, that don't.

**And it silently under-delivered.** The sizing loop made **one pass** over holdings; when the 0.5%
price buffer was smaller than the tax it under-raised and never came back. Above: ₹4,00,000
requested, **₹3,92,610 raised — ₹7,389 short — with 466 SBIN shares still held**, and nothing on the
panel said so.

**Fixed.** The loop now draws from the cheapest source until it is exhausted, then the next, and
**re-costs on the ITR basis after every sale**, so it stops on cash actually received. Same case now
raises **₹4,00,064** with `shortfall = 0`; when the book genuinely cannot cover the request it says
so in a line of its own. Tax is stated **once**, where it is subtracted, and the panel reconciles
exactly: 426,320.00 − 1,321.41 − 24,934.53 = **400,064.06**, which is the figure printed.

One subtlety worth recording, because it is the same defect in miniature: the loop can draw from one
source several times, but the user places **one order per name**. Merging the display rows while
costing three split trades left the quoted tax ₹5.63 off the orders he would actually place — caught
by the cross-surface test, not by inspection. The plan is now **re-costed from scratch as the merged
orders**, so every number describes the thing beside it.

---

## 4. The holdings table's "Weight" column is diluted by idle cash

`scripts/dashboard_app.py:1950` → `Portfolio.current_weights`, which divides by
`market_value` = **cash + holdings**.

On the real account shape today:

| Ticker | Value | Weight shown | True % of stock |
|---|---|---|---|
| HCLTECH.NS | ₹16,280 | **3.3%** | **17.8%** |
| INFY.NS | ₹12,000 | 2.4% | 13.1% |
| ITC.NS | ₹12,750 | 2.6% | 14.0% |
| … | | | |
| **SUM** | ₹91,335 | **18.6%** | 100.0% |

Every line was under-stated **5.4×**, and the column did not sum to 100% — visible on its face.

**Fixed.** The column divides by `holdings_value` and is renamed **"% of equity"**. With ₹4,00,000
parked it now reads HCLTECH **17.8%** and sums to **100.0%**. `Portfolio.current_weights` is
deliberately **not** changed — `backtest/decision.py` depends on the NAV basis, and that is rule (a).

This is load-bearing, not cosmetic. The advisor enforces `max_name_fraction = 0.20` and a 30% sector
cap. A user eyeballing "3.3%" concludes he is nowhere near concentrated; HCLTECH is at **17.8%**, one
step from the cap. It is defect #74's family again, on a third surface.

---

## 5. `position_health` never got PR-2's price-continuity guard

`src/qalpha/live/position_health.py` reads raw `adj_close`. PR-2 taught `cheapness_scores` to re-base
a name whose series contains an unexplained one-day step; nobody taught the breakdown detector.

Measured on the live watchlist (panel 2026-08-24):

| Name | Cheapness, raw | Cheapness, **guarded** | Health verdict (**unguarded**) |
|---|---|---|---|
| VEDL.NS | 64.9% | **22.1%** | 🔴 breaking, **−59% / 6mo** |
| TRENT.NS | 47.5% | 13.3% | 🟢 healthy |

**Same panel, same day, same name, opposite readings.** The guard says VEDL is 22% off its high — a
normal pullback. The detector, reading the same series unguarded, calls it *"a name-specific
breakdown, not a market move"* and recommends reviewing it for exit.

**Fixed.** `position_health` takes `rebase_from` / `exclude` — the same inputs and the same
default-off contract PR-2 gave `cheapness_scores`, so the validated SIP backtest's call is bit-for-bit
unchanged (asserted by test). A re-based name is measured from its gap day, the cross-sectional
median is computed **after** re-basing so artifacts cannot set the systemic baseline either, and the
note no longer claims "~6mo" for a shorter window. VEDL now reads:

> `VEDL.NS: +2% since its Apr 2026 corporate action (+1% vs market) — healthy.`

Every live caller — the health panel, the today-brief, the buy screen's candidate flags, the
autopilot and the Telegram alert — routes through the guard; the dashboard's go through one
`_guarded_health` helper so a future caller cannot quietly reintroduce the raw path.

Before the fix the guard corrected one direction of the artifact and left the other. It propagated
**both ways**:
PR-3 pointed `position_health` at buy *candidates*, so an artifact that no longer looks cheap still
attaches a spurious 🔴 to the buy screen; and if the name is held, it produces a spurious sell
prompt. TRENT is clean here only because its gap (2026-01-01) has aged out of the 126-day lookback —
the defect bites for roughly six months after any demerger.

*(Minor, same family, **not fixed**: the tradebook panel captions `result.realized_tax` as "realized
capital-gains tax to date". That figure comes from the same backtest engine as §2 — no set-off, no
cess, no §2(42A). It is not the ITR number and is not labelled as an estimate. It is a caption on a
historical figure, not an input to an order, which is why it is the one thing left.)*

---

## 6. The Telegram scan was the unguarded path

`scripts/scan_alerts.py:_out_of_favour_names` called `cheapness_scores(prices, tickers, as_of)` with
neither `rebase_from` nor `no_tilt`, and carried no candidate-health verdict. Every guard PR-2 and
PR-3 added to the buy screen was absent from the one surface that reaches the user's phone
**unprompted**, beneath the words *"deploy 50% of idle cash now"*.

This is not hypothetical. `data/paper/alert_state.json` records `"weakness_level": "elevated"` — the
escalation alert **has fired**, and these names have already been sent.

What went out, against what this branch sends, on the same panel:

```
BEFORE:  Most out of favour: VEDL (-65% off 1y high), TRENT (-47%), IRFC (-35%).

AFTER:   Most out of favour: 🔴 IRFC (-35% off 1y high), 🔴 ITC (-33%), 🔴 INFY (-32%).
         🔴 IRFC, ITC, INFY — the §4.7 breakdown detector would flag these for
            review-for-exit if you held them. Shown, not vetoed: open the dashboard
            for the full verdict table before you buy.
         ⚠️ Price-continuity guard adjusted 2 name(s) (TRENT, VEDL) — a one-day step
            no split or dividend explains is not a discount.
```

**Both price artifacts leave the top three entirely**, replaced by genuinely pulled-back names, each
carrying the verdict the dashboard would show. Flag, never veto — the ranking is unchanged and a 🔴
name is still named, asserted by test so a later "helpful" filter cannot creep in.

Five tests added (`tests/test_scan_alerts.py`). As in `test_price_integrity`, the property under test
is **not** "VEDL is dropped" — a guard that merely dropped volatile names would pass that. It is that
an artifact must not outrank a genuine decline, and that the phone cannot be more confident than the
screen.

The health verdict this alert carries was itself computed unguarded when this fix first landed; §5
closed that, so the alert and the screen now agree on both the ranking *and* the verdict.

---

## 7. The process lesson — this is the second time

The pre-flight audit's lesson was *"chase anything surprising in your own scratch run"*. This audit's
is narrower and more actionable:

> **When you fix a defect, grep for every other caller of the thing you fixed — the same session that
> ships a fix is the session most likely to ship the defect again.**

- #74 separated shares from cash in `account_overview`. **`market_value` had two other live callers.**
  One of them (§1) was merged in the same fortnight and now reports +444%.
- PR-2 added a re-basing guard to `cheapness_scores`. **`adj_close` had two other unguarded
  consumers** — `position_health` (§5) and the Telegram scan (§6).

Both fixes were correct. Both were applied at one call site and reasoned about as if they were
applied to a concept. `grep -rn "market_value(" src/qalpha/live/ scripts/` takes four seconds and
would have found §1 on the day #74 merged.

The second recurring shape is **basis drift between surfaces**: §2 and the tradebook caption both
quote the backtest engine's tax under a real-money label, while the Sell tab quotes the ITR figure.
PR-4 built exactly the vocabulary for this — `ReturnMeasure` refuses to render without a basis. Tax
figures never got the same treatment.

---

## 8. What was changed

All six fixes are in `live/` + `scripts/` + tests. **No file under `src/qalpha/{backtest, accounting,
data, config}` is touched** — the validated funnel and the 18.2% headline are provably unchanged, and
every new guard parameter defaults to off so existing callers (the SIP backtest among them) are
bit-for-bit identical.

| Where | Change |
|---|---|
| `dashboard_app.py` | track record marks shares only; holdings column is "% of equity"; all health calls go through one `_guarded_health` helper; Raise cash shows the unverified-branch warning |
| `live/advisor.py` | `advise_raise_cash` rebuilt on the ITR basis — boundary-corrected, plan-level §70 tax, redraw-until-met, re-costed as placed orders, `shortfall` / `realized` / `boundary_demoted` surfaced |
| `live/position_health.py` | `rebase_from` / `exclude`, median computed post-rebasing, honest window label |
| `live/deploy.py` | gaps computed once over the pre-filter universe and reused by cheapness *and* both health calls |
| `scripts/scan_alerts.py`, `scripts/autopilot.py` | routed through the same guard inputs |

**522 tests, 0 skipped** (was 503). The new ones assert properties, not values: an artifact must not
outrank a genuine decline; the two tax surfaces must return the *same number* for the same shares;
the panel must add up on its own face; the guard must be off by default; and — the one that would
have caught the worst finding — a portfolio marked with parked cash must still be able to report a
loss.

**Still open, deliberately:** the tradebook panel's `realized_tax` caption (§5, a caption on history,
not an order), and `_liquidation_efficiency`'s isolated-exemption ranking, now documented as the
heuristic it is.

## 9. What is trustworthy today

- **The Sell tab is the best-built surface in the system.** §2(42A) boundary demotion, §112A, §70
  set-off, cess, the exemption, the tax-free quantity, and an explicit warning naming which
  unreconciled branch a sale touches. Nothing was found wrong with it — which is why every other tax
  surface was made to agree with it rather than the reverse. **They now return the same number for
  the same shares, asserted by test.**
- **The tradebook reconciliation panel is honest.** It refuses to claim accuracy when the replay does
  not match the broker, and says every tax figure is an estimate when it doesn't. Only its
  `realized_tax` caption is on the wrong basis.
- **The price-continuity guard and the GO scorecard's `_benchmark_covers` refusal both work** and were
  re-verified against a same-morning refresh.

## 10. Standing limitations — unchanged by this audit

- **Nobody has watched this system fall.** Every live day so far has been calm.
- **The gate has not opened.** Nothing in this audit moves the GO scorecard, and none of it should be
  read as validation.
- **Most of the tax engine has never met a broker statement** — one sell reconciled, single-lot,
  all-STCG, no loss. §2 made this worse than it looked: there was a *second* tax path on a real-money
  tab, never reconciled against anything. There is now **one** path, but it is the same
  never-reconciled one. **The first multi-lot or LTCG sale must be reconciled against the Zerodha
  Tax P&L afterwards** — that is the evidence that closes this, and no amount of code will.

## Runbook — reproducing this audit

```bash
uv run python -c "import sys; sys.path.insert(0,'scripts'); from paper import _refresh_benchmark; _refresh_benchmark()"
uv run python scripts/paper.py refresh     # NB: refreshes neither the benchmark NOR the watchlist panel
uv run python scripts/build_nifty100_watchlist.py --prices   # the panel §5/§6 read
uv run pytest -q
```

Then instantiate a `Portfolio` with **idle cash *and* holdings** — every defect in §1, §3 and §4
vanishes on a zeroed fixture, which is precisely why the suite does not catch them.
