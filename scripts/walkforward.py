"""Walk-forward / out-of-sample validation of the rebalance-frequency result (PLAN.md Stage 0).

The headline "annual rebalance beats Nifty TRI *and* 1/N" came from ONE full-window (2012-2024)
run on a bull-heavy period. Before trusting it (let alone with real money) we must check it
out-of-sample. Two complementary, hard-to-game views — both on the survivorship-free PIT universe,
3-factor (0a), net of Zerodha cost + capital-gains tax:

  A. ROLLING 3-YEAR HOLDING-PERIOD distribution (from the continuously-run equity curve): for every
     possible entry day, the annualized return over the next 3 years. Answers "what if I'd started
     at the *worst* time?" and "in what fraction of all 3-year holds does trading less actually win?"

  B. INDEPENDENT SUB-PERIOD backtests across distinct regimes (each a fresh run with its own
     warm-up; metrics measured from first trade so the warm-up flat doesn't distort). Answers "does
     the M<Q<Y ranking, and beating TRI/1N, repeat in separate regimes — or was it one lucky window?"

Run: uv run python scripts/walkforward.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from run_phase0 import (
    PIT_PRICES_PARQUET,
    _load_benchmark,
    _load_universe_csv,
)

from qalpha.backtest.baselines import equal_weight_pit
from qalpha.backtest.engine import run_backtest
from qalpha.backtest.metrics import compute_metrics, max_drawdown
from qalpha.config import Config
from qalpha.data.ingest import load_parquet
from qalpha.data.universe import Universe

CSV = "data/universes/nifty50_membership.csv"
START, END = "2012-01-01", "2024-12-31"
CAPITAL = Config().capital.starting_capital


def _run(prices, sector_of, universe, cfg, start, end, freq):  # type: ignore[no-untyped-def]
    return run_backtest(
        prices,
        sector_of,
        universe,
        cfg,
        start=start,
        end=end,
        tax_aware=True,
        min_trade_fraction=0.10,
        rebalance_freq=freq,
    )


def _rolling_ann_returns(curve: pd.Series, window_days: int = 756) -> pd.Series:
    """Annualized return for every rolling ``window_days`` (default ~3y) holding period."""
    fut = curve.shift(-window_days)
    ratio = (fut / curve).dropna()
    return ratio ** (252.0 / window_days) - 1.0


def _ann_return(curve: pd.Series) -> float:
    years = max((curve.index[-1] - curve.index[0]).days / 365.25, 1e-9)
    return float((curve.iloc[-1] / curve.iloc[0]) ** (1.0 / years) - 1.0)


def main() -> None:
    _tickers, sector_of = _load_universe_csv(Path(CSV))
    prices = load_parquet(PIT_PRICES_PARQUET)
    universe = Universe.from_csv(CSV)
    cfg = Config()
    full_index = run_backtest(
        prices,
        sector_of,
        universe,
        cfg,
        start=START,
        end=END,
        tax_aware=True,
        min_trade_fraction=0.10,
        rebalance_freq="Y",
    ).equity.index
    assert isinstance(full_index, pd.DatetimeIndex)
    tri = _load_benchmark("NIFTYBEES.NS", START, END, refresh=False).reindex(full_index).ffill()
    one_n = equal_weight_pit(prices, universe, full_index, CAPITAL)

    # Full-window equity curves per frequency (continuously run).
    curves = {
        f: _run(prices, sector_of, universe, cfg, START, END, f).equity for f in ("M", "Q", "Y")
    }

    # ---- A. Rolling 3-year holding-period distribution ----
    print("=" * 82)
    print("A. ROLLING 3-YEAR holding-period annualized return (every entry day, net cost+tax)")
    print("=" * 82)
    series = {
        "Monthly": curves["M"],
        "Quarterly": curves["Q"],
        "Annual": curves["Y"],
        "Nifty TRI": tri,
        "1/N (PIT)": one_n,
    }
    roll = {k: _rolling_ann_returns(v) for k, v in series.items()}
    hdr = f"{'series':>12} | {'worst':>7} | {'p25':>7} | {'median':>7} | {'p75':>7} | {'best':>7}"
    print(hdr)
    print("-" * len(hdr))
    for k in series:
        r = roll[k] * 100
        print(
            f"{k:>12} | {r.min():6.1f}% | {r.quantile(0.25):6.1f}% | {r.median():6.1f}% "
            f"| {r.quantile(0.75):6.1f}% | {r.max():6.1f}%"
        )
    ann, mon, t, n = roll["Annual"], roll["Monthly"], roll["Nifty TRI"], roll["1/N (PIT)"]
    a, m2 = ann.align(mon, join="inner")
    at, _ = ann.align(t, join="inner")
    _, t2 = ann.align(t, join="inner")
    an_, n2 = ann.align(n, join="inner")
    print(
        f"\nAcross all 3y holding periods: Annual ≥ Monthly in {float((a >= m2).mean()) * 100:.0f}%, "
        f"Annual ≥ Nifty-TRI in {float((at >= t2).mean()) * 100:.0f}%, "
        f"Annual ≥ 1/N in {float((an_ >= n2).mean()) * 100:.0f}% of them."
    )
    print(
        f"Worst 3y for Annual {ann.min() * 100:.1f}% vs Monthly {mon.min() * 100:.1f}% "
        f"vs Nifty-TRI {t.min() * 100:.1f}% vs 1/N {n.min() * 100:.1f}% (downside robustness)."
    )

    # ---- B. Independent sub-period windows (distinct regimes) ----
    print("\n" + "=" * 82)
    print("B. INDEPENDENT SUB-PERIOD backtests (fresh run each; metrics from first trade)")
    print("=" * 82)
    windows = [
        ("2012-2018  (taper'13, 2015 fall, 2018 midcap crash)", "2012-01-01", "2018-12-31"),
        ("2015-2021  (2018 crash, 2020 COVID, 2021 bull)", "2015-01-01", "2021-12-31"),
        ("2018-2024  (COVID, 2022 drawdown, 2023-24 bull)", "2018-01-01", "2024-12-31"),
    ]
    for label, ws, we in windows:
        print(f"\n[{label}]")
        hh = (
            f"{'freq':>10} | {'CAGR%':>6} | {'Sharpe':>6} | {'maxDD%':>7} | {'tax ₹':>9} "
            f"| {'vs TRI':>7} | {'vs 1/N':>7}"
        )
        print(hh)
        print("-" * len(hh))
        for f in ("M", "Q", "Y"):
            res = _run(prices, sector_of, universe, cfg, ws, we, f)
            if not res.trades:
                continue
            first = min(t.date for t in res.trades)
            fts = pd.Timestamp(first)
            eq = res.equity[res.equity.index >= fts]
            mtr = compute_metrics(eq, f)
            tri_w = tri[(tri.index >= fts) & (tri.index <= pd.Timestamp(we))]
            n_w = one_n[(one_n.index >= fts) & (one_n.index <= pd.Timestamp(we))]
            tri_cagr, n_cagr = _ann_return(tri_w), _ann_return(n_w)
            print(
                f"{f:>10} | {mtr.cagr * 100:6.1f} | {mtr.sharpe:6.2f} | "
                f"{max_drawdown(eq) * 100:7.1f} | {float(res.total_tax):9,.0f} | "
                f"{(mtr.cagr - tri_cagr) * 100:+6.1f} | {(mtr.cagr - n_cagr) * 100:+6.1f}"
            )
        print(f"{'  (bench)':>10} : Nifty-TRI {tri_cagr * 100:5.1f}%  |  1/N {n_cagr * 100:5.1f}%")


if __name__ == "__main__":
    main()
