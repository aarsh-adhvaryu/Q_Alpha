# Whole-system audit — 2026-08-30

Run at the user's request after the redesign shipped: *"go through the entire system, remove what is
stale, fix what is broken, and check if the system is working."*

Checked: every module against its importers, every data file's **content date**, every claim a
surface or docstring makes against what the code does, and every path exercised end to end against
the real account.

---

## Verdict: the system works. Four defects found, all mine, all fixed.

| Path | Exercised against | Result |
|---|---|---|
| Twin daily run | the real tradebook (13 trades, gist) | ✅ 4 decisions, gate NOT YET |
| GO gate | real flows | ✅ 5 of 6 blocking, correctly |
| Tax reconciliation | the real Zerodha Tax P&L | ✅ **Δ ₹0.00** |
| Harvest | the real book | ✅ 5 candidates, 0 worth the round trip |
| Kite basket | INFY tick 0.10 | ✅ ₹1,140.05 → ₹1,140.10, on grid |
| Dashboard surfaces | import + attribute check | ✅ all present |
| Gates | — | ✅ 660 tests, ruff, format, mypy |

---

## 1. 🔴 `backtest_phase4.py` claimed to test the hedge, and did not

Its docstring said *"each component **alone** — buy screen, exits, **hedge**"*. The file contained no
hedge test, and `reports/PHASE4_BACKTEST.md` was silent on it. A claim in a docstring is a claim.

**Fixed by making it true**, not by deleting the sentence — the hedge is now backtested inside the
composite, on the screen's own equity curve, hedged against unhedged so the difference is the overlay
and nothing else, including its roll cost and the 30% F&O business-income tax.

## 2. 🔴 `backtest/overlay.py` was graduated on a claim that turned out false

Moved into the product in Phase 1 as *"needed for the Phase 4 composite backtest"*. Phase 4 was then
written without it and it sat unimported — the graduation rule (§2a) says code moves when a
pre-registered test passes, and no test ever used it.

**Returned to `research/backtest/exposure_overlay.py`**, and it belongs there on the merits too: it
is the **exposure** overlay — de-risking by *selling* — which is a published negative three times
over. The research HMM sell-overlay lost to capital-gains tax; Phase 4's §4.7 exits finished
₹69,63,833 behind buy-and-hold; the annual trim also lost. The overlay the product uses is the
futures hedge, which keeps every share at ₹0 capital-gains tax.

## 3. 🔴 The README's front door was materially out of date

It read: *"The only thing between here and real-money go-live is **calendar time**… No engineering
blocks it."* **Real money went in on 2026-08-27**, before the gate opened, and the redesign happened
precisely because engineering *did* block it — the old gate graded the wrong book.

**Rewritten** to lead with: real money is invested before the gate opened; the gate is shut; and
Phase 4's finding that **76% of the headline edge is the purchasable equal-weight premium**, so the
system's real case is **+2.35 pp/yr in-sample**, not the ~6 pp the index comparison implies.

## 4. ✅ Data: nothing stale that should be fresh

Every live artifact is within a day. The dated files that look old are **frozen evidence** and must
not move: `PHASE0_VERDICT.md`, `PREFLIGHT_AUDIT.md`, `FORWARD_RUN_1_VOID.md`, the phase-0 reports,
and `data/events/governance_events.csv` (a seed for a published negative, used only by an experiment).
A finished experiment's input drifting would be the defect, not its age.

---

## Known-and-deliberate, carried forward

- **`data/paper/book.json` keeps marking.** Archiving is a snapshot; the clock reset is one dated
  event, recorded when it happens.
- **Telegram's GO-flip alert still reads the old scorecard.** It reports a verdict the dashboard no
  longer uses; it moves to `go_gate` once the twin has a verdict worth pushing.
- **`scripts/autopilot.py` remains, unrun** (`if: false`), for one release.
- **The twin has never run under the cron** — every run so far has been local. Next weekday 12:23 UTC.

## What has not changed

**The gate is shut.** Criterion 1 needs 12 months of real cash flows (≈ August 2027); criterion 2
needs a −10% fall nobody has seen. Nothing in this audit moves either.
