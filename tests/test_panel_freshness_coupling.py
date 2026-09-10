"""The refresh must reach the panel the gate checks.

### The bug

The **Refresh market data** button could not fix the staleness it exists to fix.

```
prices_pit_2026.parquet     last=2026-09-10   ← what the refresh wrote
prices_watchlist.parquet    last=2026-08-28   ← what the screen reads and the gate checks
```

Nothing was broken in either file. `paper._refresh_prices()` rebuilds the paper book's panel from
the Nifty-50 membership list; the screen ranks from a different panel built from the 96-name
watchlist, and nothing refreshed that one. So the gate reported *"prices are 13 days old"* and went
on reporting it however many times the button was pressed.

An earlier fix in this repo made the freshness check follow the panel the decision is actually made
from. This is its other half, and it is the same lesson: **two spellings of "the prices" is one bug
waiting.** These tests assert the two halves agree, so the next person to add a panel cannot leave
it unrefreshed without a red test.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from qalpha.live import daily, panels

ROOT = Path(__file__).resolve().parent.parent


# --- the coupling ---------------------------------------------------------------------------------
def test_the_panel_the_gate_checks_is_one_the_refresh_writes() -> None:
    """THE ONE THIS FILE EXISTS FOR."""
    refreshed = {panel for panel, _universe in panels.refresh_targets()}
    assert panels.SCREEN_PANEL in refreshed, (
        "the screen's panel gates every buy and nothing refreshes it — pressing Refresh cannot "
        "clear a staleness block"
    )


def test_the_screen_panel_is_refreshed_before_the_book_panel() -> None:
    """If a refresh stops early, the file a decision rests on must be the one already done."""
    order = [panel for panel, _ in panels.refresh_targets()]
    assert order.index(panels.SCREEN_PANEL) < order.index(panels.BOOK_PANEL)


def test_every_refresh_target_is_paired_with_its_own_universe() -> None:
    """A panel rebuilt from the wrong ticker list is the same defect one level down."""
    pairs = dict(panels.refresh_targets())
    assert pairs[panels.SCREEN_PANEL] == panels.SCREEN_UNIVERSE
    assert pairs[panels.BOOK_PANEL] == panels.BOOK_UNIVERSE
    assert panels.SCREEN_UNIVERSE != panels.BOOK_UNIVERSE, (
        "these are different universes — 96 watchlist names vs the Nifty-50 membership — and "
        "collapsing them would silently change what the screen ranks"
    )


def test_the_two_panels_are_not_the_same_file() -> None:
    assert panels.SCREEN_PANEL != panels.BOOK_PANEL


# --- nobody writes these paths out by hand any more --------------------------------------------
def test_the_live_decision_path_names_no_panel_as_a_literal() -> None:
    """One definition, or two that drift. The drift was the bug.

    Scoped to the modules a buy decision passes through. Backtests and experiments legitimately
    pin a specific historical file, and pinning one is exactly what they are for.
    """
    live = ROOT / "src/qalpha/live"
    watched = [ROOT / "scripts/local_run.py", *sorted(live.glob("*.py"))]
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
    monkeypatch.setattr(panels, "refresh_targets", lambda: ((panels.SCREEN_PANEL, missing),))
    monkeypatch.setattr(daily, "_universe_tickers", lambda p: [])
    with pytest.raises(RuntimeError, match="was NOT refreshed"):
        daily._step_prices()


# --- the files on disk ------------------------------------------------------------------------
def test_the_universes_named_here_exist_in_this_checkout() -> None:
    """These are committed CSVs. A typo'd path would disable a refresh with no error until run."""
    for _panel, universe in panels.refresh_targets():
        assert (ROOT / universe).exists(), f"{universe} is named as a universe and is not there"


def test_the_screen_universe_has_a_ticker_column_the_reader_can_use() -> None:
    tickers = daily._universe_tickers(ROOT / panels.SCREEN_UNIVERSE)
    assert len(tickers) > 50, "the watchlist should carry the full screening universe"
    assert all(t.endswith(".NS") for t in tickers[:10])
