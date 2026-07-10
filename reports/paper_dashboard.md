# Q-Alpha — Paper-Trading Dashboard

_Notional paper trading (no real money) of the validated tax-aware strategy. As of **2026-07-10** · generated 2026-07-10 08:48 UTC._

## At a glance

| | |
|---|---|
| Started | 2026-06-12 (28 days) |
| Notional capital | ₹200,000 |
| Equity (marked) | ₹201,944 |
| Return since start | **+0.97%** |
| Nifty 50 TRI (same window) | +2.59% |
| Cash | ₹7,335 |
| Realized tax to date | ₹0.00 |
| Rebalances | 1 |
| Strategy | shrink-weighted, annual, tax-aware (band 0.1) |

## Today's recommendation

✅ **HOLD** — holding — next scheduled rebalance on/after 2027-01-01. No orders today.

## Holdings

| Ticker | Qty | Price | Value | Weight |
|---|---|---|---|---|
| APOLLOHOSP.NS | 4 | ₹8810.00 | ₹35,240 | 17.5% |
| ASIANPAINT.NS | 14 | ₹2675.10 | ₹37,451 | 18.5% |
| BEL.NS | 98 | ₹414.75 | ₹40,646 | 20.1% |
| NTPC.NS | 113 | ₹343.70 | ₹38,838 | 19.2% |
| SUNPHARMA.NS | 22 | ₹1928.80 | ₹42,434 | 21.0% |

## Equity track record

`▁▁▁▃▄▅▅▄▃▁▃▂▄▅▆█▆▂▃▄`  (20 daily marks; full series in `paper_equity.csv`)

| Date | Equity | Return |
|---|---|---|
| 2026-06-29 | ₹200,974 | +0.49% |
| 2026-06-30 | ₹200,596 | +0.30% |
| 2026-07-01 | ₹202,131 | +1.07% |
| 2026-07-02 | ₹202,862 | +1.43% |
| 2026-07-03 | ₹204,392 | +2.20% |
| 2026-07-06 | ₹205,500 | +2.75% |
| 2026-07-07 | ₹203,899 | +1.95% |
| 2026-07-08 | ₹200,560 | +0.28% |
| 2026-07-09 | ₹201,448 | +0.72% |
| 2026-07-10 | ₹201,944 | +0.97% |

## GO readiness (criterion 6)

🟡 **NOT YET** — accumulating evidence; the run has not yet cleared every criterion (this is the expected state until it does).

- 🟡 **Track length** — 20/63 trading days — building the minimum sample for a meaningful estimate.
- 🟡 **Volatility event withstood** — no market stress event yet (worst Nifty pullback in-window -2.1%, needs ≤ -10%). A calm run can't earn a GO — waiting on a real event.
- 🟡 **Forward vs benchmark** — within noise of the benchmark (≤ 3% behind) — strategy +1.3% vs Nifty +2.6% (Δ -1.3%).
- 🟢 **Drawdown behaviour** — market-driven, within tolerance — worst live drawdown -2.4% vs Nifty -2.1% (excess -0.3%).
- 🟢 **Data integrity** — dense track record (largest gap 4 days).

## 🩺 System health & run log

**🟢 healthy** — last autonomous run **2026-07-10T08:48:25Z** (market date 2026-07-10, `daily`).

- Action: held — no action
- Decision: holding — next scheduled rebalance on/after 2027-01-01
- Equity: ₹201,944 (+0.97%) · GO: **NOT YET**
- Freshness: ✓ Up to date — last marked 2026-07-10.

_Recent runs (last 10 of 16):_

| Ran (UTC) | As of | Cmd | Action | GO | Warnings |
|---|---|---|---|---|---|
| 2026-07-10T08:48:25Z | 2026-07-10 | daily | held — no action | NOT YET | — |
| 2026-07-09T15:39:07Z | 2026-07-09 | daily | held — no action | NOT YET | — |
| 2026-07-08T14:44:59Z | 2026-07-08 | daily | held — no action | NOT YET | — |
| 2026-07-07T15:21:31Z | 2026-07-07 | daily | held — no action | NOT YET | — |
| 2026-07-06T15:57:40Z | 2026-07-06 | daily | held — no action | NOT YET | — |
| 2026-07-03T14:36:27Z | 2026-07-03 | daily | held — no action | NOT YET | — |
| 2026-07-02T14:33:22Z | 2026-07-02 | daily | held — no action | NOT YET | — |
| 2026-07-01T15:16:57Z | 2026-07-01 | daily | held — no action | NOT YET | — |
| 2026-06-30T15:05:17Z | 2026-06-30 | daily | held — no action | NOT YET | — |
| 2026-06-29T16:15:21Z | 2026-06-29 | daily | held — no action | NOT YET | — |

---
_The decision engine is the same code validated in the backtest ([reports/PHASE0_VERDICT.md](PHASE0_VERDICT.md)); this page is regenerated daily by the pipeline, not by hand._
