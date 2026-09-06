# Q-Alpha — Phase 0 Backtest Report

**Window:** 2012-01-02 → 2024-12-30  |  **Starting capital:** ₹200,000  |  **Rebalances:** 12
**Costs charged (strategy):** ₹9,517.10  |  **Capital-gains tax:** ₹50,317.77

## Performance vs baselines (strategy is net of Zerodha cost + capital-gains tax;
## baselines are idealised, cost-free and tax-free)

                strategy    final_₹  total_return_%  cagr_%  vol_%  sharpe  sortino  max_dd_%  calmar
------------------------  ---------  --------------  ------  -----  ------  -------  --------  ------
        Q-Alpha strategy  1690398.0           745.2    18.3   15.8    1.14     1.41     -25.2    0.73
              do_nothing   200000.0             0.0     0.0    0.0     0.0      0.0       0.0     0.0
Nifty 50 TRI (NIFTYBEES)  1120734.0           460.4    14.5   15.0    0.98     1.27     -36.3     0.4
            equal_weight  1591321.0           695.7    17.7   16.7    1.06     1.34     -39.0    0.45

**Monthly SIP into Nifty 50:** invested ₹1,560,000 over 156 installments → ₹4,071,609.09 (2.61×). (Different cash-flow profile — money-weighted reference, not a lump-sum curve.)

## Per-regime breakdown (strategy)

regime  days  %time  ann_ret_%  vol_%  sharpe
------  ----  -----  ---------  -----  ------
  bull  3202  100.0       18.1   15.8    1.14

## Drawdown analysis (Section 0 — dynamic, market-relative)

- Worst **absolute** drawdown: -25.2% on 2020-03-23 — Nifty was -36.3% that day (strategy fell LESS than the market).
- Worst **excess** drawdown vs Nifty (strategy-specific): -18.3% on 2018-02-02.
- Catastrophic backstop (≈ −40% absolute): not breached.
- Adaptive strategy-halt (sustained excess DD beyond 95th pct): never fired.
- **Criterion 8 (dynamic): PASS** — absolute drawdown was market-driven (beta), not an idiosyncratic blow-out; a flat 20% freeze would have misfired here.

## Go / No-Go

### Verdict: **GO**

- ✓ beats do-nothing (₹1,690,398 vs ₹200,000)
- ✓ beats Nifty 50 value (₹1,690,398 vs ₹1,120,734)
- ✓ beats Nifty 50 Sharpe (1.14 vs 0.98)
- • vs equal-weight (informational): ₹1,690,398 vs ₹1,591,321
- ✓ criteria 1 & 3 met

**Notes & caveats:**
- Criterion 2 (no look-ahead): guaranteed by `PriceData.as_of` slicing + tests.
- Universe is point-in-time.
- Benchmark: **Nifty 50 TRI (NIFTYBEES)**. TRI (dividends reinvested) is the fair bar since the strategy trades TR-adjusted prices.
- Phase 0a uses 3 price/volume factors; Value/Quality/Dividend (0b) need historical fundamentals before the six-factor verdict is final.