"""Square-root market-impact slippage (§13): monotonicity, clamps, and the calibration anchor.

The load-bearing property is that slippage rises with order size and with volatility, falls with
liquidity, and reduces to the legacy flat 0.2% at the §3.3 order-size cap (1% of ADV, 2% daily vol)
when impact_k=1 — so turning the model on is a principled generalisation, not a recalibration.
"""

from __future__ import annotations

from decimal import Decimal

from qalpha.accounting.slippage import (
    FlatSlippage,
    SquareRootSlippage,
    square_root_impact_pct,
)

_K = Decimal("1.0")
_FLOOR = Decimal("0.0002")
_CAP = Decimal("0.02")


def _pct(trade_value: float, adv: float, vol: float) -> float:
    return float(
        square_root_impact_pct(Decimal(str(trade_value)), adv, vol, k=_K, floor=_FLOOR, cap=_CAP)
    )


def test_calibration_anchor_matches_flat_at_order_size_cap() -> None:
    # Order = 1% of ADV (the §3.3 cap), daily vol 2% → k·σ·√(0.01) = 1·0.02·0.1 = 0.002 = 0.2%.
    adv = 1_000_000.0
    assert abs(_pct(0.01 * adv, adv, 0.02) - 0.002) < 1e-9


def test_monotonic_in_size_and_vol_inverse_in_liquidity() -> None:
    adv = 5_000_000.0
    small = _pct(10_000.0, adv, 0.02)
    big = _pct(200_000.0, adv, 0.02)
    assert big > small  # larger order → more impact
    assert _pct(50_000.0, adv, 0.04) > _pct(50_000.0, adv, 0.02)  # more vol → more impact
    assert _pct(50_000.0, adv, 0.02) > _pct(50_000.0, 10 * adv, 0.02)  # deeper book → less impact


def test_floor_and_cap_clamp() -> None:
    adv = 1_000_000_000.0
    assert _pct(1.0, adv, 0.001) == float(_FLOOR)  # vanishingly small order → floored
    # Huge order in a thin, volatile name → capped, not unbounded.
    assert _pct(10_000_000.0, 100_000.0, 0.06) == float(_CAP)


def test_unknown_or_illiquid_is_conservative_cap() -> None:
    assert _pct(50_000.0, 0.0, 0.02) == float(_CAP)  # zero ADV
    assert _pct(50_000.0, 1_000_000.0, 0.0) == float(_CAP)  # zero vol
    assert _pct(50_000.0, float("nan"), 0.02) == float(_CAP)  # missing data
    assert _pct(0.0, 1_000_000.0, 0.02) == float(_CAP)  # non-positive trade


def test_flat_model_is_size_blind() -> None:
    flat = FlatSlippage(Decimal("0.002"))
    assert flat.pct("X", Decimal("1000")) == Decimal("0.002")
    assert flat.pct("X", Decimal("10000000")) == Decimal("0.002")


def test_square_root_model_reads_per_ticker_maps() -> None:
    model = SquareRootSlippage(
        adv={"LIQUID.NS": 5_000_000.0, "THIN.NS": 200_000.0},
        daily_vol={"LIQUID.NS": 0.02, "THIN.NS": 0.05},
        k=_K,
        floor=_FLOOR,
        cap=_CAP,
    )
    tv = Decimal("100000")
    assert model.pct("THIN.NS", tv) > model.pct("LIQUID.NS", tv)  # thinner+more vol → worse
    assert model.pct("UNKNOWN.NS", tv) == _CAP  # not in the maps → conservative
