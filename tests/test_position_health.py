"""Tests for the mid-cycle position-health watch (qalpha.live.position_health)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from qalpha.live.position_health import position_health

_DATES = pd.bdate_range("2024-01-01", periods=200)  # > lookback_days (126)


def _frame(paths: dict[str, list[float]]) -> pd.DataFrame:
    return pd.DataFrame(paths, index=_DATES)


def _flat_then(end_ratio: float) -> list[float]:
    """A path that ends at ``end_ratio`` × its start (linear) — controls the trailing return."""
    return list(np.linspace(100.0, 100.0 * end_ratio, len(_DATES)))


def test_idiosyncratic_breakdown_is_flagged() -> None:
    # CRATER is down ~40% while the market (median) is roughly flat → idiosyncratic breakdown.
    frame = _frame(
        {
            "A.NS": _flat_then(1.05),
            "B.NS": _flat_then(1.02),
            "C.NS": _flat_then(0.98),
            "CRATER.NS": _flat_then(0.60),
        }
    )
    rep = position_health(frame, ["CRATER.NS", "A.NS"], _DATES[-1].date())
    breaking = {h.ticker for h in rep.breaking}
    assert "CRATER.NS" in breaking
    assert "A.NS" not in breaking  # a healthy holding is not flagged
    assert any(h.ticker == "A.NS" and h.level == "healthy" for h in rep.holdings)


def test_market_wide_drawdown_is_not_flagged() -> None:
    # EVERYTHING down ~30% together → systemic, not idiosyncratic → §4.7 "don't panic-sell in a crash".
    frame = _frame({t: _flat_then(0.70) for t in ["A.NS", "B.NS", "C.NS", "D.NS"]})
    rep = position_health(frame, ["A.NS", "B.NS"], _DATES[-1].date())
    assert rep.breaking == []  # small excess vs the median → no name singled out


def test_too_little_history_returns_empty() -> None:
    short = pd.DataFrame(
        {"A.NS": [100.0, 101.0, 102.0]}, index=pd.bdate_range("2024-01-01", periods=3)
    )
    rep = position_health(short, ["A.NS"], short.index[-1].date())
    assert rep.holdings == []


def test_render_is_advisory_and_mentions_breaking() -> None:
    frame = _frame({"A.NS": _flat_then(1.05), "B.NS": _flat_then(1.0), "BAD.NS": _flat_then(0.55)})
    rep = position_health(frame, ["BAD.NS"], _DATES[-1].date())
    md = rep.render()
    assert "BAD.NS" in md
    assert "never sells" in md  # read-only framing is explicit


# ---- price-continuity guard (final audit, 2026-08-28) -------------------------------------------
#
# The defect: ``adj_close`` corrects splits and dividends and nothing else, so a demerger leaves a
# step-down this detector read as a company falling apart. On the live watchlist it called VEDL
# "-59% over ~6mo, a name-specific breakdown" on the very screen where the guarded cheapness score
# read the same name as a routine 22% pullback. PR-2 taught ``cheapness_scores`` to re-base and left
# this function on the raw series; these tests close that.


def _step_down(at_frac: float = 0.7, factor: float = 0.5) -> list[float]:
    """A flat series that halves overnight and stays flat — a corporate action, not a decline."""
    at = int(len(_DATES) * at_frac)
    return [100.0] * at + [100.0 * factor] * (len(_DATES) - at)


def test_a_corporate_action_step_is_not_a_breakdown() -> None:
    """The whole point: an artifact is not evidence that a company is failing."""
    frame = _frame({"A.NS": _flat_then(1.02), "B.NS": _flat_then(0.99), "GAP.NS": _step_down()})
    as_of = _DATES[-1].date()
    gap_day = _DATES[int(len(_DATES) * 0.7)].date()

    unguarded = position_health(frame, ["GAP.NS"], as_of)
    assert unguarded.holdings[0].level == "breaking"  # the defect, reproduced

    guarded = position_health(frame, ["GAP.NS"], as_of, rebase_from={"GAP.NS": gap_day})
    assert guarded.holdings[0].level == "healthy"


def test_a_rebased_name_is_not_labelled_with_the_full_window() -> None:
    """It is measured over a shorter window, so calling it "~6mo" would be the same mislabelling."""
    frame = _frame({"A.NS": _flat_then(1.0), "B.NS": _flat_then(1.0), "GAP.NS": _step_down()})
    gap_day = _DATES[int(len(_DATES) * 0.7)].date()
    rep = position_health(frame, ["GAP.NS"], _DATES[-1].date(), rebase_from={"GAP.NS": gap_day})
    assert "~6mo" not in rep.holdings[0].note
    assert "corporate action" in rep.holdings[0].note


def test_a_genuine_decline_is_still_flagged_when_the_guard_is_on() -> None:
    """A guard that silenced every weak name would pass the tests above and be useless."""
    frame = _frame(
        {"A.NS": _flat_then(1.02), "B.NS": _flat_then(0.99), "CRATER.NS": _flat_then(0.60)}
    )
    gap_day = _DATES[int(len(_DATES) * 0.7)].date()
    rep = position_health(
        frame, ["CRATER.NS"], _DATES[-1].date(), rebase_from={"OTHER.NS": gap_day}
    )
    assert rep.holdings[0].level == "breaking"


def test_a_name_with_too_little_history_since_its_gap_is_not_flagged() -> None:
    """Unreadable is not the same as breaking — it is reported as unreadable and left alone."""
    frame = _frame({"A.NS": _flat_then(1.0), "B.NS": _flat_then(1.0), "GAP.NS": _step_down()})
    rep = position_health(frame, ["GAP.NS"], _DATES[-1].date(), exclude={"GAP.NS"})
    assert rep.holdings[0].level == "healthy"
    assert "not readable" in rep.holdings[0].note


def test_the_guard_is_off_by_default() -> None:
    """Rule (a): the validated SIP backtest calls this function and must be bit-for-bit unchanged."""
    frame = _frame({"A.NS": _flat_then(1.02), "B.NS": _flat_then(0.99), "GAP.NS": _step_down()})
    as_of = _DATES[-1].date()
    names = ["A.NS", "B.NS", "GAP.NS"]
    plain = position_health(frame, names, as_of)
    explicit = position_health(frame, names, as_of, rebase_from=None, exclude=None)
    assert [(h.ticker, h.level, h.note) for h in plain.holdings] == [
        (h.ticker, h.level, h.note) for h in explicit.holdings
    ]
