"""Historical price ingestion: yfinance -> Parquet -> :class:`PriceData` (Q_alpha.md §5.3/§5.5).

yfinance is acceptable for *backtesting/training* per the spec (§5.1: "a few missed dividends are
absorbed as noise"); it is never trusted for live decisions. Adjusted close (dividends+splits) is
used as the Total-Return proxy. NSE tickers take the ``.NS`` suffix.

Run as a module to populate ``data/historical/``::

    uv run python -m qalpha.data.ingest --tickers RELIANCE TCS INFY --start 2010-01-01

The reshaper tolerates yfinance's single- vs multi-ticker column shapes. The Parquet is stored in
long format (one row per date×ticker) so adding fields later doesn't rewrite the schema.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from qalpha.data.prices import PriceData

DEFAULT_PARQUET = Path("data/historical/prices.parquet")


def _to_nse(ticker: str) -> str:
    """Append the ``.NS`` NSE suffix unless the ticker already carries an exchange suffix."""
    return ticker if ("." in ticker or ticker.startswith("^")) else f"{ticker}.NS"


def _reshape_yf(raw: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    """Reshape a yfinance download into the long schema: date, ticker, close, adj_close, volume."""
    frames: list[pd.DataFrame] = []
    for tkr in tickers:
        if isinstance(raw.columns, pd.MultiIndex):
            # group_by="column" => level0 = field, level1 = ticker.
            try:
                sub = raw.xs(tkr, axis=1, level=1)
            except KeyError:
                continue
        else:
            sub = raw  # single ticker: flat columns
        if "Close" not in sub.columns:
            continue
        adj = sub["Adj Close"] if "Adj Close" in sub.columns else sub["Close"]
        part = pd.DataFrame(
            {
                "date": sub.index,
                "ticker": tkr,
                "close": sub["Close"].to_numpy(),
                "adj_close": adj.to_numpy(),
                "volume": sub["Volume"].to_numpy(),
            }
        )
        frames.append(part)
    if not frames:
        raise ValueError("no usable data returned from yfinance for the requested tickers")
    out = pd.concat(frames, ignore_index=True)
    return out.dropna(subset=["close", "adj_close"]).reset_index(drop=True)


def download_prices(tickers: list[str], start: str, end: str | None = None) -> pd.DataFrame:
    """Download OHLCV for ``tickers`` from yfinance, returned in the long schema."""
    import yfinance as yf  # imported lazily so the package imports without network libs loaded

    yf_tickers = [_to_nse(t) for t in tickers]
    raw = yf.download(
        yf_tickers,
        start=start,
        end=end,
        auto_adjust=False,  # keep raw Close and Adj Close separately
        actions=False,
        progress=False,
        group_by="column",
    )
    if raw is None or raw.empty:
        raise ValueError("yfinance returned no data (check connectivity / ticker symbols)")
    return _reshape_yf(raw, yf_tickers)


def save_parquet(df: pd.DataFrame, path: str | Path = DEFAULT_PARQUET) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return out


def load_parquet(path: str | Path = DEFAULT_PARQUET) -> PriceData:
    """Load a stored long Parquet into a :class:`PriceData` panel."""
    df = pd.read_parquet(path)
    return PriceData.from_long(df)


def _main() -> None:
    parser = argparse.ArgumentParser(description="Ingest NSE OHLCV from yfinance into Parquet.")
    parser.add_argument("--tickers", nargs="+", required=True, help="NSE symbols, e.g. TCS INFY")
    parser.add_argument("--start", default="2010-01-01")
    parser.add_argument("--end", default=None)
    parser.add_argument("--out", default=str(DEFAULT_PARQUET))
    args = parser.parse_args()

    df = download_prices(args.tickers, args.start, args.end)
    path = save_parquet(df, args.out)
    n_tickers = df["ticker"].nunique()
    print(f"Saved {len(df):,} rows ({n_tickers} tickers) -> {path}")


if __name__ == "__main__":
    _main()
