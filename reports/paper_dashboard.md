# Q-Alpha — Paper-Trading Dashboard

_Notional paper trading (no real money) of the validated tax-aware strategy. As of **2026-07-24** · generated 2026-07-24 14:17 UTC._

## At a glance

| | |
|---|---|
| Started | 2026-06-12 (42 days) |
| Notional capital | ₹200,000 |
| Equity (marked) | ₹201,116 |
| Return since start | **+0.56%** |
| Nifty 50 TRI (same window) | +1.25% |
| Cash | ₹7,335 |
| Realized tax to date | ₹0.00 |
| Rebalances | 1 |
| Strategy | shrink-weighted, annual, tax-aware (band 0.1) |

## Today's recommendation

✅ **HOLD** — holding — next scheduled rebalance on/after 2027-01-01. No orders today.

## Holdings

| Ticker | Qty | Price | Value | Weight |
|---|---|---|---|---|
| APOLLOHOSP.NS | 4 | ₹8805.50 | ₹35,222 | 17.5% |
| ASIANPAINT.NS | 14 | ₹2637.90 | ₹36,931 | 18.4% |
| BEL.NS | 98 | ₹405.00 | ₹39,690 | 19.7% |
| NTPC.NS | 113 | ₹347.20 | ₹39,234 | 19.5% |
| SUNPHARMA.NS | 22 | ₹1941.10 | ₹42,704 | 21.2% |

## Equity track record

`▁▁▁▃▄▅▅▄▃▁▃▂▄▅▆█▆▂▃▄▄▄▄▄▃▅▅▅▄▃`  (30 daily marks; full series in `paper_equity.csv`)

| Date | Equity | Return |
|---|---|---|
| 2026-07-13 | ₹201,872 | +0.94% |
| 2026-07-14 | ₹202,179 | +1.09% |
| 2026-07-15 | ₹202,569 | +1.28% |
| 2026-07-16 | ₹201,828 | +0.91% |
| 2026-07-17 | ₹201,558 | +0.78% |
| 2026-07-20 | ₹202,914 | +1.46% |
| 2026-07-21 | ₹203,468 | +1.73% |
| 2026-07-22 | ₹203,001 | +1.50% |
| 2026-07-23 | ₹202,251 | +1.13% |
| 2026-07-24 | ₹201,116 | +0.56% |

## GO readiness (criterion 6)

🟡 **NOT YET** — accumulating evidence; the run has not yet cleared every criterion (this is the expected state until it does).

- 🟡 **Track length** — 30/63 trading days — building the minimum sample for a meaningful estimate.
- 🟡 **Volatility event withstood** — no market stress event yet (worst Nifty pullback in-window -2.2%, needs ≤ -10%). A calm run can't earn a GO — waiting on a real event.
- 🟡 **Forward vs benchmark** — within noise of the benchmark (≤ 3% behind) — strategy +0.9% vs Nifty +1.3% (Δ -0.4%).
- 🟢 **Drawdown behaviour** — market-driven, within tolerance — worst live drawdown -2.4% vs Nifty -2.2% (excess -0.2%).
- 🟢 **Data integrity** — dense track record (largest gap 4 days).

## 🩺 System health & run log

**🟢 healthy** — last autonomous run **2026-07-24T14:17:59Z** (market date 2026-07-24, `daily`).

- Action: held — no action
- Decision: holding — next scheduled rebalance on/after 2027-01-01
- Equity: ₹201,116 (+0.56%) · GO: **NOT YET**
- Freshness: ✓ Up to date — last marked 2026-07-24.

_Recent runs (last 10 of 31):_

| Ran (UTC) | As of | Cmd | Action | GO | Warnings |
|---|---|---|---|---|---|
| 2026-07-24T14:17:59Z | 2026-07-24 | daily | held — no action | NOT YET | — |
| 2026-07-23T14:37:59Z | 2026-07-23 | daily | held — no action | NOT YET | — |
| 2026-07-22T14:30:16Z | 2026-07-22 | daily | held — no action | NOT YET | — |
| 2026-07-21T14:30:09Z | 2026-07-21 | daily | held — no action | NOT YET | — |
| 2026-07-20T14:36:25Z | 2026-07-20 | daily | held — no action | NOT YET | — |
| 2026-07-17T14:09:03Z | 2026-07-17 | daily | held — no action | NOT YET | — |
| 2026-07-16T14:28:35Z | 2026-07-16 | daily | held — no action | NOT YET | — |
| 2026-07-15T14:15:52Z | 2026-07-15 | daily | held — no action | NOT YET | — |
| 2026-07-14T14:19:54Z | 2026-07-14 | daily | held — no action | NOT YET | — |
| 2026-07-13T15:16:53Z | 2026-07-13 | daily | held — no action | NOT YET | — |

---
_The decision engine is the same code validated in the backtest ([reports/PHASE0_VERDICT.md](PHASE0_VERDICT.md)); this page is regenerated daily by the pipeline, not by hand._
