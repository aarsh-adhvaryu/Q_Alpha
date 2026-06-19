"""Corporate actions — splits, bonuses, dividends on the FIFO book (Q_alpha.md §14 criterion 5).

A real demat holding is reshaped by corporate actions between trades, and each has a *distinct* Indian
tax treatment that the FIFO ledger must get right:

* **Split / consolidation** — share count scales, per-share cost scales inversely, **total cost and
  the acquisition date are preserved** (the new shares inherit the original holding period).
* **Bonus** — new shares are allotted at **₹0 cost** with the **allotment (ex) date** as their
  acquisition date, so their holding period starts fresh (they can be short-term even when the
  originals are long-term). The originals are untouched.
* **Dividend** — **cash**, taxed as *income* in the recipient's hands (not capital gains), so it never
  touches the lots; it only adds cash. We surface it separately from the CG tax it must not pollute.

The lot mechanics live on :class:`~qalpha.accounting.tax_lots.FIFOLedger` (``apply_split`` /
``apply_bonus``); this module is the typed action model + the dispatcher + the dividend cash math.
``Portfolio.apply_corporate_action`` ties them to the book's cash.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from qalpha.accounting.tax_lots import FIFOLedger

_PAISE = Decimal("0.01")


def _paise(value: Decimal) -> Decimal:
    return value.quantize(_PAISE, rounding=ROUND_HALF_UP)


class CorporateActionType(StrEnum):
    SPLIT = "SPLIT"  # ratio = post-split shares per pre-split share (5.0 for a 5:1 split)
    BONUS = "BONUS"  # ratio = bonus shares per held share (1.0 for a 1:1 bonus)
    DIVIDEND = "DIVIDEND"  # amount_per_share = ₹/share cash (income, not capital gains)


@dataclass(frozen=True)
class CorporateAction:
    """A single corporate action on one ticker, effective ``ex_date``."""

    ticker: str
    ex_date: date
    action_type: CorporateActionType
    ratio: Decimal = Decimal("0")  # SPLIT / BONUS
    amount_per_share: Decimal = Decimal("0")  # DIVIDEND

    @classmethod
    def split(cls, ticker: str, ex_date: date, ratio: Decimal) -> CorporateAction:
        return cls(ticker, ex_date, CorporateActionType.SPLIT, ratio=ratio)

    @classmethod
    def bonus(cls, ticker: str, ex_date: date, ratio: Decimal) -> CorporateAction:
        return cls(ticker, ex_date, CorporateActionType.BONUS, ratio=ratio)

    @classmethod
    def dividend(cls, ticker: str, ex_date: date, amount_per_share: Decimal) -> CorporateAction:
        return cls(ticker, ex_date, CorporateActionType.DIVIDEND, amount_per_share=amount_per_share)


@dataclass(frozen=True)
class CorporateActionResult:
    """What a corporate action did to the book — for the audit trail / dashboard."""

    action: CorporateAction
    shares_before: Decimal
    shares_after: Decimal
    cash_received: Decimal  # > 0 only for dividends (income, not capital gains)
    note: str


def apply_to_ledger(ledger: FIFOLedger, action: CorporateAction) -> Decimal:
    """Apply the share-count effect of ``action`` to ``ledger``; return the dividend cash (₹0 for
    split/bonus). The caller (``Portfolio``) is responsible for crediting any cash to the book.
    """
    if action.action_type is CorporateActionType.SPLIT:
        ledger.apply_split(action.ticker, action.ratio)
        return Decimal("0.00")
    if action.action_type is CorporateActionType.BONUS:
        ledger.apply_bonus(action.ticker, action.ratio, action.ex_date)
        return Decimal("0.00")
    # DIVIDEND: cash on shares held as of the ex-date; lots untouched.
    return _paise(ledger.quantity_held(action.ticker) * action.amount_per_share)
