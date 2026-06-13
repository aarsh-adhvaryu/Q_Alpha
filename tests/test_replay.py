"""Replay-harness tests: it must run the *real* validated path and be deterministic (no network)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from qalpha.backtest.engine import run_backtest
from qalpha.config import Config
from qalpha.data.prices import PriceData
from qalpha.data.universe import Universe
from qalpha.live.replay import replay, verify_determinism

SECTORS = ["FIN", "IT", "PHARMA", "ENERGY", "AUTO", "FMCG"]


def _market_panel(n_tickers: int = 12, n_days: int = 500, seed: int = 1) -> PriceData:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n_days)
    rows = []
    for i in range(n_tickers):
        drift = rng.uniform(0.0001, 0.0009)
        vol = rng.uniform(0.010, 0.025)
        price = 200.0 * np.exp(np.cumsum(rng.normal(drift, vol, n_days)))
        volume = rng.integers(200_000, 600_000, n_days)
        for d, p, v in zip(dates, price, volume, strict=True):
            rows.append(
                {"date": d, "ticker": f"STK{i:02d}", "close": p, "adj_close": p, "volume": int(v)}
            )
    return PriceData.from_long(pd.DataFrame(rows))


def _sector_map(prices: PriceData) -> dict[str, str]:
    return {t: SECTORS[i % len(SECTORS)] for i, t in enumerate(prices.tickers)}


def _fixture() -> tuple[PriceData, dict[str, str], Universe, Config]:
    prices = _market_panel()
    return prices, _sector_map(prices), Universe.static(prices.tickers), Config()


def test_replay_reproduces_backtest_trades() -> None:
    """The harness must drive the same engine — its trade stream equals run_backtest's exactly."""
    prices, sector_of, universe, cfg = _fixture()

    rep = replay(
        prices,
        sector_of,
        universe,
        cfg,
        tax_aware=True,
        min_trade_fraction=0.10,
        weighting="shrink",
        force_refresh=True,
    )
    direct = run_backtest(
        prices,
        sector_of,
        universe,
        cfg,
        tax_aware=True,
        min_trade_fraction=0.10,
        weighting="shrink",
        force_refresh=True,
    )

    assert rep.result.trades == direct.trades
    assert float(rep.result.equity.iloc[-1]) == float(direct.equity.iloc[-1])


def test_replay_feed_is_coherent() -> None:
    prices, sector_of, universe, cfg = _fixture()
    rep = replay(prices, sector_of, universe, cfg, tax_aware=True, force_refresh=True)

    assert rep.n_decisions >= 1
    assert rep.n_executed >= 1
    # Every order shown in the feed is a real trade in the result, and counts reconcile.
    fed_orders = sum(len(r.orders) for r in rep.rebalances)
    assert fed_orders == len(rep.result.trades)
    # A rebalance with orders must be flagged executed and carry a non-empty reason.
    for r in rep.rebalances:
        assert r.reason
        if r.orders:
            assert r.execute


def test_verify_determinism_true() -> None:
    prices, sector_of, universe, cfg = _fixture()
    assert verify_determinism(
        prices, sector_of, universe, cfg, tax_aware=True, weighting="shrink", force_refresh=True
    )
