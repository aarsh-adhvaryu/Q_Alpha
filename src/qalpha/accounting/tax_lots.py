"""FIFO tax-lot ledger (Q_alpha.md §2.7).

Indian demat accounts use strict First-In-First-Out for tax purposes, so the system cannot keep
a single ``entry_date`` per holding — it must track individual lots and consume the oldest first
on every sell. This module is pure bookkeeping: it knows nothing about prices today, costs, or
tax rates. It records lots, consumes them FIFO, and reports which lots were consumed (with
holding periods). The capital-gains module turns those consumptions into tax.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

_PAISE = Decimal("0.01")
_SHARE_QUANTUM = Decimal("0.000001")  # NUMERIC(15,6) per spec §5.2


def _paise(value: Decimal) -> Decimal:
    return value.quantize(_PAISE, rounding=ROUND_HALF_UP)


@dataclass
class TaxLot:
    """A single purchase lot. Mirrors ``portfolio.tax_lots`` (Q_alpha.md §2.7)."""

    ticker: str
    acquisition_date: date
    quantity_original: Decimal
    buy_price: Decimal
    pool: str = "core"
    brokerage: Decimal = Decimal("0.00")
    stamp_duty: Decimal = Decimal("0.00")
    other_costs: Decimal = Decimal("0.00")
    lot_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    broker_trade_id: str | None = None
    quantity_remaining: Decimal = field(default=Decimal("0"))

    def __post_init__(self) -> None:
        if self.quantity_original <= 0:
            raise ValueError("quantity_original must be positive")
        if self.buy_price < 0:
            raise ValueError("buy_price must be non-negative")
        # Default remaining == original on creation.
        if self.quantity_remaining == Decimal("0"):
            self.quantity_remaining = self.quantity_original

    @property
    def total_buy_cost(self) -> Decimal:
        """Cost of acquisition for the *original* lot: consideration + buy-side expenses."""
        return _paise(
            self.buy_price * self.quantity_original
            + self.brokerage
            + self.stamp_duty
            + self.other_costs
        )

    @property
    def cost_basis_per_share(self) -> Decimal:
        """Per-share acquisition cost (consideration + allocated buy expenses)."""
        return self.total_buy_cost / self.quantity_original


@dataclass(frozen=True)
class LotConsumption:
    """Record of consuming part (or all) of a lot on a sell (Q_alpha.md `lot_consumptions`)."""

    lot_id: str
    ticker: str
    quantity: Decimal
    acquisition_date: date
    sell_date: date
    buy_price: Decimal
    cost_basis: Decimal  # acquisition cost for the consumed quantity (incl. allocated buy costs)

    @property
    def holding_days(self) -> int:
        return (self.sell_date - self.acquisition_date).days

    @property
    def is_long_term(self) -> bool:
        """LTCG if held >= 365 days (Q_alpha.md §4.6). Boundary handled by the tax engine."""
        return self.holding_days >= 365


class InsufficientSharesError(ValueError):
    """Raised when a sell requests more shares than the ledger holds for a ticker."""


class FIFOLedger:
    """Holds open lots per ticker and consumes them oldest-first on sells."""

    def __init__(self) -> None:
        # Insertion order within each ticker's list is FIFO by acquisition.
        self._lots: dict[str, list[TaxLot]] = defaultdict(list)

    def add_lot(self, lot: TaxLot) -> None:
        """Record a buy. Lots are kept sorted by acquisition_date (stable) to enforce FIFO."""
        bucket = self._lots[lot.ticker]
        bucket.append(lot)
        bucket.sort(key=lambda lt: lt.acquisition_date)

    def all_tickers(self) -> list[str]:
        """Every ticker that has ever had a lot recorded (may include fully-sold names)."""
        return list(self._lots.keys())

    def quantity_held(self, ticker: str) -> Decimal:
        return sum((lt.quantity_remaining for lt in self._lots.get(ticker, [])), Decimal("0"))

    def open_lots(self, ticker: str) -> list[TaxLot]:
        """Lots with shares remaining, FIFO order (read-only view)."""
        return [lt for lt in self._lots.get(ticker, []) if lt.quantity_remaining > 0]

    def consume(self, ticker: str, quantity: Decimal, sell_date: date) -> list[LotConsumption]:
        """Consume ``quantity`` shares of ``ticker`` FIFO, mutating remaining quantities.

        Returns the per-lot consumption records (oldest first). Raises
        :class:`InsufficientSharesError` if the ledger does not hold enough — the caller must
        reconcile against the broker before forcing a sell (Q_alpha.md §4.9).
        """
        if quantity <= 0:
            raise ValueError("sell quantity must be positive")

        held = self.quantity_held(ticker)
        if quantity > held + _SHARE_QUANTUM:
            raise InsufficientSharesError(f"sell {quantity} {ticker} but only {held} held")

        remaining_to_sell = quantity
        consumptions: list[LotConsumption] = []

        for lot in self._lots[ticker]:
            if remaining_to_sell <= 0:
                break
            if lot.quantity_remaining <= 0:
                continue

            take = min(lot.quantity_remaining, remaining_to_sell)
            cost_basis = _paise(lot.cost_basis_per_share * take)

            consumptions.append(
                LotConsumption(
                    lot_id=lot.lot_id,
                    ticker=ticker,
                    quantity=take,
                    acquisition_date=lot.acquisition_date,
                    sell_date=sell_date,
                    buy_price=lot.buy_price,
                    cost_basis=cost_basis,
                )
            )
            lot.quantity_remaining -= take
            remaining_to_sell -= take

        return consumptions

    def oldest_lot_age_days(self, ticker: str, as_of: date) -> int | None:
        """Age of the oldest open lot — feeds the §3.4 STCG→LTCG boundary penalty."""
        open_lots = self.open_lots(ticker)
        if not open_lots:
            return None
        return (as_of - open_lots[0].acquisition_date).days
