# Q-Alpha — Paper-Trading Dashboard

_Notional paper trading (no real money) of the validated tax-aware strategy. As of **2026-07-02** · generated 2026-07-02 14:33 UTC._

## At a glance

| | |
|---|---|
| Started | 2026-06-12 (20 days) |
| Notional capital | ₹200,000 |
| Equity (marked) | ₹202,862 |
| Return since start | **+1.43%** |
| Nifty 50 TRI (same window) | +2.39% |
| Cash | ₹7,335 |
| Realized tax to date | ₹0.00 |
| Rebalances | 1 |
| Strategy | shrink-weighted, annual, tax-aware (band 0.1) |

## Today's recommendation

✅ **HOLD** — holding — next scheduled rebalance on/after 2027-01-01. No orders today.

## Holdings

| Ticker | Qty | Price | Value | Weight |
|---|---|---|---|---|
| APOLLOHOSP.NS | 4 | ₹8696.00 | ₹34,784 | 17.1% |
| ASIANPAINT.NS | 14 | ₹2744.50 | ₹38,423 | 18.9% |
| BEL.NS | 98 | ₹415.05 | ₹40,675 | 20.1% |
| NTPC.NS | 113 | ₹358.25 | ₹40,482 | 20.0% |
| SUNPHARMA.NS | 22 | ₹1871.00 | ₹41,162 | 20.3% |

## Equity track record

`▁▁▁▄▆▇█▅▄▁▄▃▆▇`  (14 daily marks; full series in `paper_equity.csv`)

| Date | Equity | Return |
|---|---|---|
| 2026-06-18 | ₹202,600 | +1.30% |
| 2026-06-19 | ₹203,168 | +1.58% |
| 2026-06-22 | ₹203,395 | +1.70% |
| 2026-06-23 | ₹201,998 | +1.00% |
| 2026-06-24 | ₹201,086 | +0.54% |
| 2026-06-25 | ₹199,405 | -0.30% |
| 2026-06-29 | ₹200,974 | +0.49% |
| 2026-06-30 | ₹200,596 | +0.30% |
| 2026-07-01 | ₹202,131 | +1.07% |
| 2026-07-02 | ₹202,862 | +1.43% |

## GO readiness (criterion 6)

🟡 **NOT YET** — accumulating evidence; the run has not yet cleared every criterion (this is the expected state until it does).

- 🟡 **Track length** — 14/63 trading days — building the minimum sample for a meaningful estimate.
- 🟡 **Volatility event withstood** — no market stress event yet (worst Nifty pullback in-window -1.2%, needs ≤ -10%). A calm run can't earn a GO — waiting on a real event.
- 🟡 **Forward vs benchmark** — within noise of the benchmark (≤ 3% behind) — strategy +1.7% vs Nifty +2.4% (Δ -0.7%).
- 🟢 **Drawdown behaviour** — market-driven, within tolerance — worst live drawdown -2.0% vs Nifty -1.2% (excess -0.8%).
- 🟢 **Data integrity** — dense track record (largest gap 4 days).

## 🩺 System health & run log

**🟢 healthy** — last autonomous run **2026-07-02T14:33:22Z** (market date 2026-07-02, `daily`).

- Action: held — no action
- Decision: holding — next scheduled rebalance on/after 2027-01-01
- Equity: ₹202,862 (+1.43%) · GO: **NOT YET**
- Freshness: ✓ Up to date — last marked 2026-07-02.

_Recent runs (last 10 of 10):_

| Ran (UTC) | As of | Cmd | Action | GO | Warnings |
|---|---|---|---|---|---|
| 2026-07-02T14:33:22Z | 2026-07-02 | daily | held — no action | NOT YET | — |
| 2026-07-01T15:16:57Z | 2026-07-01 | daily | held — no action | NOT YET | — |
| 2026-06-30T15:05:17Z | 2026-06-30 | daily | held — no action | NOT YET | — |
| 2026-06-29T16:15:21Z | 2026-06-29 | daily | held — no action | NOT YET | — |
| 2026-06-26T15:06:40Z | 2026-06-25 | daily | held — no action | NOT YET | — |
| 2026-06-25T15:21:21Z | 2026-06-25 | daily | held — no action | NOT YET | — |
| 2026-06-24T15:14:34Z | 2026-06-24 | daily | held — no action | NOT YET | — |
| 2026-06-23T15:28:53Z | 2026-06-23 | daily | held — no action | NOT YET | — |
| 2026-06-22T17:14:26Z | 2026-06-22 | daily | held — no action | NOT YET | — |
| 2026-06-22T12:53:00Z | 2026-06-22 | daily | held — no action | NOT YET | — |

---
_The decision engine is the same code validated in the backtest ([reports/PHASE0_VERDICT.md](PHASE0_VERDICT.md)); this page is regenerated daily by the pipeline, not by hand._
