"""``desk.gather`` against a real price panel on disk.

:mod:`tests.test_desk` drives ``assemble`` with prepared inputs. That is the shape of test this
repo has been burned by: eleven of them passed while the caller fed the screen garbage. ``gather``
is the caller — it opens the files, decides what a missing one means, and fills the gaps — so it
gets its own tests with actual parquet on actual disk.

The specific bug these pin: a watchlist row rendered **"unpriced"** while the panel it was ranked
from held a perfectly good close. "We could not price this" and "we did not ask" are different
facts, and only one of them is a warning.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("pandas")

import pandas as pd

from qalpha.live.buygate import MAX_PRICE_AGE_DAYS
from qalpha.live.desk import UNREADABLE, gather

AS_OF = date(2026, 9, 10)


def _panel(tmp_path: Path, series: dict[str, list[float]], *, days: int = 400) -> str:
    """A long-format panel of `days` business days ending at AS_OF, one column per name."""
    idx = pd.bdate_range(end=pd.Timestamp(AS_OF), periods=days)
    rows = []
    for ticker, tail in series.items():
        values = [tail[0]] * (days - len(tail)) + tail
        for when, value in zip(idx, values, strict=True):
            rows.append(
                {
                    "date": when,
                    "ticker": ticker,
                    "close": value,
                    "adj_close": value,
                    "volume": 1000,
                }
            )
    path = tmp_path / "panel.parquet"
    pd.DataFrame(rows).to_parquet(path)
    return str(path)


def test_a_watchlist_row_is_priced_from_the_panel_rather_than_called_unpriced(
    tmp_path: Path,
) -> None:
    """THE ONE THIS FILE EXISTS FOR. Nobody asked the broker; the close was on disk all along."""
    panel = _panel(tmp_path, {"INFY.NS": [1100.0, 1144.0]})
    desk = gather(
        as_of=AS_OF,
        positions={},
        prices={},
        cost_basis={},
        watchlist=["INFY.NS"],
        panel_path=panel,
    )
    row = next(r for r in desk.rows if r.ticker == "INFY.NS")
    assert row.mark == Decimal("1144.0")
    assert row.watching is True
    # It is a price, not a P&L: there is no cost basis for something that was never bought.
    assert row.unrealised is None


def test_a_supplied_mark_is_never_overwritten_by_the_panel(tmp_path: Path) -> None:
    """The broker's number wins where there is one. The panel only fills gaps."""
    panel = _panel(tmp_path, {"INFY.NS": [1100.0, 1144.0]})
    desk = gather(
        as_of=AS_OF,
        positions={"INFY.NS": 10},
        prices={"INFY.NS": Decimal("1200")},
        cost_basis={"INFY.NS": Decimal("1000")},
        panel_path=panel,
    )
    row = next(r for r in desk.rows if r.ticker == "INFY.NS")
    assert row.mark == Decimal("1200")
    assert row.unrealised == Decimal("2000")


def test_a_column_that_stopped_printing_is_left_unpriced(tmp_path: Path) -> None:
    """A fresh panel can carry a stale column. That old close is not what it is worth today."""
    idx = pd.bdate_range(end=pd.Timestamp(AS_OF), periods=200)
    rows = []
    for when in idx:
        rows.append(
            {"date": when, "ticker": "LIVE.NS", "close": 100.0, "adj_close": 100.0, "volume": 1}
        )
        # DEAD stops printing well before the panel's own last day.
        if when.date() <= AS_OF - timedelta(days=MAX_PRICE_AGE_DAYS + 30):
            rows.append(
                {"date": when, "ticker": "DEAD.NS", "close": 50.0, "adj_close": 50.0, "volume": 1}
            )
    path = tmp_path / "p.parquet"
    pd.DataFrame(rows).to_parquet(path)

    desk = gather(
        as_of=AS_OF,
        positions={},
        prices={},
        cost_basis={},
        watchlist=["LIVE.NS", "DEAD.NS"],
        panel_path=str(path),
    )
    marks = {r.ticker: r.mark for r in desk.rows}
    assert marks["LIVE.NS"] == Decimal("100.0")
    assert marks["DEAD.NS"] is None, "a seven-week-old print must not be shown as today's worth"


def test_a_name_absent_from_the_panel_reads_unreadable_and_is_named(tmp_path: Path) -> None:
    panel = _panel(tmp_path, {"INFY.NS": [1100.0, 1144.0]})
    desk = gather(
        as_of=AS_OF,
        positions={},
        prices={},
        cost_basis={},
        watchlist=["INFY.NS", "NOSUCH.NS"],
        panel_path=panel,
    )
    row = next(r for r in desk.rows if r.ticker == "NOSUCH.NS")
    assert row.mark is None
    assert row.health == UNREADABLE
    assert any("NOSUCH" in n for n in desk.notes)
    assert any("not 'healthy'" in n for n in desk.notes)


def test_a_missing_panel_degrades_one_column_and_says_so(tmp_path: Path) -> None:
    """One unreadable file must cost one column, not the page — and must never be silent."""
    desk = gather(
        as_of=AS_OF,
        positions={"VBL.NS": 147},
        prices={"VBL.NS": Decimal("420")},
        cost_basis={"VBL.NS": Decimal("400")},
        panel_path=str(tmp_path / "does-not-exist.parquet"),
    )
    row = next(r for r in desk.rows if r.ticker == "VBL.NS")
    assert row.health == UNREADABLE
    assert row.mark == Decimal("420"), "the broker's mark survives the panel being gone"
    assert row.unrealised == Decimal("2940")
    assert any("rather than healthy" in n for n in desk.notes)


def test_no_surveillance_file_leaves_every_name_unknown_and_says_it_is_not_clear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qalpha.live import flags

    monkeypatch.setattr(flags, "load_archive", lambda *a, **k: ({}, None))
    desk = gather(
        as_of=AS_OF,
        positions={"VBL.NS": 147},
        prices={"VBL.NS": Decimal("420")},
        cost_basis={},
        panel_path=str(tmp_path / "none.parquet"),
    )
    assert all(r.exchange == "UNKNOWN" for r in desk.rows)
    assert any("which is not CLEAR" in n for n in desk.notes)
