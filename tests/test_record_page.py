"""The record page reads; it does not invent.

Every figure on a display surface in this repository has, at some point, been computed on that
surface and been wrong. This page is allowed one piece of arithmetic — quantity × mark — and these
tests pin that it does not quietly acquire more.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from qalpha.live import record


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A minimal on-disk world: two books over two days, one holding, one price panel."""
    (tmp_path / "twin").mkdir()
    history = tmp_path / "twin" / "history.jsonl"
    rows = [
        {"as_of": "2026-09-14", "books": {"SYSTEM": {"value": "100", "net_invested": "100"}}},
        # A re-run on the same day supersedes the first row rather than adding a second point.
        {"as_of": "2026-09-14", "books": {"SYSTEM": {"value": "101", "net_invested": "100"}}},
        {"as_of": "2026-09-15", "books": {"SYSTEM": {"value": "103", "net_invested": "100"}}},
    ]
    history.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")

    books = tmp_path / "twin" / "books.json"
    books.write_text(
        json.dumps(
            {
                "books": {
                    "SYSTEM": {
                        "portfolio": {
                            "cash": "0",
                            "lots": [
                                {"ticker": "A.NS", "quantity_remaining": "10", "buy_price": "50"},
                                {"ticker": "A.NS", "quantity_remaining": "10", "buy_price": "70"},
                                {"ticker": "GONE.NS", "quantity_remaining": "5", "buy_price": "9"},
                            ],
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    panel = tmp_path / "panel.parquet"
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-09-11", "2026-09-14"]),
            "ticker": ["A.NS", "A.NS"],
            "close": [55.0, 66.0],
            "adj_close": [55.0, 66.0],
            "volume": [1, 1],
        }
    ).to_parquet(panel)
    watch = tmp_path / "watch.csv"
    watch.write_text("ticker,sector\nA.NS,IT\n", encoding="utf-8")

    monkeypatch.setattr(record, "HISTORY", history)
    monkeypatch.setattr(record, "BOOKS", books)
    monkeypatch.setattr(record, "EQUITY", tmp_path / "absent.csv")
    monkeypatch.setattr(record, "WATCHLIST", watch)
    monkeypatch.setattr(record, "COVERAGE", tmp_path / "absent.jsonl")
    monkeypatch.setattr("qalpha.live.panels.BOOK_PANEL", panel)
    monkeypatch.setattr("qalpha.live.panels.SCREEN_PANEL", tmp_path / "absent.parquet")
    return tmp_path


def test_a_rerun_on_the_same_day_is_one_observation_not_two(repo: Path) -> None:
    data = record.dashboard_data(date(2026, 9, 15))
    points = data["series"]["SYSTEM"]
    assert [p["date"] for p in points] == ["2026-09-14", "2026-09-15"]
    assert points[0]["value"] == 101.0, "the later revision of a day must win"


def test_lots_are_merged_at_their_weighted_cost(repo: Path) -> None:
    held = {h["ticker"]: h for h in record.dashboard_data(date(2026, 9, 15))["holdings"]}
    assert held["A"]["quantity"] == 20
    assert held["A"]["cost"] == pytest.approx(60.0)


def test_the_mark_is_the_panels_last_close_and_value_is_the_only_arithmetic(repo: Path) -> None:
    held = {h["ticker"]: h for h in record.dashboard_data(date(2026, 9, 15))["holdings"]}
    assert held["A"]["mark"] == 66.0
    assert held["A"]["value"] == pytest.approx(20 * 66.0)
    assert held["A"]["pnl"] == pytest.approx(20 * 66.0 - 20 * 60.0)


def test_an_unpriced_holding_is_unpriced_not_zero(repo: Path) -> None:
    """Unknown is never substituted. A name no panel carries has no value, not a value of ₹0."""
    data = record.dashboard_data(date(2026, 9, 15))
    gone = next(h for h in data["holdings"] if h["ticker"] == "GONE")
    assert gone["mark"] is None and gone["value"] is None and gone["pnl"] is None
    assert "unpriced, not zero" in record.dashboard_html(date(2026, 9, 15))


def test_a_sparse_series_is_labelled_as_sparse(repo: Path) -> None:
    """Two dots joined read as a trend. The page must say how many observations there are."""
    page = record.dashboard_html(date(2026, 9, 15))
    assert "2 observations" in page
    assert record.MIN_FOR_A_LINE >= 3


def test_the_banner_says_whether_system_is_deciding_yet(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qalpha.live import twin

    start = date(2026, 9, 14)
    monkeypatch.setattr(record, "EVALUATION_START", start)
    monkeypatch.setattr(record, "is_autonomous", lambda d: twin.is_autonomous(d, start=start))
    assert "starts deciding" in record.dashboard_html(date(2026, 9, 13))
    assert "deciding for itself" in record.dashboard_html(date(2026, 9, 15))


def test_with_no_registered_start_the_banner_counts_down_to_nothing(repo: Path) -> None:
    """No start date is registered. The page must say so, not print a countdown to ``None``."""
    banner = record._banner(record.dashboard_data(date(2026, 9, 15)))
    assert "SYSTEM is not deciding" in banner
    assert "starts deciding" not in banner and "deciding for itself" not in banner
    assert "None" not in banner
    assert "SYSTEM is not deciding" in record.dashboard_html(date(2026, 9, 15))


def test_inlined_data_cannot_close_its_own_script_tag(repo: Path, tmp_path: Path) -> None:
    """A '</' inside the JSON would end the <script> block and the charts would silently vanish."""
    page = record.dashboard_html(date(2026, 9, 15))
    blob = page.split("window.__QALPHA__ = ", 1)[1].split("</script>", 1)[0]
    assert "</" not in blob
    json.loads(blob.rstrip().rstrip(";").replace("<\\/", "</"))


def test_the_page_loads_nothing_from_the_network(repo: Path) -> None:
    """Served from 127.0.0.1 and meant to work unplugged: no CDN, no remote script or font."""
    page = record.dashboard_html(date(2026, 9, 15))
    assert "http://" not in page.replace("http://www.w3.org/2000/svg", "")
    assert "https://" not in page


def test_a_one_day_collapse_that_reverses_is_flagged_not_trusted(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The committed curve holds 2026-08-28 at -39% between two ordinary days. A line through it
    teaches the eye a crash that did not happen; the record is left as written but flagged."""
    equity = repo / "equity.csv"
    equity.write_text(
        "date,equity,cash,return_pct\n"
        "2026-08-27,199131.68,7335.38,-0.43\n"
        "2026-08-28,121519.03,7335.38,-39.24\n"
        "2026-09-01,198155.48,7335.38,-0.92\n"
        "2026-09-02,197147.28,7335.38,-1.43\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(record, "EQUITY", equity)
    data = record.dashboard_data(date(2026, 9, 15))
    flagged = [p["date"] for p in data["equity"] if p.get("suspect")]
    assert flagged == ["2026-08-28"]
    assert "suspect mark" in record.dashboard_html(date(2026, 9, 15))


def test_an_ordinary_fall_is_not_flagged(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The flag must not become a way to hide real losses: a fall that does not reverse stands."""
    equity = repo / "equity.csv"
    equity.write_text(
        "date,equity,cash,return_pct\n"
        "2026-08-27,200000,0,0\n2026-08-28,150000,0,-25\n2026-09-01,149000,0,-25.5\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(record, "EQUITY", equity)
    assert not [p for p in record.dashboard_data(date(2026, 9, 15))["equity"] if p.get("suspect")]
