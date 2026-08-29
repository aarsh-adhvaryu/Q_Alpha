# Staleness audit — 2026-08-29

Run after Phases 0–4, because a redesign that supersedes things without switching them off leaves a
repo that claims one state and runs another. Checked: every module referencing superseded machinery,
every data file's **content date** (not its mtime), and what the live cron actually writes.

---

## 1. 🔴 The cron was still feeding the archived books — **fixed**

`reports/ARCHIVE_2026-08-28.md` archived the System / Shadow / Baseline books with their verdicts.
**The weekday cron kept funding and marking them anyway**, so their content dates read 2026-08-26 —
three days old, not archived at all. The repo simultaneously claimed a reset and carried on accruing
to the thing it had reset.

| File | Content date | Written by |
|---|---|---|
| `data/paper/adaptive_book.json` (System) | 2026-08-26 | `autopilot.py daily` |
| `data/paper/shadow_book.json` | 2026-08-26 | `autopilot.py daily` |
| `data/autopilot/system_track.csv` | 2026-08-26 | `autopilot.py daily` |

**Fixed:** the auto-pilot step in `paper.yml` is `if: false`, with the reason inline. It is kept for
one release rather than deleted, and replaced by the twin runner once the twin books are seeded.

⚠️ `data/paper/book.json` (the GO book) is **deliberately still marking.** Archiving is a snapshot,
not a deletion — no forward day is lost while the rebuild happens, and the clock reset is one event
on one date, recorded when it occurs.

## 2. 🔴 The old GO scorecard was still the gate — **fixed**

`live/go_scorecard.py` graded the paper book running the *validated funnel*, not the system in use.
Now carries a superseded banner and gates nothing; `live/go_gate.py` replaces it with six criteria
over the composite, benchmarked against the **equal-weight fund** rather than the cap-weighted index.

**Kept, not deleted.** The archived scorecard is the evidence for why the redesign happened, and its
`_benchmark_covers` refusal-to-grade is the pattern `go_gate` inherits.

Still importing it: `scan.py`, `dashboard.py`, `scan_alerts.py`, `paper.py` — for the Telegram
GO-flip alert and the paper dashboard. **Those are reporting surfaces, not gates**, and they move to
`go_gate` when the twin is seeded and has a verdict to report.

## 3. 🟢 `data/events/governance_events.csv` — stale by design, not a defect

Content date 2019-01-25, **2,773 days old.** Not a live feed: a frozen seed for the §3.11 governance
overlay, used only by `scripts/exp_frequency_lookback.py`, and already a **published negative** — the
momentum/quality factors never bought Yes Bank or Zee, so the overlay was a backtest no-op. Left
exactly as it is; a frozen input to a finished experiment should not drift.

## 4. 🟢 No other stale live data

Every other `.json` / `.csv` outside `archive/`, `reference/` and `fixtures/` either carries a
content date within three days or has no date to check. The Kite instrument master
(`data/reference/`) is public reference data with `scripts/refresh_instruments.py` to renew it.

---

## What is still stale, and deliberately so

- **`data/paper/book.json`** keeps marking until the twin is seeded (§1).
- **The Telegram GO-flip alert** still reads the old scorecard until the twin has a verdict.
- **`scripts/autopilot.py`** remains in the tree, unrun, for one release.

Each is a *known* pointer at a superseded thing, recorded here rather than discovered later.
