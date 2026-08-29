"""The noise floor — the number forward run 1 was voided for want of (PLAN_REDESIGN §5)."""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pytest

from qalpha.backtest.significance import (
    DEFAULT_MEAN_BLOCK,
    noise_floor,
    stationary_bootstrap_index,
    summarise_null,
)


def test_the_resample_is_the_right_length_and_stays_in_range() -> None:
    idx = stationary_bootstrap_index(500, rng=np.random.default_rng(0))
    assert len(idx) == 500
    assert idx.min() >= 0 and idx.max() < 500


def test_it_draws_blocks_not_independent_points() -> None:
    """Block structure is the whole point: an i.i.d. draw destroys volatility clustering and fat
    tails, which are exactly the features that decide whether a strategy survives."""
    idx = stationary_bootstrap_index(2000, rng=np.random.default_rng(1), mean_block=20)
    consecutive = int(np.sum(np.diff(idx) == 1))
    # With mean block 20, ~95% of steps continue a block. An i.i.d. sampler would give ~0.05%.
    assert consecutive > 1500, consecutive


def test_a_shorter_block_is_less_serially_dependent() -> None:
    long_run = stationary_bootstrap_index(2000, rng=np.random.default_rng(2), mean_block=50)
    short_run = stationary_bootstrap_index(2000, rng=np.random.default_rng(2), mean_block=2)
    assert int(np.sum(np.diff(long_run) == 1)) > int(np.sum(np.diff(short_run) == 1))


def test_it_wraps_so_every_observation_can_appear_anywhere() -> None:
    """Wrapping is what makes it *stationary* — without it the tails are under-sampled."""
    idx = stationary_bootstrap_index(50, rng=np.random.default_rng(3), mean_block=1000)
    assert int(np.sum(np.diff(idx) < 0)) >= 1, "a long block must wrap past the end"


def test_it_is_reproducible() -> None:
    a = stationary_bootstrap_index(100, rng=np.random.default_rng(7))
    b = stationary_bootstrap_index(100, rng=np.random.default_rng(7))
    assert np.array_equal(a, b), "a backtest whose null cannot be reproduced cannot be audited"


def test_an_empty_series_is_handled() -> None:
    assert len(stationary_bootstrap_index(0, rng=np.random.default_rng(0))) == 0


# ---- the floor -------------------------------------------------------------------------------------


def test_the_floor_is_the_requested_percentile() -> None:
    assert noise_floor([float(x) for x in range(101)], percentile=95) == Decimal("95.0")


def test_no_draws_is_refused_rather_than_returning_zero() -> None:
    """A floor computed from nothing would let ANY gap through — worse than having none."""
    with pytest.raises(ValueError, match="worse than none"):
        noise_floor([])


def test_the_summary_states_what_the_floor_means() -> None:
    text = summarise_null([1000.0, 2000.0, 3000.0])
    assert "no-skill draws" in text
    assert "not evidence" in text


def test_the_default_block_is_about_a_trading_month() -> None:
    """Short enough to resample, long enough to keep clustering — documented, not incidental."""
    assert DEFAULT_MEAN_BLOCK == 20
