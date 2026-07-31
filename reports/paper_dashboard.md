# Q-Alpha — Paper-Trading Dashboard

_Notional paper trading (no real money) of the validated tax-aware strategy. As of **2026-07-31** · generated 2026-07-31 14:43 UTC._

## At a glance

| | |
|---|---|
| Started | 2026-06-12 (49 days) |
| Notional capital | ₹200,000 |
| Equity (marked) | ₹202,665 |
| Return since start | **+1.33%** |
| Nifty 50 TRI (same window) | +3.57% |
| Cash | ₹7,335 |
| Realized tax to date | ₹0.00 |
| Rebalances | 1 |
| Strategy | shrink-weighted, annual, tax-aware (band 0.1) |

## Today's recommendation

✅ **HOLD** — holding — next scheduled rebalance on/after 2027-01-01. No orders today.

## Holdings

| Ticker | Qty | Price | Value | Weight | LTCG-safe |
|---|---|---|---|---|---|
| APOLLOHOSP.NS | 4 | ₹8957.00 | ₹35,828 | 17.7% | ⏳ 316d · 12 Jun 27 |
| ASIANPAINT.NS | 14 | ₹2747.30 | ₹38,462 | 19.0% | ⏳ 316d · 12 Jun 27 |
| BEL.NS | 98 | ₹387.85 | ₹38,009 | 18.8% | ⏳ 316d · 12 Jun 27 |
| NTPC.NS | 113 | ₹347.25 | ₹39,239 | 19.4% | ⏳ 316d · 12 Jun 27 |
| SUNPHARMA.NS | 22 | ₹1990.50 | ₹43,791 | 21.6% | ⏳ 316d · 12 Jun 27 |

> **LTCG-safe** = the safe minimal holding date: hold until then and the whole line sells at the lower **12.5%** long-term rate instead of **20%** short-term (§111A→§112A). Selling earlier is allowed — it just taxes the still-short-term shares at 20%. `🟢 now` = already fully long-term.

## Equity track record

`▁▁▁▃▄▅▅▄▃▁▃▂▄▅▆█▆▂▃▄▄▄▄▄▃▅▅▅▄▃▆▄▄▄▅`  (35 daily marks; full series in `paper_equity.csv`)

| Date | Equity | Return |
|---|---|---|
| 2026-07-20 | ₹202,914 | +1.46% |
| 2026-07-21 | ₹203,468 | +1.73% |
| 2026-07-22 | ₹203,001 | +1.50% |
| 2026-07-23 | ₹202,251 | +1.13% |
| 2026-07-24 | ₹201,116 | +0.56% |
| 2026-07-27 | ₹203,615 | +1.81% |
| 2026-07-28 | ₹201,707 | +0.85% |
| 2026-07-29 | ₹202,266 | +1.13% |
| 2026-07-30 | ₹202,447 | +1.22% |
| 2026-07-31 | ₹202,665 | +1.33% |

## GO readiness (criterion 6)

🟡 **NOT YET** — accumulating evidence; the run has not yet cleared every criterion (this is the expected state until it does).

- 🟡 **Track length** — 35/63 trading days — building the minimum sample for a meaningful estimate.
- 🟡 **Volatility event withstood** — no market stress event yet (worst Nifty pullback in-window -2.2%, needs ≤ -10%). A calm run can't earn a GO — waiting on a real event.
- 🟡 **Forward vs benchmark** — within noise of the benchmark (≤ 3% behind) — strategy +1.6% vs Nifty +3.6% (Δ -1.9%).
- 🟢 **Drawdown behaviour** — market-driven, within tolerance — worst live drawdown -2.4% vs Nifty -2.2% (excess -0.2%).
- 🟢 **Data integrity** — dense track record (largest gap 4 days).

## 🩺 System health & run log

**🟢 healthy** — last autonomous run **2026-07-31T14:43:05Z** (market date 2026-07-31, `daily`).

- Action: held — no action
- Decision: holding — next scheduled rebalance on/after 2027-01-01
- Equity: ₹202,665 (+1.33%) · GO: **NOT YET**
- Freshness: ✓ Up to date — last marked 2026-07-31.

_Recent runs (last 10 of 36):_

| Ran (UTC) | As of | Cmd | Action | GO | Warnings |
|---|---|---|---|---|---|
| 2026-07-31T14:43:05Z | 2026-07-31 | daily | held — no action | NOT YET | — |
| 2026-07-30T14:38:23Z | 2026-07-30 | daily | held — no action | NOT YET | — |
| 2026-07-29T14:36:05Z | 2026-07-29 | daily | held — no action | NOT YET | — |
| 2026-07-28T14:46:02Z | 2026-07-28 | daily | held — no action | NOT YET | — |
| 2026-07-27T15:19:17Z | 2026-07-27 | daily | held — no action | NOT YET | — |
| 2026-07-24T14:17:59Z | 2026-07-24 | daily | held — no action | NOT YET | — |
| 2026-07-23T14:37:59Z | 2026-07-23 | daily | held — no action | NOT YET | — |
| 2026-07-22T14:30:16Z | 2026-07-22 | daily | held — no action | NOT YET | — |
| 2026-07-21T14:30:09Z | 2026-07-21 | daily | held — no action | NOT YET | — |
| 2026-07-20T14:36:25Z | 2026-07-20 | daily | held — no action | NOT YET | — |

---
_The decision engine is the same code validated in the backtest ([reports/PHASE0_VERDICT.md](PHASE0_VERDICT.md)); this page is regenerated daily by the pipeline, not by hand._
