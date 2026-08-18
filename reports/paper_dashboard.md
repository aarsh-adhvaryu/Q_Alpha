# Q-Alpha — Paper-Trading Dashboard

_Notional paper trading (no real money) of the validated tax-aware strategy. As of **2026-08-17** · generated 2026-08-17 13:11 UTC._

## At a glance

| | |
|---|---|
| Started | 2026-06-12 (66 days) |
| Notional capital | ₹200,000 |
| Equity (marked) | ₹200,167 |
| Return since start | **+0.08%** |
| Nifty 50 TRI (same window) | +3.75% |
| Cash | ₹7,335 |
| Realized tax to date | ₹0.00 |
| Rebalances | 1 |
| Strategy | shrink-weighted, annual, tax-aware (band 0.1) |

## Today's recommendation

✅ **HOLD** — holding — next scheduled rebalance on/after 2027-01-01. No orders today.

## Holdings

| Ticker | Qty | Price | Value | Weight | LTCG-safe |
|---|---|---|---|---|---|
| APOLLOHOSP.NS | 4 | ₹8825.50 | ₹35,302 | 17.6% | ⏳ 300d · 13 Jun 27 |
| ASIANPAINT.NS | 14 | ₹2687.50 | ₹37,625 | 18.8% | ⏳ 300d · 13 Jun 27 |
| BEL.NS | 98 | ₹412.45 | ₹40,420 | 20.2% | ⏳ 300d · 13 Jun 27 |
| NTPC.NS | 113 | ₹337.00 | ₹38,081 | 19.0% | ⏳ 300d · 13 Jun 27 |
| SUNPHARMA.NS | 22 | ₹1882.00 | ₹41,404 | 20.7% | ⏳ 300d · 13 Jun 27 |

> **LTCG-safe** = the safe minimal holding date: hold until then and the whole line sells at the lower **12.5%** long-term rate instead of **20%** short-term (§111A→§112A). Selling earlier is allowed — it just taxes the still-short-term shares at 20%. `🟢 now` = already fully long-term.

## Equity track record

`▁▁▁▃▄▅▅▄▃▁▃▂▄▅▆█▆▂▃▄▄▄▄▄▃▅▅▅▄▃▆▄▄▄▅▅▅▄▅▄▄▃▃▄▄▂`  (46 daily marks; full series in `paper_equity.csv`)

| Date | Equity | Return |
|---|---|---|
| 2026-08-04 | ₹202,793 | +1.40% |
| 2026-08-05 | ₹202,054 | +1.03% |
| 2026-08-06 | ₹202,832 | +1.42% |
| 2026-08-07 | ₹202,196 | +1.10% |
| 2026-08-10 | ₹202,357 | +1.18% |
| 2026-08-11 | ₹201,377 | +0.69% |
| 2026-08-12 | ₹200,968 | +0.48% |
| 2026-08-13 | ₹201,946 | +0.97% |
| 2026-08-14 | ₹201,904 | +0.95% |
| 2026-08-17 | ₹200,167 | +0.08% |

## GO readiness (criterion 6)

🟡 **NOT YET** — accumulating evidence; the run has not yet cleared every criterion (this is the expected state until it does).

- 🟡 **Track length** — 46/63 trading days — building the minimum sample for a meaningful estimate.
- 🟡 **Volatility event withstood** — no market stress event yet (worst Nifty pullback in-window -2.2%, needs ≤ -10%). A calm run can't earn a GO — waiting on a real event.
- 🟡 **Forward vs benchmark** — trailing, but the 63-day power floor isn't met yet — too short to be a NO-GO (short-sample noise) — strategy +0.4% vs Nifty +3.8% (Δ -3.4%).
- 🟢 **Drawdown behaviour** — market-driven, within tolerance — worst live drawdown -2.6% vs Nifty -2.2% (excess -0.4%).
- 🟢 **Data integrity** — dense track record (largest gap 4 days).

## 🩺 System health & run log

**🟢 healthy** — last autonomous run **2026-08-17T13:11:50Z** (market date 2026-08-17, `daily`).

- Action: held — no action
- Decision: holding — next scheduled rebalance on/after 2027-01-01
- Equity: ₹200,167 (+0.08%) · GO: **NOT YET**
- Freshness: ✓ Up to date — last marked 2026-08-17.

_Recent runs (last 10 of 47):_

| Ran (UTC) | As of | Cmd | Action | GO | Warnings |
|---|---|---|---|---|---|
| 2026-08-17T13:11:50Z | 2026-08-17 | daily | held — no action | NOT YET | — |
| 2026-08-14T13:49:38Z | 2026-08-14 | daily | held — no action | NOT YET | — |
| 2026-08-13T13:53:31Z | 2026-08-13 | daily | held — no action | NOT YET | — |
| 2026-08-12T13:53:09Z | 2026-08-12 | daily | held — no action | NOT YET | — |
| 2026-08-11T13:48:32Z | 2026-08-11 | daily | held — no action | NOT YET | — |
| 2026-08-10T13:50:05Z | 2026-08-10 | daily | held — no action | NOT YET | — |
| 2026-08-07T13:44:05Z | 2026-08-07 | daily | held — no action | NOT YET | — |
| 2026-08-06T14:40:50Z | 2026-08-06 | daily | held — no action | NOT YET | — |
| 2026-08-05T14:41:08Z | 2026-08-05 | daily | held — no action | NOT YET | — |
| 2026-08-04T14:46:22Z | 2026-08-04 | daily | held — no action | NOT YET | — |

---
_The decision engine is the same code validated in the backtest ([reports/PHASE0_VERDICT.md](PHASE0_VERDICT.md)); this page is regenerated daily by the pipeline, not by hand._
