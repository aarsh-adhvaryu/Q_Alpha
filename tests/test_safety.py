"""Fail-loud safety guards: stale feed / missing quote / dead session must BLOCK advice (§4.9).

The system never auto-trades, so the only loss vector is acting on wrong displayed data — these
guards must turn each such failure into a blocking signal, not a silently-wrong number.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pandas as pd

from qalpha.data.prices import PriceData
from qalpha.live.safety import (
    assess_advice_inputs,
    broker_session_guard,
    price_completeness_guard,
    price_freshness_guard,
)


def _prices(last_day: str) -> PriceData:
    idx = pd.bdate_range(end=last_day, periods=5)
    frame = pd.DataFrame({"AAA": [100.0] * 5, "BBB": [200.0] * 5}, index=idx)
    return PriceData(frame, frame, frame)


def test_fresh_feed_passes() -> None:
    g = price_freshness_guard(_prices("2026-06-18"), date(2026, 6, 19))
    assert g.ok and g.blocking


def test_stale_feed_blocks() -> None:
    # latest price a week before as_of → several weekdays stale → blocking failure.
    g = price_freshness_guard(_prices("2026-06-10"), date(2026, 6, 19))
    assert not g.ok and g.blocking
    assert "stale" in g.detail


def test_empty_feed_blocks() -> None:
    empty = pd.DataFrame(index=pd.DatetimeIndex([], name="date"))
    g = price_freshness_guard(PriceData(empty, empty, empty), date(2026, 6, 19))
    assert not g.ok and g.blocking


def test_missing_holding_price_blocks() -> None:
    g = price_completeness_guard({"AAA": Decimal("100")}, ["AAA", "BBB"])
    assert not g.ok and g.blocking
    assert "BBB" in g.detail


def test_zero_price_blocks() -> None:
    g = price_completeness_guard({"AAA": Decimal("100"), "BBB": Decimal("0")}, ["AAA", "BBB"])
    assert not g.ok and "BBB" in g.detail


def test_complete_prices_pass() -> None:
    g = price_completeness_guard({"AAA": Decimal("100"), "BBB": Decimal("200")}, ["AAA", "BBB"])
    assert g.ok


def test_session_guards() -> None:
    assert broker_session_guard(True).ok
    assert not broker_session_guard(False).ok
    expired = broker_session_guard(
        True, expires_at=datetime(2026, 6, 19, 6, 0), now=datetime(2026, 6, 19, 9, 0)
    )
    assert not expired.ok and "expired" in expired.detail


def test_report_blocks_and_render() -> None:
    report = assess_advice_inputs(
        _prices("2026-06-01"),  # stale
        {"AAA": Decimal("100")},  # BBB missing
        ["AAA", "BBB"],
        date(2026, 6, 19),
        session=broker_session_guard(False),
    )
    assert not report.safe_to_advise
    assert len(report.blocks) == 3  # stale feed + missing price + dead session
    assert "Advice withheld" in report.render()


def test_report_safe_when_clean() -> None:
    report = assess_advice_inputs(
        _prices("2026-06-18"),
        {"AAA": Decimal("100"), "BBB": Decimal("200")},
        ["AAA", "BBB"],
        date(2026, 6, 19),
        session=broker_session_guard(True),
    )
    assert report.safe_to_advise
    assert not report.blocks
