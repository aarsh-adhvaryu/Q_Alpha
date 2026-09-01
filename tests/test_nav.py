"""Unitized NAV — the property every contribution-bearing comparison depends on."""

from __future__ import annotations

import pandas as pd
import pytest

from qalpha.live.nav import unitized_nav

_IDX = pd.bdate_range("2026-09-01", periods=8)


def test_a_deposit_moves_units_not_the_price() -> None:
    """The defining property. A flat market plus a deposit must show zero return."""
    values = pd.Series([100.0, 100.0, 200.0, 200.0, 200.0, 200.0, 200.0, 200.0], index=_IDX)
    nav = unitized_nav(values, [(_IDX[2].date(), 100.0)])
    assert nav.iloc[-1] == pytest.approx(nav.iloc[0]), "money arriving is not performance"


def test_the_raw_ratio_it_replaces_is_diluted_by_contributions() -> None:
    """Why the statistic changed: identical deposits shrink a raw value ratio toward zero.

    ln(110/100) = 0.0953, but ln(210/200) = 0.0488 — the same 10-rupee lead reads as half the gap
    once ₹100 lands in both books. Over twelve monthly deposits the raw statistic would have walked
    steadily toward zero while nothing happened in the market.
    """
    lead = pd.Series([110.0] * 4 + [210.0] * 4, index=_IDX)
    behind = pd.Series([100.0] * 4 + [200.0] * 4, index=_IDX)
    flow = [(_IDX[4].date(), 100.0)]
    raw_before, raw_after = 110 / 100, 210 / 200
    assert raw_after < raw_before, "precondition: the raw ratio is diluted"
    a, b = unitized_nav(lead, flow), unitized_nav(behind, flow)
    assert (a.iloc[-1] / b.iloc[-1]) == pytest.approx(a.iloc[0] / b.iloc[0]), (
        "the NAV ratio must survive the deposit that dilutes the raw one"
    )


def test_a_fall_is_reported_at_full_depth_even_while_money_arrives() -> None:
    """Contributions landing during a fall keep a rupee curve near its high; a NAV is not fooled.

    Built from prices and units rather than hand-written values, so the truth is unarguable: the
    market falls 20% and recovers, with ₹100 deposited at the bottom of the fall.
    """
    prices = [1.0, 0.9, 0.9, 0.8, 0.8, 1.0, 1.0, 1.0]  # -20% peak to trough, then recovered
    units = 100.0
    values: list[float] = []
    for i, px in enumerate(prices):
        if i == 2:  # ₹100 arrives while the book is already down
            units += 100.0 / px
        values.append(units * px)
    series = pd.Series(values, index=_IDX)
    nav = unitized_nav(series, [(_IDX[2].date(), 100.0)])

    raw = float(((series - series.cummax()) / series.cummax()).min())
    felt = float(((nav - nav.cummax()) / nav.cummax()).min())
    assert raw == pytest.approx(-0.1111, abs=0.001), "the rupee curve understates the fall"
    assert felt == pytest.approx(-0.20, abs=0.001), "the NAV reports what the holder actually felt"


def test_an_empty_series_is_returned_unchanged() -> None:
    assert len(unitized_nav(pd.Series(dtype=float), [])) == 0
