"""Check the books against the broker's own statements: holdings, and the money that came in.

    uv run python scripts/reconcile_account.py            # check the books against the statements
    uv run python scripts/reconcile_account.py --import   # …and record the funding the books use

Reads what Zerodha Console exports into ``data/account/`` (gitignored — they carry a name and a PAN):

* **holdings statement** — every position and its average price. The independent check on the FIFO
  ledger: quantities must match exactly. Average price is expected to differ, because a lot's cost
  basis here includes the buy-side charges that are deductible against capital gains and Zerodha's
  "Average Price" is the execution price alone. The difference is reported, never hidden.
* **ledger** — the real deposits and withdrawals: the money the books are funded with, and the
  broker's own closing balance. Both are checked. Funding that does not match what was deposited
  means every comparison is against the wrong amount of money; cash that does not match the broker's
  balance means a trade or a movement is missing, and cash is what the investor gets to spend.

**It changes nothing.** No book, no ledger, no decision — it reads and reports. A statement that is
absent is named as absent.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qalpha.config import Config
from qalpha.live import funding as funding_record
from qalpha.live.console import use_utf8
from qalpha.live.twin import REAL, load_books

ACCOUNT = Path("data/account")
#: How far the modelled cash may sit from the broker's balance before it is a problem rather than
#: charges. The known gaps are DP fees, payment-gateway fees and cost-model rounding — tens of rupees on a five-lakh account. A larger one means a trade or a movement is missing.
CASH_TOLERANCE = Decimal("1000")


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
    kind: str = ""  # the broker's voucher type, which carries no personal detail


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
                kind=voucher,
            )
        )
    return moves


def closing_balance(path: Path) -> Decimal:
    """The broker's own last balance — what the modelled cash is checked against."""
    raw = pd.read_excel(path, sheet_name="Equity", header=None)
    frame = pd.read_excel(path, sheet_name="Equity", header=_header_row(raw, "Particulars"))
    frame = frame[frame["Net Balance"].notna()]
    return Decimal(str(frame["Net Balance"].iloc[-1]))


def main(argv: list[str] | None = None) -> int:
    use_utf8()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--import",
        dest="do_import",
        action="store_true",
        help="write the ledger's deposits and withdrawals to data/twin/funding.json",
    )
    args = ap.parse_args(argv)
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
        funded = sum((f.amount for f in books[REAL].flows), Decimal("0"))
        print(f"  net into the account:  ₹{deposited:,.2f}")
        print(f"  the books are funded:  ₹{funded:,.2f}")
        if funded != deposited:
            problems += 1
            print(
                "  ← THE BOOKS ARE NOT FUNDED WITH THE MONEY THAT WAS DEPOSITED. Run\n"
                "  `twin.py refund` (after `--import`), or every comparison is against a different\n"
                "  amount of money than you actually put in."
            )

        # Quantities can reconcile exactly while the cash is wrong, and cash is what the investor
        # gets to spend. This is the only check on it.
        broker_cash = closing_balance(ledger_file)
        gap = book.cash - broker_cash
        print(f"\n  cash:  ₹{book.cash:,.2f} modelled · ₹{broker_cash:,.2f} at the broker")
        if abs(gap) > CASH_TOLERANCE:
            problems += 1
            print(f"  ← off by ₹{gap:,.2f}, more than the ₹{CASH_TOLERANCE:,.0f} tolerance")
        else:
            print(
                f"  difference ₹{gap:,.2f}: charges the tradebook does not carry (DP, payment\n"
                "  gateway, bank) and rounding in the cost model. Within tolerance, and shown\n"
                "  rather than absorbed."
            )

    if args.do_import:
        if ledger_file is None:
            print("[account] nothing to import: no ledger.", file=sys.stderr)
            return 2
        record = funding_record.Funding(
            movements=tuple(
                funding_record.Movement(on=date.fromisoformat(m.on), amount=m.amount, kind=m.kind)
                for m in read_ledger(ledger_file)
            ),
            closing_balance=closing_balance(ledger_file),
            # Not the file name: a Console export is named for the client id, and this record is
            # committed while the statement is not.
            source=funding_record.provenance(ledger_file),
            imported_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        funding_record.save(record)
        print(
            f"\n[account] funding recorded → {funding_record.FUNDING_PATH}: "
            f"{len(record.movements)} movement(s), net ₹{record.net:,.2f}, "
            f"broker's closing balance ₹{record.closing_balance:,.2f}"
        )

    print(
        f"\n[account] {'nothing to explain' if not problems else f'{problems} thing(s) to look at'}"
    )
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
