# Integration audit + remediation plan (2026-08-17)

**Status: AUDIT ONLY — no code changed. Awaiting the user's call on what to execute.**

## Why this exists

The user's verdict after reading the dashboard end to end: *"it looks the system has 400000, and the
real go has 200000, 2 different things and 2 different baselines, at the same time — i am unable to
trust the advisor for now."*

That is a legitimate product failure independent of whether the maths is right. A prior audit pass
was run from screenshots alone and produced four blockers. **This pass verified every one of them
against the committed data and the source.** Two survived, one survived in altered form, and two
were refuted — the screenshot reading was wrong. Recording both outcomes here, because a false
blocker is as expensive as a missed one.

Every claim below is reproducible from files in this repo. Commands are given.

---

## CONFIRMED — B2 · Shadow is not a clean twin, and the mechanism is now known

**This is the finding that matters. It invalidates ENDGAME CONTRACT pillar 3 as currently measured.**

`scripts/autopilot.py:594` deploys both books through the *same* advisor on the *same* date, varying
only the amount:

```python
for key, bk, use_ai in (("system", system, True), ("shadow", shadow, False)):
    amt = book_deploy_amount(wallets[key], level, signal, ai=use_ai)
    basket, rationale = _deploy_from_wallet(bk, amt, watchlist, wl_sectors, merged, nifbees, as_of)
```

The intent (per `docs/PREREGISTRATION_autopilot.md`) is that the AI tilt changes **size only**, so
System − Shadow isolates the AI's contribution. If that held, both baskets would post an *identical
percentage* return and differ only in rupees.

They do not. From `data/autopilot/ledger.json`, same date, same advisor:

| Date | Book | Deployed | Basket return | Benchmark |
|---|---|---:|---:|---:|
| 2026-07-10 | SYS | ₹93,750 | **+18.64%** | +1.73% |
| 2026-07-10 | SHD | ₹75,000 | **+21.26%** | +1.73% |

₹93,750 / ₹75,000 = 1.25× — exactly the AI tilt, as designed. But the basket returns are **2.6pp
apart**, which the sizing rule cannot produce.

**Root cause — `advise_deploy_into_weakness` is amount-dependent in *composition*, not just size:**

1. `max_name_fraction=0.20` ([deploy.py](src/qalpha/live/deploy.py)) drops any name whose *single
   share* costs more than 20% of the deploy. A smaller deploy therefore has a **different investable
   universe** — pricier names fall out.
2. The allocator buys **whole shares** greedily against the largest shortfall, so different amounts
   land on different integer quantities and different tail names.

Both are correct, deliberate features of the advisor. They are simply fatal to the experiment: the
tilt silently changes *what is bought*, so **System − Shadow = ₹1,541 conflates "did the AI's sizing
help?" with "did two different baskets perform differently?"** No amount of further runtime fixes
this; it is a design fault in the comparison.

**Reproduce:**
```bash
uv run python -c "
import json; L=json.load(open('data/autopilot/ledger.json'))
for d in L:
    if d['as_of']=='2026-07-10' and d['book'] in ('SYS','SHD'):
        print(d['book'], d['amount'], d['outcome_return_pct'])"
```

### Fix options (user's call)

| Option | What it does | Cost |
|---|---|---|
| **A — tilt the wallet, not the basket** (recommended) | Both books compute the basket at the **same notional amount**, then scale executed quantities by the tilt. Composition identical, size differs → clean attribution. | Re-seed the trio; current System−Shadow history is void. |
| **B — accept and relabel** | Keep the mechanism, stop calling it an AI attribution. Report it as "AI-paced system vs unpaced system", a *joint* effect. | No re-seed. Pillar 3 becomes unanswerable. |
| **C — freeze the shadow** | Retire System vs Shadow; report only System vs Baseline. | No re-seed. One fewer question answered. |

Whichever is chosen, `docs/PREREGISTRATION_autopilot.md` gets a **disclosed amendment** (repo rule:
negatives get published, amendments are recorded, never rewritten).

---

## CONFIRMED — B4 · The AI brief's stock analysis feeds nothing

`grep -rn 'ai_brief' --include='*.py' src scripts` shows the only importer is its own generator; the
dashboard reads `reports/ai_brief.md` as markdown. The sole machine consumer is `parse_ai_signal` →
`signal_tilt` → deploy **amount**.

So the brief's "Watchlist names affected" (TECHM, HCLTECH, TCS, TATASTEEL, HINDALCO, AXISBANK) has
**no consumer**. It shares a page with a buy list (VEDL, TRENT, IRFC, HDFCLIFE, ITC) chosen by a
drawdown ranking, with zero intersection. A reader top-to-bottom will infer causation that does not
exist.

This is *architecturally intended* — rule (a) keeps the LLM out of the calculator, and the brief is
labelled context-only. The problem is purely presentational: **the page implies a link it does not
have**, at ~57k input tokens/day.

