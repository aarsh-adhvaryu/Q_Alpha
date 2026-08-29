"""overlay_backtest.py — research-side backtest adding an *exposure* (deploy-throttle) overlay.

The validated qalpha engine has no exposure hook, and the product repo stays untouched (the repo
split / resume-clean rule). So this orchestrates a walk-forward loop that **reuses qalpha's validated
primitives** — ``decide_rebalance`` (the §4.6 tax-aware selection) and ``Portfolio`` (the FIFO
cost+tax accounting) — and adds only the experimental piece: scaling the executed target toward cash
when the regime risk-state says "stress". Every de-risk/re-risk therefore pays real Zerodha cost +
capital-gains tax, exactly as a live throttle would.

**Fidelity guarantee (the reason this is trustworthy).** With ``exposure ≡ 1.0`` the loop must
reproduce qalpha's ``run_backtest`` equity bit-for-bit: the only trades are the annual selection
rebalances (same ``decide_rebalance`` calls, same ``Portfolio``), and the monthly exposure check is a
no-op because exposure never changes. ``exp_riskstate.py`` asserts this. So any equity *difference*
under an active overlay is attributable to the overlay alone — not to a re-implemented engine.

Design choices that keep the selection identical to the always-invested baseline (clean A/B):
- Stock **selection** is annual and untouched — ``last_target`` passed to ``decide_rebalance`` is the
  *unscaled* funnel target, so the picks don't depend on the overlay.
- The **exposure** overlay acts only when the regime *transitions* (not to chase price drift), on a
  monthly grid between annual rebalances — mirroring the engine's existing monthly defensive cadence.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import cast

import numpy as np
import pandas as pd

from qalpha.backtest.decision import decide_rebalance
from qalpha.backtest.engine import _default_regime_fn, _rebalance_dates
from qalpha.backtest.portfolio import Portfolio, TradeRecord, to_decimal_price
from qalpha.config import Config
from qalpha.data.prices import PriceData
from qalpha.data.universe import Universe

# p_stress (filtered, in [0,1]) -> equity exposure (fraction to deploy, in [0,1]).
ExposureFn = Callable[[float], float]


@dataclass(frozen=True)
class OverlayResult:
    """Daily equity + the applied exposure path + the realised trade tape (real cost+tax)."""

    equity: pd.Series
    exposure: pd.Series
    trades: list[TradeRecord]
    n_overlay_trades: int  # rebalances triggered by an exposure transition (not annual selection)


def threshold_exposure(tau: float = 0.5, floor: float = 0.0) -> ExposureFn:
    """Binary deploy-throttle: full exposure until filtered P(stress) ≥ τ, then cut to ``floor``."""

    def fn(p_stress: float) -> float:
        if np.isnan(p_stress):
            return 1.0  # no signal yet (warmup) → stay fully invested
        return floor if p_stress >= tau else 1.0

    return fn


def _prices_dec_for(adj_row: pd.Series) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for ticker, raw in adj_row.dropna().to_dict().items():
        value = float(raw)
        if value > 0:
            out[str(ticker)] = to_decimal_price(value)
    return out


def run_overlay_backtest(
    prices: PriceData,
    sector_of: dict[str, str],
    universe: Universe,
    cfg: Config,
    *,
    p_stress: pd.Series,
    exposure_fn: ExposureFn,
    start: str | None = None,
    end: str | None = None,
    rebalance_freq: str = "Y",
    overlay_freq: str = "M",
    tax_aware: bool = True,
    min_trade_fraction: float = 0.10,
    weighting: str = "shrink",
    force_refresh: bool = True,
    n_stocks_override: int | None = None,
) -> OverlayResult:
    """Walk-forward backtest of the validated annual-``shrink`` strategy with an exposure overlay.

    ``p_stress`` is the filtered stress probability indexed by Timestamp; it is reindexed onto the
    trading days with a **causal** forward-fill (only past/present values reach any decision).
    """
    adj = prices.adj_close
    start_ts = pd.Timestamp(start or cfg.backtest.start)
    end_ts = pd.Timestamp(end or cfg.backtest.end)
    trading_days = prices.dates[(prices.dates >= start_ts) & (prices.dates <= end_ts)]
    if len(trading_days) == 0:
        raise ValueError("no trading days in the requested window")

    min_history = cfg.factor.momentum_lookback_days + 1
    lookback = cfg.factor.momentum_lookback_days + 90
    rebalance_set = set(_rebalance_dates(trading_days, min_history, rebalance_freq))
    overlay_set = set(_rebalance_dates(trading_days, min_history, overlay_freq)) - rebalance_set

    # Causal alignment of the signal onto trading days (ffill uses only the last *past* value).
    ps_aligned = p_stress.reindex(trading_days, method="ffill")

    portfolio = Portfolio(cfg.cost, cfg.tax, cash=cfg.capital.starting_capital)
    base_target: pd.Series | None = None  # last annual funnel target (unscaled, sums to ~1)
    last_target: pd.Series | None = None  # reference handed to the §4.6 gate (unscaled)
    applied_expo = 1.0
    trades: list[TradeRecord] = []
    n_overlay_trades = 0

    equity_rows: list[tuple[pd.Timestamp, float]] = []
    expo_rows: list[tuple[pd.Timestamp, float]] = []

    for day in trading_days:
        d = day.date()
        prices_dec = _prices_dec_for(cast(pd.Series, adj.loc[day]))
        ps = float(ps_aligned.loc[day])
        expo = exposure_fn(ps)

        selection_changed = False
        if day in rebalance_set:
            decision = decide_rebalance(
                prices=prices,
                universe=universe,
                sector_of=sector_of,
                cfg=cfg,
                portfolio=portfolio,
                as_of=d,
                regime=_default_regime_fn(d),
                prices_dec=prices_dec,
                last_target=last_target,
                lookback=lookback,
                tax_aware=tax_aware,
                min_trade_fraction=min_trade_fraction,
                force_refresh=force_refresh,
                weighting=weighting,
                n_stocks_override=n_stocks_override,
            )
            if decision.execute and decision.target is not None and not decision.target.empty:
                base_target = decision.target
                last_target = decision.target  # keep selection independent of the overlay
                selection_changed = True

        exposure_changed = base_target is not None and abs(expo - applied_expo) > 1e-9
        act = base_target is not None and (selection_changed or exposure_changed)
        if act and base_target is not None and (day in rebalance_set or day in overlay_set):
            effective = base_target * expo
            new_trades = portfolio.rebalance(
                d, effective, prices_dec, min_trade_fraction=min_trade_fraction
            )
            trades.extend(new_trades)
            if exposure_changed and not selection_changed:
                n_overlay_trades += 1
            applied_expo = expo

        equity_rows.append((day, float(portfolio.market_value(prices_dec))))
        expo_rows.append((day, applied_expo))

    equity = pd.Series(
        [v for _, v in equity_rows],
        index=pd.DatetimeIndex([d for d, _ in equity_rows]),
        name="equity",
    )
    exposure = pd.Series(
        [v for _, v in expo_rows],
        index=pd.DatetimeIndex([d for d, _ in expo_rows]),
        name="exposure",
    )
    return OverlayResult(
        equity=equity, exposure=exposure, trades=trades, n_overlay_trades=n_overlay_trades
    )
