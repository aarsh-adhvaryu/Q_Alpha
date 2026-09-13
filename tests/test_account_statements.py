"""Reading the broker's own statements — on a synthetic workbook, never the real one.

The real exports carry a name, a PAN and every position, and are gitignored. These fixtures have the
shape that matters: a blank first column, a title block, then the header row somewhere below.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import reconcile_account as account


def _sheet(path: Path, rows: list[list[object]]) -> None:
    # A blank first column, exactly as Console writes it.
    frame = pd.DataFrame([[None, *row] for row in rows])
    with pd.ExcelWriter(path) as writer:
        frame.to_excel(writer, sheet_name="Equity", header=False, index=False)


def test_the_header_is_found_below_the_title_block_and_past_the_blank_column(
    tmp_path: Path,
) -> None:
    """Console indents every sheet by one column. Looking only at column 0 finds no header at all."""
    path = tmp_path / "holdings-TEST.xlsx"
    _sheet(
        path,
        [
            ["Client ID", "TEST01"],
            ["Equity Holdings Statement"],
            [],
            ["Symbol", "ISIN", "Sector", "Quantity Available", "Average Price"],
            ["INFY", "INE009A01021", "IT", 20, 1139.025],
            ["TCS", "INE467B01029", "IT", 10, 2339.6],
        ],
    )
    positions = account.read_holdings(path)
    assert [p.ticker for p in positions] == ["INFY.NS", "TCS.NS"]
    assert positions[0].quantity == Decimal("20")
    assert positions[0].average_price == Decimal("1139.025")


def test_a_statement_of_the_wrong_kind_is_refused_rather_than_half_read(tmp_path: Path) -> None:
    path = tmp_path / "holdings-WRONG.xlsx"
    _sheet(path, [["Client ID", "TEST01"], ["Particulars", "Posting Date"], ["x", "2026-01-01"]])
    with pytest.raises(ValueError, match="Symbol"):
        account.read_holdings(path)


def test_only_money_crossing_the_account_boundary_counts_as_funding(tmp_path: Path) -> None:
    """A settlement moves money between cash and shares inside the account; it is not a deposit.

    Counting settlements as funding would report a ₹3 lakh purchase as ₹3 lakh of new money.
    """
    path = tmp_path / "ledger-TEST.xlsx"
    _sheet(
        path,
        [
            ["Client ID", "TEST01"],
            [],
            ["Particulars", "Posting Date", "Cost Center", "Voucher Type", "Debit", "Credit"],
            ["Funds added using UPI", "2026-06-14", "NSE-EQ", "Bank Receipts", 0, 10000],
            ["Net settlement for Equity", "2026-06-15", "NSE-EQ", "Book Voucher", 9619.15, 0],
            ["DP charges", "2026-06-17", "NSE-EQ", "Journal Entry", 15.34, 0],
            ["Funds transferred back", "2026-08-07", "NSE-EQ", "Bank Payments", 4313.85, 0],
        ],
    )
    moves = account.read_ledger(path)
    assert [m.amount for m in moves] == [Decimal("10000"), Decimal("-4313.85")]
    assert sum((m.amount for m in moves), Decimal("0")) == Decimal("5686.15")
