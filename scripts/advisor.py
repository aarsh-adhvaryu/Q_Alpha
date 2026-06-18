"""Tax-smart advisor CLI — the deterministic recommendation layer (Q_alpha.md §14 crit 10).

Answers the tax question at the moment of a *manual* trade. No AI: every figure comes from the
validated FIFO/cost/tax engine. Works on the notional paper book, or — with ``--source live`` — on
the **real Zerodha account** (``kite.holdings()`` + ``ltp()``), proving the advisor is source-agnostic.

    uv run python scripts/advisor.py sell TCS.NS --qty 10     # tax of selling + smart alternatives
    uv run python scripts/advisor.py raise-cash 50000         # least-tax way to raise ₹50k
    uv run python scripts/advisor.py deploy 50000             # route ₹50k new money, ₹0 tax
    uv run python scripts/advisor.py deploy 50000 --source live   # ...against the live account
    uv run python scripts/advisor.py sell INFY.NS --source live --tradebook tb.csv  # exact dated tax

`--as-of DATE` overrides the valuation date (default: latest price date). Read-only — never trades.
Live holdings carry no purchase dates, so live tax is approximate unless `--tradebook CSV` (a Zerodha
Console tradebook export) is given — that replays exact dated FIFO lots (criterion 4). Without it the
CLI prints the short-term-assumption caveat.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from paper import BOOK_PATH, _load_market

from qalpha.backtest.portfolio import Portfolio
from qalpha.config import Config
from qalpha.data.prices import PriceData
from qalpha.data.universe import Universe
from qalpha.live.advisor import advise_deploy, advise_raise_cash, advise_sell
from qalpha.live.deploy import advise_deploy_into_weakness
from qalpha.live.paper import PaperBook, _prices_on

_WATCHLIST_CSV = Path("data/universes/nifty100_watchlist.csv")


def _as_of(prices: PriceData, arg: str | None) -> date:
    return date.fromisoformat(arg) if arg else prices.dates[-1].date()


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--as-of", default=None)
    p.add_argument(
        "--source",
        choices=["paper", "live"],
        default="paper",
        help="portfolio source: the notional paper book (default) or the live Zerodha account",
    )
    p.add_argument(
        "--tradebook",
        default=None,
        help="Zerodha Console tradebook CSV → exact dated FIFO tax (with --source live)",
    )


def _resolve_portfolio(
    source: str, book: PaperBook, cfg: Config, as_of: date, prices: PriceData, tradebook: str | None
) -> tuple[Portfolio, dict[str, Decimal]] | None:
    """Return (portfolio, marking prices) for the chosen source, or None if the live account is empty."""
    if source == "paper":
        return book.portfolio, _prices_on(prices, as_of)

    from qalpha.live.client import authenticated_kite
    from qalpha.live.holdings import (
        fetch_available_cash,
        fetch_holdings,
        fetch_prices,
        portfolio_from_holdings,
    )

    kite = authenticated_kite()
    holdings = fetch_holdings(kite)
    if not holdings:
        print("live Zerodha account holds no equity — nothing to advise on yet.", file=sys.stderr)
        return None
    prices_dec = fetch_prices(kite, holdings)

    if tradebook:
        from qalpha.live.tradebook import parse_tradebook, replay_tradebook

        result = replay_tradebook(parse_tradebook(tradebook), cfg, cash=fetch_available_cash(kite))
        for w in result.warnings:
            print(f"⚠️  {w}", file=sys.stderr)
        print(
            f"Exact tax from {result.n_trades} tradebook trades "
            f"(realized tax to date ₹{result.realized_tax:,.2f}).\n",
            file=sys.stderr,
        )
        return result.portfolio, prices_dec

    live = portfolio_from_holdings(holdings, cfg, as_of=as_of, cash=fetch_available_cash(kite))
    if live.tax_caveat:
        print(f"⚠️  {live.tax_caveat}\n", file=sys.stderr)
    return live.portfolio, prices_dec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_sell = sub.add_parser("sell", help="tax of selling a holding + smart alternatives")
    p_sell.add_argument("ticker")
    p_sell.add_argument("--qty", type=str, default=None, help="shares to sell (default: all)")
    _add_common(p_sell)

    p_raise = sub.add_parser("raise-cash", help="least-tax way to raise a cash amount")
    p_raise.add_argument("amount", type=str)
    _add_common(p_raise)

    p_deploy = sub.add_parser("deploy", help="route new money into underweights (₹0 tax)")
    p_deploy.add_argument("amount", type=str)
    _add_common(p_deploy)

    p_dw = sub.add_parser(
        "deploy-weakness",
        help="deploy new money across the Nifty-100 watchlist — diversified, tilted to out-of-favour "
        "names, leaning into market weakness (₹0 tax)",
    )
    p_dw.add_argument("amount", type=str)
    p_dw.add_argument("--tilt", type=float, default=1.0, help="cheapness tilt strength (0 = equal)")
    _add_common(p_dw)

    args = parser.parse_args(argv)
    cfg = Config()

    if not BOOK_PATH.exists():
        print(
            f"no paper book at {BOOK_PATH} — run: uv run python scripts/paper.py init",
            file=sys.stderr,
        )
        return 1
    prices, universe, sector_of = _load_market()
    book = PaperBook.load(BOOK_PATH, cfg)
    as_of = _as_of(prices, args.as_of)

    resolved = _resolve_portfolio(args.source, book, cfg, as_of, prices, args.tradebook)
    if resolved is None:
        return 1
    portfolio, prices_dec = resolved

    if args.cmd == "sell":
        price = prices_dec.get(args.ticker)
        if price is None:
            print(f"no price for {args.ticker} on {as_of}", file=sys.stderr)
            return 1
        qty = Decimal(args.qty) if args.qty else None
        print(advise_sell(portfolio, args.ticker, price, as_of, cfg, quantity=qty).render())
        return 0

    if args.cmd == "raise-cash":
        print(advise_raise_cash(portfolio, Decimal(args.amount), prices_dec, as_of).render())
        return 0

    if args.cmd == "deploy-weakness":
        if not _WATCHLIST_CSV.exists():
            print(
                f"no Nifty-100 watchlist at {_WATCHLIST_CSV} — run: "
                "uv run python scripts/build_nifty100_watchlist.py",
                file=sys.stderr,
            )
            return 1
        wl = pd.read_csv(_WATCHLIST_CSV)
        watchlist = [str(t) for t in wl["ticker"]]
        wl_sector = {str(t): str(s) for t, s in zip(wl["ticker"], wl["sector"], strict=True)}
        index_close = prices.adj_close.mean(axis=1)  # equal-weight market proxy (self-contained)
        advice = advise_deploy_into_weakness(
            portfolio,
            Decimal(args.amount),
            watchlist,
            wl_sector,
            prices,
            index_close,
            as_of,
            tilt=args.tilt,
        )
        print(advice.render())
        return 0

    # deploy: the target weights come from the model funnel (source-independent).
    target = _current_target(book, prices, universe, sector_of, as_of)
    if target is None:
        print(
            "no target weights available (funnel produced none) — cannot route new money",
            file=sys.stderr,
        )
        return 1
    print(advise_deploy(portfolio, Decimal(args.amount), target, prices_dec, as_of).render())
    return 0


def _current_target(
    book: PaperBook, prices: PriceData, universe: Universe, sector_of: dict[str, str], as_of: date
) -> pd.Series | None:
    """The funnel's current target weights for ``as_of``; fall back to the last applied target."""
    plan = book.plan(prices, universe, sector_of, as_of)
    if plan.decision.target is not None and not plan.decision.target.empty:
        return plan.decision.target
    return book.last_target


if __name__ == "__main__":
    raise SystemExit(main())
