#!/usr/bin/env bash
# Container start: bootstrap the gitignored price data (once, into the mounted volume), then serve.
set -euo pipefail

if [ ! -f data/historical/prices_pit_2026.parquet ]; then
  echo "[bootstrap] downloading strategy prices (yfinance)..."
  uv run python scripts/build_nifty_universe.py || true
  uv run python scripts/paper.py refresh || true
fi
if [ ! -f data/universes/nifty100_watchlist.csv ]; then
  uv run python scripts/build_nifty100_watchlist.py || true
fi
if [ ! -f data/historical/prices_watchlist.parquet ]; then
  echo "[bootstrap] downloading Nifty-100 watchlist prices (yfinance)..."
  uv run python scripts/build_nifty100_watchlist.py --prices || true
fi

exec uv run --extra dashboard streamlit run scripts/dashboard_app.py \
  --server.port 8501 --server.address 0.0.0.0 --server.headless true
