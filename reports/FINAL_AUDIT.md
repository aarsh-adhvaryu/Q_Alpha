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
| 1 | Track record (#71) | "You are **ahead by ₹4,01,677**" | ahead by **₹1,677** | no — one line |
| 2 | Raise cash | "₹620 tax" | **₹9,570** tax | no |
| 3 | Raise cash | "Raises ₹3,92,610.50" | ₹3,91,675.88 | no |
| 4 | Holdings table | HCLTECH "**3.3%**" weight | **17.8%** of the portfolio | no |
| 5 | Position health | VEDL "−59%, breaking down" | a demerger step, ~−22% | no |
| 6 | Telegram scan | "Most out of favour: **VEDL −65%**" | a demerger step, −22% | **yes, this PR** |

Only #6 was in the scope agreed for this session. #1–#5 are reported, reproduced, and left for the
user's decision — with a recommended order in §8.

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

**Fix:** `portfolio.holdings_value(prices)`. One word. It is left unapplied only because it was
outside the scope agreed for this session.

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

Two aggravating details on the same surface:

- **The `_unverified_branch_warning` is wired into the Sell tab only** (`dashboard_app.py:1756`). The
  Raise-cash tab sells *multiple names across multiple lots by construction* — it exercises the
  multi-lot, LTCG, set-off and exemption branches every single time, and it is the one tab that never
  warns they are unreconciled. `RaiseCashAdvice` carries no `realized` field, so the helper would
  no-op even if called.
- **`_liquidation_efficiency` ranks each holding against the full FY exemption independently**
  (`preview_sell` is non-mutating). Several holdings can each look "free within the exemption" when
  together they exhaust it, so the *ordering* — the tab's entire value proposition — is computed on an
  assumption the execution then violates. The executed tax is right; the plan may not be the cheapest.

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

**And it silently under-delivers.** The sizing loop makes **one pass** over holdings; when the 0.5%
price buffer is smaller than the tax, it under-raises and never comes back for more. Above: ₹4,00,000
requested, **₹3,92,610 raised — ₹7,389 short — with 466 SBIN shares still held**, and nothing on the
panel says so. If the money is needed for something real, the orders leave him short.

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

Every line is under-stated **5.4×**, and the column does not sum to 100% — visible on its face.

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

The guard fixed one direction of the artifact and left the other. It now propagates **both ways**:
PR-3 pointed `position_health` at buy *candidates*, so an artifact that no longer looks cheap still
attaches a spurious 🔴 to the buy screen; and if the name is held, it produces a spurious sell
prompt. TRENT is clean here only because its gap (2026-01-01) has aged out of the 126-day lookback —
the defect bites for roughly six months after any demerger.

*(Sixth, minor, same family: the tradebook panel captions `result.realized_tax` as "realized
capital-gains tax to date". That figure comes from the same backtest engine as §2 — no set-off, no
cess, no §2(42A). It is not the ITR number and is not labelled as an estimate.)*

---

## 6. The Telegram scan was the unguarded path — **fixed in this PR**

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

⚠️ **The health verdict this alert now carries is itself computed unguarded** (§5). The alert now
*matches the dashboard*, which is what this fix set out to do; it does not make the underlying
detector correct. Fixing §5 fixes both surfaces at once.

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

## 8. Recommended order

Nothing here is applied beyond §6. In priority order:

1. **§1, the track record** — one word (`market_value` → `holdings_value`), and it is the panel whose
   entire purpose is defeated. Until it is fixed, **ignore that panel completely**; it is currently
   incapable of reporting bad news.
2. **§5, `position_health`** — thread PR-2's `rebase_from`/`no_tilt` through it. Fixes the buy screen's
   🔴 flags, the exit prompts, and the alert this PR just shipped, in one change.
3. **§4, the holdings weight** — divide by `holdings_value`, or relabel the column "% of account".
   Cheap, and it currently mis-states concentration 5×.
4. **§2 and §3, Raise cash** — the largest amount of work: route it through the same ITR path as
   `advise_sell`, net `smart_raised` against the same tax it reports, loop until the target is met or
   say it fell short, and wire in the unverified-branch warning.

## 9. What is trustworthy today

- **The Sell tab is the best-built surface in the system.** §2(42A) boundary demotion, §112A, §70
  set-off, cess, the exemption, the tax-free quantity, and an explicit warning naming which
  unreconciled branch a sale touches. Nothing was found wrong with it. **When the two tabs disagree,
  the Sell tab is right.**
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
  all-STCG, no loss. §2 makes this worse than it looked: there is a *second* tax path, on a
  real-money tab, that has never been reconciled against anything at all.

## Runbook — reproducing this audit

```bash
uv run python -c "import sys; sys.path.insert(0,'scripts'); from paper import _refresh_benchmark; _refresh_benchmark()"
uv run python scripts/paper.py refresh     # NB: refreshes neither the benchmark NOR the watchlist panel
uv run python scripts/build_nifty100_watchlist.py --prices   # the panel §5/§6 read
uv run pytest -q
```

Then instantiate a `Portfolio` with **idle cash *and* holdings** — every defect in §1, §3 and §4
vanishes on a zeroed fixture, which is precisely why the suite does not catch them.
