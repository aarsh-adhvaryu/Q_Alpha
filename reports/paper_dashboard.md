# Q-Alpha — Paper-Trading Dashboard

_Notional paper trading (no real money) of the validated tax-aware strategy. As of **2026-09-01** · generated 2026-09-01 16:45 UTC._

## At a glance

| | |
|---|---|
| Started | 2026-06-12 (81 days) |
| Notional capital | ₹200,000 |
| Equity (marked) | ₹198,155 |
| Return since start | **-0.92%** |
| Nifty 50 TRI (same window) | +2.01% |
| Cash | ₹7,335 |
| Realized tax to date | ₹0.00 |
| Rebalances | 1 |
| Strategy | shrink-weighted, annual, tax-aware (band 0.1) |

## Today's recommendation

✅ **HOLD** — holding — next scheduled rebalance on/after 2027-01-01. No orders today.

## Holdings

| Ticker | Qty | Price | Value | Weight | LTCG-safe |
|---|---|---|---|---|---|
| APOLLOHOSP.NS | 4 | ₹8755.00 | ₹35,020 | 17.7% | ⏳ 285d · 13 Jun 27 |
| ASIANPAINT.NS | 14 | ₹2575.50 | ₹36,057 | 18.2% | ⏳ 285d · 13 Jun 27 |
| BEL.NS | 98 | ₹411.20 | ₹40,298 | 20.3% | ⏳ 285d · 13 Jun 27 |
| NTPC.NS | 113 | ₹327.50 | ₹37,008 | 18.7% | ⏳ 285d · 13 Jun 27 |
| SUNPHARMA.NS | 22 | ₹1929.00 | ₹42,438 | 21.4% | ⏳ 285d · 13 Jun 27 |

> **LTCG-safe** = the safe minimal holding date: hold until then and the whole line sells at the lower **12.5%** long-term rate instead of **20%** short-term (§111A→§112A). Selling earlier is allowed — it just taxes the still-short-term shares at 20%. `🟢 now` = already fully long-term.

## Equity track record

`▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇█▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▁▇`  (56 daily marks; full series in `paper_equity.csv`)

| Date | Equity | Return |
|---|---|---|
| 2026-08-18 | ₹199,121 | -0.44% |
| 2026-08-19 | ₹199,098 | -0.45% |
| 2026-08-20 | ₹199,175 | -0.41% |
| 2026-08-21 | ₹199,912 | -0.04% |
| 2026-08-24 | ₹199,580 | -0.21% |
| 2026-08-25 | ₹201,034 | +0.52% |
| 2026-08-26 | ₹198,647 | -0.68% |
| 2026-08-27 | ₹199,132 | -0.43% |
| 2026-08-28 | ₹121,519 | -39.24% |
| 2026-09-01 | ₹198,155 | -0.92% |

## GO readiness (criterion 6)

🔴 **NO-GO** — a blocking criterion is failing (see below); the strategy is not behaving as validated.

- 🟡 **Track length** — 56/63 trading days — building the minimum sample for a meaningful estimate.
- 🟡 **Volatility event withstood** — no market stress event yet (worst Nifty pullback in-window -2.6%, needs ≤ -10%). A calm run can't earn a GO — waiting on a real event.
- 🟡 **Forward vs benchmark** — within noise of the benchmark (≤ 3% behind) — strategy -0.6% vs Nifty +2.0% (Δ -2.6%).
- 🔴 **Drawdown behaviour** — fell 38.3% more than the market — idiosyncratic, behaviour diverged from the validated profile. worst live drawdown -40.9% vs Nifty -2.6% (excess -38.3%).
- 🟢 **Data integrity** — dense track record (largest gap 4 days).

## 🩺 System health & run log

**🟢 healthy** — last autonomous run **2026-09-01T16:45:56Z** (market date 2026-09-01, `daily`).

- Action: held — no action
- Decision: holding — next scheduled rebalance on/after 2027-01-01
- Equity: ₹198,155 (-0.92%) · GO: **NO-GO**
- Freshness: ✓ Up to date — last marked 2026-09-01.

_Recent runs (last 10 of 50):_

| Ran (UTC) | As of | Cmd | Action | GO | Warnings |
|---|---|---|---|---|---|
| 2026-09-01T16:45:56Z | 2026-09-01 | daily | held — no action | NO-GO | — |
| 2026-08-31T19:09:42Z | 2026-08-28 | daily | held — no action | NO-GO | — |
| 2026-08-28T22:28:48Z | 2026-08-27 | daily | held — no action | NOT YET | — |
| 2026-08-27T22:26:12Z | 2026-08-26 | daily | held — no action | NOT YET | — |
| 2026-08-26T13:29:23Z | 2026-08-26 | daily | held — no action | NOT YET | — |
| 2026-08-25T13:23:55Z | 2026-08-25 | daily | held — no action | NOT YET | — |
| 2026-08-24T13:26:25Z | 2026-08-24 | daily | held — no action | NOT YET | — |
| 2026-08-21T13:22:25Z | 2026-08-21 | daily | held — no action | NOT YET | — |
| 2026-08-20T13:22:39Z | 2026-08-20 | daily | held — no action | NOT YET | — |
| 2026-08-19T13:15:47Z | 2026-08-19 | daily | held — no action | NOT YET | — |

---
_The decision engine is the same code validated in the backtest ([reports/PHASE0_VERDICT.md](PHASE0_VERDICT.md)); this page is regenerated daily by the pipeline, not by hand._
