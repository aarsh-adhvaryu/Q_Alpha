"""Paper-trading runner CLI — the live system on a notional book (STRATEGY.md Stage 1).

Drives the validated decision engine daily against real prices, with zero money at risk, to build
the multi-month paper track record the spec requires before real capital (§14 criterion 6).

    uv run python scripts/paper.py init --capital 200000   # create the book (once)
    uv run python scripts/paper.py plan                     # today's decision + proposed orders
    uv run python scripts/paper.py apply                    # commit the orders (after you approve)
    uv run python scripts/paper.py status                   # cash, holdings, equity, tax to date

`plan` mutates nothing. `apply` commits and persists. The book lives in data/paper/ (gitignored).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pandas as pd
from run_phase0 import _load_universe_csv

from qalpha.config import Config
from qalpha.data.ingest import download_prices, load_parquet, save_parquet
from qalpha.data.prices import PriceData
from qalpha.data.universe import Universe
from qalpha.live.dashboard import equity_csv, render_markdown
from qalpha.live.paper import PaperBook

BOOK_PATH = Path("data/paper/book.json")
DASHBOARD_MD = Path("reports/paper_dashboard.md")
EQUITY_CSV = Path("reports/paper_equity.csv")
# Current (through-2026) point-in-time Nifty 50 + its price panel; `paper.py refresh` extends it.
UNIVERSE_CSV = "data/universes/nifty50_membership_2026.csv"
PRICES_PARQUET = Path("data/historical/prices_pit_2026.parquet")
BENCHMARK_PARQUET = Path("data/historical/benchmark_NIFTYBEESNS_2026.parquet")


def _load_market() -> tuple[PriceData, Universe, dict[str, str]]:
    _tickers, sector_of = _load_universe_csv(Path(UNIVERSE_CSV))
    prices = load_parquet(str(PRICES_PARQUET))
    universe = Universe.from_csv(UNIVERSE_CSV)
    return prices, universe, sector_of


def _refresh_prices() -> PriceData:
    """Re-pull the current universe from yfinance through today and cache it for the daily run."""
    tickers, _sector_of = _load_universe_csv(Path(UNIVERSE_CSV))
    print(f"Downloading {len(tickers)} names from yfinance through today...")
    panel = download_prices(tickers, "2012-01-01", None)
    save_parquet(panel, str(PRICES_PARQUET))
    prices = PriceData.from_long(panel)
    print(f"✓ Prices refreshed to {prices.dates[-1].date()} → {PRICES_PARQUET}")
    return prices


def _refresh_benchmark() -> None:
    """Re-pull the Nifty 50 TRI proxy (NIFTYBEES adj-close) through today and cache it."""
    panel = download_prices(["NIFTYBEES.NS"], "2012-01-01", None)
    save_parquet(panel, str(BENCHMARK_PARQUET))


def _load_benchmark_series() -> pd.Series:
    df = pd.read_parquet(BENCHMARK_PARQUET)
    return pd.Series(
        df["adj_close"].to_numpy(), index=pd.DatetimeIndex(df["date"]), name="nifty_tri"
    )


def _generate_dashboard(
    book: PaperBook, prices: PriceData, universe: Universe, sector_of: dict[str, str], as_of: date
) -> bool:
    """Mark the book, render the dashboard + equity CSV. Returns True if orders await approval."""
    book.mark(prices, as_of)  # pure valuation, persisted — no trades
    plan = book.plan(prices, universe, sector_of, as_of)
    DASHBOARD_MD.parent.mkdir(parents=True, exist_ok=True)
    DASHBOARD_MD.write_text(render_markdown(book, prices, _load_benchmark_series(), plan, as_of))
    EQUITY_CSV.write_text(equity_csv(book))
    return plan.has_orders


def _as_of(prices: PriceData, arg: str | None) -> date:
    return date.fromisoformat(arg) if arg else prices.dates[-1].date()


def _print_plan(
    book: PaperBook, prices: PriceData, universe: Universe, sector_of: dict[str, str], as_of: date
) -> None:
    plan = book.plan(prices, universe, sector_of, as_of)
    print(f"\n=== Plan for {as_of} ===")
    print(f"book equity      : ₹{plan.equity_before:,.0f}")
    print(
        f"decision         : {'TRADE' if plan.decision.execute else 'HOLD'} — {plan.decision.reason}"
    )
    if not plan.has_orders:
        print("proposed orders  : none (hold)")
        return
    print("proposed orders  :")
    for o in plan.proposed_orders:
        print(f"    {o.side.name:<4} {o.ticker:<14} {o.quantity} @ ₹{o.price}")
    print(
        "\nReview, then run:  uv run python scripts/paper.py apply"
        + (f" --as-of {as_of}" if as_of != prices.dates[-1].date() else "")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="create the paper book")
    p_init.add_argument(
        "--capital", type=str, default="200000", help="notional starting capital (₹)"
    )
    p_init.add_argument("--start", default=None, help="start date (default: latest price date)")

    sub.add_parser("refresh", help="re-pull prices from yfinance through today")
    sub.add_parser("dashboard", help="mark the book + regenerate the dashboard report")
    sub.add_parser("daily", help="refresh + mark + dashboard (for cron; never trades)")
    for name in ("plan", "apply", "status"):
        sp = sub.add_parser(name)
        if name in ("plan", "apply"):
            sp.add_argument(
                "--as-of", default=None, help="decision date (default: latest price date)"
            )

    args = parser.parse_args(argv)
    cfg = Config()

    if args.cmd == "refresh":
        _refresh_prices()
        return 0

    # `daily` (the cron entry point) refreshes prices + benchmark first so a fresh CI checkout (which
    # has the committed universe CSV + book, but not the large/gitignored parquets) can rebuild them.
    if args.cmd == "daily":
        _refresh_prices()
        _refresh_benchmark()
    prices, universe, sector_of = _load_market()

    if args.cmd == "init":
        if BOOK_PATH.exists():
            print(f"book already exists at {BOOK_PATH} — refusing to overwrite", file=sys.stderr)
            return 1
        start = _as_of(prices, args.start)
        PaperBook.init(BOOK_PATH, cfg, starting_capital=Decimal(args.capital), start_date=start)
        print(
            f"✓ Paper book created at {BOOK_PATH} — ₹{Decimal(args.capital):,} notional, start {start}."
        )
        return 0

    if not BOOK_PATH.exists():
        print(
            f"no paper book at {BOOK_PATH} — run:  uv run python scripts/paper.py init",
            file=sys.stderr,
        )
        return 1
    book = PaperBook.load(BOOK_PATH, cfg)

    if args.cmd in ("dashboard", "daily"):
        as_of = prices.dates[-1].date()
        action = _generate_dashboard(book, prices, universe, sector_of, as_of)
        flag = "  ⚠️ ACTION NEEDED — orders await approval (run: paper.py apply)" if action else ""
        print(f"✓ Dashboard → {DASHBOARD_MD} · equity → {EQUITY_CSV} (as of {as_of}){flag}")
        return 0

    if args.cmd == "plan":
        _print_plan(book, prices, universe, sector_of, _as_of(prices, args.as_of))
        return 0

    if args.cmd == "apply":
        as_of = _as_of(prices, args.as_of)
        plan = book.plan(prices, universe, sector_of, as_of)
        if not plan.has_orders:
            print(f"nothing to apply on {as_of} (decision: hold).")
            return 0
        records = book.apply(prices, plan)
        print(f"✓ Applied {len(records)} orders on {as_of}; book saved.")
        for r in records:
            print(f"    {r.side.name:<4} {r.ticker:<14} {r.quantity} @ ₹{r.price}  (tax ₹{r.tax})")
        return 0

    # status
    as_of = prices.dates[-1].date()
    holdings = book.portfolio.positions()
    print(f"\n=== Paper book status ({as_of}) ===")
    print(f"start date       : {book.start_date}  ({(as_of - book.start_date).days} days)")
    print(
        f"strategy         : weighting={book.params.weighting}, band={book.params.band}, "
        f"force_refresh={book.params.force_refresh}"
    )
    print(f"cash             : ₹{book.portfolio.cash:,.0f}")
    print(f"holdings         : {len(holdings)} names")
    for t, q in sorted(holdings.items()):
        print(f"    {t:<14} {q}")
    print(f"equity (mark)    : ₹{book.equity(prices, as_of):,.0f}")
    print(f"rebalances       : {len(book.history)}")
    print(f"realized tax     : ₹{book.realized_tax():,.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
