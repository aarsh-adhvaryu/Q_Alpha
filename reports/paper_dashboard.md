# Q-Alpha — Paper-Trading Dashboard

_Notional paper trading (no real money) of the validated tax-aware strategy. As of **2026-06-18** · generated 2026-06-18 15:57 UTC._

## At a glance

| | |
|---|---|
| Started | 2026-06-12 (6 days) |
| Notional capital | ₹200,000 |
| Equity (marked) | ₹202,600 |
| Return since start | **+1.30%** |
| Nifty 50 TRI (same window) | +2.28% |
| Cash | ₹7,335 |
| Realized tax to date | ₹0.00 |
| Rebalances | 1 |
| Strategy | shrink-weighted, annual, tax-aware (band 0.1) |

## Today's recommendation

⚠️ **ACTION NEEDED — scheduled refresh (force_refresh); drift 41.6%**

| Side | Ticker | Qty | Price |
|---|---|---|---|
| SELL | ASIANPAINT.NS | 14 | ₹2755.00 |
| SELL | BEL.NS | 98 | ₹428.60 |
| BUY | LT.NS | 9 | ₹4190.00 |
| BUY | NESTLEIND.NS | 29 | ₹1400.40 |

_Approve with:_ `uv run python scripts/paper.py apply`

## Holdings

| Ticker | Qty | Price | Value | Weight |
|---|---|---|---|---|
| APOLLOHOSP.NS | 4 | ₹8411.50 | ₹33,646 | 16.6% |
| ASIANPAINT.NS | 14 | ₹2755.00 | ₹38,570 | 19.0% |
| BEL.NS | 98 | ₹428.60 | ₹42,003 | 20.7% |
| NTPC.NS | 113 | ₹361.95 | ₹40,900 | 20.2% |
| SUNPHARMA.NS | 22 | ₹1824.80 | ₹40,146 | 19.8% |

## Equity track record

`▂▁▁▄█`  (5 daily marks; full series in `paper_equity.csv`)

| Date | Equity | Return |
|---|---|---|
| 2026-06-12 | ₹199,388 | -0.31% |
| 2026-06-15 | ₹198,763 | -0.62% |
| 2026-06-16 | ₹199,103 | -0.45% |
| 2026-06-17 | ₹200,749 | +0.37% |
| 2026-06-18 | ₹202,600 | +1.30% |

---
_The decision engine is the same code validated in the backtest ([reports/PHASE0_VERDICT.md](PHASE0_VERDICT.md)); this page is regenerated daily by the pipeline, not by hand._
