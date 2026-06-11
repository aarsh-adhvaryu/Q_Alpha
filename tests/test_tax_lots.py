"""FIFO ledger tests, including the Q_alpha.md §2.7 worked example."""

from datetime import date
from decimal import Decimal

import pytest

from qalpha.accounting.tax_lots import FIFOLedger, InsufficientSharesError, TaxLot


def test_spec_worked_example_section_2_7() -> None:
    """Sell 6 TCS: Lot1 (Jan, 2sh) fully -> LTCG; Lot2 (Aug, 4 of 8) -> STCG."""
    ledger = FIFOLedger()
    ledger.add_lot(TaxLot("TCS", date(2025, 1, 10), Decimal("2"), Decimal("3700")))
    ledger.add_lot(TaxLot("TCS", date(2025, 8, 15), Decimal("8"), Decimal("4000")))

    consumptions = ledger.consume("TCS", Decimal("6"), date(2026, 2, 10))

    assert len(consumptions) == 2
    lot1, lot2 = consumptions

    # Oldest lot consumed first, fully.
    assert lot1.acquisition_date == date(2025, 1, 10)
    assert lot1.quantity == Decimal("2")
    assert lot1.holding_days == 396
    assert lot1.is_long_term  # > 365 days

    # Then 4 of the 8 newer shares.
    assert lot2.acquisition_date == date(2025, 8, 15)
    assert lot2.quantity == Decimal("4")
    assert lot2.holding_days == 179
    assert not lot2.is_long_term  # < 365 days

    # 4 shares of the Aug lot remain open.
    assert ledger.quantity_held("TCS") == Decimal("4")
    assert ledger.open_lots("TCS")[0].quantity_remaining == Decimal("4")


def test_cost_basis_includes_buy_expenses() -> None:
    lot = TaxLot(
        "INFY",
        date(2025, 1, 1),
        Decimal("10"),
        Decimal("1500"),
        brokerage=Decimal("0.00"),
        stamp_duty=Decimal("2.25"),
        other_costs=Decimal("0.50"),
    )
    # 15000 + 2.25 + 0.50 = 15002.75 total; per share 1500.275
    assert lot.total_buy_cost == Decimal("15002.75")
    assert lot.cost_basis_per_share == Decimal("1500.275")


def test_consume_allocates_cost_basis_pro_rata() -> None:
    ledger = FIFOLedger()
    ledger.add_lot(
        TaxLot("INFY", date(2025, 1, 1), Decimal("10"), Decimal("1500"), stamp_duty=Decimal("2.25"))
    )
    consumptions = ledger.consume("INFY", Decimal("4"), date(2025, 6, 1))
    # cost basis per share = 15002.25 / 10 = 1500.225; * 4 = 6000.90
    assert consumptions[0].cost_basis == Decimal("6000.90")


def test_oversell_raises() -> None:
    ledger = FIFOLedger()
    ledger.add_lot(TaxLot("TCS", date(2025, 1, 1), Decimal("5"), Decimal("100")))
    with pytest.raises(InsufficientSharesError):
        ledger.consume("TCS", Decimal("6"), date(2025, 2, 1))


def test_oldest_lot_age() -> None:
    ledger = FIFOLedger()
    ledger.add_lot(TaxLot("TCS", date(2025, 8, 1), Decimal("5"), Decimal("100")))
    ledger.add_lot(TaxLot("TCS", date(2025, 1, 1), Decimal("5"), Decimal("100")))
    # Even though added second, the Jan lot is oldest after FIFO sort.
    assert ledger.oldest_lot_age_days("TCS", date(2025, 12, 27)) == 360
