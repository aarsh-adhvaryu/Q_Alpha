"""The Telegram opportunity scan must rank names the way the dashboard does.

The defect this closes: PR-2's price-continuity guard and PR-3's candidate-health verdict were wired
into the Add-money tab and **not** into ``scripts/scan_alerts.py``, so the daily alert kept ranking
on raw ``adj_close``. On the live watchlist that put a demerger step-down (VEDL, −64.9% raw against
−22.1% re-based) at the top of a message that arrives on a phone under "deploy 50% of your idle
cash". Two surfaces, one book, one day, opposite readings — and the alert was the unguarded one.

As in ``test_price_integrity``, the property under test is **not** "VEDL is dropped". It is that an
artifact must not outrank a genuine decline, and that the alert cannot be more confident than the
screen the user opens after reading it.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from qalpha.data.prices import PriceData

scan_alerts = pytest.importorskip("scan_alerts")

_AS_OF = date(2026, 7, 10)
_N = 400


def _index(n: int = _N) -> pd.DatetimeIndex:
    return pd.bdate_range(end=pd.Timestamp(_AS_OF), periods=n)


def _artifact(n: int = _N) -> list[float]:
    """A flat name that halves overnight and stays flat — a demerger, not a decline."""
    at = n - 60
    return [100.0] * at + [50.0] * (n - at)


def _genuine_decline(n: int = _N) -> list[float]:
    """A real, gradual 30% slide — the kind the strategy is meant to buy."""
    return [100.0 - 30.0 * (i / (n - 1)) for i in range(n)]


def _flat(n: int = _N) -> list[float]:
    return [100.0] * n


def _panel(**series: list[float]) -> PriceData:
    frame = pd.DataFrame(dict(series), index=_index())
    return PriceData(frame, frame.copy(), frame.copy() * 0 + 1000.0)


@pytest.fixture
def _wire(monkeypatch, tmp_path):
    """Point the scan at a synthetic panel; return a setter for the tickers under test."""
    panel_path = tmp_path / "prices.parquet"
    panel_path.write_bytes(b"")  # only its existence is checked
    csv_path = tmp_path / "watchlist.csv"
    monkeypatch.setattr(scan_alerts, "WATCHLIST_PANEL", panel_path)
    monkeypatch.setattr(scan_alerts, "WATCHLIST_CSV", csv_path)

    def _install(prices: PriceData) -> None:
        pd.DataFrame({"ticker": list(prices.adj_close.columns)}).to_csv(csv_path, index=False)
        monkeypatch.setattr("qalpha.data.ingest.load_parquet", lambda _p: prices)

    return _install


def test_an_artifact_does_not_outrank_a_genuine_decline(_wire) -> None:
    """The whole point: a 50% overnight step is not a 50% discount, and must lose to a real 30% fall."""
    _wire(_panel(ARTIFACT=_artifact(), REAL=_genuine_decline(), FLAT=_flat()))
    line = scan_alerts._out_of_favour_names(_AS_OF)
    assert line, "a weak-market alert must still name something"
    assert line.index("REAL") < line.index("ARTIFACT"), line


def test_the_alert_names_what_the_continuity_guard_adjusted(_wire) -> None:
    """Silently re-ranking would be its own defect — the user is told the guard acted."""
    _wire(_panel(ARTIFACT=_artifact(), REAL=_genuine_decline(), FLAT=_flat()))
    line = scan_alerts._out_of_favour_names(_AS_OF)
    assert "Price-continuity guard adjusted" in line
    assert "ARTIFACT" in line


def test_the_alert_agrees_with_the_dashboards_cheapness_scores(_wire) -> None:
    """Same book, same day: the phone and the screen must rank identically (the cross-surface rule)."""
    from qalpha.live.deploy import cheapness_scores
    from qalpha.live.price_integrity import excluded_from_tilt, rebase_starts, unexplained_gaps

    prices = _panel(ARTIFACT=_artifact(), REAL=_genuine_decline(), FLAT=_flat())
    _wire(prices)
    tickers = list(prices.adj_close.columns)
    gaps = unexplained_gaps(prices.adj_close, tickers, _AS_OF)
    dash = cheapness_scores(
        prices, tickers, _AS_OF, rebase_from=rebase_starts(gaps), no_tilt=excluded_from_tilt(gaps)
    )
    top = max(dash, key=lambda t: dash[t])
    line = scan_alerts._out_of_favour_names(_AS_OF)
    assert line.split("(")[0].endswith(top + " "), (line, top)


def test_a_breaking_name_is_flagged_but_never_dropped(_wire) -> None:
    """Flag, not veto — PR-3's rule, asserted so a later 'helpful' filter cannot creep in here."""
    _wire(_panel(REAL=_genuine_decline(), FLAT=_flat(), FLAT2=_flat()))
    line = scan_alerts._out_of_favour_names(_AS_OF)
    assert "REAL" in line
    assert "🔴" in line
    assert "review-for-exit" in line


def test_it_stays_fail_soft_when_the_panel_cannot_be_read(monkeypatch, tmp_path) -> None:
    """A broken panel must cost an alert line, never the cron."""
    monkeypatch.setattr(scan_alerts, "WATCHLIST_PANEL", tmp_path / "missing.parquet")
    monkeypatch.setattr(scan_alerts, "WATCHLIST_CSV", tmp_path / "missing.csv")
    assert scan_alerts._out_of_favour_names(_AS_OF) == ""
