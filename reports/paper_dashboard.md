# Q-Alpha — Paper-Trading Dashboard

_Notional paper trading (no real money) of the validated tax-aware strategy. As of **2026-06-16** · generated 2026-06-16 17:27 UTC._

## At a glance

| | |
|---|---|
| Started | 2026-06-12 (4 days) |
| Notional capital | ₹200,000 |
| Equity (marked) | ₹199,103 |
| Return since start | **-0.45%** |
| Nifty 50 TRI (same window) | +1.42% |
| Cash | ₹7,335 |
| Realized tax to date | ₹0.00 |
| Rebalances | 1 |
| Strategy | shrink-weighted, annual, tax-aware (band 0.1) |

## Today's recommendation

⚠️ **ACTION NEEDED — scheduled refresh (force_refresh); drift 22.1%**

| Side | Ticker | Qty | Price |
|---|---|---|---|
| SELL | BEL.NS | 98 | ₹407.55 |
| BUY | NESTLEIND.NS | 28 | ₹1391.70 |

_Approve with:_ `uv run python scripts/paper.py apply`

## Holdings

| Ticker | Qty | Price | Value | Weight |
|---|---|---|---|---|
| APOLLOHOSP.NS | 4 | ₹8390.50 | ₹33,562 | 16.9% |
| ASIANPAINT.NS | 14 | ₹2748.10 | ₹38,473 | 19.3% |
| BEL.NS | 98 | ₹407.55 | ₹39,940 | 20.1% |
| NTPC.NS | 113 | ₹355.55 | ₹40,177 | 20.2% |
| SUNPHARMA.NS | 22 | ₹1800.70 | ₹39,615 | 19.9% |

## Equity track record

`█▁▄`  (3 daily marks; full series in `paper_equity.csv`)

| Date | Equity | Return |
|---|---|---|
| 2026-06-12 | ₹199,388 | -0.31% |
| 2026-06-15 | ₹198,763 | -0.62% |
| 2026-06-16 | ₹199,103 | -0.45% |

---
_The decision engine is the same code validated in the backtest ([reports/PHASE0_VERDICT.md](PHASE0_VERDICT.md)); this page is regenerated daily by the pipeline, not by hand._
