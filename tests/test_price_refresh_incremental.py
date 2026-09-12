"""The daily refresh must be incremental WITHOUT inventing a price gap.

The evening was re-downloading fourteen years of history for every name on every double-click. The
fix is to fetch from the last stored bar — and the reason that is not a one-liner is `adj_close`:
it is **retroactive**. A split rewrites every prior bar, so merging new rows onto unrewritten
history leaves a permanent step exactly where old meets new, and `cheapness_scores` reads a step as
a discount from the 1-year high. That is PR-2's defect, which put two price artifacts at the top of
a real ₹1,00,000 recommendation.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from qalpha.live import daily


def _long(ticker: str, dates: pd.DatetimeIndex, adj: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": dates,
            "ticker": ticker,
            "close": adj,
            "adj_close": adj,
            "volume": 1000,
        }
    )


def test_only_the_missing_days_are_fetched(tmp_path: Path) -> None:
    panel = tmp_path / "p.parquet"
    dates = pd.bdate_range("2024-01-01", periods=40)
    _long("A.NS", dates, 100.0).to_parquet(panel)

    start, stored = daily._fetch_window(panel)
    assert stored is not None and not stored.empty
    assert pd.Timestamp(start) > dates[0], "the refresh still starts at the beginning of history"
    assert pd.Timestamp(start) <= dates[-1], "the overlap must reach back into stored data"


def test_a_missing_panel_is_still_built_from_scratch(tmp_path: Path) -> None:
    start, stored = daily._fetch_window(tmp_path / "absent.parquet")
    assert start == daily._FULL_START
    assert stored is None


def test_an_unreadable_panel_is_rebuilt_not_patched(tmp_path: Path) -> None:
    bad = tmp_path / "bad.parquet"
    bad.write_bytes(b"not a parquet file")
    start, stored = daily._fetch_window(bad)
    assert start == daily._FULL_START and stored is None


def test_new_bars_are_appended_and_history_is_kept(tmp_path: Path) -> None:
    # Deliberately NON-overlapping: overlapping days at a different price is a re-adjustment,
    # which is a different test (below) and would correctly trigger a full re-read.
    old = _long("A.NS", pd.bdate_range("2024-01-01", periods=20), 100.0)
    new = _long("A.NS", pd.bdate_range("2024-01-29", periods=5), 101.0)
    merged = daily._merge_panel(old, new, tmp_path / "p.parquet")
    assert len(merged) == 25
    assert merged["date"].min() == old["date"].min(), "history was dropped"
    assert merged["date"].max() == new["date"].max(), "the new bars did not land"


def test_overlapping_days_take_the_fresh_value(tmp_path: Path) -> None:
    dates = pd.bdate_range("2024-01-01", periods=10)
    old = _long("A.NS", dates, 100.0)
    new = _long("A.NS", dates[-3:], 100.0)
    new.loc[:, "volume"] = 5555  # a late correction to an already-stored day
    merged = daily._merge_panel(old, new, tmp_path / "p.parquet")
    assert len(merged) == 10, "the overlap duplicated rows instead of replacing them"
    assert set(merged.tail(3)["volume"]) == {5555}


def test_a_retroactive_split_forces_a_full_reread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE ONE THAT MATTERS. Disagreeing overlap means the past was rewritten.

    Without this the panel would carry pre-split history spliced onto post-split bars — a step the
    screen reads as a 50% discount, on exactly the names it is most eager to buy.
    """
    dates = pd.bdate_range("2024-01-01", periods=20)
    old = _long("A.NS", dates, 100.0)
    # yfinance now reports the whole series halved: a 2-for-1 split.
    rewritten = _long("A.NS", dates[-5:], 50.0)

    called: list[tuple[list[str], str]] = []

    def fake_download(tickers: list[str], start: str, end: str | None = None) -> pd.DataFrame:
        called.append((tickers, start))
        return _long("A.NS", dates, 50.0)

    monkeypatch.setattr("qalpha.data.ingest.download_prices", fake_download)
    merged = daily._merge_panel(old, rewritten, tmp_path / "p.parquet")

    assert called, "the re-adjustment was not detected — stale history would have been spliced on"
    assert called[0][1] == daily._FULL_START, "a re-adjusted name must be re-read in full"
    assert set(merged["adj_close"]) == {50.0}, (
        "the panel still mixes pre- and post-adjustment prices, which reads as a price gap"
    )


def test_names_whose_index_spell_ended_are_not_re_requested(tmp_path: Path) -> None:
    """CAIRN, STER, HDFC, IDFC printed 'possibly delisted' on every single double-click."""
    universe = tmp_path / "u.csv"
    universe.write_text(
        "ticker,start_date,end_date,sector\n"
        "LIVE.NS,2012-01-01,,IT\n"
        "GONE.NS,2012-01-01,2017-09-28,CEMENT\n",
        encoding="utf-8",
    )
    kept = daily._still_listed(universe, ["LIVE.NS", "GONE.NS"])
    assert kept == ["LIVE.NS"]


def test_a_universe_without_end_dates_keeps_every_name(tmp_path: Path) -> None:
    """The watchlist has no dates, so nothing there says a name stopped trading."""
    universe = tmp_path / "w.csv"
    universe.write_text("ticker,sector\nA.NS,IT\nB.NS,FIN\n", encoding="utf-8")
    assert daily._still_listed(universe, ["A.NS", "B.NS"]) == ["A.NS", "B.NS"]


def test_a_malformed_universe_never_silently_stops_the_refresh(tmp_path: Path) -> None:
    """Returning [] here would turn the price refresh off while reporting success."""
    universe = tmp_path / "empty.csv"
    universe.write_text("ticker,start_date,end_date,sector\n", encoding="utf-8")
    assert daily._still_listed(universe, ["A.NS"]) == ["A.NS"]
    assert daily._still_listed(tmp_path / "missing.csv", ["A.NS"]) == ["A.NS"]
