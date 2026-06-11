"""Regime classifier (Q_alpha.md §3.2, §4.7).

Phase-0 regime detection uses hard India-VIX thresholds (the spec flags these as §16 tunables to
calibrate via backtest; Tier-2 HMM/GMM replaces them after 12+ months of live data, §6.2). Each
regime selects a factor-weight vector. "Rotation" is signalled externally (sector-rotation flag),
not by VIX alone, so it is a separate argument.
"""

from __future__ import annotations

from enum import StrEnum

from qalpha.config import REGIME_FACTOR_WEIGHTS, RegimeConfig


class Regime(StrEnum):
    BULL = "bull"
    BEAR = "bear"
    HIGH_VOL = "high_vol"
    CRASH = "crash"
    ROTATION = "rotation"


def classify_regime(india_vix: float, cfg: RegimeConfig, *, rotation_flag: bool = False) -> Regime:
    """Map India VIX (and an optional rotation flag) to a :class:`Regime` (§4.7)."""
    if rotation_flag:
        return Regime.ROTATION
    if india_vix < cfg.vix_bull_max:
        return Regime.BULL
    if india_vix < cfg.vix_bear_max:
        return Regime.BEAR
    if india_vix < cfg.vix_high_vol_max:
        return Regime.HIGH_VOL
    return Regime.CRASH


def regime_weights(regime: Regime) -> dict[str, float]:
    """Return the per-factor weight dict for a regime (Q_alpha.md §3.2 weight table)."""
    from qalpha.config import FACTOR_NAMES

    weights = REGIME_FACTOR_WEIGHTS[regime.value]
    return dict(zip(FACTOR_NAMES, weights, strict=True))
