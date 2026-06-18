"""Stage-1 breadth screen: the validated strategy on a wider universe vs 1/N (PREREGISTRATION_universe.md).

Parameterized walk-forward on an arbitrary universe CSV, writing to a **separate** price cache so the
validated Nifty-50 PIT panel is never touched. Frozen to the product-validated config (annual · shrink ·
force_refresh · §4.6 gate · dynamic slippage). Reports the full-window metrics, the rolling-3y-hold
distribution, the **strategy − 1/N gap**, per-year price coverage (to expose mid-window IPO
truncation) and the selected book's sector spread. NOTE: on a survivorship-biased static universe the
1/N baseline is the *largest* survivorship beneficiary (buy-and-hold-all-survivors), so the gap is NOT
bias-clean — see reports/universe_breadth_findings.md. This screen is directional context, not a verdict.

Run: uv run python scripts/exp_universe_breadth.py --universe-csv data/universes/nifty100_current_static.csv \
        --cache data/historical/prices_nifty100_static.parquet --label "Nifty 100 (static)" \
        --out reports/universe_nifty100_screen.md
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import pandas as pd
from run_phase0 import _load_benchmark, _load_universe_csv

from qalpha.accounting.costs import Side
from qalpha.backtest.baselines import equal_weight_pit
from qalpha.backtest.engine import BacktestResult, run_backtest
from qalpha.backtest.metrics import compute_metrics, max_drawdown
from qalpha.config import Config
from qalpha.data.ingest import download_prices, load_parquet, save_parquet
from qalpha.data.prices import PriceData
from qalpha.data.universe import Universe

START, END = "2012-01-01", "2024-12-31"
CAPITAL = Config().capital.starting_capital


def _load_prices(tickers: list[str], cache: Path, start: str, end: str, refresh: bool) -> PriceData:
    if cache.exists() and not refresh:
        return load_parquet(cache)
    print(f"Downloading {len(tickers)} names → {cache} (incl. mid-window IPOs / dead names)...")
    df = download_prices(tickers, start, end)
    cache.parent.mkdir(parents=True, exist_ok=True)
    save_parquet(df, cache)
    return PriceData.from_long(df)


def _run(prices, sector_of, universe, cfg, start, end, freq) -> BacktestResult:  # type: ignore[no-untyped-def]
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
        weighting="shrink",
        force_refresh=True,
        dynamic_slippage=True,
    )


def _ann(curve: pd.Series) -> float:
    years = max((curve.index[-1] - curve.index[0]).days / 365.25, 1e-9)
    return float((curve.iloc[-1] / curve.iloc[0]) ** (1.0 / years) - 1.0)


def _rolling(curve: pd.Series, window: int = 756) -> pd.Series:
    ratio = (curve.shift(-window) / curve).dropna()
    return ratio ** (252.0 / window) - 1.0


def _coverage_by_year(prices: PriceData, tickers: list[str]) -> dict[int, int]:
    """How many universe names have *any* close in each calendar year (exposes IPO truncation)."""
    close = prices.close_raw
    cols = [t for t in tickers if t in close.columns]
    out: dict[int, int] = {}
    for yr in range(2012, 2025):
        window = close.loc[f"{yr}-01-01" : f"{yr}-12-31", cols]
        out[yr] = int(window.notna().any(axis=0).sum())
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe-csv", required=True)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--label", default="wider universe")
    ap.add_argument("--out", default="reports/universe_screen.md")
    ap.add_argument("--start", default=START)
    ap.add_argument("--end", default=END)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    tickers, sector_of = _load_universe_csv(Path(args.universe_csv))
    universe = Universe.from_csv(args.universe_csv)
    cfg = Config()
    prices = _load_prices(tickers, Path(args.cache), args.start, args.end, args.refresh)
    priced = sorted(set(prices.tickers) & set(tickers))

    res = _run(prices, sector_of, universe, cfg, args.start, args.end, "Y")
    eq = res.equity
    idx = eq.index
    assert isinstance(idx, pd.DatetimeIndex)
    tri = _load_benchmark("NIFTYBEES.NS", args.start, args.end, refresh=False).reindex(idx).ffill()
    one_n = equal_weight_pit(prices, universe, idx, CAPITAL)

    s_cagr, n_cagr, t_cagr = _ann(eq), _ann(one_n), _ann(tri)
    mtr = compute_metrics(eq, "Y")
    roll_s, roll_n = _rolling(eq), _rolling(one_n)
    rs, rn = roll_s.align(roll_n, join="inner")
    gap = rs - rn

    buys = Counter(sector_of.get(t.ticker, "?") for t in res.trades if t.side is Side.BUY)
    cov = _coverage_by_year(prices, tickers)

    lines = []
    lines.append(f"# Stage-1 breadth screen — {args.label}\n")
    lines.append(
        "⚠️ **Survivorship-biased static universe — directional screen, NOT a GO.** Read the "
        "**strategy − 1/N gap** — but note 1/N-on-survivors is itself the biggest survivorship "
        "beneficiary, so even the gap is contaminated; this is directional context only. "
        "See `reports/PREREGISTRATION_universe.md`.\n"
    )
    lines.append(
        f"Universe: {len(tickers)} names, {len(priced)} priceable by yfinance. "
        f"Window {args.start}..{args.end}. Config: annual · shrink · force_refresh · "
        "§4.6 gate · dynamic slippage.\n"
    )

    lines.append("## Full-window (net cost + tax)\n")
    lines.append("| series | CAGR | Sharpe | maxDD | vs 1/N | vs Nifty-50 TRI |")
    lines.append("|---|---|---|---|---|---|")
    lines.append(
        f"| **Strategy ({args.label})** | {s_cagr * 100:.1f}% | {mtr.sharpe:.2f} | "
        f"{max_drawdown(eq) * 100:.1f}% | **{(s_cagr - n_cagr) * 100:+.1f}pt** | {(s_cagr - t_cagr) * 100:+.1f}pt |"
    )
    lines.append(
        f"| 1/N (same universe) | {n_cagr * 100:.1f}% | — | {max_drawdown(one_n) * 100:.1f}% | — | — |"
    )
    lines.append(f"| Nifty-50 TRI | {t_cagr * 100:.1f}% | — | — | — | — |")
    lines.append(
        f"\nRealized tax ₹{float(res.total_tax):,.0f} · {res.n_rebalances} rebalances · "
        f"{len({t.ticker for t in res.trades})} distinct names traded."
    )

    verdict = "BEATS 1/N" if s_cagr > n_cagr else "DOES NOT beat 1/N"
    lines.append("\n## The honest read: strategy − 1/N gap\n")
    lines.append(f"- Full-window: **{(s_cagr - n_cagr) * 100:+.1f} pts** → {verdict} on the gap.")
    lines.append(
        f"- Rolling 3y holds: strategy ≥ 1/N in **{float((gap >= 0).mean()) * 100:.0f}%** of holds; "
        f"worst-3y gap **{gap.min() * 100:+.1f}pt**, median **{gap.median() * 100:+.1f}pt**."
    )
    lines.append(
        f"- Strategy worst-3y **{roll_s.min() * 100:.1f}%** vs 1/N **{roll_n.min() * 100:.1f}%**."
    )

    lines.append("\n## Price coverage by year (exposes mid-window IPO truncation)\n")
    lines.append("| year | " + " | ".join(str(y) for y in cov) + " |")
    lines.append("|" + "---|" * (len(cov) + 1))
    lines.append("| priced names | " + " | ".join(str(cov[y]) for y in cov) + " |")

    lines.append("\n## Selected book — sector spread (buys across the run)\n")
    for sec, c in buys.most_common():
        lines.append(f"- {sec}: {c}")

    report = "\n".join(lines) + "\n"
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(report)
    print(report)
    print(f"(written to {args.out})")


if __name__ == "__main__":
    main()
