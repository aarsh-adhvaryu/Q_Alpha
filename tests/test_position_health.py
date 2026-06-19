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
