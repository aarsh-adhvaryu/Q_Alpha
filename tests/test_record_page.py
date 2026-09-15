"""The record page reads; it does not invent.

Every figure on a display surface in this repository has, at some point, been computed on that
surface and been wrong. This page is allowed one piece of arithmetic — quantity × mark — and these
tests pin that it does not quietly acquire more.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

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
    monkeypatch.setattr(record, "WATCHLIST", watch)
    monkeypatch.setattr("qalpha.live.evidence_log.COVERAGE_LOG", tmp_path / "absent.jsonl")
    monkeypatch.setattr("qalpha.live.panels.NIFTY50_PANEL", panel)
    monkeypatch.setattr("qalpha.live.panels.WATCHLIST_PANEL", tmp_path / "absent.parquet")
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


def test_the_banner_follows_the_session_not_the_calendar(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SYSTEM is stepped on the day its prices come from, so the banner must key on that day.

    Keyed on the calendar instead, the page announced "deciding for itself" on the morning of a
    closed exchange while the book was still mirroring REAL — the start date wearing the wrong
    date's label, which is the defect this repository keeps paying for.
    """
    from qalpha.live import twin

    start = date(2026, 9, 15)
    monkeypatch.setattr(record, "EVALUATION_START", start)
    monkeypatch.setattr(record, "is_autonomous", lambda d: twin.is_autonomous(d, start=start))

    # The fixture's last marked session is 2026-09-15. Rendered on a later calendar day, or on the
    # day itself, the banner must say the same thing — the session is what moved, not the clock.
    assert "deciding for itself" in record.dashboard_html(date(2026, 9, 15))
    assert "deciding for itself" in record.dashboard_html(date(2026, 9, 20))

    # With the start one day beyond the last session, no calendar date may claim it has begun.
    monkeypatch.setattr(record, "EVALUATION_START", date(2026, 9, 16))
    monkeypatch.setattr(
        record, "is_autonomous", lambda d: twin.is_autonomous(d, start=date(2026, 9, 16))
    )
    page = record.dashboard_html(date(2026, 9, 20))
    assert "starts deciding" in page
    assert "deciding for itself" not in page


def test_with_no_registered_start_the_banner_counts_down_to_nothing(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A book with no registered start must say so, not print a countdown to ``None``."""
    monkeypatch.setattr(record, "EVALUATION_START", None)
    monkeypatch.setattr(record, "is_autonomous", lambda d: False)
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


def test_filings_count_as_read_only_when_the_corpus_reader_read_them(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """'Read' must mean *this* corpus read it — not another model, not a row with no reader."""
    from qalpha.live.extraction import EXTRACTION_VERSION, corpus_reader

    def coverage(reader: str | None) -> list[dict[str, Any]]:
        row: dict[str, object] = {
            "as_of": "2026-09-14",
            "ticker": "A.NS",
            "complete": True,
            "extraction_version": EXTRACTION_VERSION,
            "documents_read": 3,
            "filings_in_window": 3,
        }
        if reader is not None:
            row["reader"] = reader
        path = tmp_path / "cov.jsonl"
        path.write_text(json.dumps(row) + "\n", encoding="utf-8")
        monkeypatch.setattr("qalpha.live.evidence_log.COVERAGE_LOG", path)
        rows: list[dict[str, Any]] = record.dashboard_data(date(2026, 9, 15))["coverage"]
        return rows

    assert coverage(corpus_reader())[0]["opened"] is True
    assert coverage("qwen3-8b-32k")[0]["opened"] is False
    assert coverage(None)[0]["opened"] is False, (
        "a row with no reader says nothing about who read it"
    )


def test_a_book_holding_cash_says_so_beside_its_value(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Value alone cannot tell a lead that was chosen from a lead that is only unspent money.

    SYSTEM may buy ₹50,000 a month; the baselines buy the fund with every rupee the day it arrives.
    In a falling market that difference alone puts SYSTEM ahead, and the page must not let that read
    as skill.
    """
    (repo / "twin" / "history.jsonl").write_text(
        json.dumps(
            {
                "as_of": "2026-09-15",
                "books": {
                    "SYSTEM": {"value": "500", "net_invested": "500", "cash": "200"},
                    "BASELINE_EW": {"value": "480", "net_invested": "500", "cash": "0"},
                },
            }
        ),
        encoding="utf-8",
    )
    page = record.dashboard_html(date(2026, 9, 15))
    table = page.split("<h2>The four books</h2>", 1)[1].split("</div>", 1)[0]
    assert "Cash" in page and "In the market" in page
    assert "₹200" in page, "SYSTEM's uninvested cash must be on the page"
    assert "no cash" in page, "the page must say the baselines hold none"
    assert table is not None


def test_a_history_row_written_before_cash_was_recorded_is_unknown_not_zero(repo: Path) -> None:
    """The rows already on file carry no cash field. Printing ₹0 would claim they were fully
    invested, which is the substitution this repository keeps paying for."""
    page = record.dashboard_html(date(2026, 9, 15))
    assert "not recorded" in page
    assert "₹0" not in page.split("<h2>The four books</h2>", 1)[1][:2000]


def test_a_day_change_never_spans_a_missing_session(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B has no close on the panel's middle session: its change is unknown, not a two-day move."""
    panel = repo / "gappy.parquet"
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-09-10", "2026-09-11", "2026-09-14"] * 2),
            "ticker": ["A.NS"] * 3 + ["B.NS"] * 3,
            "close": [50.0, 55.0, 66.0, 10.0, float("nan"), 12.0],
            "adj_close": [50.0, 55.0, 66.0, 10.0, float("nan"), 12.0],
            "volume": [1] * 6,
        }
    ).to_parquet(panel)
    closes = record._panel_closes(panel)
    assert closes["A.NS"] == (66.0, 55.0, "2026-09-14")
    assert closes["B.NS"] == (12.0, None, "2026-09-14")


def test_the_page_names_the_close_its_holdings_are_marked_at(repo: Path) -> None:
    page = record.dashboard_html(date(2026, 9, 15))
    assert "close of 2026-09-14" in page


def test_no_section_shares_an_id_with_a_tab_link(repo: Path) -> None:
    """A section whose id equals the link's hash makes the browser scroll to it on every click."""
    import re

    page = record.dashboard_html(date(2026, 9, 15))
    links = set(re.findall(r'<a href="#([a-z]+)"', page))
    ids = set(re.findall(r'id="([a-z-]+)"', page))
    assert links and not links & ids
    assert {f"tab-{name}" for name in links} <= ids


def test_the_investor_never_reads_the_page() -> None:
    """The page may change during a frozen month only because nothing that decides imports it."""
    import ast

    root = Path(__file__).resolve().parents[1] / "src" / "qalpha" / "live"
    for name in ("agent", "manager", "sizing", "tools", "attention", "evidence_log", "mandate"):
        tree = ast.parse((root / f"{name}.py").read_text(encoding="utf-8"))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import | ast.ImportFrom)
            for alias in node.names
        } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        assert not any("record" in i for i in imported), f"{name} imports the page"
