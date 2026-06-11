"""Backtest engine + baseline integration tests on synthetic data (no network)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import numpy as np
import pandas as pd

from qalpha.accounting.costs import Side
from qalpha.backtest.baselines import buy_and_hold, do_nothing, equal_weight, monthly_sip
from qalpha.backtest.engine import run_backtest
from qalpha.backtest.portfolio import Portfolio
from qalpha.config import Config
from qalpha.data.prices import PriceData
from qalpha.data.universe import Universe

SECTORS = ["FIN", "IT", "PHARMA", "ENERGY", "AUTO", "FMCG"]


def _market_panel(n_tickers: int = 12, n_days: int = 500, seed: int = 1) -> PriceData:
    """A liquid multi-sector market with varied drifts/vols so the funnel has real choices."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n_days)
    rows = []
    for i in range(n_tickers):
        drift = rng.uniform(0.0001, 0.0009)
        vol = rng.uniform(0.010, 0.025)
        price = 200.0 * np.exp(np.cumsum(rng.normal(drift, vol, n_days)))
        volume = rng.integers(200_000, 600_000, n_days)  # high -> clears ADV gate
        ticker = f"STK{i:02d}"
        for d, p, v in zip(dates, price, volume, strict=True):
            rows.append({"date": d, "ticker": ticker, "close": p, "adj_close": p, "volume": int(v)})
    return PriceData.from_long(pd.DataFrame(rows))


def _sector_map(prices: PriceData) -> dict[str, str]:
    return {t: SECTORS[i % len(SECTORS)] for i, t in enumerate(prices.tickers)}


def test_engine_runs_and_produces_daily_equity() -> None:
    prices = _market_panel()
    cfg = Config()
    universe = Universe.static(prices.tickers)
    result = run_backtest(
        prices, _sector_map(prices), universe, cfg, start="2020-01-01", end="2021-12-31"
    )

    # Daily equity curve over the windowed trading days.
    assert len(result.equity) > 200
    assert result.equity.iloc[0] > 0
    # Some rebalancing happened once enough history accrued.
    assert result.n_rebalances >= 1
    assert len(result.trades) >= 1
    # Costs were actually charged (Zerodha: zero brokerage but STT/DP/slippage are non-zero).
    assert result.total_costs > Decimal("0")
    # Static universe is flagged biased.
    assert result.point_in_time_universe is False


def test_tax_aware_gate_reduces_turnover_and_tax() -> None:
    prices = _market_panel(seed=4)
    cfg = Config()
    universe = Universe.static(prices.tickers)
    sector_of = _sector_map(prices)

    plain = run_backtest(
        prices, sector_of, universe, cfg, start="2020-01-01", end="2021-12-31", tax_aware=False
    )
    gated = run_backtest(
        prices,
        sector_of,
        universe,
        cfg,
        start="2020-01-01",
        end="2021-12-31",
        tax_aware=True,
        min_trade_fraction=0.10,
    )
    # The §4.6 gate must not trade more, and should not realize more capital-gains tax.
    assert gated.n_rebalances <= plain.n_rebalances
    assert gated.total_tax <= plain.total_tax


def test_estimate_rebalance_does_not_mutate_state() -> None:
    cfg = Config()
    pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal("200000"))
    prices = {"STK00": Decimal("100.00")}
    cash_before = pf.cash
    cost, _tax, turnover = pf.estimate_rebalance(
        date(2020, 1, 1), pd.Series({"STK00": 1.0}), prices
    )
    assert turnover > 0
    assert cost > 0
    assert pf.cash == cash_before  # dry-run left the real portfolio untouched
    assert pf.positions() == {}


def test_engine_respects_starting_capital_no_free_money() -> None:
    prices = _market_panel()
    cfg = Config()
    universe = Universe.static(prices.tickers)
    result = run_backtest(prices, _sector_map(prices), universe, cfg, end="2021-12-31")
    # First-day equity equals starting capital (nothing invested before the first rebalance).
    assert abs(result.equity.iloc[0] - float(cfg.capital.starting_capital)) < 1.0


def test_portfolio_buy_then_full_sell_roundtrip() -> None:
    cfg = Config()
    pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal("200000"))
    prices = {"STK00": Decimal("100.00")}
    pf.rebalance(date(2020, 1, 1), pd.Series({"STK00": 1.0}), prices)
    assert pf.positions()["STK00"] > 0
    assert pf.cash < Decimal("200000")  # spent on shares + costs

    # Liquidate everything.
    trades = pf.rebalance(
        date(2020, 6, 1), pd.Series(dtype="float64"), {"STK00": Decimal("110.00")}
    )
    assert any(t.side is Side.SELL for t in trades)
    assert pf.positions() == {}


def test_baselines_align_to_index() -> None:
    prices = _market_panel(n_tickers=4, n_days=260)
    idx = prices.dates
    cap = Decimal("200000")
    nifty = prices.adj_close.iloc[:, 0]

    flat = do_nothing(idx, cap)
    bh = buy_and_hold(nifty, idx, cap)
    ew = equal_weight(prices, idx, cap)

    assert (flat == float(cap)).all()
    assert len(bh) == len(idx) and abs(bh.iloc[0] - float(cap)) < 1.0
    assert len(ew) == len(idx) and abs(ew.iloc[0] - float(cap)) < 1.0


def test_sip_invests_each_month() -> None:
    prices = _market_panel(n_tickers=1, n_days=260)
    series = prices.adj_close.iloc[:, 0]
    summary = monthly_sip(series, Decimal("10000"))
    assert summary.n_installments >= 11  # ~1 year of months
    assert summary.invested == Decimal("10000") * summary.n_installments
    assert summary.final_value > 0
