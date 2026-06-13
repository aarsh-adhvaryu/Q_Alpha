# Q-Alpha

[![CI](https://github.com/aarsh-adhvaryu/Q_Alpha/actions/workflows/ci.yml/badge.svg)](https://github.com/aarsh-adhvaryu/Q_Alpha/actions/workflows/ci.yml)

A tax-aware quantitative equity strategy for the Indian market (NSE/BSE), validated by a
walk-forward backtest that models **every rupee of cost and tax inside the trading decision** —
not bolted on afterwards. The full system design is in [Q_alpha.md](Q_alpha.md); developer/agent
orientation is in [CLAUDE.md](CLAUDE.md); the complete evidence chain and verdict are in
[reports/PHASE0_VERDICT.md](reports/PHASE0_VERDICT.md).

## Headline result

On a point-in-time Nifty 50 universe (delisted names included), **net of realistic Zerodha costs
and Indian FIFO capital-gains tax**, benchmarked against the Nifty 50 **total-return** index:

| Strategy | CAGR | Sharpe | vs benchmarks |
|---|---|---|---|
| **Q-Alpha** (tax-aware, annual, shrinkage-weighted) | **18.2%** | **1.13** | — |
| Nifty 50 TRI (dividends reinvested) | 14.5% | 0.98 | **+3.7%/yr** |
| Equal-weight 1/N | 17.7% | 1.09 | **+0.5%/yr** |

Beating 1/N net of friction is the hard bar — most "alpha" evaporates against equal-weight once
taxes are honest. Q-Alpha clears it **in-sample, on a genuinely out-of-time 2025–26 holdout (8.1%
vs 1/N's 7.1%), and across every rolling 3-year holding period** (it never had a losing 3-year
stretch).

Reproduce it:
```bash
cd qalpha
uv sync --extra dev
uv run python scripts/build_nifty_universe.py          # regenerate the point-in-time universe
uv run python scripts/run_phase0.py --end 2024-12-31   # → reports/phase0_report.md
```

## What's actually new here

Most backtests treat costs and taxes as a haircut applied at the end. Q-Alpha's core idea is that
**friction belongs inside the optimizer**: a rebalance is *refused* unless its risk reduction (in ₹)
beats 2× its real cost plus the FIFO capital-gains tax it would realize (spec §4.6). That single
change turns a strategy that is taxed to death (5.4% CAGR, a clear NO-GO) into one that beats the
index net of everything.

The headline finding is almost behavioral: **the edge is mostly tax-and-friction discipline, not
stock-picking genius.** Trading *less* (annual rebalancing) cut realized tax from ₹117k to ₹20k and
improved every metric monotonically; a principled **shrinkage weighting** (½ minimum-variance + ½
equal-weight over the picks — the DeMiguel/Tu-Zhou anchor-to-1/N result) is what finally beat 1/N
out-of-sample. Tax-aware portfolio construction for *Indian* retail (FIFO LTCG/STCG) is
under-explored — the academic literature is almost entirely US-centric.

## How it was validated (including the wrong turns)

The validation work is the point, not the CAGR. The result was stress-tested until it nearly broke,
then fixed honestly rather than tuned:

1. **Survivorship bias removed** — built a point-in-time Nifty 50 membership table (81 names,
   delisted companies included) by reverse-applying index reconstitutions; validation caught 4
   source errors and 2 missing exits. The edge *survived* (it wasn't being flattered by survivors).
2. **Fair benchmark** — switched from Nifty *price* to Nifty 50 **TRI** (dividends reinvested, a
   ~1.1%/yr higher bar), and found + fixed a **look-ahead bug in our own 1/N baseline** that had
   front-run future index entrants (fake 22.4%).
3. **Walk-forward** across independent regimes — the thesis held, but "annual is *the* optimal
   frequency" did not. Refined conclusion: the driver is **low *realized* turnover**, not a magic
   calendar number.
4. **Out-of-time holdout (2025–26) — initially FAILED.** On genuinely unseen data the strategy was
   flat (0.7%) while 1/N made 7.1%. Root cause diagnosed: the tax gate had *frozen* the portfolio
   after 2019 (only 5 rebalances ever), so the in-sample number was coasting on stale 2013–19
   winners. Fixed the ossification (`force_refresh`), then added shrinkage weighting — which beats
   1/N on the holdout too.
5. **Iron rule respected** — we did **not** tune parameters to manufacture a GO. Gate-multiplier
   calibration showed no value generalizes out-of-sample, so it was left at the spec default.

## Status

**Phase 0 (strategy validation by backtest): COMPLETE — defensible GO** on §14 criteria 1–3
(beats baselines net of cost+tax · no look-ahead · no survivorship bias). The strategy is validated
as far as *simulation* can go. The real-money GO is intentionally months away, gated by what no
backtest can replace: a live data pipeline, FIFO-vs-broker tax reconciliation, and a mandatory
3–6 month forward paper-trading run (spec §14 criteria 4–10, Phases 1–6).

## Setup

```bash
cd qalpha
uv sync --extra dev          # create venv + install
uv run pytest                # tests (must stay green)
uv run ruff check .          # lint
uv run ruff format --check . # format
uv run mypy src              # strict type-check
```

## Layout

```
src/qalpha/
  config.py        # all tunable parameters (Q_alpha.md §16) in one place
  data/            # yfinance ingest, point-in-time universe
  factors/         # momentum/volatility/liquidity scoring + regime classification
  alloc/           # Ledoit-Wolf covariance conditioning, sector allocator, optimizer (minvar|equal|score|shrink)
  accounting/      # FIFO tax lots, Zerodha costs, capital-gains tax  (reused by the future live system)
  backtest/        # walk-forward engine, baselines, metrics, go/no-go report
```

### Key engineering decisions
- **Broker = Zerodha (Kite Connect)**, not the spec's HDFC — notably ₹0 delivery brokerage, which
  changes the cost-gate math (`src/qalpha/accounting/costs.py`).
- **Money is `decimal.Decimal`** everywhere it touches accounting; never float (spec §5.2).
- **No look-ahead, ever** — all historical reads go through `PriceData.as_of(date)`; fundamentals
  carry a report-date + 90-day lag. There is a test that fails on look-ahead.
- The **accounting engine is standalone** so the future live decision engine reuses the exact same
  FIFO / cost / tax code path that the backtest was validated on.
