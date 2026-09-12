# PO-2 — are the picks working, or is the pacing what loses?

_Run 2026-09-12 12:11 UTC. Registered in [PREREGISTRATION_POLICY_REPLAY.md](PREREGISTRATION_POLICY_REPLAY.md) §9 before it ran._

Every month the **whole** ₹50,000 is spent immediately on the screen's top-K by `cheapness_scores` — the live ranking — equal-weighted, whole shares, Zerodha costs charged. **No weakness pacing, no cash held back, no exits, nothing ever sold.** This isolates the picks from everything else the policy does.

Point-in-time Nifty-50, which contains the 36 names that left the index. Contributed ₹8,850,000 over fourteen years.

| | Terminal | vs contributed | vs the fund |
|---|---:|---:|---:|
| Screen, top-8, fully invested | ₹30,058,634 | +239.6% | **+9.1%** |
| Screen, top-15, fully invested | ₹29,298,736 | +231.1% | **+6.3%** |
| Screen, top-30, fully invested | ₹28,007,476 | +216.5% | **+1.7%** |
| `BASELINE_EW` — the bar | ₹27,549,986 | +211.3% | — |
| NIFTYBEES — the floor | ₹21,799,934 | +146.3% | -20.9% |

| Screen, top-8, **with the live `exclude_breaking` filter** | ₹27,860,168 | +214.8% | **+1.1%** |

**The last row is the mechanism.** It is the same top-8, the same money on the same days — with the one filter the live deploy applies: refuse to buy a name in §4.7 breakdown. The deepest-pulled-back names are exactly the ones that trip it, so the filter removes the part of the ranking that was carrying the return.

**The K=30 row is the harness check, not a strategy.** Thirty names out of a fifty-name index must converge on the equal-weight baseline. If it does not, this page is wrong.

