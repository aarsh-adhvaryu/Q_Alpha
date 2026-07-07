# Q-Alpha — Paper-Trading Dashboard

_Notional paper trading (no real money) of the validated tax-aware strategy. As of **2026-07-07** · generated 2026-07-07 15:21 UTC._

## At a glance

| | |
|---|---|
| Started | 2026-06-12 (25 days) |
| Notional capital | ₹200,000 |
| Equity (marked) | ₹203,899 |
| Return since start | **+1.95%** |
| Nifty 50 TRI (same window) | +3.43% |
| Cash | ₹7,335 |
| Realized tax to date | ₹0.00 |
| Rebalances | 1 |
| Strategy | shrink-weighted, annual, tax-aware (band 0.1) |

## Today's recommendation

✅ **HOLD** — holding — next scheduled rebalance on/after 2027-01-01. No orders today.

## Holdings

| Ticker | Qty | Price | Value | Weight |
|---|---|---|---|---|
| APOLLOHOSP.NS | 4 | ₹8837.00 | ₹35,348 | 17.3% |
| ASIANPAINT.NS | 14 | ₹2731.40 | ₹38,240 | 18.8% |
| BEL.NS | 98 | ₹419.15 | ₹41,077 | 20.1% |
| NTPC.NS | 113 | ₹354.20 | ₹40,025 | 19.6% |
| SUNPHARMA.NS | 22 | ₹1903.40 | ₹41,875 | 20.5% |

## Equity track record

`▁▁▁▃▄▅▅▄▃▁▃▂▄▅▆█▆`  (17 daily marks; full series in `paper_equity.csv`)

| Date | Equity | Return |
|---|---|---|
| 2026-06-23 | ₹201,998 | +1.00% |
| 2026-06-24 | ₹201,086 | +0.54% |
| 2026-06-25 | ₹199,405 | -0.30% |
| 2026-06-29 | ₹200,974 | +0.49% |
| 2026-06-30 | ₹200,596 | +0.30% |
| 2026-07-01 | ₹202,131 | +1.07% |
| 2026-07-02 | ₹202,862 | +1.43% |
| 2026-07-03 | ₹204,392 | +2.20% |
| 2026-07-06 | ₹205,500 | +2.75% |
| 2026-07-07 | ₹203,899 | +1.95% |

## GO readiness (criterion 6)

🟡 **NOT YET** — accumulating evidence; the run has not yet cleared every criterion (this is the expected state until it does).

- 🟡 **Track length** — 17/63 trading days — building the minimum sample for a meaningful estimate.
- 🟡 **Volatility event withstood** — no market stress event yet (worst Nifty pullback in-window -1.2%, needs ≤ -10%). A calm run can't earn a GO — waiting on a real event.
- 🟡 **Forward vs benchmark** — within noise of the benchmark (≤ 3% behind) — strategy +2.3% vs Nifty +3.4% (Δ -1.2%).
- 🟢 **Drawdown behaviour** — market-driven, within tolerance — worst live drawdown -2.0% vs Nifty -1.2% (excess -0.8%).
- 🟢 **Data integrity** — dense track record (largest gap 4 days).

## 🩺 System health & run log

**🟢 healthy** — last autonomous run **2026-07-07T15:21:31Z** (market date 2026-07-07, `daily`).

- Action: held — no action
- Decision: holding — next scheduled rebalance on/after 2027-01-01
- Equity: ₹203,899 (+1.95%) · GO: **NOT YET**
- Freshness: ✓ Up to date — last marked 2026-07-07.

_Recent runs (last 10 of 13):_

| Ran (UTC) | As of | Cmd | Action | GO | Warnings |
|---|---|---|---|---|---|
| 2026-07-07T15:21:31Z | 2026-07-07 | daily | held — no action | NOT YET | — |
| 2026-07-06T15:57:40Z | 2026-07-06 | daily | held — no action | NOT YET | — |
| 2026-07-03T14:36:27Z | 2026-07-03 | daily | held — no action | NOT YET | — |
| 2026-07-02T14:33:22Z | 2026-07-02 | daily | held — no action | NOT YET | — |
| 2026-07-01T15:16:57Z | 2026-07-01 | daily | held — no action | NOT YET | — |
| 2026-06-30T15:05:17Z | 2026-06-30 | daily | held — no action | NOT YET | — |
| 2026-06-29T16:15:21Z | 2026-06-29 | daily | held — no action | NOT YET | — |
| 2026-06-26T15:06:40Z | 2026-06-25 | daily | held — no action | NOT YET | — |
| 2026-06-25T15:21:21Z | 2026-06-25 | daily | held — no action | NOT YET | — |
| 2026-06-24T15:14:34Z | 2026-06-24 | daily | held — no action | NOT YET | — |

---
_The decision engine is the same code validated in the backtest ([reports/PHASE0_VERDICT.md](PHASE0_VERDICT.md)); this page is regenerated daily by the pipeline, not by hand._
