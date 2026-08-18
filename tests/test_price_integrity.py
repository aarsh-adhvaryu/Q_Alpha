"""Price-continuity guard (PLAN_TRUST_REPAIR.md PR-2 — fixes T1.1).

The defect being closed: ``adj_close`` corrects splits and dividends and nothing else, so a demerger
leaves a permanent step-down that a 1-year-high rule reads as a discount. On the real watchlist that
put VEDL (−64.9% on 2026-04-30) and TRENT (−33.0% on 2026-01-01) at ranks #1 and #2 on cheapness.

The property that matters is not "flag those two names" — it is **an artifact must not outrank a
genuine decline**. The ordering assertions below are the real test; a guard that merely dropped every
volatile name would pass a "VEDL is flagged" check and fail these.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from qalpha.accounting.corporate_actions import CorporateAction
from qalpha.live.price_integrity import (
    excluded_from_tilt,
    gaps_note,
    rebase_starts,
    unexplained_gaps,
)

_AS_OF = date(2026, 7, 10)
_START = "2025-07-11"


def _index(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range(_START, periods=n)


def _flat(n: int, level: float = 100.0) -> list[float]:
    return [level] * n


def _panel(**series: list[float]) -> pd.DataFrame:
    n = max(len(v) for v in series.values())
    return pd.DataFrame(dict(series), index=_index(n))


def _with_step(n: int, at: int, factor: float) -> list[float]:
    """A flat series that steps by ``factor`` at position ``at`` — a demerger's shape."""
    return [100.0] * at + [100.0 * factor] * (n - at)


def _slide(n: int, to: float) -> list[float]:
    """A genuine grinding decline to ``to``% of the start — no single-day discontinuity."""
    return [100.0 - (100.0 - to) * i / (n - 1) for i in range(n)]


# ---- detection ----------------------------------------------------------------------------------


def test_flags_an_unexplained_step_and_reports_its_size_and_date() -> None:
    n = 250
    panel = _panel(DEMERGED=_with_step(n, 200, 0.35))
    gaps = unexplained_gaps(panel, ["DEMERGED"], _AS_OF)
    assert set(gaps) == {"DEMERGED"}
    gap = gaps["DEMERGED"]
    assert gap.on == _index(n)[200].date()
    assert gap.ret == pytest.approx(-0.65)
    assert gap.unexplained


def test_a_genuine_slide_is_never_flagged() -> None:
    """−60% ground out over a year is a real decline — the tilt is *supposed* to see it."""
    panel = _panel(SLIDER=_slide(250, 40.0))
    assert unexplained_gaps(panel, ["SLIDER"], _AS_OF) == {}


def test_a_step_matched_by_a_known_split_is_explained_not_flagged() -> None:
    """yfinance can lag its own adjustment; a real, understood action is not a data defect."""
    n = 250
    panel = _panel(SPLITTER=_with_step(n, 200, 0.20))
    ex_date = _index(n)[200].date()
    gaps = unexplained_gaps(
        panel,
        ["SPLITTER"],
        _AS_OF,
        actions={"SPLITTER": [CorporateAction.split("SPLITTER", ex_date, Decimal("5"))]},
    )
    assert gaps == {}


def test_an_action_days_away_still_explains_the_step() -> None:
    """The ex-date and the session the adjustment lands on need not be the same day."""
    n = 250
    panel = _panel(SPLITTER=_with_step(n, 200, 0.20))
    ex_date = _index(n)[198].date()  # two sessions earlier
    gaps = unexplained_gaps(
        panel,
        ["SPLITTER"],
        _AS_OF,
        actions={"SPLITTER": [CorporateAction.split("SPLITTER", ex_date, Decimal("5"))]},
    )
    assert gaps == {}


def test_an_unrelated_action_does_not_explain_the_step() -> None:
    n = 250
    panel = _panel(DEMERGED=_with_step(n, 200, 0.35))
    far = _index(n)[100].date()
    gaps = unexplained_gaps(
        panel,
        ["DEMERGED"],
        _AS_OF,
        actions={"DEMERGED": [CorporateAction.dividend("DEMERGED", far, Decimal("5"))]},
    )
    assert set(gaps) == {"DEMERGED"}


def test_only_the_latest_gap_is_reported() -> None:
    """Re-basing to the most recent step subsumes every earlier one — report the binding constraint."""
    n = 250
    series = [100.0] * 100 + [60.0] * 100 + [20.0] * (n - 200)
    gaps = unexplained_gaps(_panel(TWICE=series), ["TWICE"], _AS_OF)
    assert gaps["TWICE"].on == _index(n)[200].date()


def test_a_gap_older_than_the_lookback_is_not_flagged() -> None:
    """Once the step ages out of the window it no longer sets the high — nothing left to correct."""
    n = 250
    panel = _panel(OLD=_with_step(n, 5, 0.35))
    assert unexplained_gaps(panel, ["OLD"], _AS_OF, lookback=180) == {}


def test_an_upward_spike_is_flagged_too() -> None:
    """An unexplained *spike* corrupts the 1y high in exactly the same way a step-down does."""
    n = 250
    panel = _panel(SPIKE=_with_step(n, 200, 1.60))
    assert "SPIKE" in unexplained_gaps(panel, ["SPIKE"], _AS_OF)


def test_missing_and_short_series_are_skipped_not_crashed() -> None:
    panel = _panel(SHORT=[100.0])
    assert unexplained_gaps(panel, ["SHORT", "ABSENT"], _AS_OF) == {}


# ---- what the guard hands the sizing layer ------------------------------------------------------


def test_a_rebasable_gap_yields_a_rebase_start_at_the_gap_day() -> None:
    """The gap day carries the first price on the new basis, so it belongs *inside* the window."""
    n = 250
    gaps = unexplained_gaps(_panel(D=_with_step(n, 200, 0.35)), ["D"], _AS_OF)
    assert rebase_starts(gaps) == {"D": _index(n)[200].date()}
    assert excluded_from_tilt(gaps) == set()


def test_a_gap_with_too_little_history_is_zeroed_rather_than_rebased() -> None:
    """Re-basing onto a handful of marks would be a number computed on almost nothing."""
    n = 250
    gaps = unexplained_gaps(_panel(D=_with_step(n, 245, 0.35)), ["D"], _AS_OF)
    assert rebase_starts(gaps) == {}
    assert excluded_from_tilt(gaps) == {"D"}


def test_the_note_explains_itself_and_is_empty_when_clean() -> None:
    n = 250
    gaps = unexplained_gaps(_panel(D=_with_step(n, 200, 0.35)), ["D"], _AS_OF)
    note = gaps_note(gaps)
    assert "demerger" in note
    assert "re-based" in note
    assert "-65.0%" in note
    assert gaps_note({}) == ""
