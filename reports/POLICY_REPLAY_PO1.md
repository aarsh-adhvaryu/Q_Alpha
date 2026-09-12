# PO-1 — the policy the money runs, replayed on a universe that includes the dead

_Run 2026-09-12 11:50 UTC. Registered in [PREREGISTRATION_POLICY_REPLAY.md](PREREGISTRATION_POLICY_REPLAY.md) before this script existed._

**The rule under test is the rule itself.** Every trading day this builds a `Market` and calls `qalpha.live.runner.step` — the function `SYSTEM` calls every evening. Nothing here reimplements the screen, the §4.7 exits, the governor or the sizing.

₹50,000 on the first trading day of each month, to **every** line below, on the same dates. Total contributed: **₹8,850,000**. Costs and tax are charged to the policy; the fund is charged 0.41%/yr.

| | Final value | vs contributed | CAGR (terminal) | Max drawdown | Tax paid |
|---|---:|---:|---:|---:|---:|
| POLICY (the live rule) | ₹12,333,754 | +39.4% | +2.29% | -41.4% | ₹2,095,762 |
| BASELINE_EW (the bar) | ₹27,549,986 | +211.3% | +8.04% | -35.8% | ₹0 |
| BASELINE / NIFTYBEES (floor) | ₹21,799,934 | +146.3% | +6.33% | -35.5% | ₹0 |
| — diagnostic: same policy, §4.7 exits OFF | ₹20,023,958 | +126.3% | +5.72% | -42.2% | ₹25,777 |

**Against the bar: ₹-15,216,232** (-55.23% of the fund's terminal wealth).

**The exits own the gap.** With them on: 5,488 exits, ₹2,095,762 of tax, terminal ₹12,333,754. With them off: 0 exits, ₹25,777 of tax, terminal ₹20,023,958. This is the already-proven result reproduced on a clean universe by the live code path: **selling to manage risk loses to the tax.**

4463 buy decision(s) · 5488 §4.7 exit(s) · 23 names held at the end.

## Year by year

Every year is printed. Choosing a favourable window afterwards is the failure the registration exists to prevent.

| Year | Policy | BASELINE_EW | Gap |
|---|---:|---:|---:|
| 2012 | +1090.0% | +1273.2% | -183.1% |
| 2013 | +66.5% | +88.5% | -22.1% |
| 2014 | +107.0% | +89.4% | +17.6% |
| 2015 | +6.3% | +17.3% | -11.0% |
| 2016 | +13.1% | +24.8% | -11.7% |
| 2017 | +73.3% | +43.7% | +29.6% |
| 2018 | -10.6% | +6.6% | -17.2% |
| 2019 | +0.2% | +12.2% | -12.0% |
| 2020 | +12.7% | +29.2% | -16.4% |
| 2021 | +38.6% | +39.9% | -1.3% |
| 2022 | -0.5% | +12.9% | -13.4% |
| 2023 | +42.3% | +33.3% | +8.9% |
| 2024 | +12.7% | +13.4% | -0.7% |
| 2025 | +2.2% | +17.4% | -15.1% |
| 2026 | -6.3% | -2.0% | -4.3% |

> **This is not an out-of-sample test of the screen.** Its parameters were not chosen blind to 2012–2026, so this is a replay of a known configuration — *here is what this policy would have done*, not *here is what an unseen policy did*. And it is one path: terminal wealth over one history is a single draw, and a positive result is a necessary condition for the edge being real, nothing more.

> **The universe is Nifty-50 point-in-time, not the live Nifty-100.** It contains the 36 names that left the index, so it is survivorship-free — but the money runs on a static Nifty-100 watchlist whose bias is measured at ~3.8%/yr. The Next-50 change history needed to build the point-in-time Nifty-100 does not exist in any obtainable form; a list assembled from news would have holes, and a hole silently restores the bias.
