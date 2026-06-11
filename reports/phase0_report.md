# Q-Alpha — Phase 0 Backtest Report

**Window:** 2012-01-02 → 2024-12-30  |  **Starting capital:** ₹200,000  |  **Rebalances:** 9
**Costs charged (strategy):** ₹7,277.15  |  **Capital-gains tax:** ₹2,737.79

## Performance vs baselines (strategy is net of Zerodha cost + capital-gains tax;
## baselines are idealised, cost-free and tax-free)

        strategy    final_₹  total_return_%  cagr_%  vol_%  sharpe  sortino  max_dd_%  calmar
----------------  ---------  --------------  ------  -----  ------  -------  --------  ------
Q-Alpha strategy  1136672.0           468.3    14.6   15.1    0.98     1.29     -33.6    0.44
      do_nothing   200000.0             0.0     0.0    0.0     0.0      0.0       0.0     0.0
nifty50_buy_hold   992378.0           396.2    13.4   16.4    0.85     1.07     -38.4    0.35
    equal_weight  1579511.0           689.8    17.7   16.2    1.09     1.41     -35.6     0.5

**Monthly SIP into Nifty 50:** invested ₹1,560,000 over 156 installments → ₹3,761,259.18 (2.41×). (Different cash-flow profile — money-weighted reference, not a lump-sum curve.)

## Per-regime breakdown (strategy)

regime  days  %time  ann_ret_%  vol_%  sharpe
------  ----  -----  ---------  -----  ------
  bull  3202  100.0       14.8   15.1    0.98

## Go / No-Go

### Verdict: **CONDITIONAL**

- ✓ beats do-nothing (₹1,136,672 vs ₹200,000)
- ✓ beats Nifty 50 value (₹1,136,672 vs ₹992,378)
- ✓ beats Nifty 50 Sharpe (0.98 vs 0.85)
- ◦ vs equal-weight (informational): ₹1,136,672 vs ₹1,579,511
- ✓ criterion 1 met (beats all baselines net of cost+tax)
- ⚠ criterion 3 unmet: static universe carries SURVIVORSHIP BIAS — re-run on a point-in-time universe before trusting the edge

**Notes & caveats:**
- Criterion 2 (no look-ahead): guaranteed by `PriceData.as_of` slicing + tests.
- Universe is STATIC (survivorship-biased).
- Benchmark is the Nifty 50 *price* series; a Total-Return index would lift the bar slightly (the strategy is TR-adjusted). Use Nifty 50 TRI in calibration.
- Phase 0a uses 3 price/volume factors; Value/Quality/Dividend (0b) need historical fundamentals before the six-factor verdict is final.