"""A closed exchange is a closed exchange — not a failed evening, and not a missing price."""

from __future__ import annotations

import sys
from datetime import date, datetime, time
from pathlib import Path

import pytest

from qalpha.live import calendar as nse
from qalpha.live.progress import IST

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


def test_a_weekend_and_a_holiday_are_named() -> None:
    assert nse.closure_reason(date(2026, 9, 13)) == "Sunday"
    assert nse.closure_reason(date(2026, 9, 14)) == "Ganesh Chaturthi"
    assert nse.closure_reason(date(2026, 9, 15)) is None, "a trading day has no known closure"
    assert "Ganesh Chaturthi" in nse.describe(date(2026, 9, 14), traded=False)


def test_the_panel_decides_whether_a_session_happened() -> None:
    """The list names a day; it never asserts one traded. A bar does that."""
    assert "a trading session" in nse.describe(date(2026, 9, 14), traded=True)


class _Book:
    def __init__(self) -> None:
        self.name = "SYSTEM"
        self.manager: dict[str, object] = {}
        self.stepped_through: date | None = None


class _Market:
    def __init__(self, as_of: date) -> None:
        self.as_of = as_of


def _evening(day: date) -> datetime:
    return datetime.combine(day, time(19, 0), IST)


def test_a_closed_exchange_is_not_a_failed_evening(monkeypatch: pytest.MonkeyPatch) -> None:
    import twin as twin_script

    monkeypatch.setattr(twin_script.manager, "fill_pending", lambda *a, **k: [])
    asked: list[str] = []
    monkeypatch.setattr(twin_script.manager, "review", lambda *a, **k: asked.append("asked") or [])
    # Sunday: the market is Friday's close.
    failure = twin_script.step_system(
        _Book(), _Market(date(2026, 9, 11)), now=_evening(date(2026, 9, 13))
    )
    assert failure is None and asked == [], (
        "the model must not be asked about a day that had no close"
    )


def test_a_trading_day_with_no_close_is_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tuesday traded. If the panel has no bar for it, something did not download."""
    import twin as twin_script

    monkeypatch.setattr(twin_script.manager, "fill_pending", lambda *a, **k: [])
    failure = twin_script.step_system(
        _Book(), _Market(date(2026, 9, 11)), now=_evening(date(2026, 9, 15))
    )
    assert failure is not None and "Refresh prices" in failure


def test_the_saved_books_record_what_real_actually_holds(tmp_path, monkeypatch) -> None:
    """books.json said the user's own book held ₹3,04,144 in cash and nothing else.

    REAL was replayed from the tradebook *after* the books were saved, so the marks were right and
    the file was wrong — and anything reading the file (a reconciliation, a page, a later session)
    would have seen an account with no holdings.
    """
    from decimal import Decimal

    import twin as twin_script

    from qalpha.accounting.costs import Side
    from qalpha.config import Config
    from qalpha.live.tradebook import TradebookTrade
    from qalpha.live.twin import REAL, load_books, save_books, seed_books

    trades = [
        TradebookTrade(
            trade_date=date(2026, 6, 15),
            ticker="INFY.NS",
            side=Side.BUY,
            quantity=Decimal("5"),
            price=Decimal("1136"),
        )
    ]
    cfg = Config()
    books = seed_books(trades, cfg)
    monkeypatch.setattr(twin_script, "load_off_market", lambda: [])
    twin_script.replay_real(books[REAL], trades, cfg)
    save_books(books, tmp_path / "books.json")

    reloaded = load_books(cfg, tmp_path / "books.json")[REAL]
    assert reloaded.portfolio.positions() == {"INFY.NS": Decimal("5")}
    assert reloaded.portfolio.cash < Decimal("5680"), "the cash was spent on the shares"
