# Q-Alpha — Paper-Trading Dashboard

_Notional paper trading (no real money) of the validated tax-aware strategy. As of **2026-06-25** · generated 2026-06-26 15:06 UTC._

## At a glance

| | |
|---|---|
| Started | 2026-06-12 (13 days) |
| Notional capital | ₹200,000 |
| Equity (marked) | ₹199,405 |
| Return since start | **-0.30%** |
| Nifty 50 TRI (same window) | +2.08% |
| Cash | ₹7,335 |
| Realized tax to date | ₹0.00 |
| Rebalances | 1 |
| Strategy | shrink-weighted, annual, tax-aware (band 0.1) |

## Today's recommendation

✅ **HOLD** — holding — next scheduled rebalance on/after 2027-01-01. No orders today.

## Holdings

| Ticker | Qty | Price | Value | Weight |
|---|---|---|---|---|
| APOLLOHOSP.NS | 4 | ₹8592.00 | ₹34,368 | 17.2% |
| ASIANPAINT.NS | 14 | ₹2645.20 | ₹37,033 | 18.6% |
| BEL.NS | 98 | ₹407.20 | ₹39,906 | 20.0% |
| NTPC.NS | 113 | ₹352.05 | ₹39,782 | 20.0% |
| SUNPHARMA.NS | 22 | ₹1862.80 | ₹40,982 | 20.6% |

## Equity track record

`▁▁▁▄▆▇█▅▄▁`  (10 daily marks; full series in `paper_equity.csv`)

| Date | Equity | Return |
|---|---|---|
| 2026-06-12 | ₹199,388 | -0.31% |
| 2026-06-15 | ₹198,763 | -0.62% |
| 2026-06-16 | ₹199,103 | -0.45% |
| 2026-06-17 | ₹200,749 | +0.37% |
| 2026-06-18 | ₹202,600 | +1.30% |
| 2026-06-19 | ₹203,168 | +1.58% |
| 2026-06-22 | ₹203,395 | +1.70% |
| 2026-06-23 | ₹201,998 | +1.00% |
| 2026-06-24 | ₹201,086 | +0.54% |
| 2026-06-25 | ₹199,405 | -0.30% |

## GO readiness (criterion 6)

🟡 **NOT YET** — accumulating evidence; the run has not yet cleared every criterion (this is the expected state until it does).

- 🟡 **Track length** — 10/63 trading days — building the minimum sample for a meaningful estimate.
- 🟡 **Volatility event withstood** — no market stress event yet (worst Nifty pullback in-window -1.2%, needs ≤ -10%). A calm run can't earn a GO — waiting on a real event.
- 🟡 **Forward vs benchmark** — within noise of the benchmark (≤ 3% behind) — strategy +0.0% vs Nifty +2.1% (Δ -2.1%).
- 🟢 **Drawdown behaviour** — market-driven, within tolerance — worst live drawdown -2.0% vs Nifty -1.2% (excess -0.8%).
- 🟢 **Data integrity** — dense track record (largest gap 3 days).

## 🩺 System health & run log

**🟢 healthy** — last autonomous run **2026-06-26T15:06:40Z** (market date 2026-06-25, `daily`).

- Action: held — no action
- Decision: holding — next scheduled rebalance on/after 2027-01-01
- Equity: ₹199,405 (-0.30%) · GO: **NOT YET**
- Freshness: ✓ Up to date — last marked 2026-06-25.

_Recent runs (last 6 of 6):_

| Ran (UTC) | As of | Cmd | Action | GO | Warnings |
|---|---|---|---|---|---|
| 2026-06-26T15:06:40Z | 2026-06-25 | daily | held — no action | NOT YET | — |
| 2026-06-25T15:21:21Z | 2026-06-25 | daily | held — no action | NOT YET | — |
| 2026-06-24T15:14:34Z | 2026-06-24 | daily | held — no action | NOT YET | — |
| 2026-06-23T15:28:53Z | 2026-06-23 | daily | held — no action | NOT YET | — |
| 2026-06-22T17:14:26Z | 2026-06-22 | daily | held — no action | NOT YET | — |
| 2026-06-22T12:53:00Z | 2026-06-22 | daily | held — no action | NOT YET | — |

---
_The decision engine is the same code validated in the backtest ([reports/PHASE0_VERDICT.md](PHASE0_VERDICT.md)); this page is regenerated daily by the pipeline, not by hand._
