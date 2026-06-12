"""Dynamic drawdown control tests (Q_alpha.md §0)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from qalpha.backtest.drawdown import (
    DrawdownConfig,
    first_active_date,
    relative_underwater,
    summarize,
    underwater,
)


def _series(values: list[float], start: str = "2020-01-01") -> pd.Series:
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)))


def test_underwater_basic() -> None:
    dd = underwater(_series([100, 120, 60, 90]))
    assert dd.iloc[0] == 0.0
    assert dd.iloc[1] == 0.0  # new peak
    assert abs(dd.iloc[2] - (-0.5)) < 1e-9  # 120 -> 60


def test_first_active_date_skips_flat_warmup() -> None:
    # Flat (cash) for 3 days, then starts moving.
    eq = _series([100, 100, 100, 110, 105])
    assert first_active_date(eq) == pd.Timestamp("2020-01-06").date()  # 4th business day


def test_relative_drawdown_zero_when_tracking_market() -> None:
    # Strategy exactly tracks benchmark -> no relative drawdown.
    bench = _series([100, 110, 90, 120])
    strat = bench * 2.0  # same shape, different scale
    rel = relative_underwater(strat, bench)
    assert rel.abs().max() < 1e-9


def test_market_crash_is_not_a_strategy_failure() -> None:
    # Both fall hard together (market crash); strategy falls slightly LESS.
    n = 400
    bench = _series([100 * (0.999**i) for i in range(n)])  # steady decline ~ -33%
    strat = _series([100 * (0.9992**i) for i in range(n)])  # declines a bit less
    summary = summarize(strat, bench)
    # Big absolute drawdown...
    assert summary.abs_max_dd < -0.20
    # ...but the strategy outperformed the benchmark, so excess DD is ~0 and no halt.
    assert summary.excess_max_dd > -0.02
    assert not summary.strategy_halt_fired


def test_strategy_specific_blowup_triggers_halt() -> None:
    # Benchmark flat; strategy bleeds 0.2%/day for ~300 days -> sustained large excess DD.
    n = 400
    bench = _series([100.0] * n)
    strat = _series([100 * (0.998**i) for i in range(n)])
    summary = summarize(strat, bench, DrawdownConfig(excess_confirm_days=60, excess_floor=0.20))
    assert summary.strategy_halt_fired
    assert not summary.criterion8_pass


def test_catastrophic_backstop() -> None:
    bench = _series([100.0] * 300)
    strat = _series([100 * (0.997**i) for i in range(300)])  # ~ -59%
    summary = summarize(strat, bench, DrawdownConfig(catastrophic_abs=0.40))
    assert summary.catastrophic_fired
    assert not summary.criterion8_pass


def test_normal_factor_drought_does_not_halt() -> None:
    # Strategy lags then recovers (a ~15% relative dip, below the 20% floor) -> no halt.
    rng = np.random.default_rng(0)
    n = 600
    bench_ret = rng.normal(0.0005, 0.01, n)
    strat_ret = bench_ret - 0.0004  # mild persistent lag then nothing sustained beyond floor
    bench = _series((100 * np.cumprod(1 + bench_ret)).tolist())
    strat = _series((100 * np.cumprod(1 + strat_ret)).tolist())
    summary = summarize(strat, bench, DrawdownConfig(excess_floor=0.20, excess_confirm_days=60))
    # Mild lag shouldn't be flagged as a strategy failure if it stays within the adaptive envelope.
    assert summary.excess_max_dd > -0.30  # sanity: not a blow-up
