"""Cumulative tradebook master — stack new Zerodha exports onto one de-duplicated log.

The Console tradebook has no API and is exported by hand; each export overlaps the last in date
range, so uploading them repeatedly would double-count trades. This module keeps a **single master**:
it merges each new export into the running set, de-duplicated by Zerodha's unique ``trade_id`` (with a
composite fallback for older exports that lack it), so the user only ever "stacks new ones on top".

The master round-trips through :func:`trades_to_master_csv` / :func:`trades_from_master_csv` — our own
normalized schema whose ``symbol`` column already carries the canonical ``.NS`` ticker, so reading it
back must **not** re-run :func:`~qalpha.live.holdings.canonical_ticker` (that would double the suffix).
It is intentionally storage-agnostic: the caller persists the CSV wherever it likes (a private gist,
a file, …) — real trades never touch the public repo.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal

from qalpha.accounting.costs import Side
from qalpha.live.tradebook import TradebookTrade

MASTER_COLUMNS = (
    "trade_date",
    "symbol",
    "trade_type",
    "quantity",
    "price",
    "order_execution_time",
    "trade_id",
)


def _dedup_key(t: TradebookTrade) -> str:
    """De-dup identity: Zerodha's ``trade_id`` when present, else a composite of the trade fields."""
    if t.trade_id:
        return f"id:{t.trade_id}"
    return f"c:{t.trade_date}|{t.ticker}|{t.side.value}|{t.quantity}|{t.price}|{t.exec_time}"


def _sorted(trades: list[TradebookTrade]) -> list[TradebookTrade]:
    return sorted(trades, key=lambda t: (t.trade_date, t.exec_time, t.ticker, t.side.value))


def merge_trades(
    existing: list[TradebookTrade], incoming: list[TradebookTrade]
) -> tuple[list[TradebookTrade], int]:
    """Union ``existing`` + ``incoming`` de-duplicated by :func:`_dedup_key`, chronologically sorted.

    Returns ``(merged, n_added)`` where ``n_added`` is how many trades in ``incoming`` were genuinely
    new (not already in ``existing``). ``existing`` is itself de-duplicated defensively.
    """
    merged: list[TradebookTrade] = []
    seen: set[str] = set()
    for t in existing:
        k = _dedup_key(t)
        if k not in seen:
            seen.add(k)
            merged.append(t)
    base = len(merged)
    for t in incoming:
        k = _dedup_key(t)
        if k not in seen:
            seen.add(k)
            merged.append(t)
    return _sorted(merged), len(merged) - base


def trades_to_master_csv(trades: list[TradebookTrade]) -> str:
    """Serialize the master to a normalized CSV (``symbol`` is the canonical ``.NS`` ticker)."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(MASTER_COLUMNS)
    for t in _sorted(trades):
        writer.writerow(
            [
                t.trade_date.isoformat(),
                t.ticker,
                t.side.value,
                str(t.quantity),
                str(t.price),
                t.exec_time,
                t.trade_id,
            ]
        )
    return buf.getvalue()


def trades_from_master_csv(text: str) -> list[TradebookTrade]:
    """Read a master CSV written by :func:`trades_to_master_csv`. Empty/whitespace → ``[]``.

    The ``symbol`` is already canonical, so it is used verbatim (no ``canonical_ticker`` re-append).
    """
    if not text or not text.strip():
        return []
    trades: list[TradebookTrade] = []
    for row in csv.DictReader(io.StringIO(text)):
        trades.append(
            TradebookTrade(
                trade_date=date.fromisoformat(str(row["trade_date"]).strip()),
                ticker=str(row["symbol"]).strip(),
                side=Side.BUY if str(row["trade_type"]).strip().lower() == "buy" else Side.SELL,
                quantity=Decimal(str(row["quantity"]).strip()),
                price=Decimal(str(row["price"]).strip()),
                exec_time=str(row.get("order_execution_time") or "").strip(),
                trade_id=str(row.get("trade_id") or "").strip(),
            )
        )
    return trades
