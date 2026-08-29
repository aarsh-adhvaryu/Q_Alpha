"""The Kite basket generator — a format recovered by experiment, so the fixtures are the spec.

Zerodha publishes no spec. Everything asserted here was verified by exporting a basket Kite built
and round-tripping a machine-written one back in (docs/KITE_BASKET_FORMAT.md).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from qalpha.live.basket import (
    BUY,
    MAX_ORDERS_PER_BASKET,
    SELL,
    BasketOrder,
    UnknownInstrumentError,
    basket_json,
    build_baskets,
    import_instructions,
    round_to_tick,
)
from qalpha.live.instruments import load_instruments

_FIXTURE = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "kite_basket_sample.json"


@pytest.fixture(scope="module")
def instruments() -> dict:
    return load_instruments()


# ---- the format matches what Kite exported -------------------------------------------------------


def test_generated_rows_match_the_shape_kite_exported(instruments: dict) -> None:
    """The fixture is the spec: same params keys, same values, for the same order."""
    kite = json.loads(_FIXTURE.read_text())[0]  # BUY WIPRO LIMIT 100 CNC
    ours = build_baskets([BasketOrder("WIPRO.NS", BUY, 1, Decimal("100"))], instruments)[0][0]
    assert ours["params"] == {**kite["params"]}
    for key in (
        "tradingsymbol",
        "exchange",
        "segment",
        "instrumentToken",
        "exchangeToken",
        "lotSize",
    ):
        assert ours["instrument"][key] == kite["instrument"][key], key


def test_id_is_never_generated(instruments: dict) -> None:
    """Verified optional by round trip — so it is not invented."""
    row = build_baskets([BasketOrder("WIPRO.NS", BUY, 1, Decimal("100"))], instruments)[0][0]
    assert "id" not in row


def test_the_sell_side_carries_the_field_that_could_not_be_guessed(instruments: dict) -> None:
    row = build_baskets([BasketOrder("JIOFIN.NS", SELL, 1, Decimal("600"))], instruments)[0][0]
    assert row["params"]["transactionType"] == "SELL"


# ---- tick size: the finding that would have broken every harvest order ---------------------------


def test_a_price_off_the_tick_grid_is_rounded(instruments: dict) -> None:
    """INFY's tick is 0.10 — ₹1,140.05 is rejected by the exchange, and nothing upstream catches it."""
    row = build_baskets([BasketOrder("INFY.NS", SELL, 1, Decimal("1140.05"))], instruments)[0][0]
    price = Decimal(str(row["params"]["price"]))
    assert price % Decimal("0.1") == 0, price


def test_rounding_goes_toward_execution() -> None:
    """A buy rounds up and a sell rounds down: an unfilled harvest order forfeits the whole set-off."""
    assert round_to_tick(Decimal("100.023"), Decimal("0.05"), BUY) == Decimal("100.05")
    assert round_to_tick(Decimal("100.023"), Decimal("0.05"), SELL) == Decimal("100.00")


def test_a_price_already_on_the_grid_is_untouched() -> None:
    assert round_to_tick(Decimal("238.05"), Decimal("0.05"), SELL) == Decimal("238.05")


# ---- the 20-order cap ----------------------------------------------------------------------------


def test_a_large_plan_is_split_not_truncated(instruments: dict) -> None:
    """A silently dropped order is a plan the user believes he placed and did not."""
    orders = [BasketOrder("WIPRO.NS", BUY, 1, Decimal("100"))] * 25
    baskets = build_baskets(orders, instruments)
    assert len(baskets) == 2
    assert [len(b) for b in baskets] == [MAX_ORDERS_PER_BASKET, 5]
    assert sum(len(b) for b in baskets) == 25, "every order must survive the split"


def test_each_basket_reweights_from_zero(instruments: dict) -> None:
    orders = [BasketOrder("WIPRO.NS", BUY, 1, Decimal("100"))] * 22
    for basket in build_baskets(orders, instruments):
        assert [r["weight"] for r in basket] == list(range(len(basket)))


def test_a_split_plan_says_it_needs_more_than_one_basket() -> None:
    assert "2 baskets" in import_instructions(2)


# ---- safety ---------------------------------------------------------------------------------------


def test_an_unknown_ticker_is_named_not_dropped(instruments: dict) -> None:
    with pytest.raises(UnknownInstrumentError, match="NOTREAL"):
        build_baskets([BasketOrder("NOTREAL.NS", BUY, 1, Decimal("10"))], instruments)


def test_the_instructions_warn_that_import_appends(instruments: dict) -> None:
    """Importing twice into one basket doubles the quantity, and nothing on screen flags it."""
    text = import_instructions(1)
    assert "NEW basket" in text
    assert "double the quantity" in text
    assert "Kite web only" in text


def test_output_is_valid_json_and_an_array(instruments: dict) -> None:
    (doc,) = basket_json([BasketOrder("WIPRO.NS", BUY, 1, Decimal("100"))], instruments)
    parsed = json.loads(doc)
    assert isinstance(parsed, list) and len(parsed) == 1


def test_no_orders_produces_no_basket(instruments: dict) -> None:
    assert build_baskets([], instruments) == []
