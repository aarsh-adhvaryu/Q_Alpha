"""The risk governor: does the book, not the basket, respect the cap?"""

from __future__ import annotations

from decimal import Decimal

from qalpha.live.governor import (
    KITE_NUDGE_WEIGHT,
    MAX_SECTOR_WEIGHT,
    sector_concentration,
)

_SEC = {"A.NS": "POWER", "B.NS": "POWER", "C.NS": "IT", "D.NS": "FMCG"}
_PX = {t: Decimal("100") for t in _SEC}


def test_a_compliant_basket_can_still_breach_the_book() -> None:
    """The defect, in one assertion.

    Twelve individually-compliant monthly baskets simulated on the real panel produced a book that
    was 36.9% POWER. The per-basket cap constrains the names chosen *that round*; at 3-4 names a 30%
    cap cannot bind. This is that arithmetic in miniature: a two-name basket that is 50/50 by sector
    -- unarguably "capped" on its own terms -- lands on a book already leaning POWER and pushes it
    past the house cap.
    """
    holdings = {"A.NS": 10, "C.NS": 20, "D.NS": 10}  # POWER 25%, comfortably under the cap
    orders = [("B.NS", 10, Decimal("100")), ("C.NS", 10, Decimal("100"))]  # basket is 50% POWER
    report = sector_concentration(holdings, orders, _PX, _SEC)
    power = next(e for e in report.exposures if e.sector == "POWER")
    assert power.weight_after > MAX_SECTOR_WEIGHT
    assert power.worsens, "the basket added POWER, so it is responsible for the breach"
    assert not report.clear
    assert "POWER" in report.render()


def test_a_breach_the_basket_does_not_worsen_is_not_flagged() -> None:
    """A guard that fires on something the user cannot fix is a guard people learn to ignore.

    If the book is already over the cap, refusing to buy an unrelated name does not un-breach it --
    buying elsewhere actively dilutes the concentration. Only a basket that pushes a sector UP is
    held responsible for it.
    """
    holdings = {"A.NS": 90, "C.NS": 10}  # 90% POWER, nothing proposed can undo that
    report = sector_concentration(holdings, [("D.NS", 10, Decimal("100"))], _PX, _SEC)
    power = next(e for e in report.exposures if e.sector == "POWER")
    assert power.weight_after > MAX_SECTOR_WEIGHT
    assert not power.worsens, "the basket diluted POWER"
    assert report.clear, "a dilutive basket must not be blamed for an inherited breach"


def test_an_unpriced_holding_is_excluded_not_valued_at_zero() -> None:
    """Valuing an unmarked holding at zero shrinks the denominator and overstates every sector.

    This is the +444% defect's shape: a number quietly standing in for one that is missing.
    """
    holdings = {"A.NS": 10, "C.NS": 10}
    partial = {"A.NS": Decimal("100")}  # C has no mark
    report = sector_concentration(holdings, [], partial, _SEC)
    assert report.book_value_after == Decimal("1000")
    assert {e.sector for e in report.exposures} == {"POWER"}


def test_an_unclassified_name_is_reported_not_dropped() -> None:
    """A position with no sector is still concentration risk; silence would understate the book."""
    report = sector_concentration({"Z.NS": 10}, [], {"Z.NS": Decimal("100")}, {})
    assert [e.sector for e in report.exposures] == ["UNKNOWN"]


def test_the_kite_nudge_level_is_reported_separately_from_ours() -> None:
    """Ours is stricter. Both are shown so a breach can be read against the broker's own bar."""
    assert MAX_SECTOR_WEIGHT < KITE_NUDGE_WEIGHT
    report = sector_concentration({}, [("A.NS", 10, Decimal("100"))], _PX, _SEC)
    power = next(e for e in report.exposures if e.sector == "POWER")
    assert power.weight_after == Decimal("1")
    assert power.breaches_kite_nudge and power.breaches_house_cap
    assert "Kite" in report.render()


def test_an_empty_book_and_no_orders_renders_without_raising() -> None:
    assert "No priced holdings" in sector_concentration({}, [], {}, {}).render()
