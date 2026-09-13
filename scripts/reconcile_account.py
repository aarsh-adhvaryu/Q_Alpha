"""Check the books against the broker's own statements: holdings, and the money that came in.

    uv run python scripts/reconcile_account.py

Reads what Zerodha Console exports into ``data/account/`` (gitignored — they carry a name and a PAN):

* **holdings statement** — every position and its average price. The independent check on the FIFO
  ledger: quantities must match exactly. Average price is expected to differ, because a lot's cost
  basis here includes the buy-side charges that are deductible against capital gains and Zerodha's
  "Average Price" is the execution price alone. The difference is reported, never hidden.
* **ledger** — the real deposits and withdrawals. The books' flows come from the tradebook, so they
  are *money that reached the market*, not money that reached the account. Both are printed, because
  the gap between them is idle cash sitting in the broker account, and calling either one "what you
  invested" without saying which is how a number ends up wearing the wrong label.

**It changes nothing.** No book, no ledger, no decision — it reads and reports. A statement that is
absent is named as absent.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qalpha.config import Config
from qalpha.live.console import use_utf8
from qalpha.live.twin import REAL, load_books

ACCOUNT = Path("data/account")


def _header_row(raw: pd.DataFrame, marker: str) -> int:
    """The row holding ``marker``, wherever it sits.

    Console sheets carry a blank first column, so looking only at column 0 finds nothing and the
    reader reports "this is not a holdings statement" about a holdings statement.
    """
    for i in range(len(raw)):
        if any(str(cell).strip() == marker for cell in raw.iloc[i].tolist()):
            return i
    raise ValueError(f"no '{marker}' header row — is this the statement it claims to be?")


@dataclass(frozen=True)
class Position:
    ticker: str
    quantity: Decimal
    average_price: Decimal


def read_holdings(path: Path) -> list[Position]:
    """The broker's equity holdings. The header row is found, never assumed at a fixed offset."""
    raw = pd.read_excel(path, sheet_name="Equity", header=None)
    frame = pd.read_excel(path, sheet_name="Equity", header=_header_row(raw, "Symbol"))
    return [
        Position(
            ticker=f"{str(row['Symbol']).strip()}.NS",
            quantity=Decimal(str(row["Quantity Available"])),
            average_price=Decimal(str(row["Average Price"])),
        )
        for _, row in frame.iterrows()
        if str(row.get("Symbol", "nan")) != "nan"
    ]


@dataclass(frozen=True)
class CashMove:
    on: str
    amount: Decimal  # positive into the account, negative out
    what: str


def read_ledger(path: Path) -> list[CashMove]:
    """Money that actually entered or left the broker account — not settlements between them."""
    raw = pd.read_excel(path, sheet_name="Equity", header=None)
    frame = pd.read_excel(path, sheet_name="Equity", header=_header_row(raw, "Particulars"))
    frame = frame[frame["Posting Date"].notna()]
    moves: list[CashMove] = []
    for _, row in frame.iterrows():
        voucher = str(row.get("Voucher Type", ""))
        if "Bank" not in voucher:  # a settlement moves money within the account, not into it
            continue
        credit = Decimal(str(row.get("Credit", 0) or 0))
        debit = Decimal(str(row.get("Debit", 0) or 0))
        moves.append(
            CashMove(
                on=str(row["Posting Date"])[:10],
                amount=credit - debit,
                what=str(row.get("Particulars", ""))[:60],
            )
        )
    return moves


def main(argv: list[str] | None = None) -> int:
    use_utf8()
    holdings_file = next(ACCOUNT.glob("holdings-*.xlsx"), None)
    ledger_file = next(ACCOUNT.glob("ledger-*.xlsx"), None)
    books = load_books(Config())
    if REAL not in books:
        print("[account] no books yet — run `twin.py seed` first.", file=sys.stderr)
        return 2
    book = books[REAL].portfolio

    problems = 0
    if holdings_file is None:
        print(f"[account] no holdings statement in {ACCOUNT}/ — positions were NOT checked.")
        problems += 1
    else:
        print(f"[account] holdings: {holdings_file.name}")
        held = book.positions()
        print(f"  {'name':12s} {'broker':>8s} {'book':>8s}  {'broker avg':>11s} {'book avg':>11s}")
        mismatches = 0
        for position in read_holdings(holdings_file):
            ours = held.get(position.ticker, Decimal(0))
            lots = book.ledger.open_lots(position.ticker)
            cost = sum(
                (lt.cost_basis_per_share * lt.quantity_remaining for lt in lots), Decimal("0")
            )
            average = (cost / ours) if ours else Decimal(0)
            flag = "" if ours == position.quantity else "   ← QUANTITY MISMATCH"
            mismatches += ours != position.quantity
            print(
                f"  {position.ticker.removesuffix('.NS'):12s} {position.quantity:>8} {ours:>8}  "
                f"{position.average_price:>11} {average:>11.2f}{flag}"
            )
        statement = read_holdings(holdings_file)
        extra = sorted(set(held) - {p.ticker for p in statement})
        for ticker in extra:
            print(
                f"  {ticker.removesuffix('.NS'):12s} {'—':>8} {held[ticker]:>8}   ← NOT AT THE BROKER"
            )
        problems += mismatches + len(extra)
        print(
            "  Quantities must match exactly. A higher book average is expected: a lot's cost basis\n"
            "  includes the buy-side charges deductible against capital gains; the broker's average\n"
            "  price is the execution price alone."
        )

    if ledger_file is None:
        print(f"[account] no ledger in {ACCOUNT}/ — funding was NOT checked.")
        problems += 1
    else:
        print(f"\n[account] ledger: {ledger_file.name}")
        moves = read_ledger(ledger_file)
        for move in moves:
            print(f"  {move.on}  {move.amount:>12,.2f}  {move.what}")
        deposited = sum((m.amount for m in moves), Decimal("0"))
        invested = sum((f.amount for f in books[REAL].flows), Decimal("0"))
        print(f"  net into the account:      ₹{deposited:,.2f}")
        print(f"  net into the market (books): ₹{invested:,.2f}")
        print(
            f"  difference:                ₹{deposited - invested:,.2f} — cash that reached the\n"
            "  account and not the market. The books compare invested money, so this is not a gap\n"
            "  in them; it is the part of your balance no book is measuring."
        )

    print(
        f"\n[account] {'nothing to explain' if not problems else f'{problems} thing(s) to look at'}"
    )
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
