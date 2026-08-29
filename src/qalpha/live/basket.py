"""Turn a recommendation into a file you import into Kite — the output contract (PLAN_REDESIGN §2b).

Every surface here computes exact orders and then made the user retype them. This closes that: a
recommendation becomes a basket file, imported at Orders → Baskets → New Basket → Import.

**The format is verified, not inferred.** Zerodha publishes no spec, so it was recovered from a
basket Kite itself exported and then round-tripped back in (``data/fixtures/kite_basket_*.json``,
``docs/KITE_BASKET_FORMAT.md``). Three things were settled by that test and are enforced here:

* it is **JSON**, an array of order objects — the plan originally assumed CSV, and was wrong;
* ``id`` is **not** required, so it is never generated;
* a basket holds at most **20 orders**, so larger plans are **split** rather than truncated.

**Prices are rounded to the instrument's tick**, which varies by instrument and by exchange — six
distinct ticks across the NSE equity list. An order at ₹1,140.05 on INFY (tick 0.10) is rejected by
the exchange, and nothing upstream would have caught it.

**Real money never auto-trades.** A file the user imports and executes is still the user placing the
order; this makes recommendations *placeable*, never *placed*.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from qalpha.live.instruments import Instrument, to_kite_symbol

#: Kite's own cap, read off the import screen (`Instrument (n / 20)`) — documented nowhere else.
MAX_ORDERS_PER_BASKET = 20

BUY = "BUY"
SELL = "SELL"


@dataclass(frozen=True)
class BasketOrder:
    """One placeable order. ``ticker`` is the engine's form (``INFY.NS``); Kite's has no suffix."""

    ticker: str
    side: str  # BUY | SELL
    quantity: int
    price: Decimal


class UnknownInstrumentError(KeyError):
    """A ticker absent from the cached master — named, never silently dropped from the basket."""


def round_to_tick(price: Decimal, tick: Decimal, side: str) -> Decimal:
    """Round a limit price onto the instrument's tick grid, **toward execution**.

    A buy rounds up and a sell rounds down — the more aggressive side — because these are
    near-market limits meant to fill. At ticks of ₹0.01–₹0.10 on prices in the hundreds the cost is
    under a basis point, while an unfilled harvest order that misses 31 March forfeits the whole
    set-off. Cheap insurance against the failure that actually matters.
    """
    if tick <= 0:
        return price
    rounding = ROUND_CEILING if side == BUY else ROUND_FLOOR
    return (price / tick).quantize(Decimal("1"), rounding=rounding) * tick


def _row(order: BasketOrder, inst: Instrument, weight: int) -> dict[str, object]:
    return {
        "weight": weight,
        "instrument": inst.as_basket_instrument(),
        "params": {
            "transactionType": order.side,
            "product": "CNC",  # delivery — the only product this system ever recommends
            "orderType": "LIMIT",
            "validity": "DAY",
            "validityTTL": 1,
            "quantity": int(order.quantity),
            "price": float(round_to_tick(order.price, inst.tick_size, order.side)),
            "triggerPrice": 0,
            "disclosedQuantity": 0,
            "variety": "regular",
            "gtt": None,
            "tags": [],
        },
    }


def build_baskets(
    orders: Sequence[BasketOrder], instruments: dict[str, Instrument]
) -> list[list[dict[str, object]]]:
    """Orders → one or more baskets, each within Kite's 20-order cap.

    Splitting rather than truncating is the point: a silently dropped order is a plan the user
    believes he placed and did not.
    """
    rows: list[dict[str, object]] = []
    for order in orders:
        symbol = to_kite_symbol(order.ticker)
        inst = instruments.get(symbol)
        if inst is None:
            raise UnknownInstrumentError(
                f"{order.ticker} ({symbol}) is not in the cached Kite instrument master — refresh "
                "it with scripts/refresh_instruments.py rather than placing an incomplete basket."
            )
        rows.append(_row(order, inst, weight=len(rows)))
    return (
        [
            [dict(r, weight=i) for i, r in enumerate(rows[n : n + MAX_ORDERS_PER_BASKET])]
            for n in range(0, max(len(rows), 1), MAX_ORDERS_PER_BASKET)
        ]
        if rows
        else []
    )


def basket_json(orders: Sequence[BasketOrder], instruments: dict[str, Instrument]) -> list[str]:
    """One JSON document per basket, ready to write to disk and import."""
    return [json.dumps(b, separators=(",", ":")) for b in build_baskets(orders, instruments)]


def import_instructions(n_baskets: int) -> str:
    """What the user does with the file — including the one step that silently doubles an order."""
    lines = [
        "**Import into Kite** — Orders → Baskets → **New Basket** → name it → Import basket icon.",
        "",
        "⚠️ **Always a NEW basket.** Importing into an open basket **appends** to it, so importing "
        "the same file twice places **double the quantity** and nothing on screen flags it — the "
        "rows simply look like more orders.",
        "",
        "Basket import is **Kite web only**; there is no import on the mobile app.",
    ]
    if n_baskets > 1:
        lines.insert(
            1,
            f"\nThis plan needs **{n_baskets} baskets** — Kite caps a basket at "
            f"{MAX_ORDERS_PER_BASKET} orders. Import each into its own new basket.\n",
        )
    return "\n".join(lines)
