"""Corporate actions, and the bar's treatment of names it cannot price.

Two things are pinned here. First, that a dividend is checked against something other than itself
before any book receives it — a vendor's dividend row and the same vendor's price adjustment are
computed separately, and a record that does not reconcile is named and not applied. Second, that the
equal-weight bar neither holds a dead company at its last price nor counts it as ₹0.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

from qalpha.accounting.corporate_actions import CorporateAction, CorporateActionType
from qalpha.data.prices import PriceData
from qalpha.data.universe import Membership, Universe
from qalpha.live import actions
from qalpha.live.benchmarks import STALE_LIMIT, equal_weight_pit, unpriceable_members


def _panel(dividend: float = 10.0) -> pd.DataFrame:
    """Five sessions with a ₹``dividend`` ex-date on the third, back-adjusted as a vendor would.

    Before the ex-date every close is scaled by ``1 - D / close(T-1)``; from it, the factor is 1.
    """
    closes = [100.0, 100.0, 90.0, 91.0, 92.0]
    factor = 1 - dividend / closes[1]
    adj = [c * factor for c in closes[:2]] + closes[2:]
    return pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2026-03-01", "2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05"]
            ),
            "ticker": ["PAYER.NS"] * 5,
            "close": closes,
            "adj_close": adj,
            "volume": [1] * 5,
        }
    )


def _dividend(amount: str) -> CorporateAction:
    return CorporateAction(
        ticker="PAYER.NS",
        ex_date=date(2026, 3, 3),
        action_type=CorporateActionType.DIVIDEND,
        amount_per_share=Decimal(amount),
    )


def test_the_amount_is_recovered_from_the_prices_alone() -> None:
    """The check has to be independent of the number it is checking, or it checks nothing."""
    implied = actions.implied_dividend(_panel(10.0), "PAYER.NS", date(2026, 3, 3))
    assert implied is not None
    assert abs(implied - Decimal("10")) < Decimal("0.01")


def test_a_dividend_that_reconciles_is_applied_and_says_by_how_much() -> None:
    recorded = actions.check(_dividend("10"), _panel(10.0))
    assert recorded.reconciled
    assert "agree" in recorded.note
    record = actions.Record(actions=(recorded,), source="test", fetched_at="")
    assert record.for_replay() == [_dividend("10")]


def test_a_dividend_that_does_not_reconcile_is_named_and_never_applied() -> None:
    """The failure this exists for: a right-looking amount on the wrong date, or a wrong amount."""
    recorded = actions.check(_dividend("25"), _panel(10.0))
    assert not recorded.reconciled
    assert "NOT applied" in recorded.note
    record = actions.Record(actions=(recorded,), source="test", fetched_at="")
    assert record.for_replay() == [], "an unreconciled action must reach no book"
    assert record.unreconciled == (recorded,), "and must still be visible, not dropped"


def test_an_amount_that_cannot_be_checked_is_not_applied_either() -> None:
    """No session either side of the ex-date: unknown, which is not the same as agreeing."""
    empty = _panel().iloc[:0]
    recorded = actions.check(_dividend("10"), empty)
    assert recorded.implied is None
    assert not recorded.reconciled
    assert "could not be checked" in recorded.note


def test_a_split_is_checked_by_the_share_count_not_the_price() -> None:
    split = CorporateAction(
        ticker="SPLITCO.NS",
        ex_date=date(2026, 3, 3),
        action_type=CorporateActionType.SPLIT,
        ratio=Decimal("5"),
    )
    recorded = actions.check(split, _panel())
    assert recorded.reconciled
    assert "share count" in recorded.note


def test_the_record_survives_a_round_trip(tmp_path: Path) -> None:
    record = actions.Record(
        actions=(
            actions.check(_dividend("10"), _panel(10.0)),
            actions.check(_dividend("25"), _panel(10.0)),
        ),
        source="a vendor, cross-checked",
        fetched_at="2026-09-14T00:00:00+00:00",
    )
    path = tmp_path / "corporate_actions.json"
    actions.save(record, path)
    back = actions.load(path)
    assert back is not None
    assert len(back.actions) == 2
    assert len(back.unreconciled) == 1
    assert back.for_replay() == record.for_replay()


def test_an_unreadable_record_is_not_imported_rather_than_guessed_at(tmp_path: Path) -> None:
    path = tmp_path / "corporate_actions.json"
    path.write_text("{ not json", encoding="utf-8")
    assert actions.load(path) is None
    assert actions.load(tmp_path / "absent.json") is None


# ---- the bar -------------------------------------------------------------------------------------


def _index_panel(rows: list[tuple[str, str, float]]) -> PriceData:
    frame = pd.DataFrame(
        [
            {"date": pd.Timestamp(d), "ticker": t, "close": c, "adj_close": c, "volume": 1}
            for d, t, c in rows
        ]
    )
    return PriceData.from_long(frame)


def _universe(*tickers: str) -> Universe:
    return Universe([Membership(ticker=t, start=date(2012, 1, 1), end=None) for t in tickers])


def test_a_member_the_panel_cannot_price_is_named_not_silently_dropped() -> None:
    """TATAMOTORS' case: a member with no price at all. The bar is then 49 names calling itself 50."""
    days = ["2026-03-02", "2026-03-03", "2026-03-04"]
    panel = _index_panel([(d, "ALIVE.NS", 100.0) for d in days])
    universe = _universe("ALIVE.NS", "GONE.NS")
    index = pd.DatetimeIndex(pd.to_datetime(days))
    missing = unpriceable_members(panel, universe, index)
    assert missing == {"GONE.NS": 3}


def test_a_held_name_going_dark_makes_the_day_unknown_not_cheaper() -> None:
    """Counting a dark holding as ₹0 reports the bar falling 1/N the day a vendor goes quiet; holding
    it at its last price reports a dead company still trading. Neither is a measurement."""
    days = pd.bdate_range("2026-03-02", periods=STALE_LIMIT + 6).strftime("%Y-%m-%d").tolist()
    rows = [(d, "ALIVE.NS", 100.0) for d in days]
    # DARK trades for the first three sessions, then stops for good.
    rows += [(d, "DARK.NS", 50.0) for d in days[:3]]
    panel = _index_panel(rows)
    universe = _universe("ALIVE.NS", "DARK.NS")
    index = pd.DatetimeIndex(pd.to_datetime(days))
    series = equal_weight_pit(panel, universe, index, Decimal("100"))

    # Inside the fill window the last price is carried: a one-day hole is ordinary.
    assert not pd.isna(series.iloc[3])
    # Past it, the level is unknown — not a smaller number, and not the old one.
    assert pd.isna(series.iloc[3 + STALE_LIMIT]), (
        "beyond the fill limit a held, unpriced name must make the day's level unknown"
    )
