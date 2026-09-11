# Q-Alpha — Paper-Trading Dashboard

_Notional paper trading (no real money) of the validated tax-aware strategy. As of **2026-09-11** · generated 2026-09-11 06:15 UTC._

## At a glance

| | |
|---|---|
| Started | 2026-06-12 (91 days) |
| Notional capital | ₹200,000 |
| Equity (marked) | ₹194,803 |
| Return since start | **-2.60%** |
| Nifty 50 TRI (same window) | -0.43% |
| Cash | ₹7,335 |
| Realized tax to date | ₹0.00 |
| Rebalances | 1 |
| Strategy | shrink-weighted, annual, tax-aware (band 0.1) |

## Today's recommendation

✅ **HOLD** — holding — next scheduled rebalance on/after 2027-01-01. No orders today.

## Holdings

| Ticker | Qty | Price | Value | Weight | LTCG-safe |
|---|---|---|---|---|---|
| APOLLOHOSP.NS | 4 | ₹8833.00 | ₹35,332 | 18.1% | ⏳ 275d · 13 Jun 27 |
| ASIANPAINT.NS | 14 | ₹2456.00 | ₹34,384 | 17.7% | ⏳ 275d · 13 Jun 27 |
| BEL.NS | 98 | ₹402.20 | ₹39,416 | 20.2% | ⏳ 275d · 13 Jun 27 |
| NTPC.NS | 113 | ₹334.35 | ₹37,782 | 19.4% | ⏳ 275d · 13 Jun 27 |
| SUNPHARMA.NS | 22 | ₹1843.40 | ₹40,555 | 20.8% | ⏳ 275d · 13 Jun 27 |

> **LTCG-safe** = the safe minimal holding date: hold until then and the whole line sells at the lower **12.5%** long-term rate instead of **20%** short-term (§111A→§112A). Selling earlier is allowed — it just taxes the still-short-term shares at 20%. `🟢 now` = already fully long-term.

## Equity track record

`▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇█▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▁▇▇▇▇▇▇▇▇`  (63 daily marks; full series in `paper_equity.csv`)

| Date | Equity | Return |
|---|---|---|
| 2026-08-27 | ₹199,132 | -0.43% |
| 2026-08-28 | ₹121,519 | -39.24% |
| 2026-09-01 | ₹198,155 | -0.92% |
| 2026-09-02 | ₹197,147 | -1.43% |
| 2026-09-03 | ₹197,272 | -1.36% |
| 2026-09-04 | ₹196,392 | -1.80% |
| 2026-09-07 | ₹196,186 | -1.91% |
| 2026-09-08 | ₹196,532 | -1.73% |
| 2026-09-09 | ₹196,664 | -1.67% |
| 2026-09-11 | ₹194,803 | -2.60% |

## GO readiness (criterion 6)

🔴 **NO-GO** — a blocking criterion is failing (see below); the strategy is not behaving as validated.

- 🟢 **Track length** — 63 trading days marked (≥ 63).
- 🟡 **Volatility event withstood** — no market stress event yet (worst Nifty pullback in-window -5.0%, needs ≤ -10%). A calm run can't earn a GO — waiting on a real event.
- 🟡 **Forward vs benchmark** — within noise of the benchmark (≤ 3% behind) — strategy -2.3% vs Nifty -0.4% (Δ -1.9%).
- 🔴 **Drawdown behaviour** — fell 35.9% more than the market — idiosyncratic, behaviour diverged from the validated profile. worst live drawdown -40.9% vs Nifty -5.0% (excess -35.9%).
- 🟢 **Data integrity** — dense track record (largest gap 4 days).

## 🩺 System health & run log

**🟢 healthy** — last autonomous run **2026-09-09T16:46:10Z** (market date 2026-09-09, `daily`).

- Action: held — no action
- Decision: holding — next scheduled rebalance on/after 2027-01-01
- Equity: ₹196,664 (-1.67%) · GO: **NO-GO**
- Freshness: ✓ Up to date — last marked 2026-09-09.

_Recent runs (last 10 of 50):_

| Ran (UTC) | As of | Cmd | Action | GO | Warnings |
|---|---|---|---|---|---|
| 2026-09-09T16:46:10Z | 2026-09-09 | daily | held — no action | NO-GO | — |
| 2026-09-08T16:44:26Z | 2026-09-08 | daily | held — no action | NO-GO | — |
| 2026-09-08T13:34:44Z | 2026-09-08 | daily | held — no action | NO-GO | — |
| 2026-09-07T17:46:51Z | 2026-09-07 | daily | held — no action | NO-GO | — |
| 2026-09-04T16:29:05Z | 2026-09-04 | daily | held — no action | NO-GO | — |
| 2026-09-03T16:34:04Z | 2026-09-03 | daily | held — no action | NO-GO | — |
| 2026-09-02T16:42:06Z | 2026-09-02 | daily | held — no action | NO-GO | — |
| 2026-09-01T16:45:56Z | 2026-09-01 | daily | held — no action | NO-GO | — |
| 2026-08-31T19:09:42Z | 2026-08-28 | daily | held — no action | NO-GO | — |
| 2026-08-28T22:28:48Z | 2026-08-27 | daily | held — no action | NOT YET | — |

---
_The decision engine is the same code validated in the backtest ([reports/PHASE0_VERDICT.md](PHASE0_VERDICT.md)); this page is regenerated daily by the pipeline, not by hand._
