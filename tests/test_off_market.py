"""IPO allotments and other off-market credits (2026-08-29).

A Zerodha tradebook export contains *trades*. An IPO allotment is not one: the shares appear in
holdings with no matching row. For the Live tab that already surfaces as a reconciliation warning;
for the twin it is worse, because the money was never credited to any book — ``REAL`` would hold
shares the twins were never funded for, and every gap after that compares different amounts of
money. The identical-flow invariant, broken from the opposite direction to a missed SIP.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from qalpha.accounting.costs import Side
from qalpha.config import Config
from qalpha.live.twin import (
    ALL_BOOKS,
    REAL,
    TWIN_FULL,
    OffMarketCredit,
    apply_off_market,
    assert_identical_flows,
    flows_with_off_market,
    load_off_market,
    seed_books,
    sync_flows,
)


@dataclass(frozen=True)
class _T:
    trade_date: date
    ticker: str
    side: Side
    quantity: Decimal
    price: Decimal


def _trades() -> list[_T]:
    return [_T(date(2026, 6, 15), "INFY.NS", Side.BUY, Decimal("5"), Decimal("1136"))]


def _lot(pf, ticker: str, on: date, qty: str, price: str) -> None:
    from qalpha.accounting.tax_lots import TaxLot

    pf.ledger.add_lot(
        TaxLot(
            ticker=ticker,
            acquisition_date=on,
            quantity_original=Decimal(qty),
            buy_price=Decimal(price),
        )
    )


def _ipo(on: date = date(2026, 7, 10)) -> OffMarketCredit:
    """A small IPO allotment: 15 shares at a ₹230 issue price."""
    return OffMarketCredit(
        ticker="NEWCO.NS",
        on=on,
        quantity=Decimal("15"),
        cost_per_share=Decimal("230"),
        note="IPO allotment",
    )


def test_an_allotment_becomes_a_dated_flow() -> None:
    flows = flows_with_off_market(_trades(), [_ipo()])
    assert [f.on for f in flows] == [date(2026, 6, 15), date(2026, 7, 10)]
    assert flows[1].amount == Decimal("3450")  # 15 × ₹230, the issue price


def test_an_allotment_on_a_day_that_already_has_trades_is_netted() -> None:
    """Allotments can land on a day the user also traded — one flow per day, not two."""
    flows = flows_with_off_market(_trades(), [_ipo(on=date(2026, 6, 15))])
    assert len(flows) == 1
    assert flows[0].amount == Decimal("5") * Decimal("1136") + Decimal("3450")


def test_every_book_is_funded_for_the_allotment() -> None:
    """The twins must get the same rupees, to deploy their own way."""
    books = seed_books(_trades(), Config())
    before = books[TWIN_FULL].net_invested
    deltas = sync_flows(books, _trades(), [_ipo()])
    assert len(deltas) == 1 and deltas[0].amount == Decimal("3450")
    for name in ALL_BOOKS:
        assert books[name].net_invested == before + Decimal("3450"), name
    assert_identical_flows(list(books.values()))


def test_real_receives_the_actual_lot_dated_from_allotment() -> None:
    """§2(42A) counts the holding period from the allotment date, not the application date."""
    books = seed_books(_trades(), Config())
    real = books[REAL].portfolio
    apply_off_market(real, [_ipo()])
    (lot,) = real.ledger.open_lots("NEWCO.NS")
    assert lot.quantity_remaining == Decimal("15")
    assert lot.acquisition_date == date(2026, 7, 10)
    assert lot.cost_basis_per_share == Decimal("230")


def test_no_credits_file_is_not_an_error() -> None:
    assert load_off_market(Path("data/twin/does-not-exist.json")) == []


def test_credits_round_trip_from_disk(tmp_path: Path) -> None:
    p = tmp_path / "off_market.json"
    p.write_text(
        json.dumps(
            {
                "credits": [
                    {
                        "ticker": "NEWCO.NS",
                        "on": "2026-07-10",
                        "quantity": "15",
                        "cost_per_share": "230",
                        "note": "IPO allotment",
                    }
                ]
            }
        )
    )
    (c,) = load_off_market(p)
    assert c.ticker == "NEWCO.NS" and c.amount == Decimal("3450")
    assert c.note == "IPO allotment"


def test_credits_are_ordered_oldest_first() -> None:
    """Flows are diffed by day; out-of-order credits would confuse that."""
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(
            {
                "credits": [
                    {"ticker": "B.NS", "on": "2026-09-01", "quantity": "1", "cost_per_share": "10"},
                    {"ticker": "A.NS", "on": "2026-07-01", "quantity": "1", "cost_per_share": "10"},
                ]
            },
            fh,
        )
        path = Path(fh.name)
    assert [c.ticker for c in load_off_market(path)] == ["A.NS", "B.NS"]


# ---- detected from the broker, not typed by hand -------------------------------------------------


def _broker_book() -> tuple:
    """A replayed book missing 15 shares the broker holds — an allotment that credited."""
    from qalpha.live.twin import unexplained_holdings

    books = seed_books(_trades(), Config())
    replayed = books[REAL].portfolio
    # add_lot, not buy(): buy() is affordability-capped, so it would under-fill and the shortfall
    # would itself register as "unexplained" — which is correct behaviour and a wrong fixture.
    _lot(replayed, "INFY.NS", date(2026, 6, 15), "5", "1136")
    broker_qty = {"INFY.NS": Decimal("5"), "NEWCO.NS": Decimal("15")}
    broker_avg = {"INFY.NS": Decimal("1136"), "NEWCO.NS": Decimal("230")}
    return unexplained_holdings(replayed, broker_qty, broker_avg), replayed


def test_the_broker_supplies_three_of_the_four_fields() -> None:
    """kite.holdings() returns settled demat stock, so an allotment appears the moment it credits."""
    detected, _ = _broker_book()
    (c,) = detected
    assert c.ticker == "NEWCO.NS"
    assert c.quantity == Decimal("15")
    assert c.cost_per_share == Decimal("230"), "average_price is the issue price for an allotment"


def test_explained_holdings_are_not_flagged() -> None:
    """Only the gap is detected — a share the tradebook accounts for must never be double-counted."""
    detected, _ = _broker_book()
    assert [c.ticker for c in detected] == ["NEWCO.NS"]


def test_a_partial_gap_detects_only_the_difference() -> None:
    from qalpha.live.twin import unexplained_holdings

    books = seed_books(_trades(), Config())
    pf = books[REAL].portfolio
    _lot(pf, "INFY.NS", date(2026, 6, 15), "5", "1136")
    (c,) = unexplained_holdings(pf, {"INFY.NS": Decimal("12")}, {"INFY.NS": Decimal("1136")})
    assert c.quantity == Decimal("7"), "12 held, 5 explained → 7 unexplained"


def test_the_snippet_prefills_everything_except_the_date() -> None:
    """The date is the one field the broker cannot supply, so it is the only one left blank."""
    from qalpha.live.twin import off_market_snippet

    detected, _ = _broker_book()
    snippet = off_market_snippet(detected)
    assert '"ticker": "NEWCO.NS"' in snippet
    assert '"quantity": "15"' in snippet
    assert '"cost_per_share": "230"' in snippet
    assert '"on": "YYYY-MM-DD"' in snippet, "the date must be the blank the user fills"
