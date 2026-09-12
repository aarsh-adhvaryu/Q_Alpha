# WC-2 — does holding money back for deep drawdowns actually pay?

_Run 2026-09-12 13:57 UTC. Registered in [PREREGISTRATION_WEAKNESS_RESERVE.md](PREREGISTRATION_WEAKNESS_RESERVE.md) before this script existed._

`WC-1` found money deployed in a deep drawdown beat the fund by a median **+30.3%**. Every WC-1 cohort was **fully invested on arrival**, so it could not say whether *withholding* money on ordinary months to have more in deep ones is worth doing. This does.

Each month ₹50,000 arrives. On a `normal` day a fraction `r` is held back in cash; on a release day the allowance **and the whole reserve** go in. Everything deployed buys the top-8 by `cheapness_scores`, equal-weighted, whole shares, Zerodha costs charged, **nothing ever sold**. Point-in-time Nifty-50.

**The reserve counts as part of the portfolio.** Money held back is money this policy is responsible for; excluding it would score the strategy on only the capital it chose to use, which is how parked SIP cash once read as +444% performance.

| Policy | Terminal | vs control | vs the fund | Mean cash | Releases |
|---|---:|---:|---:|---:|---:|
| control — deploy everything, always | ₹30,058,634 | **+0.00%** | +9.1% | 0.1% | 11 |
| hold back 25% on normal, release on deep | ₹31,942,979 | **+6.27%** | +15.9% | 3.6% | 11 |
| hold back 25% on normal, release on deep+elevated | ₹29,761,855 | **-0.99%** | +8.0% | 1.4% | 71 |
| hold back 50% on normal, release on deep | ₹33,736,105 | **+12.23%** | +22.5% | 7.2% | 11 |
| hold back 50% on normal, release on deep+elevated | ₹29,642,627 | **-1.38%** | +7.6% | 2.8% | 71 |
| `BASELINE_EW` — the bar | ₹27,549,986 | — | — | 0.0% | — |

Contributed ₹8,850,000 over fourteen years. Largest reserve ever accumulated, across the non-control cells: ₹800,000.

**The control is the harness check.** `r = 0.00` is *deploy everything, always* — the current live behaviour — and it must reproduce PO-2's top-8 terminal of **₹30,058,634**. If it does not, nothing else on this page may be read.

> **One path.** Fourteen years of one market. The deep episodes are about seven events with COVID supplying four of the eleven months, so this result is substantially a statement about whether one reserve release in 2020 happened to land well.

> **This is market timing**, and it sits against this repository's own strongest proven result: trading less and staying invested beat the alternatives net of cost and tax. A reserve is the first mechanism here that deliberately stays out of the market.
