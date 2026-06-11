"""Run the Phase-0 backtest on real NSE data and print the go/no-go report.

Phase 0a: 3 price/volume factors on a curated, liquid large-cap watchlist (~25 names, 8 sectors).
The watchlist is *static* (today's survivors), so the report self-flags SURVIVORSHIP BIAS and the
verdict is capped at CONDITIONAL — this is the honest Phase-0a smoke test, not the final word.

Usage:
    uv run python scripts/run_phase0.py                 # use cached parquet if present
    uv run python scripts/run_phase0.py --refresh       # re-download from yfinance
    uv run python scripts/run_phase0.py --start 2012-01-01 --end 2024-12-31
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from qalpha.backtest.engine import run_backtest
from qalpha.backtest.report import build_report
from qalpha.config import Config
from qalpha.data.fundamentals import FundamentalsStore, ingest_dir
from qalpha.data.ingest import download_prices, load_parquet, save_parquet
from qalpha.data.prices import PriceData
from qalpha.data.universe import Universe

RAW_FUNDAMENTALS_DIR = Path("data/fundamentals/raw")

# Curated liquid large-caps, >= 3 per sector so sector-relative ranking is meaningful.
WATCHLIST: dict[str, str] = {
    "TCS": "IT",
    "INFY": "IT",
    "WIPRO": "IT",
    "HDFCBANK": "FIN",
    "ICICIBANK": "FIN",
    "SBIN": "FIN",
    "KOTAKBANK": "FIN",
    "RELIANCE": "ENERGY",
    "ONGC": "ENERGY",
    "NTPC": "ENERGY",
    "HINDUNILVR": "FMCG",
    "ITC": "FMCG",
    "NESTLEIND": "FMCG",
    "MARUTI": "AUTO",
    "TATAMOTORS": "AUTO",
    "M&M": "AUTO",
    "SUNPHARMA": "PHARMA",
    "CIPLA": "PHARMA",
    "DRREDDY": "PHARMA",
    "TATASTEEL": "METAL",
    "HINDALCO": "METAL",
    "JSWSTEEL": "METAL",
    "LT": "INFRA",
    "ULTRACEMCO": "INFRA",
    "GRASIM": "INFRA",
}

PRICES_PARQUET = Path("data/historical/prices.parquet")
BENCH_PARQUET = Path("data/historical/benchmark.parquet")
BENCHMARK = "^NSEI"


def _yf_sector_map() -> dict[str, str]:
    """Sector map keyed by the yfinance ticker form (.NS suffix) the panel will use."""
    return {f"{sym}.NS": sector for sym, sector in WATCHLIST.items()}


def _load_or_download(start: str, end: str | None, refresh: bool) -> tuple[PriceData, pd.Series]:
    if not refresh and PRICES_PARQUET.exists() and BENCH_PARQUET.exists():
        prices = load_parquet(PRICES_PARQUET)
        bench_df = pd.read_parquet(BENCH_PARQUET)
    else:
        print("Downloading watchlist from yfinance...")
        price_df = download_prices(list(WATCHLIST), start, end)
        save_parquet(price_df, PRICES_PARQUET)
        prices = PriceData.from_long(price_df)
        print("Downloading Nifty 50 benchmark...")
        bench_df = download_prices([BENCHMARK], start, end)
        save_parquet(bench_df, BENCH_PARQUET)
    benchmark = (
        bench_df.assign(date=pd.to_datetime(bench_df["date"]))
        .set_index("date")["adj_close"]
        .sort_index()
    )
    return prices, benchmark


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2012-01-01")
    parser.add_argument("--end", default=None)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--out", default="reports/phase0_report.md")
    parser.add_argument(
        "--no-tax-aware",
        action="store_true",
        help="disable the §4.6 tax-aware net-benefit gate (for A/B comparison)",
    )
    parser.add_argument("--band", type=float, default=0.10, help="no-trade band (fraction of MV)")
    parser.add_argument(
        "--no-fundamentals", action="store_true", help="force Phase 0a (price/volume factors only)"
    )
    args = parser.parse_args()

    cfg = Config()
    prices, benchmark = _load_or_download(args.start, args.end, args.refresh)
    sector_of = _yf_sector_map()
    universe = Universe.static(prices.tickers)

    # Phase 0b: use Screener fundamentals if any xlsx are present (re-ingest to pick up new files).
    fundamentals: FundamentalsStore | None = None
    have_xlsx = list(RAW_FUNDAMENTALS_DIR.glob("*.xlsx"))
    if have_xlsx and not args.no_fundamentals:
        ingest_dir(RAW_FUNDAMENTALS_DIR)
        fundamentals = FundamentalsStore.from_parquet()
        covered = sum(1 for t in prices.tickers if t in set(fundamentals.tickers))
        phase = (
            "0b (six-factor)"
            if covered >= len(prices.tickers)
            else f"0b partial ({covered}/{len(prices.tickers)} have fundamentals)"
        )
        print(f"Fundamentals loaded for {len(fundamentals.tickers)} tickers → Phase {phase}")
    else:
        print("No fundamentals → Phase 0a (3 price/volume factors)")

    result = run_backtest(
        prices,
        sector_of,
        universe,
        cfg,
        start=args.start,
        end=args.end or cfg.backtest.end,
        tax_aware=not args.no_tax_aware,
        min_trade_fraction=args.band,
        fundamentals=fundamentals,
    )
    report = build_report(result, prices, benchmark, cfg)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report)
    print(report)
    print(f"\nReport written to {out}")


if __name__ == "__main__":
    main()
