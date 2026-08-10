# Q-Alpha — Paper-Trading Dashboard

_Notional paper trading (no real money) of the validated tax-aware strategy. As of **2026-08-10** · generated 2026-08-10 13:50 UTC._

## At a glance

| | |
|---|---|
| Started | 2026-06-12 (59 days) |
| Notional capital | ₹200,000 |
| Equity (marked) | ₹202,357 |
| Return since start | **+1.18%** |
| Nifty 50 TRI (same window) | +4.70% |
| Cash | ₹7,335 |
| Realized tax to date | ₹0.00 |
| Rebalances | 1 |
| Strategy | shrink-weighted, annual, tax-aware (band 0.1) |

## Today's recommendation

✅ **HOLD** — holding — next scheduled rebalance on/after 2027-01-01. No orders today.

## Holdings

| Ticker | Qty | Price | Value | Weight | LTCG-safe |
|---|---|---|---|---|---|
| APOLLOHOSP.NS | 4 | ₹8912.00 | ₹35,648 | 17.6% | ⏳ 306d · 12 Jun 27 |
| ASIANPAINT.NS | 14 | ₹2750.00 | ₹38,500 | 19.0% | ⏳ 306d · 12 Jun 27 |
| BEL.NS | 98 | ₹404.35 | ₹39,626 | 19.6% | ⏳ 306d · 12 Jun 27 |
| NTPC.NS | 113 | ₹340.45 | ₹38,471 | 19.0% | ⏳ 306d · 12 Jun 27 |
| SUNPHARMA.NS | 22 | ₹1944.40 | ₹42,777 | 21.1% | ⏳ 306d · 12 Jun 27 |

> **LTCG-safe** = the safe minimal holding date: hold until then and the whole line sells at the lower **12.5%** long-term rate instead of **20%** short-term (§111A→§112A). Selling earlier is allowed — it just taxes the still-short-term shares at 20%. `🟢 now` = already fully long-term.

## Equity track record

`▁▁▁▃▄▅▅▄▃▁▃▂▄▅▆█▆▂▃▄▄▄▄▄▃▅▅▅▄▃▆▄▄▄▅▅▅▄▅▄▄`  (41 daily marks; full series in `paper_equity.csv`)

| Date | Equity | Return |
|---|---|---|
| 2026-07-28 | ₹201,707 | +0.85% |
| 2026-07-29 | ₹202,266 | +1.13% |
| 2026-07-30 | ₹202,447 | +1.22% |
| 2026-07-31 | ₹202,665 | +1.33% |
| 2026-08-03 | ₹203,235 | +1.62% |
| 2026-08-04 | ₹202,793 | +1.40% |
| 2026-08-05 | ₹202,054 | +1.03% |
| 2026-08-06 | ₹202,832 | +1.42% |
| 2026-08-07 | ₹202,196 | +1.10% |
| 2026-08-10 | ₹202,357 | +1.18% |

## GO readiness (criterion 6)

🟡 **NOT YET** — accumulating evidence; the run has not yet cleared every criterion (this is the expected state until it does).

- 🟡 **Track length** — 41/63 trading days — building the minimum sample for a meaningful estimate.
- 🟡 **Volatility event withstood** — no market stress event yet (worst Nifty pullback in-window -2.2%, needs ≤ -10%). A calm run can't earn a GO — waiting on a real event.
- 🟡 **Forward vs benchmark** — trailing, but the 63-day power floor isn't met yet — too short to be a NO-GO (short-sample noise) — strategy +1.5% vs Nifty +4.7% (Δ -3.2%).
- 🟢 **Drawdown behaviour** — market-driven, within tolerance — worst live drawdown -2.4% vs Nifty -2.2% (excess -0.2%).
- 🟢 **Data integrity** — dense track record (largest gap 4 days).

## 🩺 System health & run log

**🟢 healthy** — last autonomous run **2026-08-10T13:50:05Z** (market date 2026-08-10, `daily`).

- Action: held — no action
- Decision: holding — next scheduled rebalance on/after 2027-01-01
- Equity: ₹202,357 (+1.18%) · GO: **NOT YET**
- Freshness: ✓ Up to date — last marked 2026-08-10.

_Recent runs (last 10 of 42):_

| Ran (UTC) | As of | Cmd | Action | GO | Warnings |
|---|---|---|---|---|---|
| 2026-08-10T13:50:05Z | 2026-08-10 | daily | held — no action | NOT YET | — |
| 2026-08-07T13:44:05Z | 2026-08-07 | daily | held — no action | NOT YET | — |
| 2026-08-06T14:40:50Z | 2026-08-06 | daily | held — no action | NOT YET | — |
| 2026-08-05T14:41:08Z | 2026-08-05 | daily | held — no action | NOT YET | — |
| 2026-08-04T14:46:22Z | 2026-08-04 | daily | held — no action | NOT YET | — |
| 2026-08-03T15:21:57Z | 2026-08-03 | daily | held — no action | NOT YET | — |
| 2026-07-31T14:43:05Z | 2026-07-31 | daily | held — no action | NOT YET | — |
| 2026-07-30T14:38:23Z | 2026-07-30 | daily | held — no action | NOT YET | — |
| 2026-07-29T14:36:05Z | 2026-07-29 | daily | held — no action | NOT YET | — |
| 2026-07-28T14:46:02Z | 2026-07-28 | daily | held — no action | NOT YET | — |

---
_The decision engine is the same code validated in the backtest ([reports/PHASE0_VERDICT.md](PHASE0_VERDICT.md)); this page is regenerated daily by the pipeline, not by hand._
