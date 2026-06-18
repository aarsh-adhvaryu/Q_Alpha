"""Tests for the deploy-in-weakness engine (qalpha.live.deploy)."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from qalpha.accounting.costs import Side
from qalpha.backtest.portfolio import Portfolio
from qalpha.config import Config
from qalpha.data.prices import PriceData
from qalpha.live.deploy import (
    advise_deploy_into_weakness,
    cheapness_scores,
    deploy_target,
    market_weakness,
)

_DATES = pd.bdate_range("2023-01-02", periods=300)


def _series(peak: float, last: float) -> list[float]:
    """A price path that rises to ``peak`` mid-window then ends at ``last`` (controls the pullback)."""
    up = list(pd.Series(range(150)).apply(lambda i: 50 + (peak - 50) * i / 149))
    down = list(pd.Series(range(150)).apply(lambda i: peak + (last - peak) * i / 149))
    return up + down


def _prices() -> PriceData:
    # ATHIGH ends at its high; MILD ends 20% below; DEEP ends 40% below.
    paths = {
        "ATHIGH.NS": _series(100, 100),
        "MILD.NS": _series(100, 80),
        "DEEP.NS": _series(100, 60),
    }
    rows = []
    for t, vals in paths.items():
        for d, v in zip(_DATES, vals, strict=True):
            rows.append({"date": d, "ticker": t, "close": v, "adj_close": v, "volume": 1000})
    return PriceData.from_long(pd.DataFrame(rows))


def _index_ending_at(last: float) -> pd.Series:
    """A flat-100 index that ends at ``last`` (so the drawdown from the 1y high is 1 - last/100)."""
    idx = pd.bdate_range("2023-01-02", periods=252)
    return pd.Series([100.0] * 251 + [last], index=idx)


def test_market_weakness_levels() -> None:
    as_of = pd.bdate_range("2023-01-02", periods=252)[-1].date()
    assert market_weakness(_index_ending_at(97.0), as_of).level == "normal"  # -3%
    assert market_weakness(_index_ending_at(92.0), as_of).level == "elevated"  # -8%
    assert market_weakness(_index_ending_at(85.0), as_of).level == "deep"  # -15%


def test_cheapness_scores_track_pullback() -> None:
    prices = _prices()
    as_of = _DATES[-1].date()
    scores = cheapness_scores(prices, ["ATHIGH.NS", "MILD.NS", "DEEP.NS"], as_of)
    assert scores["ATHIGH.NS"] < 0.01
    assert 0.18 < scores["MILD.NS"] < 0.22  # ~20% below high
    assert 0.38 < scores["DEEP.NS"] < 0.42  # ~40% below high


def test_deploy_target_tilts_to_cheaper_and_sums_to_one() -> None:
    cheap = {"ATHIGH.NS": 0.0, "MILD.NS": 0.2, "DEEP.NS": 0.4}
    sector_of = {"ATHIGH.NS": "IT", "MILD.NS": "FIN", "DEEP.NS": "AUTO"}
    target = deploy_target(list(cheap), sector_of, cheap, tilt=1.0, max_sector_weight=1.0)
    assert abs(float(target.sum()) - 1.0) < 1e-9
    assert target["DEEP.NS"] > target["MILD.NS"] > target["ATHIGH.NS"]


def test_deploy_target_caps_sector_weight() -> None:
    # 4 FIN + one each of IT/AUTO/FMCG → 4 sectors, so a 30% cap is feasible (4·0.30 ≥ 1).
    fin = ["A.NS", "B.NS", "C.NS", "D.NS"]
    names = [*fin, "E.NS", "F.NS", "G.NS"]
    cheap = dict.fromkeys(names, 0.0)
    sectors = {**dict.fromkeys(fin, "FIN"), "E.NS": "IT", "F.NS": "AUTO", "G.NS": "FMCG"}
    target = deploy_target(names, sectors, cheap, tilt=0.0, max_sector_weight=0.30)
    assert float(target[fin].sum()) <= 0.30 + 1e-6  # FIN capped despite holding 4 of 7 names
    assert abs(float(target.sum()) - 1.0) < 1e-9


def _flat_prices(last: dict[str, float]) -> PriceData:
    """A PriceData where each ticker sits flat at its given price for the whole window."""
    rows = []
    for t, p in last.items():
        for d in _DATES:
            rows.append({"date": d, "ticker": t, "close": p, "adj_close": p, "volume": 1000})
    return PriceData.from_long(pd.DataFrame(rows))


def test_anti_dominance_drops_names_too_pricey_for_a_small_deploy() -> None:
    # 4 cheap names + 1 very pricey one; a small deploy must not blow on the pricey share.
    prices = _flat_prices({"A.NS": 100, "B.NS": 100, "C.NS": 100, "D.NS": 100, "PRICEY.NS": 50_000})
    as_of = _DATES[-1].date()
    sector_of = {"A.NS": "IT", "B.NS": "FIN", "C.NS": "AUTO", "D.NS": "FMCG", "PRICEY.NS": "METAL"}
    index_close = prices.adj_close.mean(axis=1)
    pf = Portfolio(Config().cost, Config().tax, cash=Decimal("5000"))
    advice = advise_deploy_into_weakness(
        pf,
        Decimal("5000"),
        list(sector_of),
        sector_of,
        prices,
        index_close,
        as_of,
        max_name_fraction=0.20,  # cap = ₹1,000 → PRICEY (₹50k) excluded
    )
    bought = {o.ticker for o in advice.deploy.buy_orders}
    assert "PRICEY.NS" not in bought  # one share would swallow the deploy → dropped
    assert "PRICEY.NS" not in advice.target.index
    assert bought  # the cheap names still get deployed


def test_advise_deploy_into_weakness_is_buys_only() -> None:
    prices = _prices()
    as_of = _DATES[-1].date()
    sector_of = {"ATHIGH.NS": "IT", "MILD.NS": "FIN", "DEEP.NS": "AUTO"}
    index_close = prices.adj_close.mean(axis=1)
    pf = Portfolio(Config().cost, Config().tax, cash=Decimal("100000"))
    advice = advise_deploy_into_weakness(
        pf, Decimal("50000"), list(sector_of), sector_of, prices, index_close, as_of
    )
    assert all(o.side is Side.BUY for o in advice.deploy.buy_orders)
    assert advice.deploy.naive_tax >= advice.deploy.tax_saved  # buys realize ₹0 tax
    assert abs(float(advice.target.sum()) - 1.0) < 1e-9
    # The deepest-pulled-back name should head the cheapest list.
    assert advice.cheapest[0][0] == "DEEP.NS"
