# Q-Alpha — Paper-Trading Dashboard

_Notional paper trading (no real money) of the validated tax-aware strategy. As of **2026-07-28** · generated 2026-07-28 14:46 UTC._

## At a glance

| | |
|---|---|
| Started | 2026-06-12 (46 days) |
| Notional capital | ₹200,000 |
| Equity (marked) | ₹201,707 |
| Return since start | **+0.85%** |
| Nifty 50 TRI (same window) | +2.12% |
| Cash | ₹7,335 |
| Realized tax to date | ₹0.00 |
| Rebalances | 1 |
| Strategy | shrink-weighted, annual, tax-aware (band 0.1) |

## Today's recommendation

✅ **HOLD** — holding — next scheduled rebalance on/after 2027-01-01. No orders today.

## Holdings

| Ticker | Qty | Price | Value | Weight | LTCG-safe |
|---|---|---|---|---|---|
| APOLLOHOSP.NS | 4 | ₹8903.00 | ₹35,612 | 17.7% | ⏳ 319d · 12 Jun 27 |
| ASIANPAINT.NS | 14 | ₹2736.20 | ₹38,307 | 19.0% | ⏳ 319d · 12 Jun 27 |
| BEL.NS | 98 | ₹389.00 | ₹38,122 | 18.9% | ⏳ 319d · 12 Jun 27 |
| NTPC.NS | 113 | ₹343.75 | ₹38,844 | 19.3% | ⏳ 319d · 12 Jun 27 |
| SUNPHARMA.NS | 22 | ₹1976.70 | ₹43,487 | 21.6% | ⏳ 319d · 12 Jun 27 |

> **LTCG-safe** = the safe minimal holding date: hold until then and the whole line sells at the lower **12.5%** long-term rate instead of **20%** short-term (§111A→§112A). Selling earlier is allowed — it just taxes the still-short-term shares at 20%. `🟢 now` = already fully long-term.

## Equity track record

`▁▁▁▃▄▅▅▄▃▁▃▂▄▅▆█▆▂▃▄▄▄▄▄▃▅▅▅▄▃▆▄`  (32 daily marks; full series in `paper_equity.csv`)

| Date | Equity | Return |
|---|---|---|
| 2026-07-15 | ₹202,569 | +1.28% |
| 2026-07-16 | ₹201,828 | +0.91% |
| 2026-07-17 | ₹201,558 | +0.78% |
| 2026-07-20 | ₹202,914 | +1.46% |
| 2026-07-21 | ₹203,468 | +1.73% |
| 2026-07-22 | ₹203,001 | +1.50% |
| 2026-07-23 | ₹202,251 | +1.13% |
| 2026-07-24 | ₹201,116 | +0.56% |
| 2026-07-27 | ₹203,615 | +1.81% |
| 2026-07-28 | ₹201,707 | +0.85% |

## GO readiness (criterion 6)

🟡 **NOT YET** — accumulating evidence; the run has not yet cleared every criterion (this is the expected state until it does).

- 🟡 **Track length** — 32/63 trading days — building the minimum sample for a meaningful estimate.
- 🟡 **Volatility event withstood** — no market stress event yet (worst Nifty pullback in-window -2.2%, needs ≤ -10%). A calm run can't earn a GO — waiting on a real event.
- 🟡 **Forward vs benchmark** — within noise of the benchmark (≤ 3% behind) — strategy +1.2% vs Nifty +2.1% (Δ -1.0%).
- 🟢 **Drawdown behaviour** — market-driven, within tolerance — worst live drawdown -2.4% vs Nifty -2.2% (excess -0.2%).
- 🟢 **Data integrity** — dense track record (largest gap 4 days).

## 🩺 System health & run log

**🟢 healthy** — last autonomous run **2026-07-28T14:46:02Z** (market date 2026-07-28, `daily`).

- Action: held — no action
- Decision: holding — next scheduled rebalance on/after 2027-01-01
- Equity: ₹201,707 (+0.85%) · GO: **NOT YET**
- Freshness: ✓ Up to date — last marked 2026-07-28.

_Recent runs (last 10 of 33):_

| Ran (UTC) | As of | Cmd | Action | GO | Warnings |
|---|---|---|---|---|---|
| 2026-07-28T14:46:02Z | 2026-07-28 | daily | held — no action | NOT YET | — |
| 2026-07-27T15:19:17Z | 2026-07-27 | daily | held — no action | NOT YET | — |
| 2026-07-24T14:17:59Z | 2026-07-24 | daily | held — no action | NOT YET | — |
| 2026-07-23T14:37:59Z | 2026-07-23 | daily | held — no action | NOT YET | — |
| 2026-07-22T14:30:16Z | 2026-07-22 | daily | held — no action | NOT YET | — |
| 2026-07-21T14:30:09Z | 2026-07-21 | daily | held — no action | NOT YET | — |
| 2026-07-20T14:36:25Z | 2026-07-20 | daily | held — no action | NOT YET | — |
| 2026-07-17T14:09:03Z | 2026-07-17 | daily | held — no action | NOT YET | — |
| 2026-07-16T14:28:35Z | 2026-07-16 | daily | held — no action | NOT YET | — |
| 2026-07-15T14:15:52Z | 2026-07-15 | daily | held — no action | NOT YET | — |

---
_The decision engine is the same code validated in the backtest ([reports/PHASE0_VERDICT.md](PHASE0_VERDICT.md)); this page is regenerated daily by the pipeline, not by hand._
