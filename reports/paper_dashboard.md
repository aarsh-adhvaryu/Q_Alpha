# Q-Alpha — Paper-Trading Dashboard

_Notional paper trading (no real money) of the validated tax-aware strategy. As of **2026-06-19** · generated 2026-06-19 15:46 UTC._

## At a glance

| | |
|---|---|
| Started | 2026-06-12 (7 days) |
| Notional capital | ₹200,000 |
| Equity (marked) | ₹203,168 |
| Return since start | **+1.58%** |
| Nifty 50 TRI (same window) | +1.90% |
| Cash | ₹7,335 |
| Realized tax to date | ₹0.00 |
| Rebalances | 1 |
| Strategy | shrink-weighted, annual, tax-aware (band 0.1) |

## Today's recommendation

✅ **HOLD** — holding — next scheduled rebalance on/after 2027-01-01. No orders today.

## Holdings

| Ticker | Qty | Price | Value | Weight |
|---|---|---|---|---|
| APOLLOHOSP.NS | 4 | ₹8489.50 | ₹33,958 | 16.7% |
| ASIANPAINT.NS | 14 | ₹2732.90 | ₹38,261 | 18.8% |
| BEL.NS | 98 | ₹426.90 | ₹41,836 | 20.6% |
| NTPC.NS | 113 | ₹365.80 | ₹41,335 | 20.3% |
| SUNPHARMA.NS | 22 | ₹1838.30 | ₹40,443 | 19.9% |

## Equity track record

`▁▁▁▄▇█`  (6 daily marks; full series in `paper_equity.csv`)

| Date | Equity | Return |
|---|---|---|
| 2026-06-12 | ₹199,388 | -0.31% |
| 2026-06-15 | ₹198,763 | -0.62% |
| 2026-06-16 | ₹199,103 | -0.45% |
| 2026-06-17 | ₹200,749 | +0.37% |
| 2026-06-18 | ₹202,600 | +1.30% |
| 2026-06-19 | ₹203,168 | +1.58% |

## GO readiness (criterion 6)

🟡 **NOT YET** — accumulating evidence; the run has not yet cleared every criterion (this is the expected state until it does).

- 🟡 **Track length** — 6/63 trading days — building the minimum sample for a meaningful estimate.
- 🟡 **Volatility event withstood** — no market stress event yet (worst Nifty pullback in-window -0.4%, needs ≤ -10%). A calm run can't earn a GO — waiting on a real event.
- 🟡 **Forward vs benchmark** — within noise of the benchmark (≤ 3% behind) — strategy +1.9% vs Nifty +1.9% (Δ -0.0%).
- 🟢 **Drawdown behaviour** — worst live drawdown -0.3% (within the backtest envelope).
- 🟢 **Data integrity** — dense track record (largest gap 3 days).

---
_The decision engine is the same code validated in the backtest ([reports/PHASE0_VERDICT.md](PHASE0_VERDICT.md)); this page is regenerated daily by the pipeline, not by hand._
