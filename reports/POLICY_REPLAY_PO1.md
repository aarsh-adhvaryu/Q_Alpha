# PO-1 — the policy the money runs, replayed on a universe that includes the dead

_Run 2026-09-12 13:42 UTC. Registered in [PREREGISTRATION_POLICY_REPLAY.md](PREREGISTRATION_POLICY_REPLAY.md) before this script existed._

**The rule under test is the rule itself.** Every trading day this builds a `Market` and calls `qalpha.live.runner.step` — the function `SYSTEM` calls every evening. Nothing here reimplements the screen, the §4.7 exits, the governor or the sizing.

₹50,000 on the first trading day of each month, to **every** line below, on the same dates. Total contributed: **₹8,850,000**. Costs and tax are charged to the policy; the fund is charged 0.41%/yr.

| | Final value | vs contributed | CAGR (terminal) | Max drawdown | Tax paid |
|---|---:|---:|---:|---:|---:|
| POLICY (the live rule) | ₹13,191,363 | +49.1% | +2.75% | -37.7% | ₹2,401,804 |
| BASELINE_EW (the bar) | ₹27,549,986 | +211.3% | +8.04% | -35.8% | ₹0 |
| BASELINE / NIFTYBEES (floor) | ₹21,799,934 | +146.3% | +6.33% | -35.5% | ₹0 |
| — diagnostic: same policy, §4.7 exits OFF | ₹20,138,663 | +127.6% | +5.76% | -37.7% | ₹53,924 |

**Against the bar: ₹-14,358,623** (-52.12% of the fund's terminal wealth).

**The exits own the gap.** With them on: 4,278 exits, ₹2,401,804 of tax, terminal ₹13,191,363. With them off: 0 exits, ₹53,924 of tax, terminal ₹20,138,663. This is the already-proven result reproduced on a clean universe by the live code path: **selling to manage risk loses to the tax.**

2332 buy decision(s) · 4278 §4.7 exit(s) · 14 names held at the end.

## Year by year

Every year is printed. Choosing a favourable window afterwards is the failure the registration exists to prevent.

| Year | Policy | BASELINE_EW | Gap |
|---|---:|---:|---:|
| 2012 | +1017.6% | +1273.2% | -255.6% |
| 2013 | +50.2% | +88.5% | -38.4% |
| 2014 | +134.0% | +89.4% | +44.6% |
| 2015 | +22.2% | +17.3% | +4.9% |
| 2016 | +8.8% | +24.8% | -16.0% |
| 2017 | +83.8% | +43.7% | +40.1% |
| 2018 | -17.3% | +6.6% | -23.9% |
| 2019 | +11.4% | +12.2% | -0.8% |
| 2020 | +12.6% | +29.2% | -16.5% |
| 2021 | +42.6% | +39.9% | +2.6% |
| 2022 | -1.6% | +12.9% | -14.5% |
| 2023 | +34.4% | +33.3% | +1.1% |
| 2024 | +17.8% | +13.4% | +4.4% |
| 2025 | -1.3% | +17.4% | -18.7% |
| 2026 | -10.7% | -2.0% | -8.7% |

> **This is not an out-of-sample test of the screen.** Its parameters were not chosen blind to 2012–2026, so this is a replay of a known configuration — *here is what this policy would have done*, not *here is what an unseen policy did*. And it is one path: terminal wealth over one history is a single draw, and a positive result is a necessary condition for the edge being real, nothing more.

> **The universe is Nifty-50 point-in-time, not the live Nifty-100.** It contains the 36 names that left the index, so it is survivorship-free — but the money runs on a static Nifty-100 watchlist whose bias is measured at ~3.8%/yr. The Next-50 change history needed to build the point-in-time Nifty-100 does not exist in any obtainable form; a list assembled from news would have holes, and a hole silently restores the bias.
