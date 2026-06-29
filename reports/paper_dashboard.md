# Q-Alpha — Paper-Trading Dashboard

_Notional paper trading (no real money) of the validated tax-aware strategy. As of **2026-06-29** · generated 2026-06-29 16:15 UTC._

## At a glance

| | |
|---|---|
| Started | 2026-06-12 (17 days) |
| Notional capital | ₹200,000 |
| Equity (marked) | ₹200,974 |
| Return since start | **+0.49%** |
| Nifty 50 TRI (same window) | +1.61% |
| Cash | ₹7,335 |
| Realized tax to date | ₹0.00 |
| Rebalances | 1 |
| Strategy | shrink-weighted, annual, tax-aware (band 0.1) |

## Today's recommendation

✅ **HOLD** — holding — next scheduled rebalance on/after 2027-01-01. No orders today.

## Holdings

| Ticker | Qty | Price | Value | Weight |
|---|---|---|---|---|
| APOLLOHOSP.NS | 4 | ₹8655.00 | ₹34,620 | 17.2% |
| ASIANPAINT.NS | 14 | ₹2656.90 | ₹37,197 | 18.5% |
| BEL.NS | 98 | ₹411.60 | ₹40,337 | 20.1% |
| NTPC.NS | 113 | ₹356.10 | ₹40,239 | 20.0% |
| SUNPHARMA.NS | 22 | ₹1874.80 | ₹41,246 | 20.5% |

## Equity track record

`▁▁▁▄▆▇█▅▄▁▄`  (11 daily marks; full series in `paper_equity.csv`)

| Date | Equity | Return |
|---|---|---|
| 2026-06-15 | ₹198,763 | -0.62% |
| 2026-06-16 | ₹199,103 | -0.45% |
| 2026-06-17 | ₹200,749 | +0.37% |
| 2026-06-18 | ₹202,600 | +1.30% |
| 2026-06-19 | ₹203,168 | +1.58% |
| 2026-06-22 | ₹203,395 | +1.70% |
| 2026-06-23 | ₹201,998 | +1.00% |
| 2026-06-24 | ₹201,086 | +0.54% |
| 2026-06-25 | ₹199,405 | -0.30% |
| 2026-06-29 | ₹200,974 | +0.49% |

## GO readiness (criterion 6)

🟡 **NOT YET** — accumulating evidence; the run has not yet cleared every criterion (this is the expected state until it does).

- 🟡 **Track length** — 11/63 trading days — building the minimum sample for a meaningful estimate.
- 🟡 **Volatility event withstood** — no market stress event yet (worst Nifty pullback in-window -1.2%, needs ≤ -10%). A calm run can't earn a GO — waiting on a real event.
- 🟡 **Forward vs benchmark** — within noise of the benchmark (≤ 3% behind) — strategy +0.8% vs Nifty +1.6% (Δ -0.8%).
- 🟢 **Drawdown behaviour** — market-driven, within tolerance — worst live drawdown -2.0% vs Nifty -1.2% (excess -0.8%).
- 🟢 **Data integrity** — dense track record (largest gap 4 days).

## 🩺 System health & run log

**🟢 healthy** — last autonomous run **2026-06-29T16:15:21Z** (market date 2026-06-29, `daily`).

- Action: held — no action
- Decision: holding — next scheduled rebalance on/after 2027-01-01
- Equity: ₹200,974 (+0.49%) · GO: **NOT YET**
- Freshness: ✓ Up to date — last marked 2026-06-29.

_Recent runs (last 7 of 7):_

| Ran (UTC) | As of | Cmd | Action | GO | Warnings |
|---|---|---|---|---|---|
| 2026-06-29T16:15:21Z | 2026-06-29 | daily | held — no action | NOT YET | — |
| 2026-06-26T15:06:40Z | 2026-06-25 | daily | held — no action | NOT YET | — |
| 2026-06-25T15:21:21Z | 2026-06-25 | daily | held — no action | NOT YET | — |
| 2026-06-24T15:14:34Z | 2026-06-24 | daily | held — no action | NOT YET | — |
| 2026-06-23T15:28:53Z | 2026-06-23 | daily | held — no action | NOT YET | — |
| 2026-06-22T17:14:26Z | 2026-06-22 | daily | held — no action | NOT YET | — |
| 2026-06-22T12:53:00Z | 2026-06-22 | daily | held — no action | NOT YET | — |

---
_The decision engine is the same code validated in the backtest ([reports/PHASE0_VERDICT.md](PHASE0_VERDICT.md)); this page is regenerated daily by the pipeline, not by hand._
