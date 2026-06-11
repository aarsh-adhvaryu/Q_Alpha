"""Zerodha delivery-equity transaction-cost model (Q_alpha.md §4.6).

One function, `compute_costs`, returns an itemised `CostBreakdown` for a single buy or sell.
Broker swapped from HDFC to Zerodha (plan improvement #1); the headline difference is ₹0
brokerage on delivery, which the percentages below encode via `CostConfig`.

STT is included in the *total transaction cost* but is excluded from the capital-gains
computation by the tax engine (Q_alpha.md §2.7, §4.6) — the two concerns live in different
modules precisely so that boundary is never blurred.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

from qalpha.config import CostConfig

_PAISE = Decimal("0.01")


def _paise(value: Decimal) -> Decimal:
    """Round a money amount to 2 decimal places (paise), half-up — as contract notes do."""
    return value.quantize(_PAISE, rounding=ROUND_HALF_UP)


class Side(Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class CostBreakdown:
    """Itemised charges for one trade. All values are Decimal rupees, rounded to paise."""

    side: Side
    turnover: Decimal
    brokerage: Decimal
    stt: Decimal
    exchange_txn: Decimal
    sebi: Decimal
    stamp_duty: Decimal
    gst: Decimal
    dp_charge: Decimal
    slippage: Decimal

    @property
    def total(self) -> Decimal:
        """Full friction for the trade, including STT and modelled slippage."""
        return _paise(
            self.brokerage
            + self.stt
            + self.exchange_txn
            + self.sebi
            + self.stamp_duty
            + self.gst
            + self.dp_charge
            + self.slippage
        )

    @property
    def total_ex_slippage(self) -> Decimal:
        """Statutory + broker charges only (what a contract note shows; excludes slippage)."""
        return _paise(self.total - self.slippage)

    @property
    def deductible_for_gains(self) -> Decimal:
        """Transfer expenses deductible when computing capital gains.

        Per Income-Tax rules (Q_alpha.md §2.7/§4.6) STT is NOT deductible; brokerage and the
        other statutory charges incurred wholly in connection with the transfer are. Slippage is
        an execution artefact, not an invoiced expense, so it is excluded here.
        """
        return _paise(
            self.brokerage
            + self.exchange_txn
            + self.sebi
            + self.stamp_duty
            + self.gst
            + self.dp_charge
        )


def compute_costs(
    side: Side,
    quantity: Decimal,
    price: Decimal,
    cfg: CostConfig,
    slippage_pct: Decimal | None = None,
) -> CostBreakdown:
    """Compute the full Zerodha cost breakdown for a single delivery-equity trade.

    Args:
        side: BUY or SELL.
        quantity: number of shares (Decimal; fractional allowed for generality).
        price: execution price per share.
        cfg: cost configuration (rates).
        slippage_pct: fraction of turnover to model as slippage; defaults to
            ``cfg.default_slippage_pct``.

    Returns:
        A fully itemised :class:`CostBreakdown`.
    """
    if quantity < 0 or price < 0:
        raise ValueError("quantity and price must be non-negative")

    slip_pct = cfg.default_slippage_pct if slippage_pct is None else slippage_pct
    turnover = price * quantity

    brokerage = _paise(turnover * cfg.brokerage_pct + cfg.brokerage_flat)
    stt = _paise(turnover * cfg.stt_pct)  # delivery: charged on both buy and sell
    exchange_txn = _paise(turnover * cfg.exchange_txn_pct)
    sebi = _paise(turnover * cfg.sebi_pct)
    stamp_duty = _paise(turnover * cfg.stamp_duty_buy_pct) if side is Side.BUY else Decimal("0.00")
    gst = _paise((brokerage + exchange_txn + sebi) * cfg.gst_pct)
    dp_charge = _paise(cfg.dp_charge_per_sell) if side is Side.SELL else Decimal("0.00")
    slippage = _paise(turnover * slip_pct)

    return CostBreakdown(
        side=side,
        turnover=_paise(turnover),
        brokerage=brokerage,
        stt=stt,
        exchange_txn=exchange_txn,
        sebi=sebi,
        stamp_duty=stamp_duty,
        gst=gst,
        dp_charge=dp_charge,
        slippage=slippage,
    )
