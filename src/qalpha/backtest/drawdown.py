"""Dynamic drawdown control (Q_alpha.md §0, three-part rule).

A flat absolute drawdown freeze is rejected (see §0): it misfires at crash bottoms. Drawdown is
split into the two jobs it conflates:

1. **Absolute drawdown → posture.** Large absolute drawdown = the *market* fell; set defensive
   posture, never a hard halt.
2. **Excess (relative) drawdown vs benchmark, adaptive threshold → the real "strategy broken"
   halt.** Trigger only when relative underperformance exceeds the strategy's own historical
   95th-percentile **and** is sustained for a confirmation window — so ordinary factor droughts
   (e.g. the −18.6% relative drawdown in the 2014 beta rally) do not trip it.
3. **Catastrophic absolute backstop → human alert** for true tail events.

In the Phase-0 backtest this runs as a *monitor* (it reports when each part would fire) rather than
actively halting — the active halt belongs in the live decision engine (Phase 4). The relative
series starts at the first *active* date (first deviation from flat starting cash) so the warm-up
cash-drag period isn't mismeasured as underperformance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

import pandas as pd


class DrawdownState(StrEnum):
    NORMAL = "normal"
    DEFENSIVE = "defensive"  # large absolute DD, but not a strategy failure
    STRATEGY_HALT = "strategy_halt"  # adaptive excess-DD trigger fired
    CATASTROPHIC = "catastrophic"  # deep absolute DD -> human alert


@dataclass(frozen=True)
class DrawdownConfig:
    defensive_abs: float = 0.20  # absolute DD that flips to defensive posture (§4.7)
    catastrophic_abs: float = 0.40  # deep absolute DD -> human alert
    excess_percentile: float = 0.95  # adaptive relative-DD threshold percentile
    excess_floor: float = 0.20  # never trigger on relative DD shallower than this
    excess_confirm_days: int = 60  # sustained underperformance required before halt


def underwater(equity: pd.Series) -> pd.Series:
    """Drawdown series: value / running-peak − 1 (≤ 0)."""
    return equity / equity.cummax() - 1.0


def first_active_date(equity: pd.Series) -> date:
    """First date the curve deviates from its starting value (first trade) — drops cash-drag warmup."""
    changed = equity[equity != equity.iloc[0]]
    ts = changed.index[0] if len(changed) else equity.index[0]
    return pd.Timestamp(ts).date()


def relative_underwater(equity: pd.Series, benchmark: pd.Series) -> pd.Series:
    """Drawdown of the strategy/benchmark ratio — the strategy-specific underperformance metric."""
    aligned = benchmark.reindex(equity.index).ffill().bfill()
    rel = (equity / equity.iloc[0]) / (aligned / aligned.iloc[0])
    return underwater(rel)


@dataclass(frozen=True)
class DrawdownSummary:
    """Drawdown analysis for one backtest run (the §0/criterion-8 evidence)."""

    abs_max_dd: float
    abs_max_dd_date: date
    benchmark_dd_at_abs_max: float  # what the benchmark was doing at the strategy's worst moment
    excess_max_dd: float  # worst strategy-vs-benchmark drawdown, from first active date
    excess_max_dd_date: date
    catastrophic_fired: bool
    strategy_halt_fired: bool

    @property
    def criterion8_pass(self) -> bool:
        """Dynamic criterion 8: no catastrophic tail and no sustained strategy-specific failure."""
        return not self.catastrophic_fired and not self.strategy_halt_fired


def _strategy_halt_fires(rel_dd: pd.Series, cfg: DrawdownConfig) -> bool:
    """True if relative DD ever exceeds its adaptive threshold, sustained for the confirm window.

    Adaptive threshold at each point = max(floor, expanding 95th percentile of |relative DD|). A
    halt requires the current relative DD to be below that threshold (i.e. deeper underperformance)
    continuously for ``excess_confirm_days``.
    """
    depth = -rel_dd  # positive magnitude of relative drawdown
    threshold = (
        depth.expanding(min_periods=252)
        .quantile(cfg.excess_percentile)
        .clip(lower=cfg.excess_floor)
    )
    breached = (depth > threshold).fillna(False)
    # Require a sustained run of >= confirm_days consecutive breached days.
    run = breached.groupby((~breached).cumsum()).cumcount() + 1
    return bool((run.where(breached, 0) >= cfg.excess_confirm_days).any())


def summarize(
    equity: pd.Series,
    benchmark: pd.Series,
    cfg: DrawdownConfig | None = None,
) -> DrawdownSummary:
    """Compute the dynamic-drawdown summary for an equity curve vs its benchmark."""
    cfg = cfg or DrawdownConfig()
    abs_dd = underwater(equity)
    abs_min_date = pd.Timestamp(abs_dd.idxmin()).date()

    bench_aligned = benchmark.reindex(equity.index).ffill().bfill()
    bench_dd = underwater(bench_aligned)

    active = pd.Timestamp(first_active_date(equity))
    rel_dd = relative_underwater(equity.loc[active:], bench_aligned.loc[active:])

    return DrawdownSummary(
        abs_max_dd=float(abs_dd.min()),
        abs_max_dd_date=abs_min_date,
        benchmark_dd_at_abs_max=float(bench_dd.loc[abs_dd.idxmin()]),
        excess_max_dd=float(rel_dd.min()),
        excess_max_dd_date=pd.Timestamp(rel_dd.idxmin()).date(),
        catastrophic_fired=bool(abs_dd.min() <= -cfg.catastrophic_abs),
        strategy_halt_fired=_strategy_halt_fires(rel_dd, cfg),
    )
