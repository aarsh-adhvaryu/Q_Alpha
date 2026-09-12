# WC-1 — does buying into weakness actually pay?

_Run 2026-09-12 12:34 UTC. Registered in [PREREGISTRATION_WEAKNESS_COHORTS.md](PREREGISTRATION_WEAKNESS_COHORTS.md) before this script existed._

Each month's ₹50,000 buys the top-8 by `cheapness_scores`, equal-weighted, whole shares, Zerodha costs charged. **Nothing is ever sold.** Every month is tracked as its own cohort against the same ₹50,000 into `BASELINE_EW` on the same day — same money, same day, only the choice differs. Cohorts are grouped by `market_weakness` **as it was on the day the money went in**, from data up to that day only.

*Multiple* is what ₹1 became. *vs fund* is that cohort against the fund over **its own** holding period, which is the number comparable across groups — a 2012 cohort has had fourteen years to compound and a 2026 one has had weeks.

### Point-in-time Nifty-50 — the headline, survivorship-free

| Market on the day | Cohorts | Median multiple | Median vs fund | Beat the fund |
|---|---:|---:|---:|---:|
| **deep** | 11 | ×5.16 | +30.3% | 7/11 (64%) |
| **elevated** | 60 | ×3.17 | +2.0% | 30/60 (50%) |
| **normal** | 106 | ×3.11 | -3.1% | 44/106 (42%) |

### Static Nifty-100 — the live universe, and SURVIVORSHIP-CONTAMINATED

| Market on the day | Cohorts | Median multiple | Median vs fund | Beat the fund |
|---|---:|---:|---:|---:|
| **deep** | 9 | ×15.01 | +82.2% | 9/9 (100%) |
| **elevated** | 49 | ×8.03 | +15.3% | 37/49 (76%) |
| **normal** | 98 | ×6.00 | +2.4% | 52/98 (53%) |

> **The second table is not evidence and is not the headline.** `nifty100_watchlist.csv` is a list of *today's* members, so every name in it survived to be there — a bias measured at **~3.8%/yr**, more than the effect being looked for. It is shown because it is the universe the money actually runs on, and because the gap between the two tables is itself informative.

> **The point-in-time Nifty-100 does not exist and cannot currently be built.** NIFTY 100 = NIFTY 50 + NIFTY Next 50, and the Next-50 reconstitution history is not obtainable — Wikipedia carries no Next-50 change section and news coverage is fragmentary, so any list assembled from it would have holes, and a hole silently restores the bias it was built to remove. `scripts/build_nifty100_pit.py` refuses to write for that reason.

> **One path.** Fourteen years of one market, 176 heavily-overlapping cohorts, and India 2012–2026 contained no 2008-style event. The deepest drawdown in the sample is the 2020 COVID fall, and one crash is not a sample of crashes.
