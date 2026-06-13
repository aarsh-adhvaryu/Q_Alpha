"""Tax-smart advisor CLI — the deterministic recommendation layer (Q_alpha.md §14 crit 10).

Answers the tax question at the moment of a *manual* trade, against the current paper book (and,
once funded, a live Zerodha holdings snapshot — same code). No AI: every figure comes from the
validated FIFO/cost/tax engine.

    uv run python scripts/advisor.py sell TCS.NS --qty 10     # tax of selling + smart alternatives
    uv run python scripts/advisor.py raise-cash 50000         # least-tax way to raise ₹50k
    uv run python scripts/advisor.py deploy 50000             # route ₹50k new money, ₹0 tax

`--as-of DATE` overrides the valuation date (default: latest price date). Read-only — never trades.
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

from qalpha.config import Config
from qalpha.data.prices import PriceData
from qalpha.data.universe import Universe
from qalpha.live.advisor import advise_deploy, advise_raise_cash, advise_sell
from qalpha.live.paper import PaperBook, _prices_on


def _as_of(prices: PriceData, arg: str | None) -> date:
    return date.fromisoformat(arg) if arg else prices.dates[-1].date()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_sell = sub.add_parser("sell", help="tax of selling a holding + smart alternatives")
    p_sell.add_argument("ticker")
    p_sell.add_argument("--qty", type=str, default=None, help="shares to sell (default: all)")
    p_sell.add_argument("--as-of", default=None)

    p_raise = sub.add_parser("raise-cash", help="least-tax way to raise a cash amount")
    p_raise.add_argument("amount", type=str)
    p_raise.add_argument("--as-of", default=None)

    p_deploy = sub.add_parser("deploy", help="route new money into underweights (₹0 tax)")
    p_deploy.add_argument("amount", type=str)
    p_deploy.add_argument("--as-of", default=None)

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
    prices_dec = _prices_on(prices, as_of)

    if args.cmd == "sell":
        price = prices_dec.get(args.ticker)
        if price is None:
            print(f"no price for {args.ticker} on {as_of}", file=sys.stderr)
            return 1
        qty = Decimal(args.qty) if args.qty else None
        print(advise_sell(book.portfolio, args.ticker, price, as_of, cfg, quantity=qty).render())
        return 0

    if args.cmd == "raise-cash":
        advice = advise_raise_cash(book.portfolio, Decimal(args.amount), prices_dec, as_of)
        print(advice.render())
        return 0

    # deploy: needs target weights — use the funnel's current target (or the last applied one).
    target = _current_target(book, prices, universe, sector_of, as_of)
    if target is None:
        print(
            "no target weights available (funnel produced none) — cannot route new money",
            file=sys.stderr,
        )
        return 1
    print(advise_deploy(book.portfolio, Decimal(args.amount), target, prices_dec, as_of).render())
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
