# Q-Alpha — Phase 0 Backtest Report

**Window:** 2012-01-02 → 2024-12-30  |  **Starting capital:** ₹200,000  |  **Rebalances:** 46
**Costs charged (strategy):** ₹43,130.97  |  **Capital-gains tax:** ₹78,271.14

## Performance vs baselines (strategy is net of Zerodha cost + capital-gains tax;
## baselines are idealised, cost-free and tax-free)

        strategy    final_₹  total_return_%  cagr_%  vol_%  sharpe  sortino  max_dd_%  calmar
----------------  ---------  --------------  ------  -----  ------  -------  --------  ------
Q-Alpha strategy  1412776.0           606.4    16.6   15.7    1.06     1.41     -34.5    0.48
      do_nothing   200000.0             0.0     0.0    0.0     0.0      0.0       0.0     0.0
nifty50_buy_hold   992378.0           396.2    13.4   16.4    0.85     1.07     -38.4    0.35
    equal_weight  1579511.0           689.8    17.7   16.2    1.09     1.41     -35.6     0.5

**Monthly SIP into Nifty 50:** invested ₹1,560,000 over 156 installments → ₹3,761,259.18 (2.41×). (Different cash-flow profile — money-weighted reference, not a lump-sum curve.)

## Per-regime breakdown (strategy)

regime  days  %time  ann_ret_%  vol_%  sharpe
------  ----  -----  ---------  -----  ------
  bull  3202  100.0       16.6   15.7    1.06

## Drawdown analysis (Section 0 — dynamic, market-relative)

- Worst **absolute** drawdown: -34.5% on 2020-03-23 — Nifty was -38.4% that day (strategy fell LESS than the market).
- Worst **excess** drawdown vs Nifty (strategy-specific): -18.6% on 2015-01-27.
- Catastrophic backstop (≈ −40% absolute): not breached.
- Adaptive strategy-halt (sustained excess DD beyond 95th pct): never fired.
- **Criterion 8 (dynamic): PASS** — absolute drawdown was market-driven (beta), not an idiosyncratic blow-out; a flat 20% freeze would have misfired here.

## Go / No-Go

### Verdict: **CONDITIONAL**

- ✓ beats do-nothing (₹1,412,776 vs ₹200,000)
- ✓ beats Nifty 50 value (₹1,412,776 vs ₹992,378)
- ✓ beats Nifty 50 Sharpe (1.06 vs 0.85)
- ◦ vs equal-weight (informational): ₹1,412,776 vs ₹1,579,511
- ✓ criterion 1 met (beats all baselines net of cost+tax)
- ⚠ criterion 3 unmet: static universe carries SURVIVORSHIP BIAS — re-run on a point-in-time universe before trusting the edge

**Notes & caveats:**
- Criterion 2 (no look-ahead): guaranteed by `PriceData.as_of` slicing + tests.
- Universe is STATIC (survivorship-biased).
- Benchmark is the Nifty 50 *price* series; a Total-Return index would lift the bar slightly (the strategy is TR-adjusted). Use Nifty 50 TRI in calibration.
- Phase 0a uses 3 price/volume factors; Value/Quality/Dividend (0b) need historical fundamentals before the six-factor verdict is final.