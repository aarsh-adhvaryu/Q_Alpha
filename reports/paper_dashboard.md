# Q-Alpha — Paper-Trading Dashboard

_Notional paper trading (no real money) of the validated tax-aware strategy. As of **2026-06-17** · generated 2026-06-17 16:09 UTC._

## At a glance

| | |
|---|---|
| Started | 2026-06-12 (5 days) |
| Notional capital | ₹200,000 |
| Equity (marked) | ₹200,749 |
| Return since start | **+0.37%** |
| Nifty 50 TRI (same window) | +1.96% |
| Cash | ₹7,335 |
| Realized tax to date | ₹0.00 |
| Rebalances | 1 |
| Strategy | shrink-weighted, annual, tax-aware (band 0.1) |

## Today's recommendation

⚠️ **ACTION NEEDED — scheduled refresh (force_refresh); drift 41.4%**

| Side | Ticker | Qty | Price |
|---|---|---|---|
| SELL | ASIANPAINT.NS | 14 | ₹2738.00 |
| SELL | BEL.NS | 98 | ₹419.85 |
| BUY | HINDALCO.NS | 38 | ₹1007.90 |
| BUY | NESTLEIND.NS | 29 | ₹1407.30 |

_Approve with:_ `uv run python scripts/paper.py apply`

## Holdings

| Ticker | Qty | Price | Value | Weight |
|---|---|---|---|---|
| APOLLOHOSP.NS | 4 | ₹8427.50 | ₹33,710 | 16.8% |
| ASIANPAINT.NS | 14 | ₹2738.00 | ₹38,332 | 19.1% |
| BEL.NS | 98 | ₹419.85 | ₹41,145 | 20.5% |
| NTPC.NS | 113 | ₹355.55 | ₹40,177 | 20.0% |
| SUNPHARMA.NS | 22 | ₹1820.40 | ₹40,049 | 19.9% |

## Equity track record

`▃▁▂█`  (4 daily marks; full series in `paper_equity.csv`)

| Date | Equity | Return |
|---|---|---|
| 2026-06-12 | ₹199,388 | -0.31% |
| 2026-06-15 | ₹198,763 | -0.62% |
| 2026-06-16 | ₹199,103 | -0.45% |
| 2026-06-17 | ₹200,749 | +0.37% |

---
_The decision engine is the same code validated in the backtest ([reports/PHASE0_VERDICT.md](PHASE0_VERDICT.md)); this page is regenerated daily by the pipeline, not by hand._
