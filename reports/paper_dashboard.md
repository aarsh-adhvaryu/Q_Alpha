# Q-Alpha — Paper-Trading Dashboard

_Notional paper trading (no real money) of the validated tax-aware strategy. As of **2026-08-13** · generated 2026-08-13 13:53 UTC._

## At a glance

| | |
|---|---|
| Started | 2026-06-12 (62 days) |
| Notional capital | ₹200,000 |
| Equity (marked) | ₹201,946 |
| Return since start | **+0.97%** |
| Nifty 50 TRI (same window) | +3.85% |
| Cash | ₹7,335 |
| Realized tax to date | ₹0.00 |
| Rebalances | 1 |
| Strategy | shrink-weighted, annual, tax-aware (band 0.1) |

## Today's recommendation

✅ **HOLD** — holding — next scheduled rebalance on/after 2027-01-01. No orders today.

## Holdings

| Ticker | Qty | Price | Value | Weight | LTCG-safe |
|---|---|---|---|---|---|
| APOLLOHOSP.NS | 4 | ₹8600.00 | ₹34,400 | 17.0% | ⏳ 304d · 13 Jun 27 |
| ASIANPAINT.NS | 14 | ₹2755.50 | ₹38,577 | 19.1% | ⏳ 304d · 13 Jun 27 |
| BEL.NS | 98 | ₹410.50 | ₹40,229 | 19.9% | ⏳ 304d · 13 Jun 27 |
| NTPC.NS | 113 | ₹344.25 | ₹38,900 | 19.3% | ⏳ 304d · 13 Jun 27 |
| SUNPHARMA.NS | 22 | ₹1932.00 | ₹42,504 | 21.0% | ⏳ 304d · 13 Jun 27 |

> **LTCG-safe** = the safe minimal holding date: hold until then and the whole line sells at the lower **12.5%** long-term rate instead of **20%** short-term (§111A→§112A). Selling earlier is allowed — it just taxes the still-short-term shares at 20%. `🟢 now` = already fully long-term.

## Equity track record

`▁▁▁▃▄▅▅▄▃▁▃▂▄▅▆█▆▂▃▄▄▄▄▄▃▅▅▅▄▃▆▄▄▄▅▅▅▄▅▄▄▃▃▄`  (44 daily marks; full series in `paper_equity.csv`)

| Date | Equity | Return |
|---|---|---|
| 2026-07-31 | ₹202,665 | +1.33% |
| 2026-08-03 | ₹203,235 | +1.62% |
| 2026-08-04 | ₹202,793 | +1.40% |
| 2026-08-05 | ₹202,054 | +1.03% |
| 2026-08-06 | ₹202,832 | +1.42% |
| 2026-08-07 | ₹202,196 | +1.10% |
| 2026-08-10 | ₹202,357 | +1.18% |
| 2026-08-11 | ₹201,377 | +0.69% |
| 2026-08-12 | ₹200,968 | +0.48% |
| 2026-08-13 | ₹201,946 | +0.97% |

## GO readiness (criterion 6)

🟡 **NOT YET** — accumulating evidence; the run has not yet cleared every criterion (this is the expected state until it does).

- 🟡 **Track length** — 44/63 trading days — building the minimum sample for a meaningful estimate.
- 🟡 **Volatility event withstood** — no market stress event yet (worst Nifty pullback in-window -2.2%, needs ≤ -10%). A calm run can't earn a GO — waiting on a real event.
- 🟡 **Forward vs benchmark** — within noise of the benchmark (≤ 3% behind) — strategy +1.3% vs Nifty +3.8% (Δ -2.6%).
- 🟢 **Drawdown behaviour** — market-driven, within tolerance — worst live drawdown -2.4% vs Nifty -2.2% (excess -0.2%).
- 🟢 **Data integrity** — dense track record (largest gap 4 days).

## 🩺 System health & run log

**🟢 healthy** — last autonomous run **2026-08-13T13:53:31Z** (market date 2026-08-13, `daily`).

- Action: held — no action
- Decision: holding — next scheduled rebalance on/after 2027-01-01
- Equity: ₹201,946 (+0.97%) · GO: **NOT YET**
- Freshness: ✓ Up to date — last marked 2026-08-13.

_Recent runs (last 10 of 45):_

| Ran (UTC) | As of | Cmd | Action | GO | Warnings |
|---|---|---|---|---|---|
| 2026-08-13T13:53:31Z | 2026-08-13 | daily | held — no action | NOT YET | — |
| 2026-08-12T13:53:09Z | 2026-08-12 | daily | held — no action | NOT YET | — |
| 2026-08-11T13:48:32Z | 2026-08-11 | daily | held — no action | NOT YET | — |
| 2026-08-10T13:50:05Z | 2026-08-10 | daily | held — no action | NOT YET | — |
| 2026-08-07T13:44:05Z | 2026-08-07 | daily | held — no action | NOT YET | — |
| 2026-08-06T14:40:50Z | 2026-08-06 | daily | held — no action | NOT YET | — |
| 2026-08-05T14:41:08Z | 2026-08-05 | daily | held — no action | NOT YET | — |
| 2026-08-04T14:46:22Z | 2026-08-04 | daily | held — no action | NOT YET | — |
| 2026-08-03T15:21:57Z | 2026-08-03 | daily | held — no action | NOT YET | — |
| 2026-07-31T14:43:05Z | 2026-07-31 | daily | held — no action | NOT YET | — |

---
_The decision engine is the same code validated in the backtest ([reports/PHASE0_VERDICT.md](PHASE0_VERDICT.md)); this page is regenerated daily by the pipeline, not by hand._
