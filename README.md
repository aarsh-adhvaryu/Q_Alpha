# Q-Alpha

Quantitative wealth engine for Indian (NSE/BSE) equities. See [Q_alpha.md](Q_alpha.md) for the full
v3.1 system architecture, and [CLAUDE.md](CLAUDE.md) for a developer/agent orientation.

## Status: Phase 0 — Strategy Validation

Per the spec (§13), **no infrastructure is built until the strategy proves it beats baselines
after costs and taxes.** This repo currently contains only the Phase 0 backtest: a walk-forward
simulation that answers a single question —

> Does the six-factor → sector-allocator → min-variance strategy beat (a) doing nothing,
> (b) Nifty 50 buy-and-hold, (c) a monthly SIP, and (d) equal-weight — **net of realistic
> Zerodha costs and Indian capital-gains taxes**, with no look-ahead and no survivorship bias?

If the answer is no, we stop and rethink the strategy before writing any DB / broker / dashboard
code.

### Phase staging
- **0a** — price/volume factors only (Momentum, Volatility, Liquidity), free yfinance data.
  Proves the engine, cost/tax model, baselines, and walk-forward harness end-to-end.
- **0b** — full six factors (adds Value, Quality, Dividend) once historical fundamentals are
  sourced.

### Key deviations from the spec
- **Broker = Zerodha (Kite Connect)**, not HDFC. Notably ₹0 delivery brokerage — see
  `src/qalpha/accounting/costs.py`.
- The **cost + tax + FIFO-lot engine** (`src/qalpha/accounting/`) is built standalone so the
  future live decision engine reuses the exact same code.

## Setup

```bash
cd qalpha
uv sync --extra dev          # create venv + install
uv run pytest                # run tests
uv run ruff check .          # lint
uv run mypy src              # type-check
```

## Layout
```
src/qalpha/
  config.py        # all tunable parameters (Q_alpha.md §16) in one place
  data/            # yfinance ingest, point-in-time universe
  factors/         # factor scoring + regime classification
  alloc/           # covariance conditioning, sector allocator, optimizer
  accounting/      # FIFO tax lots, Zerodha costs, capital gains  (reused live)
  backtest/        # walk-forward engine, baselines, metrics, report
```
