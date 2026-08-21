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


# ---- repairing corrupt prints (2026-08-20) -------------------------------------------------------
#
# Found in the NIFTYBEES benchmark: two days at ₹13.02 against a true level near ₹129, then a snap
# back. That series drives market_weakness, which sizes every deploy — so on those days the rule
# would have read the index as 90% below its 1-year high and deployed the whole wallet on a typo.


def test_a_round_trip_spike_is_repaired() -> None:
    from qalpha.live.price_integrity import repair_price_spikes

    s = pd.Series([129.0, 129.3, 13.0, 13.0, 129.9, 130.1], index=_index(6))
    clean, repaired = repair_price_spikes(s)
    assert [d.day for d in repaired] == [_index(6)[2].day, _index(6)[3].day]
    assert list(clean) == [129.0, 129.3, 129.3, 129.3, 129.9, 130.1]  # ffilled, never interpolated
    assert (clean.pct_change().dropna().abs() < 0.25).all()


def test_a_real_crash_is_left_completely_alone() -> None:
    """The property that makes this safe: a fall that *persists* is the signal, not an artifact.

    Repairing it would blind the system to exactly the event it exists to react to.
    """
    from qalpha.live.price_integrity import repair_price_spikes

    crash = pd.Series([100.0, 99.0, 60.0, 58.0, 61.0, 63.0], index=_index(6))
    clean, repaired = repair_price_spikes(crash)
    assert repaired == []
    assert list(clean) == list(crash)


def test_the_repair_is_causal_never_forward_looking() -> None:
    """Bad points take the last *good* price, so no future information enters the series."""
    from qalpha.live.price_integrity import repair_price_spikes

    # A genuine round trip: the recovery must land near the pre-spike level, else it is not an
    # artifact at all (100 → 10 → 200 is two real moves, and is correctly left alone).
    s = pd.Series([100.0, 10.0, 105.0], index=_index(3))
    clean, repaired = repair_price_spikes(s)
    assert len(repaired) == 1
    assert clean.iloc[1] == 100.0  # the prior price — never the (higher) recovery price ahead of it

    not_a_round_trip = pd.Series([100.0, 10.0, 200.0], index=_index(3))
    assert repair_price_spikes(not_a_round_trip)[1] == []


def test_a_clean_series_is_returned_untouched() -> None:
    from qalpha.live.price_integrity import repair_price_spikes

    s = pd.Series([100.0, 101.0, 99.5, 102.0], index=_index(4))
    clean, repaired = repair_price_spikes(s)
    assert repaired == []
    assert list(clean) == list(s)
