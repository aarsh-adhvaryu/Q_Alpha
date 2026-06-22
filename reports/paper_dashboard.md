# Q-Alpha — Paper-Trading Dashboard

_Notional paper trading (no real money) of the validated tax-aware strategy. As of **2026-06-22** · generated 2026-06-22 12:53 UTC._

## At a glance

| | |
|---|---|
| Started | 2026-06-12 (10 days) |
| Notional capital | ₹200,000 |
| Equity (marked) | ₹203,395 |
| Return since start | **+1.70%** |
| Nifty 50 TRI (same window) | +2.17% |
| Cash | ₹7,335 |
| Realized tax to date | ₹0.00 |
| Rebalances | 1 |
| Strategy | shrink-weighted, annual, tax-aware (band 0.1) |

## Today's recommendation

✅ **HOLD** — holding — next scheduled rebalance on/after 2027-01-01. No orders today.

## Holdings

| Ticker | Qty | Price | Value | Weight |
|---|---|---|---|---|
| APOLLOHOSP.NS | 4 | ₹8469.00 | ₹33,876 | 16.7% |
| ASIANPAINT.NS | 14 | ₹2674.00 | ₹37,436 | 18.4% |
| BEL.NS | 98 | ₹431.50 | ₹42,287 | 20.8% |
| NTPC.NS | 113 | ₹367.05 | ₹41,477 | 20.4% |
| SUNPHARMA.NS | 22 | ₹1862.90 | ₹40,984 | 20.1% |

## Equity track record

`▁▁▁▄▆▇█`  (7 daily marks; full series in `paper_equity.csv`)

| Date | Equity | Return |
|---|---|---|
| 2026-06-12 | ₹199,388 | -0.31% |
| 2026-06-15 | ₹198,763 | -0.62% |
| 2026-06-16 | ₹199,103 | -0.45% |
| 2026-06-17 | ₹200,749 | +0.37% |
| 2026-06-18 | ₹202,600 | +1.30% |
| 2026-06-19 | ₹203,168 | +1.58% |
| 2026-06-22 | ₹203,395 | +1.70% |

## GO readiness (criterion 6)

🟡 **NOT YET** — accumulating evidence; the run has not yet cleared every criterion (this is the expected state until it does).

- 🟡 **Track length** — 7/63 trading days — building the minimum sample for a meaningful estimate.
- 🟡 **Volatility event withstood** — no market stress event yet (worst Nifty pullback in-window -0.4%, needs ≤ -10%). A calm run can't earn a GO — waiting on a real event.
- 🟡 **Forward vs benchmark** — within noise of the benchmark (≤ 3% behind) — strategy +2.0% vs Nifty +2.2% (Δ -0.2%).
- 🟢 **Drawdown behaviour** — worst live drawdown -0.3% (within the backtest envelope).
- 🟢 **Data integrity** — dense track record (largest gap 3 days).

## 🩺 System health & run log

**🟢 healthy** — last autonomous run **2026-06-22T12:53:00Z** (market date 2026-06-22, `daily`).

- Action: held — no action
- Decision: holding — next scheduled rebalance on/after 2027-01-01
- Equity: ₹203,395 (+1.70%) · GO: **NOT YET**
- Freshness: ✓ Up to date — last marked 2026-06-22.

_Recent runs (last 1 of 1):_

| Ran (UTC) | As of | Cmd | Action | GO | Warnings |
|---|---|---|---|---|---|
| 2026-06-22T12:53:00Z | 2026-06-22 | daily | held — no action | NOT YET | — |

---
_The decision engine is the same code validated in the backtest ([reports/PHASE0_VERDICT.md](PHASE0_VERDICT.md)); this page is regenerated daily by the pipeline, not by hand._
