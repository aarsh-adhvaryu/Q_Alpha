# Q-Alpha — Paper-Trading Dashboard

_Notional paper trading (no real money) of the validated tax-aware strategy. As of **2026-07-16** · generated 2026-07-16 14:28 UTC._

## At a glance

| | |
|---|---|
| Started | 2026-06-12 (34 days) |
| Notional capital | ₹200,000 |
| Equity (marked) | ₹201,828 |
| Return since start | **+0.91%** |
| Nifty 50 TRI (same window) | +2.29% |
| Cash | ₹7,335 |
| Realized tax to date | ₹0.00 |
| Rebalances | 1 |
| Strategy | shrink-weighted, annual, tax-aware (band 0.1) |

## Today's recommendation

✅ **HOLD** — holding — next scheduled rebalance on/after 2027-01-01. No orders today.

## Holdings

| Ticker | Qty | Price | Value | Weight |
|---|---|---|---|---|
| APOLLOHOSP.NS | 4 | ₹8888.00 | ₹35,552 | 17.6% |
| ASIANPAINT.NS | 14 | ₹2674.70 | ₹37,446 | 18.6% |
| BEL.NS | 98 | ₹407.10 | ₹39,896 | 19.8% |
| NTPC.NS | 113 | ₹342.45 | ₹38,697 | 19.2% |
| SUNPHARMA.NS | 22 | ₹1950.10 | ₹42,902 | 21.3% |

## Equity track record

`▁▁▁▃▄▅▅▄▃▁▃▂▄▅▆█▆▂▃▄▄▄▄▄`  (24 daily marks; full series in `paper_equity.csv`)

| Date | Equity | Return |
|---|---|---|
| 2026-07-03 | ₹204,392 | +2.20% |
| 2026-07-06 | ₹205,500 | +2.75% |
| 2026-07-07 | ₹203,899 | +1.95% |
| 2026-07-08 | ₹200,560 | +0.28% |
| 2026-07-09 | ₹201,448 | +0.72% |
| 2026-07-10 | ₹202,359 | +1.18% |
| 2026-07-13 | ₹201,872 | +0.94% |
| 2026-07-14 | ₹202,179 | +1.09% |
| 2026-07-15 | ₹202,569 | +1.28% |
| 2026-07-16 | ₹201,828 | +0.91% |

## GO readiness (criterion 6)

🟡 **NOT YET** — accumulating evidence; the run has not yet cleared every criterion (this is the expected state until it does).

- 🟡 **Track length** — 24/63 trading days — building the minimum sample for a meaningful estimate.
- 🟡 **Volatility event withstood** — no market stress event yet (worst Nifty pullback in-window -2.1%, needs ≤ -10%). A calm run can't earn a GO — waiting on a real event.
- 🟡 **Forward vs benchmark** — within noise of the benchmark (≤ 3% behind) — strategy +1.2% vs Nifty +2.3% (Δ -1.1%).
- 🟢 **Drawdown behaviour** — market-driven, within tolerance — worst live drawdown -2.4% vs Nifty -2.1% (excess -0.3%).
- 🟢 **Data integrity** — dense track record (largest gap 4 days).

## 🩺 System health & run log

**🟢 healthy** — last autonomous run **2026-07-16T14:28:35Z** (market date 2026-07-16, `daily`).

- Action: held — no action
- Decision: holding — next scheduled rebalance on/after 2027-01-01
- Equity: ₹201,828 (+0.91%) · GO: **NOT YET**
- Freshness: ✓ Up to date — last marked 2026-07-16.

_Recent runs (last 10 of 25):_

| Ran (UTC) | As of | Cmd | Action | GO | Warnings |
|---|---|---|---|---|---|
| 2026-07-16T14:28:35Z | 2026-07-16 | daily | held — no action | NOT YET | — |
| 2026-07-15T14:15:52Z | 2026-07-15 | daily | held — no action | NOT YET | — |
| 2026-07-14T14:19:54Z | 2026-07-14 | daily | held — no action | NOT YET | — |
| 2026-07-13T15:16:53Z | 2026-07-13 | daily | held — no action | NOT YET | — |
| 2026-07-12T08:58:51Z | 2026-07-10 | daily | held — no action | NOT YET | — |
| 2026-07-12T05:03:39Z | 2026-07-10 | daily | held — no action | NOT YET | — |
| 2026-07-12T04:30:34Z | 2026-07-10 | daily | held — no action | NOT YET | — |
| 2026-07-11T16:11:21Z | 2026-07-10 | daily | held — no action | NOT YET | — |
| 2026-07-10T15:07:00Z | 2026-07-10 | daily | held — no action | NOT YET | — |
| 2026-07-10T08:48:25Z | 2026-07-10 | daily | held — no action | NOT YET | — |

---
_The decision engine is the same code validated in the backtest ([reports/PHASE0_VERDICT.md](PHASE0_VERDICT.md)); this page is regenerated daily by the pipeline, not by hand._
