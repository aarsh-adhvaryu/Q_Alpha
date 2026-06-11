"""Metrics + go/no-go report tests."""

from __future__ import annotations

import numpy as np
import pandas as pd

from qalpha.backtest.metrics import PerformanceMetrics, compute_metrics, max_drawdown
from qalpha.backtest.report import evaluate


def _curve(daily_ret: float, n: int = 504) -> pd.Series:
    idx = pd.bdate_range("2020-01-01", periods=n)
    return pd.Series(100000.0 * (1 + daily_ret) ** np.arange(n), index=idx)


def test_metrics_on_steady_growth() -> None:
    m = compute_metrics(_curve(0.0005), "test")
    assert m.total_return > 0
    assert m.cagr > 0
    assert m.max_drawdown == 0.0  # monotonic curve never draws down
    assert m.sharpe > 0


def test_max_drawdown_detects_decline() -> None:
    idx = pd.bdate_range("2020-01-01", periods=5)
    equity = pd.Series([100.0, 120.0, 60.0, 80.0, 130.0], index=idx)
    # Peak 120 -> trough 60 = -50%.
    assert abs(max_drawdown(equity) - (-0.5)) < 1e-9


def _m(name: str, final: float, sharpe: float) -> PerformanceMetrics:
    return PerformanceMetrics(name, final, 0.0, 0.0, 0.1, sharpe, sharpe, -0.1, 0.0)


def test_verdict_go_requires_point_in_time() -> None:
    strat = _m("strat", final=160000, sharpe=1.2)
    baselines = {
        "do_nothing": _m("do_nothing", 100000, 0.0),
        "nifty50_buy_hold": _m("nifty50_buy_hold", 140000, 0.8),
        "equal_weight": _m("equal_weight", 150000, 0.9),
    }
    assert evaluate(strat, baselines, point_in_time_universe=True).verdict == "GO"
    # Same numbers but static universe -> downgraded to CONDITIONAL (survivorship caveat).
    assert evaluate(strat, baselines, point_in_time_universe=False).verdict == "CONDITIONAL"


def test_verdict_no_go_when_underperforming() -> None:
    strat = _m("strat", final=120000, sharpe=0.5)
    baselines = {
        "do_nothing": _m("do_nothing", 100000, 0.0),
        "nifty50_buy_hold": _m("nifty50_buy_hold", 140000, 0.8),  # strategy loses to Nifty
        "equal_weight": _m("equal_weight", 130000, 0.7),
    }
    assert evaluate(strat, baselines, point_in_time_universe=True).verdict == "NO-GO"


def test_verdict_passes_when_beats_nifty_even_if_trails_equal_weight() -> None:
    # Spec §14.1 gate is do-nothing AND Nifty 50; equal-weight is informational only.
    strat = _m("strat", final=160000, sharpe=1.0)
    baselines = {
        "do_nothing": _m("do_nothing", 100000, 0.0),
        "nifty50_buy_hold": _m("nifty50_buy_hold", 140000, 0.85),  # strategy beats Nifty
        "equal_weight": _m("equal_weight", 180000, 1.2),  # ...but trails equal-weight
    }
    # Point-in-time -> GO; static universe -> CONDITIONAL. Trailing equal-weight must NOT force NO-GO.
    assert evaluate(strat, baselines, point_in_time_universe=True).verdict == "GO"
    assert evaluate(strat, baselines, point_in_time_universe=False).verdict == "CONDITIONAL"
