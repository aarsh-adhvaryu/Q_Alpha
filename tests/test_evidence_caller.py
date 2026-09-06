"""The production caller — the thing that was untested while the function it calls was not.

``propose()`` had eleven tests and every one passed while the scheduled caller fed it
**alphabetically ordered one-share candidates** priced from a fabricated budget. The tests supplied
correct inputs; nothing checked what the cron supplied. That is the integration-defect class this
repo keeps producing, and the golden-day replay did not catch it because I wrote the replay to hand
`propose` good data too.

These tests exercise the caller.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, "scripts")

from evidence import ScreenBasket, _screen_basket

from qalpha.config import Config
from qalpha.live.pipeline import ProposedOrder

PANEL = Path("data/historical/prices_watchlist.parquet")


def _basket(orders: list[ProposedOrder], held: list[str]) -> ScreenBasket:
    return ScreenBasket(orders, held, Decimal("1000"), {}, {})


# --- the ordering contract, which needs no data -----------------------------------------------


def test_tickers_follow_the_screen_ranking_not_the_alphabet() -> None:
    """The bug in one assertion: `sorted()` would return AAA first."""
    orders = [
        ProposedOrder("ZZZ.NS", 10, Decimal("100"), rank=0),
        ProposedOrder("MMM.NS", 5, Decimal("200"), rank=1),
        ProposedOrder("AAA.NS", 3, Decimal("300"), rank=2),
    ]
    assert _basket(orders, []).tickers == ["ZZZ.NS", "MMM.NS", "AAA.NS"]


def test_held_names_come_after_the_screen_picks_and_never_displace_them() -> None:
    orders = [ProposedOrder("ZZZ.NS", 10, Decimal("100"), rank=0)]
    assert _basket(orders, ["AAA.NS", "BBB.NS"]).tickers == ["ZZZ.NS", "AAA.NS", "BBB.NS"]


def test_a_name_both_screened_and_held_appears_once_at_its_screen_rank() -> None:
    orders = [
        ProposedOrder("ZZZ.NS", 10, Decimal("100"), rank=0),
        ProposedOrder("AAA.NS", 1, Decimal("100"), rank=1),
    ]
    out = _basket(orders, ["AAA.NS", "BBB.NS"]).tickers
    assert out == ["ZZZ.NS", "AAA.NS", "BBB.NS"] and out.count("AAA.NS") == 1


# --- what the caller actually builds, against the real panel -------------------------------------


def _real() -> ScreenBasket:
    if not PANEL.exists():  # pragma: no cover - the panel is gitignored, refreshed in CI
        pytest.skip("watchlist panel not present")
    from datetime import date

    return _screen_basket(Config(), date(2026, 8, 28))


def test_the_caller_preserves_the_screens_sizing() -> None:
    """The bug: every candidate was built with `quantity=1`."""
    basket = _real()
    if not basket.orders:
        pytest.skip("no screen basket (no book or no idle cash)")
    quantities = [o.quantity for o in basket.orders]
    assert all(q > 0 for q in quantities)
    assert set(quantities) != {1}, "every order being one share means the sizing was discarded"


def test_ranks_are_dense_and_ordered() -> None:
    basket = _real()
    if not basket.orders:
        pytest.skip("no screen basket")
    assert [o.rank for o in basket.orders] == list(range(len(basket.orders)))


def test_the_basket_is_sized_against_the_books_real_cash() -> None:
    """The bug: the screen ran on a fabricated ₹1,00,000 and an empty portfolio."""
    basket = _real()
    if not basket.orders:
        pytest.skip("no screen basket")
    spent = sum((o.value for o in basket.orders), Decimal("0"))
    assert spent <= basket.cash, "the screen cannot propose more than the book actually holds"
    assert basket.cash > 0


def test_prices_are_read_not_defaulted() -> None:
    basket = _real()
    assert all(p > 0 for p in basket.prices.values()), "a zero price is a missing price"


def test_the_anchor_is_priced_so_leftover_cash_has_somewhere_to_go() -> None:
    from qalpha.live.pipeline import ANCHOR_TICKER

    basket = _real()
    if not basket.prices:
        pytest.skip("no marks")
    assert ANCHOR_TICKER in basket.prices
