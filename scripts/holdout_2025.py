"""True out-of-time HOLDOUT: run the frozen, validated config on 2025-2026 data — which was never
seen or used in any calibration (dev cutoff was 2024-12-31). The cheap overfitting filter before
spending build effort: does the edge survive on genuinely unseen data?

Config is frozen exactly as Phase 0 concluded: survivorship-free PIT universe (extended through the
2025 reconstitutions), 3-factor (0a), ANNUAL rebalance, tax-aware gate 2.0, band 0.10, vs Nifty 50
TRI (NIFTYBEES). Caveats: ~18 months + annual rebalance ≈ 1-2 rebalances → low statistical power
(directional smoke test, not proof); a possible early-2026 reconstitution may be missing.

Run: uv run python scripts/holdout_2025.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from run_phase0 import _load_universe_csv, _sanitize_series

from qalpha.backtest.baselines import equal_weight_pit
from qalpha.backtest.engine import run_backtest
from qalpha.backtest.metrics import compute_metrics, max_drawdown
from qalpha.config import Config
from qalpha.data.ingest import PriceData, download_prices, load_parquet, save_parquet
from qalpha.data.universe import Universe

CSV = "data/universes/nifty50_membership_2026.csv"
PRICES = Path("data/historical/prices_pit_2026.parquet")
BENCH = Path("data/historical/benchmark_NIFTYBEESNS_2026.parquet")
START, SPLIT, END = "2012-01-01", "2024-12-31", "2026-06-30"
CAPITAL = Config().capital.starting_capital


def _seg(curve: pd.Series, lo: str, hi: str) -> tuple[float, float, float]:
    """(annualized return %, Sharpe, max drawdown %) of an equity curve over [lo, hi]."""
    s = curve[(curve.index >= pd.Timestamp(lo)) & (curve.index <= pd.Timestamp(hi))]
    if len(s) < 2:
        return 0.0, 0.0, 0.0
    m = compute_metrics(s, "x")
    return m.cagr * 100, m.sharpe, max_drawdown(s) * 100


def _load_prices(tickers: list[str], refresh: bool) -> PriceData:
    if PRICES.exists() and not refresh:
        return load_parquet(PRICES)
    print(f"Downloading {len(tickers)} names through {END} (incl. dropped/dead + 2025 entrants)...")
    df = download_prices(tickers, START, END)
    save_parquet(df, PRICES)
    return PriceData.from_long(df)


def _load_tri(refresh: bool) -> pd.Series:
    if BENCH.exists() and not refresh:
        bdf = pd.read_parquet(BENCH)
    else:
        bdf = download_prices(["NIFTYBEES.NS"], START, END)
        save_parquet(bdf, BENCH)
    s = bdf.assign(date=pd.to_datetime(bdf["date"])).set_index("date")["adj_close"].sort_index()
    return _sanitize_series(s)


def main() -> None:
    tickers, sector_of = _load_universe_csv(Path(CSV))
    refresh = "--refresh" in sys.argv
    prices = _load_prices(tickers, refresh)
    universe = Universe.from_csv(CSV)
    tri = _load_tri(refresh)
    got = set(prices.tickers)
    print(f"Price coverage: {len(got & set(tickers))}/{len(tickers)}.")
    print(f"Data runs to: {prices.dates.max().date()} (holdout = 2025-01-01 → there)\n")

    variants = {
        "frozen (gate can freeze)": run_backtest(
            prices,
            sector_of,
            universe,
            Config(),
            start=START,
            end=END,
            tax_aware=True,
            min_trade_fraction=0.10,
            rebalance_freq="Y",
        ),
        "forced-refresh (anti-ossify)": run_backtest(
            prices,
            sector_of,
            universe,
            Config(),
            start=START,
            end=END,
            tax_aware=True,
            min_trade_fraction=0.10,
            rebalance_freq="Y",
            force_refresh=True,
        ),
    }
    idx = next(iter(variants.values())).equity.index
    one_n = equal_weight_pit(prices, universe, idx, CAPITAL)  # type: ignore[arg-type]
    tri_a = tri.reindex(idx).ffill()
    last = str(prices.dates.max().date())

    for title, lo, hi in [
        ("IN-SAMPLE  (2012-01 → 2024-12, dev window)", START, SPLIT),
        (f"HOLDOUT    (2025-01 → {last}, UNSEEN)", "2025-01-01", END),
    ]:
        print(f"=== {title} ===")
        h = f"{'series':>32} | {'CAGR%':>6} | {'Sharpe':>6} | {'maxDD%':>7}"
        print(h)
        print("-" * len(h))
        for name, res in variants.items():
            c, s, dd = _seg(res.equity, lo, hi)
            print(f"{'Q-Alpha ' + name:>32} | {c:6.1f} | {s:6.2f} | {dd:7.1f}")
        for name, curve in (("Nifty 50 TRI", tri_a), ("1/N (PIT, frictionless)", one_n)):
            c, s, dd = _seg(curve, lo, hi)
            print(f"{name:>32} | {c:6.1f} | {s:6.2f} | {dd:7.1f}")
        print()

    tc, _, _ = _seg(tri_a, "2025-01-01", END)
    nc, _, _ = _seg(one_n, "2025-01-01", END)
    print(f"HOLDOUT benchmarks: Nifty-TRI {tc:.1f}%  |  1/N {nc:.1f}%")
    for name, res in variants.items():
        sc, _, _ = _seg(res.equity, "2025-01-01", END)
        n25 = sum(1 for t in res.trades if t.date.year >= 2025)
        last_rebal = max((t.date for t in res.trades), default=None)
        print(
            f"  {name:>30}: holdout {sc:5.1f}%  ({'BEATS' if sc > tc else 'trails'} TRI, "
            f"{'beats' if sc > nc else 'trails'} 1/N) | {res.n_rebalances} rebals, last {last_rebal}, "
            f"{n25} trades in 2025-26"
        )


if __name__ == "__main__":
    main()
