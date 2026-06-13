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
import re
from pathlib import Path

import openpyxl
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
PIT_PRICES_PARQUET = Path("data/historical/prices_pit.parquet")
BENCH_PARQUET = Path("data/historical/benchmark.parquet")
BENCHMARK = "^NSEI"

# Screener "COMPANY NAME" (normalized: lowercased, alphanumerics only) -> NSE base symbol. Keying on
# the company name *inside* the file makes ingestion robust to however the export file was named.
_COMPANY_TO_SYMBOL: dict[str, str] = {
    "tataconsultancyservicesltd": "TCS",
    "infosysltd": "INFY",
    "wiproltd": "WIPRO",
    "hdfcbankltd": "HDFCBANK",
    "icicibankltd": "ICICIBANK",
    "statebankofindia": "SBIN",
    "kotakmahindrabankltd": "KOTAKBANK",
    "relianceindustriesltd": "RELIANCE",
    "oilnaturalgascorpnltd": "ONGC",
    "ntpcltd": "NTPC",
    "hindustanunileverltd": "HINDUNILVR",
    "itcltd": "ITC",
    "nestleindialtd": "NESTLEIND",
    "marutisuzukiindialtd": "MARUTI",
    "tatamotorsltd": "TATAMOTORS",
    "tatamotorsdvr": "TATAMOTORS",
    "mahindramahindraltd": "M&M",
    "sunpharmaceuticalindustriesltd": "SUNPHARMA",
    "ciplaltd": "CIPLA",
    "drreddyslaboratoriesltd": "DRREDDY",
    "tatasteelltd": "TATASTEEL",
    "hindalcoindustriesltd": "HINDALCO",
    "jswsteelltd": "JSWSTEEL",
    "larsentoubroltd": "LT",
    "ultratechcementltd": "ULTRACEMCO",
    "grasimindustriesltd": "GRASIM",
}


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _build_fundamentals_filemap(raw_dir: Path) -> dict[str, str]:
    """Map each xlsx filename -> NSE ticker by reading its internal Screener company name."""
    mapping: dict[str, str] = {}
    for xlsx in sorted(raw_dir.glob("*.xlsx")):
        company = openpyxl.load_workbook(xlsx, data_only=True)["Data Sheet"].cell(1, 2).value
        symbol = _COMPANY_TO_SYMBOL.get(_normalize(str(company)))
        if symbol is None:
            print(f"  WARN: no ticker mapping for '{xlsx.name}' (company '{company}') — skipped")
            continue
        mapping[xlsx.name] = f"{symbol}.NS"
    return mapping


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


def _load_universe_csv(csv_path: Path) -> tuple[list[str], dict[str, str]]:
    """Read a point-in-time membership CSV → (distinct .NS tickers, sector map keyed by .NS).

    The CSV (from ``scripts/build_nifty_universe.py``) carries a ``sector`` column alongside the
    ticker/start/end that ``Universe.from_csv`` consumes; we lift the sector map from it so the
    funnel needs no hand-maintained watchlist for the PIT run.
    """
    df = pd.read_csv(csv_path)
    if "sector" not in df.columns:
        raise ValueError(f"{csv_path} has no 'sector' column — rebuild via build_nifty_universe.py")
    sector_of = {str(t): str(s) for t, s in zip(df["ticker"], df["sector"], strict=True)}
    tickers = sorted(sector_of)
    return tickers, sector_of


def _load_or_download_pit(
    tickers: list[str], start: str, end: str | None, refresh: bool
) -> PriceData:
    """Download (or load cached) prices for the full PIT ticker set, including dropped/dead names.

    Names yfinance can no longer price (merged/delisted away — e.g. HDFC Ltd, Tata Motors) simply
    fail to download and are absent from the panel; the engine then skips them at each rebalance.
    Coverage is reported so the residual survivorship gap is explicit, not hidden.
    """
    if not refresh and PIT_PRICES_PARQUET.exists():
        prices = load_parquet(PIT_PRICES_PARQUET)
    else:
        print(
            f"Downloading {len(tickers)} PIT-universe names from yfinance (incl. dropped/dead)..."
        )
        price_df = download_prices(tickers, start, end)
        save_parquet(price_df, PIT_PRICES_PARQUET)
        prices = PriceData.from_long(price_df)
    got = set(prices.tickers)
    missing = sorted(t for t in tickers if t not in got)
    print(f"PIT price coverage: {len(got)}/{len(tickers)} names priced.")
    if missing:
        print(f"  Unpriceable (merged/delisted away; engine skips them): {missing}")
    return prices


def _sanitize_series(s: pd.Series) -> pd.Series:
    """Repair isolated yfinance bad ticks (Q_alpha.md §5.1 — silent corruption is the #1 data risk).

    A Nifty 50 ETF never moves ±40% from its own 5-day median; such points are split/print glitches
    (e.g. NIFTYBEES shows two days at ₹13 vs ~₹129 neighbours in Dec-2019). We flag points that
    deviate >40% from the centred rolling median, blank them, and linearly interpolate. The
    cumulative level is unaffected; the daily-return-based risk metrics (vol, Sharpe, drawdown) are
    no longer poisoned by the spike-and-rebound.
    """
    med = s.rolling(5, center=True, min_periods=1).median()
    ratio = s / med
    bad = (ratio < 0.6) | (ratio > 1.6)
    if bool(bad.any()):
        dates = ", ".join(str(d.date()) for d in s.index[bad])
        print(f"  Benchmark sanitizer: repaired {int(bad.sum())} bad tick(s) at {dates}")
        s = s.mask(bad).interpolate().bfill().ffill()
    return s


