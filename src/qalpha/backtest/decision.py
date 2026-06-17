"""The per-rebalance decision, shared by the backtest and the live runner (Q_alpha.md §3, §4.6).

This is **the production decision**: given a date, the current portfolio, and a look-ahead-safe
price panel, it runs the funnel (``select_and_weight``) to get target weights and then decides
whether to execute — the §4.6 net-benefit gate, the no-trade band, the first-deploy / idle-cash /
force-refresh overrides. The backtest calls it at every rebalance; the live daily runner and the
replay harness call the *exact same function*, so what was validated in-sample is literally the code
that runs live. The decision is **pure**: it reads portfolio state (including a dry-run cost/tax
estimate) but never mutates it — the caller applies ``target`` via ``Portfolio.rebalance``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd

from qalpha.backtest.portfolio import Portfolio
from qalpha.backtest.strategy import select_and_weight
from qalpha.config import Config
from qalpha.data.fundamentals import FundamentalsStore
from qalpha.data.prices import PriceData
from qalpha.data.universe import Universe
from qalpha.factors.regime import Regime


@dataclass(frozen=True)
class RebalanceDecision:
    """Outcome of evaluating one rebalance date.

    ``target`` is the funnel's weight vector (``None`` when no valid selection exists); ``execute``
    is whether the gates cleared. ``reason`` is a human-readable explanation for the daily approval
    log. ``actionable`` is the single condition the caller checks before trading.
    """

    as_of: date
    target: pd.Series | None
    execute: bool
    reason: str
    n_candidates: int

    @property
    def actionable(self) -> bool:
        return self.execute and self.target is not None and not self.target.empty


def _drift(current: Mapping[str, float], target: pd.Series) -> float:
    """Sum of absolute weight deviations / 2 (Q_alpha.md §3.4)."""
    tickers = set(current) | {str(t) for t in target.index}
    total = 0.0
    for t in tickers:
        cur = current.get(t, 0.0)
        tgt = float(target.get(t, 0.0))
        total += abs(cur - tgt)
    return total / 2.0


def _annualized_vol(weights: Mapping[str, float], returns: pd.DataFrame, halflife: int) -> float:
    """Annualized portfolio volatility for ``weights`` using conditioned covariance of ``returns``."""
    import numpy as np

    from qalpha.alloc.conditioning import conditioned_covariance

    cols = [t for t in returns.columns if weights.get(str(t), 0.0) != 0.0]
    if len(cols) < 2:
        return 0.0
    cov = conditioned_covariance(returns[cols], halflife=halflife)
    w = np.array([weights.get(str(t), 0.0) for t in cov.tickers], dtype=float)
    var = float(w @ cov.matrix @ w)
    return float(np.sqrt(max(var, 0.0) * 252.0))


def _net_benefit_ok(
    portfolio: Portfolio,
    target: pd.Series,
    prices_dec: Mapping[str, Decimal],
    returns: pd.DataFrame,
    cfg: Config,
    min_trade_fraction: float,
    as_of: date,
) -> bool:
    """§4.6 gate: execute only if annual risk reduction (₹) exceeds 2× the trade's cost+tax.

    Risk benefit is the drop in annualized portfolio volatility (a ₹/yr figure when scaled by
    portfolio value); cost is the real Zerodha cost + FIFO capital-gains tax from a dry-run.

    The dry-run is dated at ``as_of`` (the decision date), NOT wall-clock ``date.today()``: the FIFO
    holding-period drives the STCG/LTCG split and the FY ₹1.25L exemption bucket, so a historical
    backtest rebalance must estimate its tax as of *that* date — otherwise every lot looks long-term
    and the gate systematically under-estimates tax. Live, ``as_of`` is today, so this is also correct.
    """
    value = float(portfolio.market_value(prices_dec))
    current_w = portfolio.current_weights(prices_dec)
    target_w = {str(t): float(w) for t, w in target.items()}

    vol_now = _annualized_vol(current_w, returns, cfg.optimizer.ewma_halflife_days)
    vol_target = _annualized_vol(target_w, returns, cfg.optimizer.ewma_halflife_days)
    risk_benefit_rs = max(0.0, vol_now - vol_target) * value

    cost, tax, _ = portfolio.estimate_rebalance(
        as_of, target, prices_dec, min_trade_fraction=min_trade_fraction
    )
    friction = float(cost + tax)
    if friction <= 0:
        return True  # nothing to sell (no tax) and ~no cost: harmless to apply
    return risk_benefit_rs > float(cfg.optimizer.rebalance_net_benefit_multiple) * friction


def decide_rebalance(
    *,
    prices: PriceData,
    universe: Universe,
    sector_of: dict[str, str],
    cfg: Config,
    portfolio: Portfolio,
    as_of: date,
    regime: Regime,
    prices_dec: Mapping[str, Decimal],
    last_target: pd.Series | None,
    lookback: int,
    blacklist: set[str] | None = None,
    tax_aware: bool = False,
    min_trade_fraction: float = 0.0,
    force_refresh: bool = False,
    weighting: str = "minvar",
    n_stocks_override: int | None = None,
    fundamentals: FundamentalsStore | None = None,
) -> RebalanceDecision:
    """Run the funnel and the §4.6 execution gate for ``as_of``; return a :class:`RebalanceDecision`.

    Mirrors exactly the rebalance branch of :func:`qalpha.backtest.engine.run_backtest` — the engine
    now delegates to this function so the backtest and the live path can never diverge.
    """
    blacklist = blacklist or set()
    members = universe.members_on(as_of)
    asof = prices.as_of(as_of, lookback=lookback)
    in_scope = [t for t in members if t in asof.tickers and t not in blacklist]
    if len(in_scope) < 2:
        return RebalanceDecision(
            as_of, None, False, "fewer than 2 investable names in scope", len(in_scope)
        )

    asof = asof.subset(in_scope)
    core_value = portfolio.market_value(prices_dec)
    n_stocks = n_stocks_override or cfg.capital.max_core_stocks(core_value)
    target = select_and_weight(
        asof,
        sector_of,
        regime,
        cfg,
        weighting=weighting,
        n_stocks=n_stocks,
        fundamentals=fundamentals,
        as_of=as_of,
    )
    if target.empty:
        return RebalanceDecision(
            as_of, None, False, "funnel produced no target weights", len(in_scope)
        )

    current_w = portfolio.current_weights(prices_dec)
    drift = _drift(current_w, target)
    first = last_target is None
    drift_ok = drift > cfg.optimizer.drift_threshold
    benefit_ok = (not tax_aware) or _net_benefit_ok(
        portfolio, target, prices_dec, asof.returns(), cfg, min_trade_fraction, as_of
    )
    # Deploying idle settled cash is tax-free and never "churn" — so it must not be blocked by the
    # variance-reduction gate (cash→stocks looks like a risk *rise*). Without this, a portfolio
    # driven to cash by defensive exits stays locked out of re-investing (§2.9 fresh-capital routing).
    mv = core_value
    cash_frac = float(portfolio.cash / mv) if mv > 0 else 0.0
    under_invested = cash_frac > min_trade_fraction
    # ``force_refresh`` makes the *scheduled* rebalance always execute (the no-trade band still
    # suppresses dust trades). It exists because the all-or-nothing §4.6 benefit gate, by refusing to
    # sell appreciated winners, can FREEZE the book for years holding stale picks (the 2025-26 holdout
    # failure mode). Refreshing re-selects current factor leaders on schedule.
    execute = first or under_invested or force_refresh or (drift_ok and benefit_ok)
    reason = _explain(
        first=first,
        under_invested=under_invested,
        force_refresh=force_refresh,
        drift_ok=drift_ok,
        benefit_ok=benefit_ok,
        drift=drift,
    )
    return RebalanceDecision(as_of, target, execute, reason, len(in_scope))


def _explain(
    *,
    first: bool,
    under_invested: bool,
    force_refresh: bool,
    drift_ok: bool,
    benefit_ok: bool,
    drift: float,
) -> str:
    """Human-readable why-string for the daily approval log (does not affect the decision)."""
    if first:
        return "first deployment of capital"
    if under_invested:
        return "idle cash above the no-trade band → redeploy (tax-free)"
    if force_refresh:
        return f"scheduled refresh (force_refresh); drift {drift:.1%}"
    if drift_ok and benefit_ok:
        return f"drift {drift:.1%} > threshold and §4.6 net-benefit gate cleared"
    if not drift_ok:
        return f"hold: drift {drift:.1%} below threshold"
    return "hold: §4.6 net-benefit gate not cleared (risk cut < 2× cost+tax)"
