"""Tests for the forward hedge paper run (regime/hedge_paper.py)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from qalpha.live.hedge_study import (
    forward_hedge_track,
    track_record_csv,
)

_FWD_START = date(2025, 6, 1)  # the panel below has ≥1y before this, so the gauge is live by then
_COLS = ["sp500", "us_vix", "move", "hyg", "lqd", "dxy", "usdinr", "sensex", "nifty", "india_vix"]


def _panel(seed: int = 0) -> pd.DataFrame:
    """A synthetic cross-asset panel spanning enough history for the gauge to emit (pct_min=252)."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2023-01-02", "2025-09-01")  # ~2.7y → gauge live well before _FWD_START
    data = {}
    for c in _COLS:
        steps = rng.normal(0.0003, 0.012, len(idx))
        data[c] = 100.0 * np.exp(np.cumsum(steps))
    df = pd.DataFrame(data, index=idx)
    df.index.name = "date"
    return df


def test_forward_track_is_restricted_to_the_forward_window() -> None:
    res = forward_hedge_track(_panel(), forward_start=_FWD_START, base="nifty")
    assert res.days > 0
    assert res.unhedged.index[0].date() >= _FWD_START  # nothing before the forward start leaks in
    # Both curves are normalised to ~1.0 at the start (paper books begin at par).
    assert abs(float(res.unhedged.iloc[0]) - 1.0) < 0.05
    assert 0.0 <= res.gauge_now <= 1.0
    assert isinstance(res.hedge_on, bool)
    assert len(res.gauge_history) > 1  # the ~2y gauge context series is populated for the chart


def test_never_hedging_equals_unhedged() -> None:
    # An unreachable threshold (gauge ≤ 1.0 < 2.0) → hedge never fires → hedged == unhedged, no cost/tax.
    res = forward_hedge_track(_panel(), forward_start=_FWD_START, tau=2.0)
    assert res.episodes == 0
    assert res.cost == 0.0 and res.tax == 0.0
    assert np.allclose(res.hedged.to_numpy(), res.unhedged.to_numpy())
    assert res.hedge_on is False
    assert res.level == "calm"


def test_track_record_csv_round_trips() -> None:
    res = forward_hedge_track(_panel(), forward_start=_FWD_START)
    csv = track_record_csv(res)
    lines = csv.strip().splitlines()
    assert lines[0] == "date,hedged,unhedged"
    assert len(lines) == res.days + 1  # header + one row per forward trading day
    first = lines[1].split(",")
    assert date.fromisoformat(first[0]) >= _FWD_START


# ---- liveness: the failure that hid for 38 days (2026-08-29) ------------------------------------


def _result(*, as_of: date, days: int, episodes: int) -> object:
    """A minimal HedgePaperResult stand-in for the status text."""
    from qalpha.live.hedge_study import HedgePaperResult

    idx = pd.bdate_range(end=pd.Timestamp(as_of), periods=days)
    flat = pd.Series([1.0] * days, index=idx)
    return HedgePaperResult(
        forward_start=idx[0].date(),
        as_of=as_of,
        base="NIFTYBEES.NS",
        tau=0.7,
        persist=3,
        h=0.5,
        gauge_now=0.1,
        hedge_on=False,
        gauge_history=flat,
        hedged=flat,
        unhedged=flat,
        episodes=episodes,
        cost=0.0,
        tax=0.0,
    )


def test_a_dead_study_says_so_instead_of_looking_calm() -> None:
    """The 2026-07-21 outage: 38 days dead, invisible because the curves overlapped either way."""
    from qalpha.live.hedge_study import study_status

    note = study_status(_result(as_of=date(2026, 7, 21), days=23, episodes=0), date(2026, 8, 28))
    assert "not running" in note
    assert "2026-07-21" in note


def test_a_live_study_with_no_episodes_reports_zero_evidence() -> None:
    """ "No episodes" is a legitimate state — but it must be SAID, not left to look like success."""
    from qalpha.live.hedge_study import study_status

    note = study_status(_result(as_of=date(2026, 8, 28), days=23, episodes=0), date(2026, 8, 28))
    assert "Running" in note
    assert "fired 0 times" in note
    assert "no evidence" in note


def test_the_two_states_are_distinguishable() -> None:
    """The whole point: a dead run and a quiet run produced identical charts. They must not read alike."""
    from qalpha.live.hedge_study import study_status

    dead = study_status(_result(as_of=date(2026, 7, 21), days=23, episodes=0), date(2026, 8, 28))
    quiet = study_status(_result(as_of=date(2026, 8, 28), days=23, episodes=0), date(2026, 8, 28))
    assert dead != quiet
    assert ("not running" in dead) and ("not running" not in quiet)


def test_episodes_change_the_verdict() -> None:
    """Once the gauge fires the run is measuring something, and the text must switch."""
    from qalpha.live.hedge_study import study_status

    note = study_status(_result(as_of=date(2026, 8, 28), days=60, episodes=2), date(2026, 8, 28))
    assert "2 hedge episode(s)" in note
    assert "no evidence" not in note