def _load_benchmark(ticker: str, start: str, end: str | None, refresh: bool) -> pd.Series:
    """Load (or download+cache) a benchmark's TR-adjusted series.

    For ``^NSEI`` adj-close == close (an index pays no dividends) → a *price* benchmark. For an ETF
    like ``NIFTYBEES.NS`` the adj-close reinvests dividends → a Nifty 50 *total-return* proxy, the
    fair bar against a TR-adjusted strategy. Cached per ticker so switching benchmarks is cheap.
    """
    safe = re.sub(r"[^A-Za-z0-9]", "", ticker)
    path = (
        BENCH_PARQUET if ticker == BENCHMARK else Path(f"data/historical/benchmark_{safe}.parquet")
    )
    if not refresh and path.exists():
        bench_df = pd.read_parquet(path)
    else:
        print(f"Downloading benchmark {ticker}...")
        bench_df = download_prices([ticker], start, end)
        save_parquet(bench_df, path)
    series = (
        bench_df.assign(date=pd.to_datetime(bench_df["date"]))
        .set_index("date")["adj_close"]
        .sort_index()
    )
    return _sanitize_series(series)


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
        "--rebalance",
        default="Y",
        choices=["M", "Q", "Y"],
        help="rebalance frequency: M(onthly), Q(uarterly), Y(early, DEFAULT — the validated config). "
        "Lower = longer holds = less tax (more LTCG, fewer events).",
    )
    parser.add_argument(
        "--weighting",
        default="shrink",
        choices=["minvar", "equal", "score", "shrink"],
        help="final weighting. shrink (DEFAULT) = ½ min-var + ½ equal-weight (anchor-to-1/N) — the "
        "Phase-0 validated edge over both index and 1/N. minvar = concentrated (old default).",
    )
    parser.add_argument(
        "--force-refresh",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="force the scheduled rebalance to execute (anti-ossification, DEFAULT on); "
        "--no-force-refresh lets the §4.6 gate freeze the book (the 2025-26 holdout failure mode).",
    )
    parser.add_argument(
        "--no-fundamentals", action="store_true", help="force Phase 0a (price/volume factors only)"
    )
    parser.add_argument(
        "--universe-csv",
        default="data/universes/nifty50_membership.csv",
        help="point-in-time membership CSV (DEFAULT: the survivorship-free Nifty 50). "
        "Pass an empty string for the STATIC survivor universe (verdict capped at CONDITIONAL).",
    )
    parser.add_argument(
        "--benchmark",
        default="NIFTYBEES.NS",
        help="benchmark ticker. DEFAULT NIFTYBEES.NS = Nifty 50 TRI proxy (ETF adj-close = dividends "
        "reinvested), the fair bar vs a TR-adjusted strategy. ^NSEI = Nifty 50 price.",
    )
    args = parser.parse_args()

    cfg = Config()
    benchmark_label = (
        "Nifty 50 TRI (NIFTYBEES)" if "NIFTYBEES" in args.benchmark.upper() else "Nifty 50 (price)"
    )
    pit_mode = bool(args.universe_csv and Path(args.universe_csv).exists())
    if pit_mode:
        # Point-in-time run: universe, tickers and sectors all come from the membership CSV.
        tickers, sector_of = _load_universe_csv(Path(args.universe_csv))
        prices = _load_or_download_pit(tickers, args.start, args.end, args.refresh)
        benchmark = _load_benchmark(args.benchmark, args.start, args.end, args.refresh)
        universe = Universe.from_csv(args.universe_csv)
        print(f"Universe: POINT-IN-TIME from {args.universe_csv} (survivorship-free)")
        if not args.no_fundamentals:
            # We only hold Screener fundamentals for the 24 static names; scoring the ~76 PIT names
            # on a mix of 6- and 3-factor models would be apples-to-oranges. Force a clean 0a run.
            print("  Forcing Phase 0a (price/volume factors) for a clean survivorship comparison.")
            args.no_fundamentals = True
    else:
        prices, _ = _load_or_download(args.start, args.end, args.refresh)
        benchmark = _load_benchmark(args.benchmark, args.start, args.end, args.refresh)
        sector_of = _yf_sector_map()
        universe = Universe.static(prices.tickers)
        print("Universe: STATIC survivor set (survivorship-biased) → verdict capped at CONDITIONAL")

    # Phase 0b: use Screener fundamentals if any xlsx are present (re-ingest to pick up new files).
    fundamentals: FundamentalsStore | None = None
    have_xlsx = list(RAW_FUNDAMENTALS_DIR.glob("*.xlsx"))
    if have_xlsx and not args.no_fundamentals:
        filemap = _build_fundamentals_filemap(RAW_FUNDAMENTALS_DIR)
        ingest_dir(RAW_FUNDAMENTALS_DIR, filename_to_ticker=filemap)
        fundamentals = FundamentalsStore.from_parquet()
        covered_set = set(fundamentals.tickers) & set(prices.tickers)
        missing = sorted(set(prices.tickers) - set(fundamentals.tickers))
        phase = "0b six-factor" if len(covered_set) >= len(prices.tickers) else "0b partial"
        print(
            f"Fundamentals: {len(covered_set)}/{len(prices.tickers)} priced tickers covered "
            f"→ Phase {phase}"
        )
        if missing:
            print(f"  No fundamentals (price-only factors): {missing}")
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
        rebalance_freq=args.rebalance,
        weighting=args.weighting,
        force_refresh=args.force_refresh,
    )
    report = build_report(
        result, prices, benchmark, cfg, universe=universe, benchmark_label=benchmark_label
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report)
    print(report)
    print(f"\nReport written to {out}")


if __name__ == "__main__":
    main()
