"""Factor model + regime classification (Q_alpha.md §3.2).

Phase 0a ships the three price/volume factors (momentum, volatility, liquidity); Phase 0b adds the
fundamentals factors (value, quality, dividend). The scorer renormalises regime weights over
whichever factors are present, so 0a runs end-to-end before fundamentals data is sourced.
"""

from qalpha.factors.liquidity import liquidity
from qalpha.factors.momentum import momentum
from qalpha.factors.regime import Regime, classify_regime, regime_weights
from qalpha.factors.score import HIGHER_IS_BETTER, composite_score, sector_percentile_ranks
from qalpha.factors.volatility import volatility

__all__ = [
    "HIGHER_IS_BETTER",
    "Regime",
    "classify_regime",
    "composite_score",
    "liquidity",
    "momentum",
    "regime_weights",
    "sector_percentile_ranks",
    "volatility",
]
