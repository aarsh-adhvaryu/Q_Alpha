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

from qalpha.backtest.portfolio import TradeRecord
from qalpha.config import Config
from qalpha.data.ingest import download_prices, load_parquet, save_parquet
from qalpha.data.prices import PriceData
from qalpha.data.universe import Universe
from qalpha.live.dashboard import equity_csv, paper_freshness, render_markdown
from qalpha.live.go_scorecard import build_scorecard
from qalpha.live.paper import PaperBook
from qalpha.live.runlog import RunLogEntry, append_run, load_runs, now_utc_iso

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
    book: PaperBook,
    prices: PriceData,
    universe: Universe,
    sector_of: dict[str, str],
    as_of: date,
    *,
    auto_apply: bool = False,
) -> tuple[bool, list[TradeRecord]]:
    """Mark the book, optionally auto-apply a scheduled rebalance, render the dashboard + equity CSV.

    Returns ``(orders_pending, applied)``. With ``auto_apply`` (the cron path) a *scheduled,
    actionable* plan is committed to the NOTIONAL book before rendering — so the forward run executes
    its own decisions instead of freezing on the start basket (criterion-6 must test the live
    strategy, not a stale June portfolio). Zero real money is at risk. The cadence gate in
    :meth:`PaperBook.plan` guarantees this fires only on scheduled (annual) days, never daily churn.
    """
    book.mark(prices, as_of)  # pure valuation, persisted — no trades
    plan = book.plan(prices, universe, sector_of, as_of)
    applied: list[TradeRecord] = []
    if auto_apply and plan.decision.actionable:
        applied = book.apply(prices, plan)
        book.mark(prices, as_of)  # re-mark post-trade so this date's point reflects the fills
        plan = book.plan(prices, universe, sector_of, as_of)  # now a 'holding' plan

    # Autonomous audit trail: record what this run did (the cron path persists it; a local `dashboard`
    # preview only renders the existing log so it never pollutes the headless history).
    benchmark = _load_benchmark_series()
    fresh = paper_freshness(book, as_of)
    warnings: list[str] = []
    if fresh.is_stale:
        warnings.append(fresh.note)
    if applied:
        action = f"auto-applied {len(applied)} scheduled order(s)"
    elif plan.has_orders:
        action = "orders pending approval"
        warnings.append("orders await human approval (run: paper.py apply)")
    else:
        action = "held — no action"
    entry = RunLogEntry(
        ran_at=now_utc_iso(),
        as_of=as_of.isoformat(),
        command="daily" if auto_apply else "dashboard",
        action=action,
        decision_reason=plan.decision.reason,
        equity=str(book.equity(prices, as_of)),
        return_pct=book.total_return_pct(prices, as_of),
        go_verdict=build_scorecard(book.equity_curve, benchmark, as_of).verdict,
        freshness=fresh.note,
        warnings=warnings,
    )
    if auto_apply:
        append_run(entry)
    run_log = load_runs(limit=50)

    DASHBOARD_MD.parent.mkdir(parents=True, exist_ok=True)
    DASHBOARD_MD.write_text(render_markdown(book, prices, benchmark, plan, as_of, run_log))
    EQUITY_CSV.write_text(equity_csv(book))
    return plan.has_orders, applied


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
        # The cron (`daily`) auto-applies a scheduled rebalance to the notional book; `dashboard`
        # (local preview) stays read-only and only flags that orders are due.
        pending, applied = _generate_dashboard(
            book, prices, universe, sector_of, as_of, auto_apply=(args.cmd == "daily")
        )
        if applied:
            print(f"✓ Auto-applied {len(applied)} scheduled paper order(s) on {as_of}:")
            for r in applied:
                print(
                    f"    {r.side.name:<4} {r.ticker:<14} {r.quantity} @ ₹{r.price}  (tax ₹{r.tax})"
                )
        flag = "  ⚠️ ACTION NEEDED — orders await approval (run: paper.py apply)" if pending else ""
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
