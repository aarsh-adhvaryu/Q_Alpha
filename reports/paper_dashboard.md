# Q-Alpha — Paper-Trading Dashboard

_Notional paper trading (no real money) of the validated tax-aware strategy. As of **2026-07-03** · generated 2026-07-03 14:36 UTC._

## At a glance

| | |
|---|---|
| Started | 2026-06-12 (21 days) |
| Notional capital | ₹200,000 |
| Equity (marked) | ₹204,392 |
| Return since start | **+2.20%** |
| Nifty 50 TRI (same window) | +3.01% |
| Cash | ₹7,335 |
| Realized tax to date | ₹0.00 |
| Rebalances | 1 |
| Strategy | shrink-weighted, annual, tax-aware (band 0.1) |

## Today's recommendation

✅ **HOLD** — holding — next scheduled rebalance on/after 2027-01-01. No orders today.

## Holdings

| Ticker | Qty | Price | Value | Weight |
|---|---|---|---|---|
| APOLLOHOSP.NS | 4 | ₹8893.50 | ₹35,574 | 17.4% |
| ASIANPAINT.NS | 14 | ₹2737.80 | ₹38,329 | 18.8% |
| BEL.NS | 98 | ₹418.05 | ₹40,969 | 20.0% |
| NTPC.NS | 113 | ₹356.45 | ₹40,279 | 19.7% |
| SUNPHARMA.NS | 22 | ₹1904.80 | ₹41,906 | 20.5% |

## Equity track record

`▁▁▁▃▅▆▆▅▃▁▃▃▅▆█`  (15 daily marks; full series in `paper_equity.csv`)

| Date | Equity | Return |
|---|---|---|
| 2026-06-19 | ₹203,168 | +1.58% |
| 2026-06-22 | ₹203,395 | +1.70% |
| 2026-06-23 | ₹201,998 | +1.00% |
| 2026-06-24 | ₹201,086 | +0.54% |
| 2026-06-25 | ₹199,405 | -0.30% |
| 2026-06-29 | ₹200,974 | +0.49% |
| 2026-06-30 | ₹200,596 | +0.30% |
| 2026-07-01 | ₹202,131 | +1.07% |
| 2026-07-02 | ₹202,862 | +1.43% |
| 2026-07-03 | ₹204,392 | +2.20% |

## GO readiness (criterion 6)

🟡 **NOT YET** — accumulating evidence; the run has not yet cleared every criterion (this is the expected state until it does).

- 🟡 **Track length** — 15/63 trading days — building the minimum sample for a meaningful estimate.
- 🟡 **Volatility event withstood** — no market stress event yet (worst Nifty pullback in-window -1.2%, needs ≤ -10%). A calm run can't earn a GO — waiting on a real event.
- 🟡 **Forward vs benchmark** — within noise of the benchmark (≤ 3% behind) — strategy +2.5% vs Nifty +3.0% (Δ -0.5%).
- 🟢 **Drawdown behaviour** — market-driven, within tolerance — worst live drawdown -2.0% vs Nifty -1.2% (excess -0.8%).
- 🟢 **Data integrity** — dense track record (largest gap 4 days).

## 🩺 System health & run log

**🟢 healthy** — last autonomous run **2026-07-03T14:36:27Z** (market date 2026-07-03, `daily`).

- Action: held — no action
- Decision: holding — next scheduled rebalance on/after 2027-01-01
- Equity: ₹204,392 (+2.20%) · GO: **NOT YET**
- Freshness: ✓ Up to date — last marked 2026-07-03.

_Recent runs (last 10 of 11):_

| Ran (UTC) | As of | Cmd | Action | GO | Warnings |
|---|---|---|---|---|---|
| 2026-07-03T14:36:27Z | 2026-07-03 | daily | held — no action | NOT YET | — |
| 2026-07-02T14:33:22Z | 2026-07-02 | daily | held — no action | NOT YET | — |
| 2026-07-01T15:16:57Z | 2026-07-01 | daily | held — no action | NOT YET | — |
| 2026-06-30T15:05:17Z | 2026-06-30 | daily | held — no action | NOT YET | — |
| 2026-06-29T16:15:21Z | 2026-06-29 | daily | held — no action | NOT YET | — |
| 2026-06-26T15:06:40Z | 2026-06-25 | daily | held — no action | NOT YET | — |
| 2026-06-25T15:21:21Z | 2026-06-25 | daily | held — no action | NOT YET | — |
| 2026-06-24T15:14:34Z | 2026-06-24 | daily | held — no action | NOT YET | — |
| 2026-06-23T15:28:53Z | 2026-06-23 | daily | held — no action | NOT YET | — |
| 2026-06-22T17:14:26Z | 2026-06-22 | daily | held — no action | NOT YET | — |

---
_The decision engine is the same code validated in the backtest ([reports/PHASE0_VERDICT.md](PHASE0_VERDICT.md)); this page is regenerated daily by the pipeline, not by hand._
