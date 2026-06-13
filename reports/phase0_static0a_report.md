# Q-Alpha — Phase 0 Backtest Report

**Window:** 2012-01-02 → 2024-12-30  |  **Starting capital:** ₹200,000  |  **Rebalances:** 9
**Costs charged (strategy):** ₹7,277.15  |  **Capital-gains tax:** ₹2,737.79

## Performance vs baselines (strategy is net of Zerodha cost + capital-gains tax;
## baselines are idealised, cost-free and tax-free)

                strategy    final_₹  total_return_%  cagr_%  vol_%  sharpe  sortino  max_dd_%  calmar
------------------------  ---------  --------------  ------  -----  ------  -------  --------  ------
        Q-Alpha strategy  1136672.0           468.3    14.6   15.1    0.98     1.29     -33.6    0.44
              do_nothing   200000.0             0.0     0.0    0.0     0.0      0.0       0.0     0.0
Nifty 50 TRI (NIFTYBEES)  1120734.0           460.4    14.5  253.3    0.31      2.0     -89.9    0.16
            equal_weight  1579511.0           689.8    17.7   16.2    1.09     1.41     -35.6     0.5

**Monthly SIP into Nifty 50:** invested ₹1,560,000 over 156 installments → ₹4,071,609.09 (2.61×). (Different cash-flow profile — money-weighted reference, not a lump-sum curve.)

## Per-regime breakdown (strategy)

regime  days  %time  ann_ret_%  vol_%  sharpe
------  ----  -----  ---------  -----  ------
  bull  3202  100.0       14.8   15.1    0.98

## Drawdown analysis (Section 0 — dynamic, market-relative)

- Worst **absolute** drawdown: -33.6% on 2020-03-23 — Nifty was -36.3% that day (strategy fell LESS than the market).
- Worst **excess** drawdown vs Nifty (strategy-specific): -90.5% on 2022-09-16.
- Catastrophic backstop (≈ −40% absolute): not breached.
- Adaptive strategy-halt (sustained excess DD beyond 95th pct): TRIGGERED.
- **Criterion 8 (dynamic): FAIL** — absolute drawdown was market-driven (beta), not an idiosyncratic blow-out; a flat 20% freeze would have misfired here.

## Go / No-Go

### Verdict: **CONDITIONAL**

- ✓ beats do-nothing (₹1,136,672 vs ₹200,000)
- ✓ beats Nifty 50 value (₹1,136,672 vs ₹1,120,734)
- ✓ beats Nifty 50 Sharpe (0.98 vs 0.31)
- ◦ vs equal-weight (informational): ₹1,136,672 vs ₹1,579,511
- ✓ criterion 1 met (beats all baselines net of cost+tax)
- ⚠ criterion 3 unmet: static universe carries SURVIVORSHIP BIAS — re-run on a point-in-time universe before trusting the edge

**Notes & caveats:**
- Criterion 2 (no look-ahead): guaranteed by `PriceData.as_of` slicing + tests.
- Universe is STATIC (survivorship-biased).
- Benchmark: **Nifty 50 TRI (NIFTYBEES)**. TRI (dividends reinvested) is the fair bar since the strategy trades TR-adjusted prices.
- Phase 0a uses 3 price/volume factors; Value/Quality/Dividend (0b) need historical fundamentals before the six-factor verdict is final.