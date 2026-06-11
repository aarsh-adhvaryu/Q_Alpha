"""Performance metrics for an equity curve (Q_alpha.md §13 deliverable).

All metrics derive from a daily equity series. Returns are simple daily returns; annualisation uses
252 trading days. Per-regime breakdown segments the same daily returns by the regime label the
engine recorded, so the report can answer "did the strategy work in crashes vs bulls?".
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

_TRADING_DAYS = 252


@dataclass(frozen=True)
class PerformanceMetrics:
    """Headline risk/return metrics for one equity curve."""

    name: str
    final_value: float
    total_return: float
    cagr: float
    ann_volatility: float
    sharpe: float
    sortino: float
    max_drawdown: float
    calmar: float

    def as_row(self) -> dict[str, float | str]:
        return {
            "strategy": self.name,
            "final_₹": round(self.final_value, 0),
            "total_return_%": round(self.total_return * 100, 1),
            "cagr_%": round(self.cagr * 100, 1),
            "vol_%": round(self.ann_volatility * 100, 1),
            "sharpe": round(self.sharpe, 2),
            "sortino": round(self.sortino, 2),
            "max_dd_%": round(self.max_drawdown * 100, 1),
            "calmar": round(self.calmar, 2),
        }


def max_drawdown(equity: pd.Series) -> float:
    """Most negative peak-to-trough drawdown as a fraction (e.g. -0.23 for -23%)."""
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    return float(drawdown.min())


def compute_metrics(equity: pd.Series, name: str) -> PerformanceMetrics:
    """Compute headline metrics from a daily equity curve."""
    equity = equity.dropna()
    if len(equity) < 2 or equity.iloc[0] <= 0:
        raise ValueError(f"equity curve '{name}' too short or non-positive")

    rets = equity.pct_change().dropna()
    n_days = len(equity)
    years = n_days / _TRADING_DAYS
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    cagr = float((equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0) if years > 0 else 0.0

    daily_mean = float(rets.mean())
    daily_std = float(rets.std())
    ann_vol = daily_std * np.sqrt(_TRADING_DAYS)
    sharpe = (daily_mean * _TRADING_DAYS) / ann_vol if ann_vol > 0 else 0.0

    downside = rets[rets < 0]
    downside_std = float(downside.std()) * np.sqrt(_TRADING_DAYS) if len(downside) > 1 else 0.0
    sortino = (daily_mean * _TRADING_DAYS) / downside_std if downside_std > 0 else 0.0

    mdd = max_drawdown(equity)
    calmar = cagr / abs(mdd) if mdd < 0 else 0.0

    return PerformanceMetrics(
        name=name,
        final_value=float(equity.iloc[-1]),
        total_return=total_return,
        cagr=cagr,
        ann_volatility=ann_vol,
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown=mdd,
        calmar=calmar,
    )


@dataclass(frozen=True)
class RegimeMetrics:
    regime: str
    days: int
    pct_of_time: float
    ann_return: float
    ann_volatility: float
    sharpe: float


def per_regime_metrics(equity: pd.Series, regimes: pd.Series) -> list[RegimeMetrics]:
    """Annualised return/vol/Sharpe of the strategy within each recorded regime."""
    rets = equity.pct_change()
    df = pd.DataFrame({"ret": rets, "regime": regimes}).dropna()
    total = len(df)
    out: list[RegimeMetrics] = []
    for regime, group in df.groupby("regime"):
        r = group["ret"]
        ann_ret = float(r.mean()) * _TRADING_DAYS
        ann_vol = float(r.std()) * np.sqrt(_TRADING_DAYS)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0
        out.append(
            RegimeMetrics(
                regime=str(regime),
                days=len(r),
                pct_of_time=len(r) / total if total else 0.0,
                ann_return=ann_ret,
                ann_volatility=ann_vol,
                sharpe=sharpe,
            )
        )
    return out
