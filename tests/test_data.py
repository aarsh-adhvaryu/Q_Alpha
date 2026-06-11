"""Data-layer tests: panel construction, the no-look-ahead guard, and the universe."""

from __future__ import annotations

from datetime import date

import pandas as pd

from qalpha.data.prices import PriceData
from qalpha.data.universe import Universe


def test_panel_shapes(synthetic_prices: PriceData) -> None:
    assert synthetic_prices.tickers == ["AAA", "BBB", "CCC"]
    assert len(synthetic_prices.dates) == 300
    # returns drops the first NaN row.
    assert len(synthetic_prices.returns()) == 299


def test_as_of_has_no_lookahead(synthetic_prices: PriceData) -> None:
    cutoff = date(2022, 6, 1)
    view = synthetic_prices.as_of(cutoff)
    assert view.dates.max() <= pd.Timestamp(cutoff)
    # The full panel extends past the cutoff; the view must not.
    assert synthetic_prices.dates.max() > pd.Timestamp(cutoff)


def test_as_of_lookback_bounds_rows(synthetic_prices: PriceData) -> None:
    view = synthetic_prices.as_of(date(2022, 12, 31), lookback=20)
    assert len(view.dates) == 20


def test_adv_is_value_not_shares(synthetic_prices: PriceData) -> None:
    adv = synthetic_prices.adv(window=20)
    # First 19 rows are NaN (min_periods=window); later rows are positive ₹ values.
    assert adv.iloc[:19].isna().all().all()
    assert (adv.iloc[20:] > 0).all().all()


def test_subset_selects_columns(synthetic_prices: PriceData) -> None:
    sub = synthetic_prices.subset(["AAA", "CCC", "ZZZ"])  # ZZZ absent -> ignored
    assert sub.tickers == ["AAA", "CCC"]


def test_universe_point_in_time() -> None:
    csv = pd.DataFrame(
        {
            "ticker": ["AAA", "BBB", "CCC"],
            "start_date": ["2010-01-01", "2010-01-01", "2018-06-01"],
            "end_date": ["", "2015-12-31", ""],  # BBB delisted end-2015
        }
    )
    import io

    buf = io.StringIO()
    csv.to_csv(buf, index=False)
    buf.seek(0)
    uni = Universe.from_csv(buf)

    assert uni.members_on(date(2012, 1, 1)) == ["AAA", "BBB"]  # CCC not yet listed
    assert uni.members_on(date(2016, 1, 1)) == ["AAA"]  # BBB delisted, CCC not yet
    assert uni.members_on(date(2019, 1, 1)) == ["AAA", "CCC"]  # BBB gone
    assert uni.point_in_time is True


def test_static_universe_flagged_biased() -> None:
    uni = Universe.static(["AAA", "BBB"])
    assert uni.point_in_time is False
    assert uni.members_on(date(2000, 1, 1)) == ["AAA", "BBB"]
