"""Walk-forward backtest engine (Q_alpha.md §13, Phase 0).

Steps month by month over the price history. At each rebalance date it builds a look-ahead-safe
panel (``PriceData.as_of``), restricts it to the point-in-time universe, runs the funnel, and — only
if portfolio drift exceeds the threshold (§3.4/§4.2) — trades toward the new targets through the
cost/tax-aware :class:`Portfolio`. Every trading day it marks the portfolio to market to build a
daily equity curve for metrics.

Phase 0 deploys the full starting capital into the core strategy so the comparison against Nifty 50
/ SIP / equal-weight is apples-to-apples; the 50/25/25 pool split is a Phase-2 concern.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import cast

import pandas as pd

from qalpha.backtest.defensive import GovernanceEvents, idiosyncratic_exit_flags
from qalpha.backtest.portfolio import Portfolio, TradeRecord, to_decimal_price
from qalpha.backtest.strategy import select_and_weight
from qalpha.config import Config
from qalpha.data.fundamentals import FundamentalsStore
from qalpha.data.prices import PriceData
from qalpha.data.universe import Universe
from qalpha.factors.regime import Regime

RegimeFn = Callable[[date], Regime]


@dataclass(frozen=True)
class BacktestResult:
    """Outputs of a backtest run."""

    equity: pd.Series  # daily portfolio market value, indexed by date
    trades: list[TradeRecord]
    regimes: pd.Series  # daily regime label (str), indexed by date
    point_in_time_universe: bool
    starting_capital: Decimal
    defensive_exits: list[tuple[date, str]] = field(default_factory=list)  # (date, ticker) stops

    @property
    def total_costs(self) -> Decimal:
        return sum((t.cost for t in self.trades), Decimal("0.00"))

    @property
    def total_tax(self) -> Decimal:
        return sum((t.tax for t in self.trades), Decimal("0.00"))

    @property
    def n_rebalances(self) -> int:
        return len({t.date for t in self.trades})


def _rebalance_dates(
    trading_days: pd.DatetimeIndex, min_history: int, freq: str = "M"
) -> list[pd.Timestamp]:
    """Last trading day of each period, excluding the first ``min_history`` warm-up days.

    ``freq`` is a pandas period alias: ``M`` (monthly, default), ``Q`` (quarterly), ``Y`` (annual).
    Lower frequency = longer holds = fewer taxable events and more lots crossing the 365-day
    LTCG line (Q_alpha.md §2.1 "core is rarely touched"; §4.6 tax-aware gate).
    """
    if len(trading_days) <= min_history:
        return []
    eligible = trading_days[min_history:]
    s = pd.Series(eligible, index=eligible)
    period_last = s.groupby(eligible.to_period(freq)).last()
    return list(period_last)


def _drift(current: Mapping[str, float], target: pd.Series) -> float:
    """Sum of absolute weight deviations / 2 (Q_alpha.md §3.4)."""
    tickers = set(current) | {str(t) for t in target.index}
    total = 0.0
    for t in tickers:
        cur = current.get(t, 0.0)
        tgt = float(target.get(t, 0.0))
        total += abs(cur - tgt)
    return total / 2.0


def _default_regime_fn(_d: date) -> Regime:
    """Static BULL regime. Real India-VIX regime detection is a §16 calibration task."""
    return Regime.BULL


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
) -> bool:
    """§4.6 gate: execute only if annual risk reduction (₹) exceeds 2× the trade's cost+tax.

    Risk benefit is the drop in annualized portfolio volatility (a ₹/yr figure when scaled by
    portfolio value); cost is the real Zerodha cost + FIFO capital-gains tax from a dry-run.
    """
    value = float(portfolio.market_value(prices_dec))
    current_w = portfolio.current_weights(prices_dec)
    target_w = {str(t): float(w) for t, w in target.items()}

    vol_now = _annualized_vol(current_w, returns, cfg.optimizer.ewma_halflife_days)
    vol_target = _annualized_vol(target_w, returns, cfg.optimizer.ewma_halflife_days)
    risk_benefit_rs = max(0.0, vol_now - vol_target) * value

    cost, tax, _ = portfolio.estimate_rebalance(
        date.today(), target, prices_dec, min_trade_fraction=min_trade_fraction
    )
    friction = float(cost + tax)
    if friction <= 0:
        return True  # nothing to sell (no tax) and ~no cost: harmless to apply
    return risk_benefit_rs > float(cfg.optimizer.rebalance_net_benefit_multiple) * friction


def run_backtest(
    prices: PriceData,
    sector_of: dict[str, str],
    universe: Universe,
    cfg: Config,
    *,
    regime_fn: RegimeFn | None = None,
    start: str | None = None,
    end: str | None = None,
    tax_aware: bool = False,
    min_trade_fraction: float = 0.0,
    fundamentals: FundamentalsStore | None = None,
    rebalance_freq: str = "M",
    defensive: bool = False,
    governance_events: GovernanceEvents | None = None,
    force_refresh: bool = False,
    weighting: str = "minvar",
    n_stocks_override: int | None = None,
) -> BacktestResult:
    """Run the walk-forward backtest and return a :class:`BacktestResult`.

    ``tax_aware=True`` applies the §4.6 net-benefit gate (suppress a rebalance whose risk benefit
    doesn't beat 2× its real cost+tax). ``min_trade_fraction`` adds a per-name no-trade band.
    Passing ``fundamentals`` switches the funnel to the full six-factor model (Phase 0b).
    ``rebalance_freq`` (M/Q/Y) sets how often rebalancing is even *considered* — lower frequency
    means longer holds, fewer taxable events, and more lots maturing past the 365-day LTCG line.
    ``defensive=True`` adds the §3.6 *price* overlay: on month-ends between core rebalances it exits
    a holding in a sustained idiosyncratic breakdown (shown to whipsaw quality names — kept for the
    record). ``governance_events`` adds the §3.11 *event-driven* defence: a CRITICAL governance event
    freezes its ticker — exited between rebalances and blacklisted from re-purchase — which fires on
    a broken business (Yes Bank, Zee) without touching a merely-out-of-favour blue-chip.
    ``force_refresh=True`` makes every scheduled rebalance execute (band-limited) so the §4.6 gate
    can't freeze the book holding stale picks for years (the 2025-26 holdout failure mode).
    """
    regime_fn = regime_fn or _default_regime_fn
    adj = prices.adj_close
    start_ts = pd.Timestamp(start or cfg.backtest.start)
    end_ts = pd.Timestamp(end or cfg.backtest.end)
    trading_days = prices.dates[(prices.dates >= start_ts) & (prices.dates <= end_ts)]
    if len(trading_days) == 0:
        raise ValueError("no trading days in the requested window")

    min_history = cfg.factor.momentum_lookback_days + 1
    lookback = cfg.factor.momentum_lookback_days + 90
    rebalance_set = set(_rebalance_dates(trading_days, min_history, rebalance_freq))
    # Defensive scan runs on month-ends that are NOT core rebalance days (between rebalances).
    defensive_on = defensive or governance_events is not None
    defensive_days = (
        set(_rebalance_dates(trading_days, min_history, "M")) - rebalance_set
        if defensive_on
        else set()
    )

    portfolio = Portfolio(cfg.cost, cfg.tax, cash=cfg.capital.starting_capital)
    last_target: pd.Series | None = None
    trades: list[TradeRecord] = []
    defensive_exits: list[tuple[date, str]] = []

    equity_rows: list[tuple[pd.Timestamp, float]] = []
    regime_rows: list[tuple[pd.Timestamp, str]] = []

    for day in trading_days:
        d = day.date()
        price_row = cast(pd.Series, adj.loc[day]).dropna()
        prices_dec: dict[str, Decimal] = {}
        for ticker, raw in price_row.to_dict().items():
            value = float(raw)
            if value > 0:
                prices_dec[str(ticker)] = to_decimal_price(value)
        regime = regime_fn(d)

        if day in rebalance_set:
            members = universe.members_on(d)
            asof = prices.as_of(d, lookback=lookback)
            blacklist = governance_events.blacklisted_asof(d) if governance_events else set()
            in_scope = [t for t in members if t in asof.tickers and t not in blacklist]
            if len(in_scope) >= 2:
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
                    as_of=d,
                )
                if not target.empty:
                    current_w = portfolio.current_weights(prices_dec)
                    drift = _drift(current_w, target)
                    first = last_target is None
                    drift_ok = drift > cfg.optimizer.drift_threshold
                    benefit_ok = (not tax_aware) or _net_benefit_ok(
                        portfolio, target, prices_dec, asof.returns(), cfg, min_trade_fraction
                    )
                    # Deploying idle settled cash is tax-free and never "churn" — so it must not be
                    # blocked by the variance-reduction gate (cash→stocks looks like a risk *rise*).
                    # Without this, a portfolio driven to cash by defensive exits stays locked out
                    # of re-investing (§2.9 fresh-capital routing: overflow buys the underweights).
                    mv = core_value
                    cash_frac = float(portfolio.cash / mv) if mv > 0 else 0.0
                    under_invested = cash_frac > min_trade_fraction
                    # ``force_refresh`` makes the *scheduled* rebalance always execute (the no-trade
                    # band still suppresses dust trades, so it stays tax-efficient). It exists because
                    # the all-or-nothing §4.6 benefit gate, by refusing to sell appreciated winners,
                    # can FREEZE the book for years — leaving it holding stale picks (the 2025-26
                    # holdout failure mode). Refreshing re-selects current factor leaders on schedule.
                    if first or under_invested or force_refresh or (drift_ok and benefit_ok):
                        trades.extend(
                            portfolio.rebalance(
                                d, target, prices_dec, min_trade_fraction=min_trade_fraction
                            )
                        )
                        last_target = target
        elif day in defensive_days:
            held = [t for t, q in portfolio.positions().items() if q > 0]
            if held:
                flags: set[str] = set()
                if governance_events is not None:  # §3.11 event freeze (fires on broken businesses)
                    flags |= governance_events.blacklisted_asof(d) & set(held)
                if defensive:  # §3.6 price overlay (kept for the record; whipsaws quality names)
                    asof = prices.as_of(d, lookback=cfg.defensive.lookback_days + 10)
                    flags |= set(idiosyncratic_exit_flags(asof.adj_close, held, cfg.defensive))
                if flags:
                    recs = portfolio.liquidate(d, sorted(flags), prices_dec)
                    trades.extend(recs)
                    defensive_exits.extend((d, r.ticker) for r in recs)

        equity_rows.append((day, float(portfolio.market_value(prices_dec))))
        regime_rows.append((day, regime.value))

    equity = pd.Series(
        [v for _, v in equity_rows],
        index=pd.DatetimeIndex([d for d, _ in equity_rows]),
        name="equity",
    )
    regimes = pd.Series(
        [r for _, r in regime_rows],
        index=pd.DatetimeIndex([d for d, _ in regime_rows]),
        name="regime",
    )
    return BacktestResult(
        equity=equity,
        trades=trades,
        regimes=regimes,
        point_in_time_universe=universe.point_in_time,
        starting_capital=cfg.capital.starting_capital,
        defensive_exits=defensive_exits,
    )
