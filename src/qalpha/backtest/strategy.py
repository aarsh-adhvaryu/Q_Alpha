"""The funnel as a single function (Q_alpha.md §3.1): screen -> sector bounds -> stock weights.

``select_and_weight`` takes a *look-ahead-safe* price panel (already sliced via ``as_of``) plus the
investable universe and sector map for that date, and returns target stock weights. Phase 0a uses
the three price/volume factors; Phase 0b will pass more factor columns and the same code path runs.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from qalpha.alloc.optimizer import optimize_weights
from qalpha.alloc.sectors import allocate_sectors, sector_returns_from_stocks
from qalpha.config import Config
from qalpha.data.fundamentals import FundamentalsStore
from qalpha.data.prices import PriceData
from qalpha.factors.fundamental import dividend, quality, value
from qalpha.factors.liquidity import liquidity, passes_liquidity_gate
from qalpha.factors.momentum import momentum
from qalpha.factors.regime import Regime, regime_weights
from qalpha.factors.score import composite_score
from qalpha.factors.volatility import volatility


def _price_volume_factor_frame(prices: PriceData, cfg: Config) -> pd.DataFrame:
    """Compute the Phase-0a (price/volume) raw factor columns at the panel's last date."""
    return pd.DataFrame(
        {
            "momentum": momentum(
                prices, cfg.factor.momentum_lookback_days, cfg.factor.momentum_skip_days
            ),
            "volatility": volatility(
                prices, cfg.factor.volatility_window_days, cfg.factor.trading_days_per_year
            ),
            "liquidity": liquidity(prices, cfg.liquidity.adv_window_days),
        }
    )


def _add_fundamental_factors(
    factor_frame: pd.DataFrame,
    panel: PriceData,
    sector_of: dict[str, str],
    fundamentals: FundamentalsStore,
    as_of: date,
) -> pd.DataFrame:
    """Append Value/Quality/Dividend columns (Phase 0b) using point-in-time fundamentals."""
    raw_price = panel.close_raw.iloc[-1]  # P/E uses actual (non-TR-adjusted) price
    factor_frame["value"] = value(fundamentals, raw_price, sector_of, as_of)
    factor_frame["quality"] = quality(fundamentals, raw_price, sector_of, as_of)
    factor_frame["dividend"] = dividend(fundamentals, list(panel.tickers), as_of)
    return factor_frame


def _cap_renorm(w: pd.Series, cap: float) -> pd.Series:
    """Clip weights to ``cap`` and renormalise to sum 1 (one pass; good enough for screens)."""
    w = w.clip(upper=cap)
    total = w.sum()
    return w / total if total > 0 else w


def select_and_weight(
    prices: PriceData,
    sector_of: dict[str, str],
    regime: Regime,
    cfg: Config,
    *,
    n_stocks: int,
    fundamentals: FundamentalsStore | None = None,
    as_of: date | None = None,
    weighting: str = "minvar",
) -> pd.Series:
    """Return target stock weights (sums to ~1), or an empty Series if nothing qualifies.

    Steps: liquidity gate -> factor scores -> top-N selection -> weighting. ``weighting`` chooses the
    final step (the Track-A lever the OOS holdout motivated — 1/N keeps winning, so test breadth):
      * ``minvar`` — sector allocator + min-variance optimiser (the concentrated production default);
      * ``equal``  — 1/N across the selected names (breadth, like the winning baseline);
      * ``score``  — tilt ∝ composite score (capped at the per-stock max);
      * ``shrink`` — 50/50 blend of minvar and equal (the DeMiguel-style anchor-to-1/N hybrid).
    Passing ``fundamentals`` + ``as_of`` enables the full six-factor model (Phase 0b).
    """
    # 1) Liquidity gate (core ADV threshold) — hard pre-screen (§3.2/§3.3).
    adv = liquidity(prices, cfg.liquidity.adv_window_days)
    gate = passes_liquidity_gate(adv, cfg.liquidity.min_adv_core)
    eligible = [t for t in prices.tickers if bool(gate.get(t, False))]
    if len(eligible) < 2:
        return pd.Series(dtype="float64")

    panel = prices.subset(eligible)

    # 2) Factor scores under the active regime's weights (3 factors, or 6 with fundamentals).
    factor_frame = _price_volume_factor_frame(panel, cfg)
    if fundamentals is not None and as_of is not None:
        factor_frame = _add_fundamental_factors(factor_frame, panel, sector_of, fundamentals, as_of)
    scores = composite_score(factor_frame, sector_of, regime_weights(regime)).dropna()
    if scores.empty:
        return pd.Series(dtype="float64")

    # 3) Top-N selection.
    selected = scores.sort_values(ascending=False).head(n_stocks).index.tolist()
    if len(selected) < 2:
        return pd.Series(dtype="float64")

    sel_panel = panel.subset(selected)
    returns = sel_panel.returns()
    cap = cfg.optimizer.max_single_stock

    # 3b) Non-minvar weighting schemes (breadth / anchor-to-1/N): return directly.
    if weighting == "equal":
        return _cap_renorm(pd.Series(1.0, index=selected), cap)
    if weighting == "score":
        pos = scores.loc[selected].clip(lower=0.0)
        base = pos if pos.sum() > 0 else pd.Series(1.0, index=selected)
        return _cap_renorm(base, cap)

    # 4) Sector allocator over the sectors present among selected stocks.
    sectors_present = {sector_of.get(t, "UNKNOWN") for t in selected}
    if len(sectors_present) < 2:
        # All in one sector: the sector allocator (which needs the 5-30% bounds to sum to 1) can't
        # run, so weight purely by the optimizer with a single 100% sector target.
        sector_targets = pd.Series(dict.fromkeys(sectors_present, 1.0))
    else:
        sector_rets = sector_returns_from_stocks(returns, sector_of)
        try:
            sector_targets = allocate_sectors(sector_rets, cfg.optimizer)
        except ValueError:
            # Bounds infeasible for the number of present sectors -> equal-weight the sectors.
            sector_targets = pd.Series({s: 1.0 / len(sectors_present) for s in sectors_present})

    # 5) Portfolio optimizer: exact stock weights within sector totals.
    weights = optimize_weights(returns, sector_of, sector_targets, cfg.optimizer)
    if weighting == "shrink":  # anchor the optimiser halfway to 1/N (robust to covariance noise)
        equal = pd.Series(1.0 / len(selected), index=selected)
        weights = 0.5 * weights.reindex(selected).fillna(0.0) + 0.5 * equal
    return weights[weights > 1e-6]
