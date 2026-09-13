"""The refresh must reach every panel the evening reads.

The **Refresh** button once rebuilt one panel while the page read another, so pressing it could never
clear the staleness it existed to clear. Two spellings of "the prices" is one bug waiting; these
tests assert the panel names, the refresh and the readers agree.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from qalpha.live import daily, panels

ROOT = Path(__file__).resolve().parent.parent


# --- the coupling ---------------------------------------------------------------------------------
def test_the_watchlist_panel_is_one_the_refresh_writes() -> None:
    """The investor's whole world is this panel; nothing may leave it unrefreshed."""
    refreshed = {panel for panel, _universe in panels.refresh_targets()}
    assert panels.WATCHLIST_PANEL in refreshed, (
        "the watchlist panel holds every name the investor reads about and nothing refreshes it"
    )


def test_the_watchlist_panel_is_refreshed_first() -> None:
    """If a refresh stops early, the file the investor reads must be the one already done."""
    order = [panel for panel, _ in panels.refresh_targets()]
    assert order.index(panels.WATCHLIST_PANEL) < order.index(panels.NIFTY50_PANEL)


def test_every_refresh_target_is_paired_with_its_own_universe() -> None:
    """A panel rebuilt from the wrong ticker list is the same defect one level down."""
    pairs = dict(panels.refresh_targets())
    assert pairs[panels.WATCHLIST_PANEL] == panels.WATCHLIST_UNIVERSE
    assert pairs[panels.NIFTY50_PANEL] == panels.NIFTY50_UNIVERSE
    assert panels.WATCHLIST_UNIVERSE != panels.NIFTY50_UNIVERSE, (
        "these are different universes — the watchlist vs point-in-time Nifty-50 membership"
    )


def test_the_two_panels_are_not_the_same_file() -> None:
    assert panels.WATCHLIST_PANEL != panels.NIFTY50_PANEL


# --- nobody writes these paths out by hand any more --------------------------------------------
def test_the_live_decision_path_names_no_panel_as_a_literal() -> None:
    """One definition, or two that drift. The drift was the bug.

    Every live module and every entry point.
    """
    live = ROOT / "src/qalpha/live"
    watched = [*sorted((ROOT / "scripts").glob("*.py")), *sorted(live.glob("*.py"))]
    offenders: list[str] = []
    for path in watched:
        if path.name == "panels.py":
            continue
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if ".parquet" not in line or "#" in line.split(".parquet")[0][-90:]:
                continue
            if "data/historical" in line:
                offenders.append(f"{path.name}: {line.strip()}")
    assert not offenders, (
        "these name a panel directly instead of importing it from qalpha.live.panels:\n"
        + "\n".join(offenders)
    )


def test_the_refresh_step_actually_walks_the_targets() -> None:
    """A constant nothing reads is a comment. This is the step that has to read it."""
    src = inspect.getsource(daily._step_prices)
    assert "refresh_targets" in src


def test_a_missing_universe_fails_the_step_rather_than_skipping_it(monkeypatch) -> None:
    """Silently not refreshing a panel is precisely how this shipped. It must be loud.

    The step raising means `run_pipeline` records `failed` and the page says so, rather than the
    ledger recording a refresh that did not happen.
    """
    import pytest

    missing = Path("data/universes/definitely-not-here.csv")
    monkeypatch.setattr(panels, "refresh_targets", lambda: ((panels.WATCHLIST_PANEL, missing),))
    monkeypatch.setattr(daily, "_universe_tickers", lambda p: [])
    with pytest.raises(RuntimeError, match="was NOT refreshed"):
        daily._step_prices()


# --- the files on disk ------------------------------------------------------------------------
def test_the_universes_named_here_exist_in_this_checkout() -> None:
    """These are committed CSVs. A typo'd path would disable a refresh with no error until run."""
    for _panel, universe in panels.refresh_targets():
        assert (ROOT / universe).exists(), f"{universe} is named as a universe and is not there"


def test_the_watchlist_universe_has_a_ticker_column_the_reader_can_use() -> None:
    tickers = daily._universe_tickers(ROOT / panels.WATCHLIST_UNIVERSE)
    assert len(tickers) > 50, "the watchlist should carry the full Nifty-100 universe"
    assert all(t.endswith(".NS") for t in tickers[:10])
