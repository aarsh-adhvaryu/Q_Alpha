"""Phase-A follow-ups: (1) is "trade less" robust across regimes? (2) does a longer momentum
lookback (smoother signal, less noise) help? Both on the HARD test — survivorship-free PIT universe,
fair Nifty 50 TRI bar, 3-factor (0a), net of Zerodha cost + capital-gains tax.

Run: uv run python scripts/exp_frequency_lookback.py
(uses the prices/benchmark already cached by run_phase0.py).
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from run_phase0 import (
    PIT_PRICES_PARQUET,
    _load_benchmark,
    _load_universe_csv,
)

from qalpha.backtest.defensive import GovernanceEvents
from qalpha.backtest.engine import run_backtest
from qalpha.backtest.metrics import compute_metrics, max_drawdown
from qalpha.config import Config, FactorConfig
from qalpha.data.ingest import load_parquet
from qalpha.data.universe import Universe

CSV = "data/universes/nifty50_membership.csv"
START, END = "2012-01-01", "2024-12-31"


def _seg_return(curve: pd.Series, year: int) -> tuple[float, float]:
    """(% return, % max drawdown) of an equity curve within one calendar year."""
    seg = curve[curve.index.year == year]
    if len(seg) < 2:
        return 0.0, 0.0
    ret = float(seg.iloc[-1] / seg.iloc[0] - 1.0) * 100.0
    return ret, max_drawdown(seg) * 100.0


def main() -> None:
    _tickers, sector_of = _load_universe_csv(Path(CSV))
    prices = load_parquet(PIT_PRICES_PARQUET)
    universe = Universe.from_csv(CSV)
    tri = _load_benchmark("NIFTYBEES.NS", START, END, refresh=False)
    cfg = Config()

    # ---- run the full-window strategy at each rebalance frequency, keep equity + tax ----
    runs = {}
    for freq in ("M", "Q", "Y"):
        res = run_backtest(
            prices,
            sector_of,
            universe,
            cfg,
            start=START,
            end=END,
            tax_aware=True,
            min_trade_fraction=0.10,
            rebalance_freq=freq,
        )
        runs[freq] = res

    print("=" * 78)
    print("TEST 1 — is 'trade less' robust across regimes? (per-calendar-year, same strategy)")
    print("Each cell: strategy return% (intra-year maxDD%). TRI = Nifty 50 total-return.")
    print("=" * 78)
    header = f"{'year':>4} | {'TRI ret%':>8} | {'Monthly':>16} | {'Quarterly':>16} | {'Annual':>16}"
    print(header)
    print("-" * len(header))
    for year in range(2013, 2025):  # 2012 is warm-up (no trades yet)
        tri_seg = tri[tri.index.year == year]
        tri_ret = (
            float(tri_seg.iloc[-1] / tri_seg.iloc[0] - 1.0) * 100.0 if len(tri_seg) > 1 else 0.0
        )
        cells = []
        for freq in ("M", "Q", "Y"):
            r, dd = _seg_return(runs[freq].equity, year)
            cells.append(f"{r:+6.1f} ({dd:5.1f})")
        print(f"{year:>4} | {tri_ret:+8.1f} | {cells[0]:>16} | {cells[1]:>16} | {cells[2]:>16}")

    print("\nFull-window summary (net of cost+tax):")
    fh = f"{'freq':>9} | {'CAGR%':>6} | {'Sharpe':>6} | {'maxDD%':>7} | {'tax ₹':>10} | {'#rebal':>6}"
    print(fh)
    print("-" * len(fh))
    for freq in ("M", "Q", "Y"):
        m = compute_metrics(runs[freq].equity, freq)
        print(
            f"{freq:>9} | {m.cagr * 100:6.1f} | {m.sharpe:6.2f} | {max_drawdown(runs[freq].equity) * 100:7.1f} "
            f"| {float(runs[freq].total_tax):10,.0f} | {runs[freq].n_rebalances:6d}"
        )

    # ---- TEST 2: longer momentum lookback at the winning (annual) frequency ----
    print("\n" + "=" * 78)
    print("TEST 2 — longer momentum lookback (smoother = less noise) @ ANNUAL rebalance")
    print("=" * 78)
    lh = f"{'lookback':>12} | {'CAGR%':>6} | {'Sharpe':>6} | {'maxDD%':>7} | {'tax ₹':>10} | {'#rebal':>6}"
    print(lh)
    print("-" * len(lh))
    for days in (126, 252, 378, 504):
        cfg_l = replace(cfg, factor=FactorConfig(momentum_lookback_days=days))
        res = run_backtest(
            prices,
            sector_of,
            universe,
            cfg_l,
            start=START,
            end=END,
            tax_aware=True,
            min_trade_fraction=0.10,
            rebalance_freq="Y",
        )
        m = compute_metrics(res.equity, "x")
        label = f"{days}d ({days // 21}mo)"
        print(
            f"{label:>12} | {m.cagr * 100:6.1f} | {m.sharpe:6.2f} | {max_drawdown(res.equity) * 100:7.1f} "
            f"| {float(res.total_tax):10,.0f} | {res.n_rebalances:6d}"
        )
    print("\nReference: Nifty 50 TRI 14.5% / Sharpe 0.98 ; frictionless 1/N 17.7% / 1.06")

    # ---- TEST 3: defensive overlay on the annual core — plug 2022 without breaking 2020? ----
    print("\n" + "=" * 78)
    print("TEST 3 — defensive overlay (idiosyncratic exit) on ANNUAL core")
    print("Goal: cut the 2022 idiosyncratic bleed, stay quiet through the 2020 systemic crash.")
    print("=" * 78)
    base = runs["Y"]  # annual, no overlay (from Test 1)
    defn = run_backtest(
        prices,
        sector_of,
        universe,
        cfg,
        start=START,
        end=END,
        tax_aware=True,
        min_trade_fraction=0.10,
        rebalance_freq="Y",
        defensive=True,
    )
    sh = f"{'variant':>22} | {'CAGR%':>6} | {'Sharpe':>6} | {'maxDD%':>7} | {'tax ₹':>10}"
    print(sh)
    print("-" * len(sh))
    for label, res in (("annual core", base), ("annual core + defensive", defn)):
        m = compute_metrics(res.equity, "x")
        print(
            f"{label:>22} | {m.cagr * 100:6.1f} | {m.sharpe:6.2f} | "
            f"{max_drawdown(res.equity) * 100:7.1f} | {float(res.total_tax):10,.0f}"
        )

    print("\nPer-year (does the overlay help 2022 and leave 2020 alone?):")
    yr = (
        f"{'year':>4} | {'core ret%':>9} | {'+defensive ret%':>15} | {'# def. exits that year':>22}"
    )
    print(yr)
    print("-" * len(yr))
    exits_by_year: dict[int, list[str]] = {}
    for dt, tk in defn.defensive_exits:
        exits_by_year.setdefault(dt.year, []).append(tk)
    for year in range(2013, 2025):
        b, _ = _seg_return(base.equity, year)
        dv, _ = _seg_return(defn.equity, year)
        n_ex = len(exits_by_year.get(year, []))
        print(f"{year:>4} | {b:+9.1f} | {dv:+15.1f} | {n_ex:>22}")

    print("\nDefensive exits fired (date → ticker):")
    for dt, tk in defn.defensive_exits:
        print(f"  {dt} → {tk}")

    # ---- TEST 4: EVENT-DRIVEN defensive (the pivot) — surgical, fact-based, not price-based ----
    print("\n" + "=" * 78)
    print("TEST 4 — event-driven defence (§3.11 governance freeze) on ANNUAL core")
    print("Fires on a broken *business* (Yes Bank, Zee), never on an out-of-favour blue-chip.")
    print("=" * 78)
    events = GovernanceEvents.from_csv("data/events/governance_events.csv")
    evn = run_backtest(
        prices,
        sector_of,
        universe,
        cfg,
        start=START,
        end=END,
        tax_aware=True,
        min_trade_fraction=0.10,
        rebalance_freq="Y",
        governance_events=events,
    )
    sh = f"{'variant':>26} | {'CAGR%':>6} | {'Sharpe':>6} | {'maxDD%':>7} | {'tax ₹':>10}"
    print(sh)
    print("-" * len(sh))
    for label, res in (("annual core", base), ("annual core + event-defence", evn)):
        m = compute_metrics(res.equity, "x")
        print(
            f"{label:>26} | {m.cagr * 100:6.1f} | {m.sharpe:6.2f} | "
            f"{max_drawdown(res.equity) * 100:7.1f} | {float(res.total_tax):10,.0f}"
        )
    # Did the core ever hold the flagged names (so the freeze had something to act on)?
    flagged = {"YESBANK.NS", "ZEEL.NS"}
    held_flagged = sorted({t.ticker for t in base.trades if t.ticker in flagged})
    print(f"\nCore ever traded the flagged names: {held_flagged or 'none'}")
    print("Event-driven exits/freezes fired (date → ticker):")
    for dt, tk in evn.defensive_exits:
        print(f"  {dt} → {tk}")
    if not evn.defensive_exits:
        print("  (none held at event time — but the blacklist still blocked any re-entry)")
    print(
        "\nRead: event-defence only ever touches the broken-business names — it cannot whipsaw a\n"
        "quality name the way the price overlay did. Its backtest impact here is small because the\n"
        "momentum/quality factors already avoid falling knives; its real value is per-position risk\n"
        "control + a human-escalation trigger, and it is gated on a full historical event feed."
    )


if __name__ == "__main__":
    main()
