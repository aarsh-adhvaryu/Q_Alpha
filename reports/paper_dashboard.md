# Q-Alpha — Paper-Trading Dashboard

_Notional paper trading (no real money) of the validated tax-aware strategy. As of **2026-08-26** · generated 2026-08-26 13:29 UTC._

## At a glance

| | |
|---|---|
| Started | 2026-06-12 (75 days) |
| Notional capital | ₹200,000 |
| Equity (marked) | ₹198,647 |
| Return since start | **-0.68%** |
| Nifty 50 TRI (same window) | +3.42% |
| Cash | ₹7,335 |
| Realized tax to date | ₹0.00 |
| Rebalances | 1 |
| Strategy | shrink-weighted, annual, tax-aware (band 0.1) |

## Today's recommendation

✅ **HOLD** — holding — next scheduled rebalance on/after 2027-01-01. No orders today.

## Holdings

| Ticker | Qty | Price | Value | Weight | LTCG-safe |
|---|---|---|---|---|---|
| APOLLOHOSP.NS | 4 | ₹8766.50 | ₹35,066 | 17.7% | ⏳ 291d · 13 Jun 27 |
| ASIANPAINT.NS | 14 | ₹2626.50 | ₹36,771 | 18.5% | ⏳ 291d · 13 Jun 27 |
| BEL.NS | 98 | ₹406.90 | ₹39,876 | 20.1% | ⏳ 291d · 13 Jun 27 |
| NTPC.NS | 113 | ₹334.60 | ₹37,810 | 19.0% | ⏳ 291d · 13 Jun 27 |
| SUNPHARMA.NS | 22 | ₹1899.50 | ₹41,789 | 21.0% | ⏳ 291d · 13 Jun 27 |

> **LTCG-safe** = the safe minimal holding date: hold until then and the whole line sells at the lower **12.5%** long-term rate instead of **20%** short-term (§111A→§112A). Selling earlier is allowed — it just taxes the still-short-term shares at 20%. `🟢 now` = already fully long-term.

## Equity track record

`▁▁▁▃▅▅▅▄▃▁▃▂▄▅▆█▆▂▃▄▄▄▅▄▃▅▅▅▄▃▆▄▄▄▅▅▅▄▅▄▄▃▃▄▄▂▁▁▁▂▁▃▁`  (53 daily marks; full series in `paper_equity.csv`)

| Date | Equity | Return |
|---|---|---|
| 2026-08-13 | ₹201,946 | +0.97% |
| 2026-08-14 | ₹201,904 | +0.95% |
| 2026-08-17 | ₹200,167 | +0.08% |
| 2026-08-18 | ₹199,121 | -0.44% |
| 2026-08-19 | ₹199,098 | -0.45% |
| 2026-08-20 | ₹199,175 | -0.41% |
| 2026-08-21 | ₹199,912 | -0.04% |
| 2026-08-24 | ₹199,580 | -0.21% |
| 2026-08-25 | ₹201,034 | +0.52% |
| 2026-08-26 | ₹198,647 | -0.68% |

## GO readiness (criterion 6)

🟡 **NOT YET** — accumulating evidence; the run has not yet cleared every criterion (this is the expected state until it does).

- 🟡 **Track length** — 53/63 trading days — building the minimum sample for a meaningful estimate.
- 🟡 **Volatility event withstood** — no market stress event yet (worst Nifty pullback in-window -2.2%, needs ≤ -10%). A calm run can't earn a GO — waiting on a real event.
- 🟡 **Forward vs benchmark** — trailing, but the 63-day power floor isn't met yet — too short to be a NO-GO (short-sample noise) — strategy -0.4% vs Nifty +3.4% (Δ -3.8%).
- 🟢 **Drawdown behaviour** — market-driven, within tolerance — worst live drawdown -3.3% vs Nifty -2.2% (excess -1.1%).
- 🟢 **Data integrity** — dense track record (largest gap 4 days).

## 🩺 System health & run log

**🟢 healthy** — last autonomous run **2026-08-26T13:29:23Z** (market date 2026-08-26, `daily`).

- Action: held — no action
- Decision: holding — next scheduled rebalance on/after 2027-01-01
- Equity: ₹198,647 (-0.68%) · GO: **NOT YET**
- Freshness: ✓ Up to date — last marked 2026-08-26.

_Recent runs (last 10 of 50):_

| Ran (UTC) | As of | Cmd | Action | GO | Warnings |
|---|---|---|---|---|---|
| 2026-08-26T13:29:23Z | 2026-08-26 | daily | held — no action | NOT YET | — |
| 2026-08-25T13:23:55Z | 2026-08-25 | daily | held — no action | NOT YET | — |
| 2026-08-24T13:26:25Z | 2026-08-24 | daily | held — no action | NOT YET | — |
| 2026-08-21T13:22:25Z | 2026-08-21 | daily | held — no action | NOT YET | — |
| 2026-08-20T13:22:39Z | 2026-08-20 | daily | held — no action | NOT YET | — |
| 2026-08-19T13:15:47Z | 2026-08-19 | daily | held — no action | NOT YET | — |
| 2026-08-18T13:14:11Z | 2026-08-18 | daily | held — no action | NOT YET | — |
| 2026-08-17T13:11:50Z | 2026-08-17 | daily | held — no action | NOT YET | — |
| 2026-08-14T13:49:38Z | 2026-08-14 | daily | held — no action | NOT YET | — |
| 2026-08-13T13:53:31Z | 2026-08-13 | daily | held — no action | NOT YET | — |

---
_The decision engine is the same code validated in the backtest ([reports/PHASE0_VERDICT.md](PHASE0_VERDICT.md)); this page is regenerated daily by the pipeline, not by hand._
