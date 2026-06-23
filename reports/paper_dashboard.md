# Q-Alpha — Paper-Trading Dashboard

_Notional paper trading (no real money) of the validated tax-aware strategy. As of **2026-06-23** · generated 2026-06-23 15:28 UTC._

## At a glance

| | |
|---|---|
| Started | 2026-06-12 (11 days) |
| Notional capital | ₹200,000 |
| Equity (marked) | ₹201,998 |
| Return since start | **+1.00%** |
| Nifty 50 TRI (same window) | +1.10% |
| Cash | ₹7,335 |
| Realized tax to date | ₹0.00 |
| Rebalances | 1 |
| Strategy | shrink-weighted, annual, tax-aware (band 0.1) |

## Today's recommendation

✅ **HOLD** — holding — next scheduled rebalance on/after 2027-01-01. No orders today.

## Holdings

| Ticker | Qty | Price | Value | Weight |
|---|---|---|---|---|
| APOLLOHOSP.NS | 4 | ₹8487.50 | ₹33,950 | 16.8% |
| ASIANPAINT.NS | 14 | ₹2661.20 | ₹37,257 | 18.4% |
| BEL.NS | 98 | ₹420.00 | ₹41,160 | 20.4% |
| NTPC.NS | 113 | ₹364.60 | ₹41,200 | 20.4% |
| SUNPHARMA.NS | 22 | ₹1868.00 | ₹41,096 | 20.3% |

## Equity track record

`▁▁▁▄▆▇█▅`  (8 daily marks; full series in `paper_equity.csv`)

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

## GO readiness (criterion 6)

🟡 **NOT YET** — accumulating evidence; the run has not yet cleared every criterion (this is the expected state until it does).

- 🟡 **Track length** — 8/63 trading days — building the minimum sample for a meaningful estimate.
- 🟡 **Volatility event withstood** — no market stress event yet (worst Nifty pullback in-window -1.2%, needs ≤ -10%). A calm run can't earn a GO — waiting on a real event.
- 🟢 **Forward vs benchmark** — ahead of the benchmark net — strategy +1.3% vs Nifty +1.1% (Δ +0.2%).
- 🟢 **Drawdown behaviour** — market-driven, within tolerance — worst live drawdown -0.7% vs Nifty -1.2% (excess +0.5%).
- 🟢 **Data integrity** — dense track record (largest gap 3 days).

## 🩺 System health & run log

**🟢 healthy** — last autonomous run **2026-06-23T15:28:53Z** (market date 2026-06-23, `daily`).

- Action: held — no action
- Decision: holding — next scheduled rebalance on/after 2027-01-01
- Equity: ₹201,998 (+1.00%) · GO: **NOT YET**
- Freshness: ✓ Up to date — last marked 2026-06-23.

_Recent runs (last 3 of 3):_

| Ran (UTC) | As of | Cmd | Action | GO | Warnings |
|---|---|---|---|---|---|
| 2026-06-23T15:28:53Z | 2026-06-23 | daily | held — no action | NOT YET | — |
| 2026-06-22T17:14:26Z | 2026-06-22 | daily | held — no action | NOT YET | — |
| 2026-06-22T12:53:00Z | 2026-06-22 | daily | held — no action | NOT YET | — |

---
_The decision engine is the same code validated in the backtest ([reports/PHASE0_VERDICT.md](PHASE0_VERDICT.md)); this page is regenerated daily by the pipeline, not by hand._
