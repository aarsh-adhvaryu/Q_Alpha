# Q-Alpha — Phase 0 Backtest Report

**Window:** 2012-01-02 → 2024-12-30  |  **Starting capital:** ₹200,000  |  **Rebalances:** 5
**Costs charged (strategy):** ₹8,853.08  |  **Capital-gains tax:** ₹20,085.75

## Performance vs baselines (strategy is net of Zerodha cost + capital-gains tax;
## baselines are idealised, cost-free and tax-free)

                strategy    final_₹  total_return_%  cagr_%  vol_%  sharpe  sortino  max_dd_%  calmar
------------------------  ---------  --------------  ------  -----  ------  -------  --------  ------
        Q-Alpha strategy  1728331.0           764.2    18.5   16.1    1.13     1.43     -24.1    0.77
              do_nothing   200000.0             0.0     0.0    0.0     0.0      0.0       0.0     0.0
Nifty 50 TRI (NIFTYBEES)  1120734.0           460.4    14.5   15.0    0.98     1.27     -36.3     0.4
            equal_weight  1591321.0           695.7    17.7   16.7    1.06     1.34     -39.0    0.45

**Monthly SIP into Nifty 50:** invested ₹1,560,000 over 156 installments → ₹4,071,609.09 (2.61×). (Different cash-flow profile — money-weighted reference, not a lump-sum curve.)

## Per-regime breakdown (strategy)

regime  days  %time  ann_ret_%  vol_%  sharpe
------  ----  -----  ---------  -----  ------
  bull  3202  100.0       18.3   16.1    1.13

## Drawdown analysis (Section 0 — dynamic, market-relative)

- Worst **absolute** drawdown: -24.1% on 2020-03-23 — Nifty was -36.3% that day (strategy fell LESS than the market).
- Worst **excess** drawdown vs Nifty (strategy-specific): -19.4% on 2023-02-15.
- Catastrophic backstop (≈ −40% absolute): not breached.
- Adaptive strategy-halt (sustained excess DD beyond 95th pct): never fired.
- **Criterion 8 (dynamic): PASS** — absolute drawdown was market-driven (beta), not an idiosyncratic blow-out; a flat 20% freeze would have misfired here.

## Go / No-Go

### Verdict: **GO**

- ✓ beats do-nothing (₹1,728,331 vs ₹200,000)
- ✓ beats Nifty 50 value (₹1,728,331 vs ₹1,120,734)
- ✓ beats Nifty 50 Sharpe (1.13 vs 0.98)
- • vs equal-weight (informational): ₹1,728,331 vs ₹1,591,321
- ✓ criteria 1 & 3 met

**Notes & caveats:**
- Criterion 2 (no look-ahead): guaranteed by `PriceData.as_of` slicing + tests.
- Universe is point-in-time.
- Benchmark: **Nifty 50 TRI (NIFTYBEES)**. TRI (dividends reinvested) is the fair bar since the strategy trades TR-adjusted prices.
- Phase 0a uses 3 price/volume factors; Value/Quality/Dividend (0b) need historical fundamentals before the six-factor verdict is final.