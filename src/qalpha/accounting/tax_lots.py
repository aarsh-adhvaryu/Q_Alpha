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
from collections.abc import Mapping
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

    def to_dict(self) -> dict[str, str | None]:
        """JSON-safe snapshot of the lot (Decimals→str, date→ISO) for persisting a live book."""
        return {
            "ticker": self.ticker,
            "acquisition_date": self.acquisition_date.isoformat(),
            "quantity_original": str(self.quantity_original),
            "buy_price": str(self.buy_price),
            "pool": self.pool,
            "brokerage": str(self.brokerage),
            "stamp_duty": str(self.stamp_duty),
            "other_costs": str(self.other_costs),
            "lot_id": self.lot_id,
            "broker_trade_id": self.broker_trade_id,
            "quantity_remaining": str(self.quantity_remaining),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, str | None]) -> TaxLot:
        """Reconstruct a lot from :meth:`to_dict` (inverse round-trip)."""

        def dec(key: str) -> Decimal:
            return Decimal(str(d[key]))

        return cls(
            ticker=str(d["ticker"]),
            acquisition_date=date.fromisoformat(str(d["acquisition_date"])),
            quantity_original=dec("quantity_original"),
            buy_price=dec("buy_price"),
            pool=str(d["pool"]),
            brokerage=dec("brokerage"),
            stamp_duty=dec("stamp_duty"),
            other_costs=dec("other_costs"),
            lot_id=str(d["lot_id"]),
            broker_trade_id=d["broker_trade_id"],
            quantity_remaining=dec("quantity_remaining"),
        )


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

    # ---- corporate actions (§14 criterion 5) -----------------------------

    def apply_split(self, ticker: str, ratio: Decimal) -> Decimal:
        """Stock split / consolidation: scale every lot's shares by ``ratio`` and its per-share price
        by ``1/ratio``, so **total cost of acquisition is preserved** and the **acquisition date is
        unchanged** (the split shares inherit the original holding period — the Indian tax treatment).

        ``ratio`` = post-split shares per pre-split share (5.0 for a 5:1 split; 0.5 for a 1:2
        consolidation). Returns the net change in shares held. Both ``quantity_original`` and
        ``quantity_remaining`` scale, so partially-sold lots stay consistent; the fixed buy-side
        expenses are untouched (they were ₹, not per-share), keeping ``total_buy_cost`` invariant.
        """
        if ratio <= 0:
            raise ValueError("split ratio must be positive")
        before = self.quantity_held(ticker)
        for lot in self._lots.get(ticker, []):
            lot.quantity_original *= ratio
            lot.quantity_remaining *= ratio
            lot.buy_price = lot.buy_price / ratio
        return self.quantity_held(ticker) - before

    def apply_bonus(self, ticker: str, ratio: Decimal, ex_date: date) -> Decimal:
        """Bonus issue: add new lots of ``held × ratio`` shares at **₹0 cost**, dated ``ex_date``.

        Indian tax treats bonus shares as acquired at **nil cost** with the **allotment date** as the
        acquisition date (so their holding period starts fresh — they can be STCG even when the
        originals are long-term). Originals are left untouched. One bonus lot per source lot, so each
        keeps its sleeve (``pool``). ``ratio`` = bonus shares per held share (1.0 for 1:1). Returns the
        bonus shares added.
        """
        if ratio <= 0:
            raise ValueError("bonus ratio must be positive")
        added = Decimal("0")
        bonus_lots: list[TaxLot] = []
        for lot in self.open_lots(ticker):
            bonus_qty = lot.quantity_remaining * ratio
            if bonus_qty > 0:
                bonus_lots.append(
                    TaxLot(
                        ticker=ticker,
                        acquisition_date=ex_date,
                        quantity_original=bonus_qty,
                        buy_price=Decimal("0"),
                        pool=lot.pool,
                    )
                )
                added += bonus_qty
        for nl in bonus_lots:
            self.add_lot(nl)
        return added
