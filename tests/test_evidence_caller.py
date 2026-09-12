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


def _real(monkeypatch: pytest.MonkeyPatch) -> ScreenBasket:
    """The caller against the REAL panel, with a book that has money to spend.

    **The cash is supplied, not read off disk, and that is the point.** These tests guard two
    shipped defects — every candidate built with ``quantity=1``, and the screen run against a
    fabricated ₹1,00,000 — and they used whatever book happened to be saved. On 2026-09-12 ``SYSTEM``
    was reseeded as a mirror of ``REAL``: fully invested, ₹0 idle. The basket came back empty, all
    three tests skipped, and they would have skipped **for ever** while reading as green.

    A test that goes quiet when the data changes is not a test. The panel stays real; only the
    book's cash is a fixture.
    """
    if not PANEL.exists():  # pragma: no cover - the panel is gitignored, refreshed in CI
        pytest.skip("watchlist panel not present")
    from datetime import date

    from qalpha.backtest.portfolio import Portfolio
    from qalpha.live import twin as twin_mod

    cfg = Config()

    def _funded(_cfg: Config, *_a: object, **_k: object) -> dict[str, twin_mod.TwinBook]:
        pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal("100000"))
        return {twin_mod.SYSTEM: twin_mod.TwinBook(name=twin_mod.SYSTEM, portfolio=pf, flows=[])}

    monkeypatch.setattr(twin_mod, "load_books", _funded)
    return _screen_basket(cfg, date(2026, 8, 28))


def test_the_caller_preserves_the_screens_sizing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bug: every candidate was built with `quantity=1`."""
    basket = _real(monkeypatch)
    assert basket.orders, "the book is funded, so the screen must propose something"
    quantities = [o.quantity for o in basket.orders]
    assert all(q > 0 for q in quantities)
    assert set(quantities) != {1}, "every order being one share means the sizing was discarded"


def test_ranks_are_dense_and_ordered(monkeypatch: pytest.MonkeyPatch) -> None:
    basket = _real(monkeypatch)
    assert basket.orders
    assert [o.rank for o in basket.orders] == list(range(len(basket.orders)))


def test_the_basket_is_sized_against_the_books_real_cash(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bug: the screen ran on a fabricated ₹1,00,000 and an empty portfolio."""
    basket = _real(monkeypatch)
    assert basket.orders
    spent = sum((o.value for o in basket.orders), Decimal("0"))
    assert spent <= basket.cash, "the screen cannot propose more than the book actually holds"
    assert basket.cash > 0


def test_prices_are_read_not_defaulted(monkeypatch: pytest.MonkeyPatch) -> None:
    basket = _real(monkeypatch)
    assert all(p > 0 for p in basket.prices.values()), "a zero price is a missing price"


def test_the_anchor_is_priced_so_leftover_cash_has_somewhere_to_go(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qalpha.live.pipeline import ANCHOR_TICKER

    basket = _real(monkeypatch)
    if not basket.prices:
        pytest.skip("no marks")
    assert ANCHOR_TICKER in basket.prices
