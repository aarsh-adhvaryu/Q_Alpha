# Q-Alpha — Paper-Trading Dashboard

_Notional paper trading (no real money) of the validated tax-aware strategy. As of **2026-07-21** · generated 2026-07-21 14:30 UTC._

## At a glance

| | |
|---|---|
| Started | 2026-06-12 (39 days) |
| Notional capital | ₹200,000 |
| Equity (marked) | ₹203,468 |
| Return since start | **+1.73%** |
| Nifty 50 TRI (same window) | +2.71% |
| Cash | ₹7,335 |
| Realized tax to date | ₹0.00 |
| Rebalances | 1 |
| Strategy | shrink-weighted, annual, tax-aware (band 0.1) |

## Today's recommendation

✅ **HOLD** — holding — next scheduled rebalance on/after 2027-01-01. No orders today.

## Holdings

| Ticker | Qty | Price | Value | Weight |
|---|---|---|---|---|
| APOLLOHOSP.NS | 4 | ₹8926.50 | ₹35,706 | 17.5% |
| ASIANPAINT.NS | 14 | ₹2692.40 | ₹37,694 | 18.5% |
| BEL.NS | 98 | ₹410.05 | ₹40,185 | 19.8% |
| NTPC.NS | 113 | ₹348.55 | ₹39,386 | 19.4% |
| SUNPHARMA.NS | 22 | ₹1961.90 | ₹43,162 | 21.2% |

## Equity track record

`▁▁▁▃▄▅▅▄▃▁▃▂▄▅▆█▆▂▃▄▄▄▄▄▃▅▅`  (27 daily marks; full series in `paper_equity.csv`)

| Date | Equity | Return |
|---|---|---|
| 2026-07-08 | ₹200,560 | +0.28% |
| 2026-07-09 | ₹201,448 | +0.72% |
| 2026-07-10 | ₹202,359 | +1.18% |
| 2026-07-13 | ₹201,872 | +0.94% |
| 2026-07-14 | ₹202,179 | +1.09% |
| 2026-07-15 | ₹202,569 | +1.28% |
| 2026-07-16 | ₹201,828 | +0.91% |
| 2026-07-17 | ₹201,558 | +0.78% |
| 2026-07-20 | ₹202,914 | +1.46% |
| 2026-07-21 | ₹203,468 | +1.73% |

## GO readiness (criterion 6)

🟡 **NOT YET** — accumulating evidence; the run has not yet cleared every criterion (this is the expected state until it does).

- 🟡 **Track length** — 27/63 trading days — building the minimum sample for a meaningful estimate.
- 🟡 **Volatility event withstood** — no market stress event yet (worst Nifty pullback in-window -2.1%, needs ≤ -10%). A calm run can't earn a GO — waiting on a real event.
- 🟡 **Forward vs benchmark** — within noise of the benchmark (≤ 3% behind) — strategy +2.0% vs Nifty +2.7% (Δ -0.7%).
- 🟢 **Drawdown behaviour** — market-driven, within tolerance — worst live drawdown -2.4% vs Nifty -2.1% (excess -0.3%).
- 🟢 **Data integrity** — dense track record (largest gap 4 days).

## 🩺 System health & run log

**🟢 healthy** — last autonomous run **2026-07-21T14:30:09Z** (market date 2026-07-21, `daily`).

- Action: held — no action
- Decision: holding — next scheduled rebalance on/after 2027-01-01
- Equity: ₹203,468 (+1.73%) · GO: **NOT YET**
- Freshness: ✓ Up to date — last marked 2026-07-21.

_Recent runs (last 10 of 28):_

| Ran (UTC) | As of | Cmd | Action | GO | Warnings |
|---|---|---|---|---|---|
| 2026-07-21T14:30:09Z | 2026-07-21 | daily | held — no action | NOT YET | — |
| 2026-07-20T14:36:25Z | 2026-07-20 | daily | held — no action | NOT YET | — |
| 2026-07-17T14:09:03Z | 2026-07-17 | daily | held — no action | NOT YET | — |
| 2026-07-16T14:28:35Z | 2026-07-16 | daily | held — no action | NOT YET | — |
| 2026-07-15T14:15:52Z | 2026-07-15 | daily | held — no action | NOT YET | — |
| 2026-07-14T14:19:54Z | 2026-07-14 | daily | held — no action | NOT YET | — |
| 2026-07-13T15:16:53Z | 2026-07-13 | daily | held — no action | NOT YET | — |
| 2026-07-12T08:58:51Z | 2026-07-10 | daily | held — no action | NOT YET | — |
| 2026-07-12T05:03:39Z | 2026-07-10 | daily | held — no action | NOT YET | — |
| 2026-07-12T04:30:34Z | 2026-07-10 | daily | held — no action | NOT YET | — |

---
_The decision engine is the same code validated in the backtest ([reports/PHASE0_VERDICT.md](PHASE0_VERDICT.md)); this page is regenerated daily by the pipeline, not by hand._
