"""Tests for the deterministic GO scorecard (qalpha.live.go_scorecard)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from qalpha.live.go_scorecard import (
    MIN_TRADING_DAYS,
    build_scorecard,
    trading_days_remaining,
)

_DATES = pd.bdate_range("2026-01-01", periods=70)


def _curve(values: list[float], dates: pd.DatetimeIndex = _DATES) -> list[dict[str, str]]:
    return [
        {"date": d.date().isoformat(), "equity": str(v), "cash": "0"}
        for d, v in zip(dates, values, strict=True)
    ]


def _ramp(start: float, end: float, n: int = 70) -> list[float]:
    return list(np.linspace(start, end, n))


def _benchmark_with_dip() -> pd.Series:
    """Rises to a peak, drops ~14% (a genuine vol event), recovers — ends only modestly up."""
    vals = _ramp(100, 110, 20) + _ramp(110, 95, 15) + _ramp(95, 102, 35)
    return pd.Series(vals, index=_DATES, name="nifty_tri")


def _benchmark_calm() -> pd.Series:
    """Monotonic climb — no ≥10% pullback, so no volatility event occurs."""
    return pd.Series(_ramp(100, 108), index=_DATES, name="nifty_tri")


def test_empty_curve_is_not_yet() -> None:
    sc = build_scorecard([], _benchmark_calm(), date(2026, 4, 1))
    assert sc.verdict == "NOT YET"


def test_full_pass_is_go() -> None:
    # 70 marks, a real vol event in the window, strategy beats the benchmark, shallow DD, dense feed.
    sc = build_scorecard(_curve(_ramp(200_000, 212_000)), _benchmark_with_dip(), date(2026, 4, 10))
    assert sc.verdict == "GO"
    assert all(c.status == "green" for c in sc.criteria)


def test_calm_market_is_ready_pending_event() -> None:
    # Everything else green (beats the calm +8% benchmark), only the awaitable vol-event missing → READY.
    sc = build_scorecard(_curve(_ramp(200_000, 220_000)), _benchmark_calm(), date(2026, 4, 10))
    assert sc.verdict == "READY"
    vol = next(c for c in sc.criteria if c.name == "Volatility event withstood")
    assert vol.status == "yellow" and vol.awaitable


def test_trailing_benchmark_is_no_go() -> None:
    # Strategy badly behind the benchmark (which itself had the dip) → blocking red → NO-GO.
    sc = build_scorecard(_curve(_ramp(200_000, 198_000)), _benchmark_with_dip(), date(2026, 4, 10))
    assert sc.verdict == "NO-GO"
    fwd = next(c for c in sc.criteria if c.name == "Forward vs benchmark")
    assert fwd.status == "red"


def test_catastrophic_drawdown_is_no_go() -> None:
    # A 40% mid-window crash in the book → drawdown behaviour red → NO-GO.
    vals = _ramp(200_000, 205_000, 30) + _ramp(205_000, 123_000, 10) + _ramp(123_000, 130_000, 30)
    sc = build_scorecard(_curve(vals), _benchmark_with_dip(), date(2026, 4, 10))
    assert sc.verdict == "NO-GO"
    dd = next(c for c in sc.criteria if c.name == "Drawdown behaviour")
    assert dd.status == "red"


def test_feed_gap_is_no_go() -> None:
    # Drop a fortnight of marks → a >7-day gap → integrity red → NO-GO.
    dates = _DATES.delete(range(30, 40))
    vals = _ramp(200_000, 212_000, len(dates))
    sc = build_scorecard(_curve(vals, dates), _benchmark_with_dip(), date(2026, 4, 10))
    integ = next(c for c in sc.criteria if c.name == "Data integrity")
    assert integ.status == "red"
    assert sc.verdict == "NO-GO"


def test_short_track_is_not_yet_and_counts_down() -> None:
    # Keeps pace with the benchmark (so forward isn't red), but too short + no vol event yet → NOT YET.
    short = _DATES[:20]
    curve = _curve(
        _ramp(200_000, 222_000, 20), short
    )  # +11%, matching the benchmark's first-20 climb
    sc = build_scorecard(curve, _benchmark_with_dip(), date(2026, 2, 1))
    assert sc.verdict == "NOT YET"
    assert trading_days_remaining(curve) == MIN_TRADING_DAYS - 20


def test_short_track_trailing_is_not_yet_not_no_go() -> None:
    # Fix 1: badly trailing the benchmark BUT over a 20-day window → short-sample noise, not a NO-GO.
    short = _DATES[:20]
    curve = _curve(_ramp(200_000, 190_000, 20), short)  # -5% while the benchmark climbs ~+10%
    sc = build_scorecard(curve, _benchmark_with_dip(), date(2026, 2, 1))
    fwd = next(c for c in sc.criteria if c.name == "Forward vs benchmark")
    assert fwd.status == "yellow"  # NOT red — the sample is too short to judge
    assert sc.verdict == "NOT YET"  # NOT NO-GO


def test_deep_drawdown_tracking_a_market_crash_is_green() -> None:
    # Fix 2: the book falls -36% but the market fell -45% — it BEAT the index, so this is beta, not a
    # behaviour break. A flat -35% floor would have wrongly flagged it red; market-relative passes it.
    bench = pd.Series(
        _ramp(100, 55, 35) + _ramp(55, 70, 35), index=_DATES, name="nifty_tri"
    )  # -45%
    book = _curve(_ramp(200_000, 128_000, 35) + _ramp(128_000, 150_000, 35))  # -36% trough
    sc = build_scorecard(book, bench, date(2026, 4, 10))
    dd = next(c for c in sc.criteria if c.name == "Drawdown behaviour")
    assert dd.status == "green"  # fell LESS than the market → not idiosyncratic


def test_idiosyncratic_drawdown_in_calm_market_is_no_go() -> None:
    # Fix 2: the book craters -30% while the market is flat → idiosyncratic → red → NO-GO.
    bench = _benchmark_calm()  # ~+8%, no crash
    book = _curve(
        _ramp(200_000, 205_000, 30) + _ramp(205_000, 143_000, 10) + _ramp(143_000, 150_000, 30)
    )
    sc = build_scorecard(book, bench, date(2026, 4, 10))
    dd = next(c for c in sc.criteria if c.name == "Drawdown behaviour")
    assert dd.status == "red"
    assert sc.verdict == "NO-GO"
