"""fragility.py — cause-agnostic systemic-fragility + stress gauge for Indian equities.

Pre-registered in PREREGISTRATION_systemic.md (Sprint 2, P1). The thesis: you cannot predict the
*trigger* of a crash (2008 contagion, oil, USD-INR, war, domestic, COVID), but you CAN measure the
shared, cause-agnostic state — how much *fragility* (dry tinder) exists and whether *stress* (the
fire) is starting. This module turns the cross-asset panel (`data/fragility_panel.csv`) into two
causal sub-scores in [0,1] plus a composite:

- **STRESS** (coincident, "it's burning"): US/India vol, bond vol, a credit-stress proxy (HYG/LQD
  drawdown), USD-INR & dollar spikes, equity drawdown, and India↔global correlation rising toward 1
  (contagion). Spikes *at* a crash.
- **FRAGILITY** (leading, "dry tinder"): price extension of global tech (NASDAQ) and India (Sensex)
  above their own long trend. Elevated in euphoric run-ups (2007, 2017–18, 2021).

Every feature is **causal**: a value at date t is a trailing-window percentile rank using only data
≤ t (the same no-look-ahead discipline as the HMM filtered posterior). Factors start on different
dates (India VIX only 2008+); the composite averages whatever factors exist on each date — a factor
with no history yet simply abstains.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

# Feature → ("stress" | "fragility") block membership, for the two sub-scores.
STRESS_FEATURES = ("vix", "move", "india_vix", "credit", "usdinr", "dxy", "drawdown", "contagion")
FRAGILITY_FEATURES = ("ext_nasdaq", "ext_sensex")


@dataclass(frozen=True)
class FragilityConfig:
    """Windows for the causal features. Defaults a priori; tune only on the pre-2015 train span."""

    pct_window: int = 1000  # ~4y trailing window for percentile ranks
    pct_min: int = 252  # need ≥1y before a percentile is emitted
    mom_window: int = 21  # 1m change for USD-INR / DXY spikes
    dd_window: int = 252  # 1y trailing high for equity drawdown
    corr_window: int = 63  # ~3m rolling correlation for contagion
    trend_window: int = 200  # long MA for price extension (fragility)


def _causal_pct_rank(s: pd.Series, window: int, min_periods: int) -> pd.Series:
    """Trailing-window percentile rank in [0,1]: fraction of the window ≤ today's value.

    Causal — the window ends at t, so only past/present data is used (no look-ahead).
    """
    return s.rolling(window, min_periods=min_periods).apply(
        lambda a: float((a <= a[-1]).mean()), raw=True
    )


def _drawdown(s: pd.Series, window: int) -> pd.Series:
    """Drawdown from the trailing rolling high (≤ 0)."""
    return s / s.rolling(window, min_periods=1).max() - 1.0


@dataclass
class FragilityResult:
    stress: pd.Series
    fragility: pd.Series
    composite: pd.Series  # headline gauge = STRESS (fragility proxy dropped; see compute_fragility)
    features: pd.DataFrame  # the per-factor causal percentiles (audit trail)
    coverage: pd.Series = field(default_factory=pd.Series)  # # factors available each day


def compute_fragility(
    panel: pd.DataFrame, config: FragilityConfig | None = None
) -> FragilityResult:
    """Build the causal stress/fragility sub-scores from the cross-asset panel."""
    cfg = config or FragilityConfig()
    w, mp = cfg.pct_window, cfg.pct_min
    feats: dict[str, pd.Series] = {}

    def has(*cols: str) -> bool:
        return all(c in panel.columns for c in cols)

    # ---- STRESS block (higher raw value already means more stress unless noted) ----
    if has("us_vix"):
        feats["vix"] = _causal_pct_rank(panel["us_vix"], w, mp)
    if has("move"):
        feats["move"] = _causal_pct_rank(panel["move"], w, mp)
    if has("india_vix"):
        feats["india_vix"] = _causal_pct_rank(panel["india_vix"], w, mp)
    if has("hyg", "lqd"):  # credit stress = HYG/LQD ratio falling → its drawdown deepening
        credit_dd = _drawdown(panel["hyg"] / panel["lqd"], cfg.dd_window)
        feats["credit"] = _causal_pct_rank(-credit_dd, w, mp)  # deeper drawdown → higher stress
    if has("usdinr"):  # INR depreciation (positive 1m change) = stress
        feats["usdinr"] = _causal_pct_rank(panel["usdinr"].pct_change(cfg.mom_window), w, mp)
    if has("dxy"):  # dollar spike = EM funding stress
        feats["dxy"] = _causal_pct_rank(panel["dxy"].pct_change(cfg.mom_window), w, mp)
    india = "sensex" if has("sensex") else ("nifty" if has("nifty") else None)
    if india is not None:  # deeper equity drawdown = stress
        feats["drawdown"] = _causal_pct_rank(-_drawdown(panel[india], cfg.dd_window), w, mp)
    if india is not None and has("sp500"):  # India↔global correlation → 1 = contagion
        corr = panel[india].pct_change().rolling(cfg.corr_window).corr(panel["sp500"].pct_change())
        feats["contagion"] = _causal_pct_rank(corr, w, mp)

    # ---- FRAGILITY block (price extension above long trend = dry tinder) ----
    if has("nasdaq"):
        ext = panel["nasdaq"] / panel["nasdaq"].rolling(cfg.trend_window, min_periods=50).mean() - 1
        feats["ext_nasdaq"] = _causal_pct_rank(ext, w, mp)
    if india is not None:
        ext = panel[india] / panel[india].rolling(cfg.trend_window, min_periods=50).mean() - 1
        feats["ext_sensex"] = _causal_pct_rank(ext, w, mp)

    features = pd.DataFrame(feats, index=panel.index)
    stress_cols = [c for c in STRESS_FEATURES if c in features.columns]
    frag_cols = [c for c in FRAGILITY_FEATURES if c in features.columns]
    stress = features[stress_cols].mean(axis=1, skipna=True)
    fragility = features[frag_cols].mean(axis=1, skipna=True)
    # Composite = STRESS. The price-extension fragility proxy validated as too "always-on" in a bull
    # market (≈0.68 in every calm year — see reports/fragility_gauge_validation.md), so it is NOT
    # blended into the headline gauge; it is reported as context until true valuation inputs (index
    # P/E, credit-spread tightness, concentration) replace the price proxy (a later data task).
    composite = stress.copy()

    return FragilityResult(
        stress=stress.rename("stress"),
        fragility=fragility.rename("fragility"),
        composite=composite.rename("composite"),
        features=features,
        coverage=features.notna().sum(axis=1).rename("coverage"),
    )
