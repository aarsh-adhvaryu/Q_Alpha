"""Zerodha Console **Tax P&L** parser + criterion-4 reconciliation (Q_alpha.md §14 crit 4).

The Tax P&L (Console → Reports → Tax P&L, exported as ``.xlsx``) is the broker's *official* realized
capital-gains statement — the ground truth our FIFO engine must match before any real-money reliance.
This module parses that messy multi-section workbook into a clean :class:`TaxPnL`, and reconciles it
against a tradebook :class:`~qalpha.live.tradebook.ReplayResult`.

Two honest reconciliation layers, because the two systems define "profit" differently:

* **Gross realized P&L** — what Zerodha's Tax P&L reports (sell value − buy value, charges listed
  *separately* and **not** netted). Our engine reproduces this exactly via a **zero-cost replay**, so a
  match here proves the FIFO lot-matching, holding-period classification (STCG/LTCG) and quantities are
  correct to the paise.
* **Net taxable gain + tax** — our engine's legally-correct capital gain nets the statutory transfer
  expenses (brokerage, exchange/SEBI charges, stamp duty, GST; **STT excluded**, per §2.7) from the
  consideration, then applies the STCG/LTCG rate. Zerodha leaves that expense deduction to the filer,
  so the difference vs gross is exactly our modelled deductible charges — sub-rupee on liquid
  delivery trades, and itemised in the reconciliation rather than hidden.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import IO

import pandas as pd

# Section titles in the "Equity and Non Equity" sheet → our gain-type tag.
_SECTION_TYPES = {
    "Intraday": "INTRADAY",
    "Short Term Trades": "STCG",
    "Long Term Trades": "LTCG",
    "Non Equity": "NON_EQUITY",
}
_REALIZED_LABELS = {
    "Intraday/Speculative profit": "intraday",
    "Short Term profit": "short_term",
    "Long Term profit": "long_term",
    "Non Equity profit": "non_equity",
}
_SUMMARY_SHEET = "Equity and Non Equity"


def _dec(value: object) -> Decimal:
    """Parse a possibly comma-grouped Zerodha numeric cell into Decimal."""
    return Decimal(str(value).replace(",", "").strip())


@dataclass(frozen=True)
class TaxPnLTrade:
    """One symbol's realized line from a Tax P&L section (gross of charges, as Zerodha reports it)."""

    symbol: str
    gain_type: str  # "STCG" | "LTCG" | "INTRADAY" | "NON_EQUITY"
    quantity: Decimal
    buy_value: Decimal
    sell_value: Decimal
    realized_pnl: Decimal  # gross: sell_value - buy_value


@dataclass(frozen=True)
class TaxPnL:
    """The parsed Zerodha Tax P&L statement (realized-profit breakdown + per-symbol trades)."""

    client_id: str
    intraday_profit: Decimal
    short_term_profit: Decimal
    long_term_profit: Decimal
    non_equity_profit: Decimal
    charges: dict[str, Decimal]
    trades: list[TaxPnLTrade]

    def trades_of(self, gain_type: str) -> list[TaxPnLTrade]:
        return [t for t in self.trades if t.gain_type == gain_type]

    @property
    def gross_by_type(self) -> dict[str, Decimal]:
        """Reported realized profit per gain type (the reconciliation target)."""
        return {
            "INTRADAY": self.intraday_profit,
            "STCG": self.short_term_profit,
            "LTCG": self.long_term_profit,
            "NON_EQUITY": self.non_equity_profit,
        }