**Fix (cheap, no experiment impact):** render only the `SIGNAL:` line and the tilt it produced;
move the narrative behind a collapsed "AI commentary (nothing here is acted on)" expander, or drop
the watchlist section from the prompt.

---

## CONFIRMED (altered) — B1 · The experiment and the GO ride different strategies

Verified windows and cadences:

| Book | File | Marks | Window | Rebalance |
|---|---|---:|---|---|
| GO (criterion 6) | `data/paper/book.json` | 45 | 2026-06-12 → 08-14 | **annual** |
| System | `data/paper/adaptive_book.json` | 26 | 2026-07-10 → 08-14 | **§4.6-gated, evaluated daily** |

These are genuinely different rebalance policies over different windows. **This is by design and
documented** (CLAUDE.md: the System book is the former smart-rebalance book upgraded in place), so it
is *not* a code bug — the prior audit overstated it.

What is wrong is the **claim** on the page: *"the System book above is the full system being
proven."* It proves the adaptive variant. The real-money GO rides the annual book. Attribution on
one does not transfer to the other, and nothing on the page says so.

**Fix:** relabel. The System book is "the full system, adaptive-cadence variant — not the GO book".
One sentence, no re-seed.

---

## REFUTED — B3 · The baseline is fine; the two *pages* are not comparable

The prior audit claimed the NIFTYBEES baseline was mis-seeded and 2.7pp off the index. **The data
says otherwise.** `data/autopilot/system_track.csv` row 1:

```
2026-07-10, ... , baseline_value=350000.0, baseline_profit=0.0, baseline_return_pct=0.0
```

All three books start **2026-07-10 at ₹350,000**, baseline return exactly `0.0`. The trio shares a
window; that comparison is valid.

The `+3.69%` Nifty TRI figure is on the **GO page**, measured since **2026-06-12** — a window 28 days
longer. Comparing it to the baseline's `+0.98%` is a cross-page mismatch the *user* was invited to
make, not one the code makes.

**Fix:** presentational only. Never render a return from one book beside a return from another
without both windows on screen.

---

## REFUTED — H2 · The hit-rate verdicts are correct

The prior audit read the screenshot as marking `SYS +0.4% vs Nifty +0.7%` as *worked*. The ledger's
actual figures are consistent with `resolve_decision` (`gap > _WORK_TOL` → worked):

| Date | Book | Basket | Bench | Verdict | Correct? |
|---|---|---:|---:|---|---|
| 2026-07-13 | SHD | 1.31% | 1.87% | didn't | ✓ |
| 2026-07-14 | SYS | 3.31% | 2.11% | worked | ✓ |
| 2026-07-15 | SYS | 1.31% | 1.70% | flat | ✓ |
| 2026-07-17 | SYS | 8.75% | 0.68% | worked | ✓ |

**Not a bug.** The small-text reading was wrong.

Standing caveat unchanged: **n = 5 resolved decisions.** The page's own "low power early — not a
verdict" is the correct framing and should stay.

---

## CONFIRMED — H4 · The "Equity" tile includes cash

`data/paper/book.json` stores `equity` as **total book value**:

```json
{"date": "2026-08-14", "equity": "201903.98", "cash": "7335.38"}
```

The screenshot's holdings sum to ₹193,388; + ₹7,335 cash = ₹200,723 = the "Equity" tile. Shown
beside a separate "Cash ₹7,335" tile, it reads as additive and invites a ₹208k mental total.

**Fix:** relabel the tile **Book value**, or make it `equity − cash`. One line.

---

## Verified sound — no action

- Deploy arithmetic exact to the rupee (₹99,545.46 + ₹317.15 + ₹137.39 = ₹100,000.00).
- Track CSV internally consistent (8,135 / 400,000 = 2.03%).
- Trio funded equally — `_inject_trio` credits system/shadow/baseline the same amount, so no top-up
  can bias the comparison.
- The disclaimers are honest throughout: "fake money, no real orders", "low power early", "GO
  verdict: NOT YET".

---

## Recommended order

| # | Item | Effort | Blocks the GO? |
|---|---|---|---|
| 1 | **Decide B2** (option A / B / C) + amend the pre-registration | decision, then ~half a day for A | **Yes — pillar 3** |
| 2 | Relabel the System book (B1) — it is not the GO book | 1 sentence | No, but it misleads |
| 3 | Relabel Equity → Book value (H4) | 1 line | No |
| 4 | Never render two books' returns side by side without windows (B3) | small | No |
| 5 | Collapse the AI narrative to the SIGNAL line (B4) | small | No |

**Items 2–5 are an afternoon and touch presentation only.** Item 1 is a real decision about the
experiment's design, and under option A it voids the current System−Shadow history — which is the
honest cost of having measured the wrong thing for six weeks.

## On running code to verify

Everything in this document was verified by reading committed data and source. Where a fix needs a
run to confirm (e.g. option A's claim that identical-notional baskets produce identical percentage
returns), that is a short scripted check against the existing panels — say the word and it gets
written, run, and its output pasted back before any behaviour changes.

**Nothing has been changed. Awaiting instruction.**
