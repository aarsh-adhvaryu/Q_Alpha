# Q-Alpha — Paper-Trading Dashboard

_Notional paper trading (no real money) of the validated tax-aware strategy. As of **2026-07-20** · generated 2026-07-20 14:36 UTC._

## At a glance

| | |
|---|---|
| Started | 2026-06-12 (38 days) |
| Notional capital | ₹200,000 |
| Equity (marked) | ₹202,914 |
| Return since start | **+1.46%** |
| Nifty 50 TRI (same window) | +2.88% |
| Cash | ₹7,335 |
| Realized tax to date | ₹0.00 |
| Rebalances | 1 |
| Strategy | shrink-weighted, annual, tax-aware (band 0.1) |

## Today's recommendation

✅ **HOLD** — holding — next scheduled rebalance on/after 2027-01-01. No orders today.

## Holdings

| Ticker | Qty | Price | Value | Weight |
|---|---|---|---|---|
| APOLLOHOSP.NS | 4 | ₹8905.00 | ₹35,620 | 17.6% |
| ASIANPAINT.NS | 14 | ₹2691.40 | ₹37,680 | 18.6% |
| BEL.NS | 98 | ₹408.15 | ₹39,999 | 19.7% |
| NTPC.NS | 113 | ₹347.25 | ₹39,239 | 19.3% |
| SUNPHARMA.NS | 22 | ₹1956.40 | ₹43,041 | 21.2% |

## Equity track record

`▁▁▁▃▄▅▅▄▃▁▃▂▄▅▆█▆▂▃▄▄▄▄▄▃▅`  (26 daily marks; full series in `paper_equity.csv`)

| Date | Equity | Return |
|---|---|---|
| 2026-07-07 | ₹203,899 | +1.95% |
| 2026-07-08 | ₹200,560 | +0.28% |
| 2026-07-09 | ₹201,448 | +0.72% |
| 2026-07-10 | ₹202,359 | +1.18% |
| 2026-07-13 | ₹201,872 | +0.94% |
| 2026-07-14 | ₹202,179 | +1.09% |
| 2026-07-15 | ₹202,569 | +1.28% |
| 2026-07-16 | ₹201,828 | +0.91% |
| 2026-07-17 | ₹201,558 | +0.78% |
| 2026-07-20 | ₹202,914 | +1.46% |

## GO readiness (criterion 6)

🟡 **NOT YET** — accumulating evidence; the run has not yet cleared every criterion (this is the expected state until it does).

- 🟡 **Track length** — 26/63 trading days — building the minimum sample for a meaningful estimate.
- 🟡 **Volatility event withstood** — no market stress event yet (worst Nifty pullback in-window -2.1%, needs ≤ -10%). A calm run can't earn a GO — waiting on a real event.
- 🟡 **Forward vs benchmark** — within noise of the benchmark (≤ 3% behind) — strategy +1.8% vs Nifty +2.9% (Δ -1.1%).
- 🟢 **Drawdown behaviour** — market-driven, within tolerance — worst live drawdown -2.4% vs Nifty -2.1% (excess -0.3%).
- 🟢 **Data integrity** — dense track record (largest gap 4 days).

## 🩺 System health & run log

**🟢 healthy** — last autonomous run **2026-07-20T14:36:25Z** (market date 2026-07-20, `daily`).

- Action: held — no action
- Decision: holding — next scheduled rebalance on/after 2027-01-01
- Equity: ₹202,914 (+1.46%) · GO: **NOT YET**
- Freshness: ✓ Up to date — last marked 2026-07-20.

_Recent runs (last 10 of 27):_

| Ran (UTC) | As of | Cmd | Action | GO | Warnings |
|---|---|---|---|---|---|
| 2026-07-20T14:36:25Z | 2026-07-20 | daily | held — no action | NOT YET | — |
| 2026-07-17T14:09:03Z | 2026-07-17 | daily | held — no action | NOT YET | — |
| 2026-07-16T14:28:35Z | 2026-07-16 | daily | held — no action | NOT YET | — |
| 2026-07-15T14:15:52Z | 2026-07-15 | daily | held — no action | NOT YET | — |
| 2026-07-14T14:19:54Z | 2026-07-14 | daily | held — no action | NOT YET | — |
| 2026-07-13T15:16:53Z | 2026-07-13 | daily | held — no action | NOT YET | — |
| 2026-07-12T08:58:51Z | 2026-07-10 | daily | held — no action | NOT YET | — |
| 2026-07-12T05:03:39Z | 2026-07-10 | daily | held — no action | NOT YET | — |
| 2026-07-12T04:30:34Z | 2026-07-10 | daily | held — no action | NOT YET | — |
| 2026-07-11T16:11:21Z | 2026-07-10 | daily | held — no action | NOT YET | — |

---
_The decision engine is the same code validated in the backtest ([reports/PHASE0_VERDICT.md](PHASE0_VERDICT.md)); this page is regenerated daily by the pipeline, not by hand._
