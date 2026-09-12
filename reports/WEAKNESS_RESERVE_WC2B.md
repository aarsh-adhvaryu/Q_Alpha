# WC-2b — is the deep-only reserve an effect, or fitted to this history?

_Run 2026-09-12 14:08 UTC. Registered in [PREREGISTRATION_WEAKNESS_RESERVE.md](PREREGISTRATION_WEAKNESS_RESERVE.md) §8, after WC-2's grid was seen and before this script was written._

WC-2 found the deep-only reserve worth **+6.27%** at `r=0.25` and **+12.23%** at `r=0.50` over fourteen years. One path, eleven deep months, about seven episodes, COVID supplying four of them. Two attacks: split the period, and move the threshold that defines *deep*.

Each row is measured against **its own control** — the same period and the same threshold, deploying everything on arrival. `r` is the fraction of an ordinary month's ₹50,000 held back; the whole reserve goes in on a deep month.

| Period | `deep` at | `r` | Terminal | vs its control | Releases |
|---|---:|---:|---:|---:|---:|
| full 2012-2026 | -10% | 25% | ₹31,036,052 | **+3.25%** | 20 |
| full 2012-2026 | -10% | 50% | ₹31,921,349 | **+6.20%** | 20 |
| full 2012-2026 | -12% | 25% | ₹31,942,979 | **+6.27%** | 11 |
| full 2012-2026 | -12% | 50% | ₹33,736,105 | **+12.23%** | 11 |
| full 2012-2026 | -15% | 25% | ₹31,643,463 | **+5.27%** | 7 |
| full 2012-2026 | -15% | 50% | ₹33,197,304 | **+10.44%** | 7 |
| first half 2012-2019 | -10% | 25% | ₹7,078,249 | **+0.93%** | 9 |
| first half 2012-2019 | -10% | 50% | ₹7,132,005 | **+1.70%** | 9 |
| first half 2012-2019 | -12% | 25% | ₹7,049,955 | **+0.53%** | 4 |
| first half 2012-2019 | -12% | 50% | ₹7,075,241 | **+0.89%** | 4 |
| first half 2012-2019 | -15% | 25% | ₹6,956,335 | **-0.81%** | 2 |
| first half 2012-2019 | -15% | 50% | ₹6,900,781 | **-1.60%** | 2 |
| second half 2019-2026 | -10% | 25% | ₹8,929,860 | **+0.74%** | 11 |
| second half 2019-2026 | -10% | 50% | ₹8,977,393 | **+1.28%** | 11 |
| second half 2019-2026 | -12% | 25% | ₹8,936,013 | **+0.81%** | 7 |
| second half 2019-2026 | -12% | 50% | ₹8,996,684 | **+1.49%** | 7 |
| second half 2019-2026 | -15% | 25% | ₹8,817,718 | **-0.53%** | 5 |
| second half 2019-2026 | -15% | 50% | ₹8,767,586 | **-1.09%** | 5 |

## Verdict

**THE LEVER STAYS DISCONNECTED.** 4 of 18 cells failed: first half 2012-2019 @ -15%, r=25%; first half 2012-2019 @ -15%, r=50%; second half 2019-2026 @ -15%, r=25%; second half 2019-2026 @ -15%, r=50%.

**The classifier is checked, not assumed.** `market_weakness` hard-codes −12%, so this test reproduces its classification with the threshold exposed — and the run asserts that copy equals the live function on **every payday** at the shipped −12% before any row is computed. A silent drift there would mean measuring a rule nobody runs.

> **The threshold perturbation is the sharper of the two attacks.** −12% was not chosen blind: it was set by people who had seen this history. A reserve that pays at −12% and not at −10% or −15% is a rule fitted to where this particular path's drawdowns happened to fall, and it would not survive contact with a different market.

> **One path, either way.** Fourteen years of one market, and no 2008-style event in it. Passing every cell here makes the effect harder to dismiss. It does not make it proven, and nothing in this file authorizes anything.
