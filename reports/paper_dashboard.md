# Q-Alpha — Paper-Trading Dashboard

_Notional paper trading (no real money) of the validated tax-aware strategy. As of **2026-06-15** · generated 2026-06-15 15:16 UTC._

## At a glance

| | |
|---|---|
| Started | 2026-06-12 (3 days) |
| Notional capital | ₹200,000 |
| Equity (marked) | ₹198,763 |
| Return since start | **-0.62%** |
| Nifty 50 TRI (same window) | +1.03% |
| Cash | ₹7,335 |
| Realized tax to date | ₹0.00 |
| Rebalances | 1 |
| Strategy | shrink-weighted, annual, tax-aware (band 0.1) |

## Today's recommendation

⚠️ **ACTION NEEDED — scheduled refresh (force_refresh); drift 22.0%**

| Side | Ticker | Qty | Price |
|---|---|---|---|
| SELL | BEL.NS | 98 | ₹409.55 |
| BUY | NESTLEIND.NS | 28 | ₹1374.70 |

_Approve with:_ `uv run python scripts/paper.py apply`

## Holdings

| Ticker | Qty | Price | Value | Weight |
|---|---|---|---|---|
| APOLLOHOSP.NS | 4 | ₹8468.50 | ₹33,874 | 17.0% |
| ASIANPAINT.NS | 14 | ₹2739.30 | ₹38,350 | 19.3% |
| BEL.NS | 98 | ₹409.55 | ₹40,136 | 20.2% |
| NTPC.NS | 113 | ₹348.10 | ₹39,335 | 19.8% |
| SUNPHARMA.NS | 22 | ₹1806.00 | ₹39,732 | 20.0% |

## Equity track record

`█▁`  (2 daily marks; full series in `paper_equity.csv`)

| Date | Equity | Return |
|---|---|---|
| 2026-06-12 | ₹199,388 | -0.31% |
| 2026-06-15 | ₹198,763 | -0.62% |

---
_The decision engine is the same code validated in the backtest ([reports/PHASE0_VERDICT.md](PHASE0_VERDICT.md)); this page is regenerated daily by the pipeline, not by hand._
