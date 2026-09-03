# Q-Alpha — Paper-Trading Dashboard

_Notional paper trading (no real money) of the validated tax-aware strategy. As of **2026-09-03** · generated 2026-09-03 16:34 UTC._

## At a glance

| | |
|---|---|
| Started | 2026-06-12 (83 days) |
| Notional capital | ₹200,000 |
| Equity (marked) | ₹197,272 |
| Return since start | **-1.36%** |
| Nifty 50 TRI (same window) | +1.78% |
| Cash | ₹7,335 |
| Realized tax to date | ₹0.00 |
| Rebalances | 1 |
| Strategy | shrink-weighted, annual, tax-aware (band 0.1) |

## Today's recommendation

✅ **HOLD** — holding — next scheduled rebalance on/after 2027-01-01. No orders today.

## Holdings

| Ticker | Qty | Price | Value | Weight | LTCG-safe |
|---|---|---|---|---|---|
| APOLLOHOSP.NS | 4 | ₹8692.00 | ₹34,768 | 17.6% | ⏳ 283d · 13 Jun 27 |
| ASIANPAINT.NS | 14 | ₹2541.60 | ₹35,582 | 18.0% | ⏳ 283d · 13 Jun 27 |
| BEL.NS | 98 | ₹408.60 | ₹40,043 | 20.3% | ⏳ 283d · 13 Jun 27 |
| NTPC.NS | 113 | ₹330.90 | ₹37,392 | 19.0% | ⏳ 283d · 13 Jun 27 |
| SUNPHARMA.NS | 22 | ₹1916.00 | ₹42,152 | 21.4% | ⏳ 283d · 13 Jun 27 |

> **LTCG-safe** = the safe minimal holding date: hold until then and the whole line sells at the lower **12.5%** long-term rate instead of **20%** short-term (§111A→§112A). Selling earlier is allowed — it just taxes the still-short-term shares at 20%. `🟢 now` = already fully long-term.

## Equity track record

`▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇█▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▁▇▇▇`  (58 daily marks; full series in `paper_equity.csv`)

| Date | Equity | Return |
|---|---|---|
| 2026-08-20 | ₹199,175 | -0.41% |
| 2026-08-21 | ₹199,912 | -0.04% |
| 2026-08-24 | ₹199,580 | -0.21% |
| 2026-08-25 | ₹201,034 | +0.52% |
| 2026-08-26 | ₹198,647 | -0.68% |
| 2026-08-27 | ₹199,132 | -0.43% |
| 2026-08-28 | ₹121,519 | -39.24% |
| 2026-09-01 | ₹198,155 | -0.92% |
| 2026-09-02 | ₹197,147 | -1.43% |
| 2026-09-03 | ₹197,272 | -1.36% |

## GO readiness (criterion 6)

🔴 **NO-GO** — a blocking criterion is failing (see below); the strategy is not behaving as validated.

- 🟡 **Track length** — 58/63 trading days — building the minimum sample for a meaningful estimate.
- 🟡 **Volatility event withstood** — no market stress event yet (worst Nifty pullback in-window -2.8%, needs ≤ -10%). A calm run can't earn a GO — waiting on a real event.
- 🟡 **Forward vs benchmark** — within noise of the benchmark (≤ 3% behind) — strategy -1.1% vs Nifty +1.8% (Δ -2.8%).
- 🔴 **Drawdown behaviour** — fell 38.0% more than the market — idiosyncratic, behaviour diverged from the validated profile. worst live drawdown -40.9% vs Nifty -2.8% (excess -38.0%).
- 🟢 **Data integrity** — dense track record (largest gap 4 days).

## 🩺 System health & run log

**🟢 healthy** — last autonomous run **2026-09-03T16:34:04Z** (market date 2026-09-03, `daily`).

- Action: held — no action
- Decision: holding — next scheduled rebalance on/after 2027-01-01
- Equity: ₹197,272 (-1.36%) · GO: **NO-GO**
- Freshness: ✓ Up to date — last marked 2026-09-03.

_Recent runs (last 10 of 50):_

| Ran (UTC) | As of | Cmd | Action | GO | Warnings |
|---|---|---|---|---|---|
| 2026-09-03T16:34:04Z | 2026-09-03 | daily | held — no action | NO-GO | — |
| 2026-09-02T16:42:06Z | 2026-09-02 | daily | held — no action | NO-GO | — |
| 2026-09-01T16:45:56Z | 2026-09-01 | daily | held — no action | NO-GO | — |
| 2026-08-31T19:09:42Z | 2026-08-28 | daily | held — no action | NO-GO | — |
| 2026-08-28T22:28:48Z | 2026-08-27 | daily | held — no action | NOT YET | — |
| 2026-08-27T22:26:12Z | 2026-08-26 | daily | held — no action | NOT YET | — |
| 2026-08-26T13:29:23Z | 2026-08-26 | daily | held — no action | NOT YET | — |
| 2026-08-25T13:23:55Z | 2026-08-25 | daily | held — no action | NOT YET | — |
| 2026-08-24T13:26:25Z | 2026-08-24 | daily | held — no action | NOT YET | — |
| 2026-08-21T13:22:25Z | 2026-08-21 | daily | held — no action | NOT YET | — |

---
_The decision engine is the same code validated in the backtest ([reports/PHASE0_VERDICT.md](PHASE0_VERDICT.md)); this page is regenerated daily by the pipeline, not by hand._
