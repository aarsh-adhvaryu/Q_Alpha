"""Track A: does a 1/N-anchored (broader, equal-weight) tax-aware core beat both the concentrated
factor strategy AND naive 1/N — in-sample AND on the 2025-26 holdout? Three signals (in-sample gap,
walk-forward, holdout) say 1/N keeps winning; the question is whether breadth + the factor screen +
the tax gate capture 1/N's robustness while adding value.

All variants: survivorship-free PIT universe (through 2025), annual rebalance, force_refresh,
tax-aware gate 2.0, band 0.10, net Zerodha cost + capital-gains tax. vs Nifty 50 TRI and PIT 1/N.

Run: uv run python scripts/exp_breadth.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from holdout_2025 import BENCH, CSV, END, PRICES, SPLIT, START, _seg

from qalpha.backtest.baselines import equal_weight_pit
from qalpha.backtest.engine import run_backtest
from qalpha.config import Config
from qalpha.data.ingest import load_parquet
from qalpha.data.universe import Universe

CAPITAL = Config().capital.starting_capital

# (label, weighting, n_stocks_override) — None = capital-scaled default (~5-20, concentrated).
VARIANTS = [
    ("minvar  ~default (current)", "minvar", None),
    ("equal   ~default", "equal", None),
    ("equal   top-25", "equal", 25),
    ("equal   top-40 (broad)", "equal", 40),
    ("score   top-25 (tilt)", "score", 25),
    ("shrink  ~default (½ to 1/N)", "shrink", None),
]


def main() -> None:
    df = pd.read_csv(CSV)
    sector_of = {str(t): str(s) for t, s in zip(df["ticker"], df["sector"], strict=True)}
    tickers = sorted(sector_of)
    prices = load_parquet(PRICES)
    universe = Universe.from_csv(CSV)
    bdf = pd.read_parquet(BENCH)
    from run_phase0 import _sanitize_series

    tri = _sanitize_series(
        bdf.assign(date=pd.to_datetime(bdf["date"])).set_index("date")["adj_close"].sort_index()
    )
    if len(set(prices.tickers) & set(tickers)) < 10:
        raise SystemExit("Run scripts/holdout_2025.py first to populate the 2026 price cache.")

    runs = {
        label: run_backtest(
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
            weighting=w,
            n_stocks_override=n,
        )
        for label, w, n in VARIANTS
    }
    idx = next(iter(runs.values())).equity.index
    one_n = equal_weight_pit(prices, universe, idx, CAPITAL)  # type: ignore[arg-type]
    tri_a = tri.reindex(idx).ffill()
    last = str(prices.dates.max().date())

    for title, lo, hi in [
        ("IN-SAMPLE (2012 → 2024)", START, SPLIT),
        (f"HOLDOUT (2025 → {last}, UNSEEN)", "2025-01-01", END),
    ]:
        print(f"=== {title} ===")
        h = f"{'variant':>28} | {'CAGR%':>6} | {'Sharpe':>6} | {'maxDD%':>7} | {'tax ₹':>9}"
        print(h)
        print("-" * len(h))
        for label, res in runs.items():
            c, s, dd = _seg(res.equity, lo, hi)
            tax = float(sum(t.tax for t in res.trades if lo <= t.date.isoformat() <= hi))
            print(f"{label:>28} | {c:6.1f} | {s:6.2f} | {dd:7.1f} | {tax:9,.0f}")
        for label, curve in (("Nifty 50 TRI", tri_a), ("1/N (PIT, frictionless)", one_n)):
            c, s, dd = _seg(curve, lo, hi)
            print(f"{label:>28} | {c:6.1f} | {s:6.2f} | {dd:7.1f} | {'—':>9}")
        print()

    tc, _, _ = _seg(tri_a, "2025-01-01", END)
    nc, _, _ = _seg(one_n, "2025-01-01", END)
    print(
        f"Holdout bar to clear: Nifty-TRI {tc:.1f}% / 1/N {nc:.1f}%. "
        f"A variant 'wins' only if it beats BOTH in-sample AND holdout."
    )
    for label, res in runs.items():
        ci, _, _ = _seg(res.equity, START, SPLIT)
        ch, _, _ = _seg(res.equity, "2025-01-01", END)
        verdict = "BEATS 1/N both" if (ci > 17.7 and ch > nc) else "no"
        print(f"  {label:>28}: in-sample {ci:5.1f}% | holdout {ch:5.1f}%  → {verdict}")

    # ---- Part C: is the shrink winner ROBUST? rolling 3y holding-period distribution vs 1/N ----
    # (guards against the two caveats: one short holdout window + picking 1 of 6 variants)
    from walkforward import _rolling_ann_returns

    print("\n=== ROBUSTNESS: rolling 3-year holding-period annualized return (every entry day) ===")
    shrink = next(r for k, r in runs.items() if k.startswith("shrink"))
    minv = next(r for k, r in runs.items() if k.startswith("minvar"))
    series = {
        "shrink (½→1/N)": shrink.equity,
        "minvar (current)": minv.equity,
        "1/N (PIT)": one_n,
    }
    roll = {k: _rolling_ann_returns(v) for k, v in series.items()}
    hh = f"{'series':>18} | {'worst':>7} | {'p25':>7} | {'median':>7} | {'p75':>7} | {'best':>7}"
    print(hh)
    print("-" * len(hh))
    for k, r in roll.items():
        rp = r * 100
        print(
            f"{k:>18} | {rp.min():6.1f}% | {rp.quantile(0.25):6.1f}% | {rp.median():6.1f}% "
            f"| {rp.quantile(0.75):6.1f}% | {rp.max():6.1f}%"
        )
    sh, nn = roll["shrink (½→1/N)"].align(roll["1/N (PIT)"], join="inner")
    print(
        f"\nShrink ≥ 1/N in {float((sh >= nn).mean()) * 100:.0f}% of all 3y holds; "
        f"worst-ever 3y: shrink {roll['shrink (½→1/N)'].min() * 100:.1f}% vs 1/N {nn.min() * 100:.1f}%."
    )


if __name__ == "__main__":
    main()
