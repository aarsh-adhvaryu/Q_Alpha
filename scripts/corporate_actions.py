"""Corporate actions on the names this book has held: import them, check them, show them.

    uv run python scripts/corporate_actions.py            # what is recorded, and what it credits
    uv run python scripts/corporate_actions.py --import   # fetch, cross-check, write the record

Dividends were simply missing. The baselines are marked on an adjusted (total-return) index, so
their dividends are reinvested for them; the twin's holdings are marked on raw closes and were
credited nothing, which quietly handed the baselines a free lead. This is the other half of that
arithmetic.

Every dividend is cross-checked against the **price panel's own adjustment factor** before it is
allowed anywhere near a book: a dividend of D on ex-date T must move ``adj_close / close`` by exactly
``1 - D / close(T-1)``. An amount that does not reconcile is written down, named, and not applied.

**It changes no book.** The record is a file; :mod:`scripts.twin` applies it on the next run.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import twin as twin_script

from qalpha.accounting.corporate_actions import CorporateAction, CorporateActionType
from qalpha.config import Config
from qalpha.live import actions as actions_record
from qalpha.live.console import use_utf8
from qalpha.live.panels import WATCHLIST_PANEL
from qalpha.live.tradebook import TradebookTrade, replay_tradebook
from qalpha.live.twin import REAL, load_books


def _trades_and_names(cfg: Config) -> tuple[list[TradebookTrade], list[str]]:
    """Every trade the export holds, and every name it has ever touched.

    Not only what is held now: a dividend paid while a name was held is income the book earned, even
    if the name was sold afterwards.
    """
    trades, notes = twin_script._tradebook()
    if notes:
        print(f"[actions] tradebook: {'; '.join(notes)}", file=sys.stderr)
    return trades, sorted({t.ticker for t in trades})


def _fetch(tickers: list[str], *, since: date) -> list[CorporateAction]:
    """Dividends and splits from the price vendor, from ``since`` onwards."""
    import yfinance as yf

    out: list[CorporateAction] = []
    for ticker in tickers:
        handle = yf.Ticker(ticker)
        for stamp, amount in handle.dividends.items():
            when = stamp.date()
            if when >= since:
                out.append(
                    CorporateAction(
                        ticker=ticker,
                        ex_date=when,
                        action_type=CorporateActionType.DIVIDEND,
                        amount_per_share=Decimal(str(round(float(amount), 4))),
                    )
                )
        for stamp, ratio in handle.splits.items():
            when = stamp.date()
            if when >= since:
                out.append(
                    CorporateAction(
                        ticker=ticker,
                        ex_date=when,
                        action_type=CorporateActionType.SPLIT,
                        ratio=Decimal(str(round(float(ratio), 6))),
                    )
                )
    return out


def _held_on(trades: list[TradebookTrade], cfg: Config, ticker: str, when: date) -> Decimal:
    """Shares held going **into** ``when``, replayed through the real engine.

    Entitlement is holding on the ex-date, and a purchase made on the ex-date does not earn the
    dividend — so the replay stops at the day before, rather than counting today's buys.
    """
    earlier = [t for t in trades if t.trade_date < when]
    if not earlier:
        return Decimal("0")
    return replay_tradebook(earlier, cfg).portfolio.ledger.quantity_held(ticker)


def main(argv: list[str] | None = None) -> int:
    use_utf8()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--import",
        dest="do_import",
        action="store_true",
        help="fetch from the price vendor, cross-check, and write data/twin/corporate_actions.json",
    )
    args = ap.parse_args(argv)
    cfg = Config()
    trades, _ = _trades_and_names(cfg)

    if args.do_import:
        trades, names = _trades_and_names(cfg)
        if not names:
            print("[actions] no tradebook - nothing has ever been held.", file=sys.stderr)
            return 2
        books = load_books(cfg)
        start = books[REAL].start if REAL in books else None
        if start is None:
            print("[actions] the book has no flows, so it has held nothing.", file=sys.stderr)
            return 2
        print(f"[actions] asking the price vendor about {len(names)} name(s) since {start}")
        panel = pd.read_parquet(WATCHLIST_PANEL)
        fetched = _fetch(names, since=start)
        record = actions_record.Record(
            actions=tuple(actions_record.check(a, panel) for a in fetched),
            source="yfinance dividends/splits, cross-checked against the panel's own adjustment",
            fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        actions_record.save(record)
        print(f"[actions] wrote {len(record.actions)} action(s) -> {actions_record.ACTIONS_PATH}")

    stored = actions_record.load()
    if stored is None:
        print(
            "[actions] nothing imported yet. Run: "
            "uv run python scripts/corporate_actions.py --import"
        )
        return 1

    print(f"\n[actions] {record.source}")
    print(f"[actions] fetched {record.fetched_at}")
    credited = Decimal("0")
    for r in sorted(record.actions, key=lambda x: (x.action.ex_date, x.action.ticker)):
        action = r.action
        name = action.ticker.removesuffix(".NS")
        mark = "ok " if r.reconciled else "NOT"
        line = f"  {mark} {action.ex_date}  {name:12s} {action.action_type}"
        if action.action_type is CorporateActionType.DIVIDEND:
            held = _held_on(trades, cfg, action.ticker, action.ex_date)
            cash = held * action.amount_per_share
            if r.reconciled:
                credited += cash
            line += f" ₹{action.amount_per_share}/sh on {held:g} held = ₹{cash:,.2f}" + (
                "" if held else "  (not held on the ex-date - nothing is due)"
            )
        else:
            line += f" x{action.ratio}"
        print(line)
        print(f"      {r.note}")

    print(
        f"\n[actions] ₹{credited:,.2f} of dividend income on the real book's holdings. It is "
        "credited inside the replay, on the ex-date, before that day's trades."
    )
    if record.unreconciled:
        print(
            f"[actions] {len(record.unreconciled)} action(s) did not reconcile and are NOT applied."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