def parse_taxpnl(source: str | Path | IO[bytes]) -> TaxPnL:
    """Parse a Zerodha Console Tax P&L ``.xlsx`` (path or uploaded file) into a :class:`TaxPnL`.

    Reads the "Equity and Non Equity" summary sheet, which carries both the realized-profit breakdown
    and clean per-symbol [Symbol, Quantity, Buy Value, Sell Value, Realized P&L] tables. Tolerant to
    the sheet's leading blank columns / scattered layout: rows are flattened to their non-empty cells
    and located by label, not by fixed offsets.
    """
    df = pd.read_excel(source, sheet_name=_SUMMARY_SHEET, header=None)
    rows: list[list[object]] = [
        [v for v in row.tolist() if pd.notna(v)] for _, row in df.iterrows()
    ]

    client_id = ""
    profits = {
        "intraday": Decimal("0"),
        "short_term": Decimal("0"),
        "long_term": Decimal("0"),
        "non_equity": Decimal("0"),
    }
    charges: dict[str, Decimal] = {}
    trades: list[TaxPnLTrade] = []

    in_charges = False
    current_type: str | None = None
    for vals in rows:
        if not vals:
            # Blank rows separate a section title from its table — do NOT reset the section here.
            continue
        head = str(vals[0]).strip()

        if head == "Client ID" and len(vals) >= 2:
            client_id = str(vals[1]).strip()
            continue
        if head in _REALIZED_LABELS and len(vals) >= 2:
            profits[_REALIZED_LABELS[head]] = _dec(vals[1])
            continue
        if head == "Charges":
            in_charges = True
            continue
        if head == "Account Head":
            continue

        # Per-symbol trade tables: a section title opens a block, "Symbol" is its header, then data.
        # Reaching either also closes the charges block (which runs through the "Other Charges"
        # subsection, capturing e.g. the DP charge booked as "Other Credits & Debits").
        if head in _SECTION_TYPES:
            in_charges = False
            current_type = _SECTION_TYPES[head]
            continue
        if head == "Symbol":
            in_charges = False
            continue
        if in_charges and len(vals) >= 2:
            with contextlib.suppress(ValueError, ArithmeticError):
                charges[head] = _dec(vals[1])
            continue
        if current_type is not None and len(vals) >= 5:
            try:
                trades.append(
                    TaxPnLTrade(
                        symbol=head,
                        gain_type=current_type,
                        quantity=_dec(vals[1]),
                        buy_value=_dec(vals[2]),
                        sell_value=_dec(vals[3]),
                        realized_pnl=_dec(vals[4]),
                    )
                )
            except (ValueError, ArithmeticError):
                current_type = None

    return TaxPnL(
        client_id=client_id,
        intraday_profit=profits["intraday"],
        short_term_profit=profits["short_term"],
        long_term_profit=profits["long_term"],
        non_equity_profit=profits["non_equity"],
        charges=charges,
        trades=trades,
    )


@dataclass(frozen=True)
class ReconcileResult:
    """Outcome of reconciling our replayed FIFO gains against the broker's Tax P&L."""

    ok: bool  # gross reconciles within tolerance for every equity gain type
    tolerance: Decimal
    gross_by_type: dict[str, Decimal]  # ours (zero-cost replay) per type
    theirs_by_type: dict[str, Decimal]  # Zerodha reported per type
    lines: list[str]  # human-readable comparison


def reconcile_gross(
    ours_gross_by_type: dict[str, Decimal],
    statement: TaxPnL,
    *,
    tolerance: Decimal = Decimal("0.01"),
) -> ReconcileResult:
    """Compare our gross realized gain per type (STCG/LTCG) against the Tax P&L's reported profit.

    ``ours_gross_by_type`` should come from a **zero-cost** tradebook replay (so our gain == sell −
    buy, the same gross basis Zerodha reports). Equity types (STCG/LTCG) must match within
    ``tolerance``; intraday/non-equity are reported for completeness but not gated (this engine is
    delivery-only).
    """
    theirs = statement.gross_by_type
    lines: list[str] = []
    ok = True
    for gain_type in ("STCG", "LTCG"):
        ours = ours_gross_by_type.get(gain_type, Decimal("0"))
        them = theirs.get(gain_type, Decimal("0"))
        diff = ours - them
        within = abs(diff) <= tolerance
        ok = ok and within
        flag = "OK" if within else "MISMATCH"
        lines.append(
            f"{gain_type}: ours ₹{ours:,.2f} vs Zerodha ₹{them:,.2f} (Δ ₹{diff:,.2f}) [{flag}]"
        )
    return ReconcileResult(
        ok=ok,
        tolerance=tolerance,
        gross_by_type=ours_gross_by_type,
        theirs_by_type=theirs,
        lines=lines,
    )
