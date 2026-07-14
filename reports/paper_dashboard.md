# Q-Alpha — Paper-Trading Dashboard

_Notional paper trading (no real money) of the validated tax-aware strategy. As of **2026-07-14** · generated 2026-07-14 14:19 UTC._

## At a glance

| | |
|---|---|
| Started | 2026-06-12 (32 days) |
| Notional capital | ₹200,000 |
| Equity (marked) | ₹202,179 |
| Return since start | **+1.09%** |
| Nifty 50 TRI (same window) | +2.05% |
| Cash | ₹7,335 |
| Realized tax to date | ₹0.00 |
| Rebalances | 1 |
| Strategy | shrink-weighted, annual, tax-aware (band 0.1) |

## Today's recommendation

✅ **HOLD** — holding — next scheduled rebalance on/after 2027-01-01. No orders today.

## Holdings

| Ticker | Qty | Price | Value | Weight |
|---|---|---|---|---|
| APOLLOHOSP.NS | 4 | ₹8900.50 | ₹35,602 | 17.6% |
| ASIANPAINT.NS | 14 | ₹2641.00 | ₹36,974 | 18.3% |
| BEL.NS | 98 | ₹410.10 | ₹40,190 | 19.9% |
| NTPC.NS | 113 | ₹348.15 | ₹39,341 | 19.5% |
| SUNPHARMA.NS | 22 | ₹1942.60 | ₹42,737 | 21.1% |

## Equity track record

`▁▁▁▃▄▅▅▄▃▁▃▂▄▅▆█▆▂▃▄▄▄`  (22 daily marks; full series in `paper_equity.csv`)

| Date | Equity | Return |
|---|---|---|
| 2026-07-01 | ₹202,131 | +1.07% |
| 2026-07-02 | ₹202,862 | +1.43% |
| 2026-07-03 | ₹204,392 | +2.20% |
| 2026-07-06 | ₹205,500 | +2.75% |
| 2026-07-07 | ₹203,899 | +1.95% |
| 2026-07-08 | ₹200,560 | +0.28% |
| 2026-07-09 | ₹201,448 | +0.72% |
| 2026-07-10 | ₹202,359 | +1.18% |
| 2026-07-13 | ₹201,872 | +0.94% |
| 2026-07-14 | ₹202,179 | +1.09% |

## GO readiness (criterion 6)

🟡 **NOT YET** — accumulating evidence; the run has not yet cleared every criterion (this is the expected state until it does).

- 🟡 **Track length** — 22/63 trading days — building the minimum sample for a meaningful estimate.
- 🟡 **Volatility event withstood** — no market stress event yet (worst Nifty pullback in-window -2.1%, needs ≤ -10%). A calm run can't earn a GO — waiting on a real event.
- 🟡 **Forward vs benchmark** — within noise of the benchmark (≤ 3% behind) — strategy +1.4% vs Nifty +2.0% (Δ -0.6%).
- 🟢 **Drawdown behaviour** — market-driven, within tolerance — worst live drawdown -2.4% vs Nifty -2.1% (excess -0.3%).
- 🟢 **Data integrity** — dense track record (largest gap 4 days).

## 🩺 System health & run log

**🟢 healthy** — last autonomous run **2026-07-14T14:19:54Z** (market date 2026-07-14, `daily`).

- Action: held — no action
- Decision: holding — next scheduled rebalance on/after 2027-01-01
- Equity: ₹202,179 (+1.09%) · GO: **NOT YET**
- Freshness: ✓ Up to date — last marked 2026-07-14.

_Recent runs (last 10 of 23):_

| Ran (UTC) | As of | Cmd | Action | GO | Warnings |
|---|---|---|---|---|---|
| 2026-07-14T14:19:54Z | 2026-07-14 | daily | held — no action | NOT YET | — |
| 2026-07-13T15:16:53Z | 2026-07-13 | daily | held — no action | NOT YET | — |
| 2026-07-12T08:58:51Z | 2026-07-10 | daily | held — no action | NOT YET | — |
| 2026-07-12T05:03:39Z | 2026-07-10 | daily | held — no action | NOT YET | — |
| 2026-07-12T04:30:34Z | 2026-07-10 | daily | held — no action | NOT YET | — |
| 2026-07-11T16:11:21Z | 2026-07-10 | daily | held — no action | NOT YET | — |
| 2026-07-10T15:07:00Z | 2026-07-10 | daily | held — no action | NOT YET | — |
| 2026-07-10T08:48:25Z | 2026-07-10 | daily | held — no action | NOT YET | — |
| 2026-07-09T15:39:07Z | 2026-07-09 | daily | held — no action | NOT YET | — |
| 2026-07-08T14:44:59Z | 2026-07-08 | daily | held — no action | NOT YET | — |

---
_The decision engine is the same code validated in the backtest ([reports/PHASE0_VERDICT.md](PHASE0_VERDICT.md)); this page is regenerated daily by the pipeline, not by hand._
