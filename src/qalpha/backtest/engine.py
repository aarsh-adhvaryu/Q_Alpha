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

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import cast

import pandas as pd

from qalpha.accounting.slippage import SquareRootSlippage
from qalpha.backtest.decision import RebalanceDecision, decide_rebalance
from qalpha.backtest.defensive import GovernanceEvents, idiosyncratic_exit_flags
from qalpha.backtest.portfolio import Portfolio, TradeRecord, to_decimal_price
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


def _default_regime_fn(_d: date) -> Regime:
    """Static BULL regime. Real India-VIX regime detection is a §16 calibration task."""
    return Regime.BULL


def _impact_model(prices: PriceData, as_of: date, cfg: Config) -> SquareRootSlippage:
    """Build a causal (as-of) square-root-slippage snapshot: per-ticker ₹ADV + daily vol (§13).

    Uses only data ≤ ``as_of`` (via ``PriceData.as_of``), so the cost charged to a historical trade
    never peeks at future liquidity/volatility. ADV is the §3.3 rolling traded value; daily vol is
    the std of recent daily returns over the volatility window.
    """
    win = max(cfg.liquidity.adv_window_days, cfg.factor.volatility_window_days)
    asof = prices.as_of(as_of, lookback=win + 10)
    adv = asof.adv(cfg.liquidity.adv_window_days).iloc[-1]
    rets = asof.returns()
    vol = rets.iloc[-cfg.factor.volatility_window_days :].std()
    return SquareRootSlippage(
        adv={str(t): float(v) for t, v in adv.items()},
        daily_vol={str(t): float(v) for t, v in vol.items()},
        k=cfg.cost.impact_k,
        floor=cfg.cost.slippage_floor_pct,
        cap=cfg.cost.slippage_cap_pct,
    )


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
    on_decision: Callable[[RebalanceDecision], None] | None = None,
    dynamic_slippage: bool = False,
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
    ``dynamic_slippage=True`` replaces the flat slippage with the size-aware square-root market-impact
    law (§13): per trade, ``impact_k·σ_daily·√(value/ADV)`` from a causal as-of ADV+vol snapshot — so
    the cost of moving a large notional through a thin name is charged honestly and the gate avoids it.
    """
    regime_fn = regime_fn or _default_regime_fn
    adj = prices.adj_close
    start_ts = pd.Timestamp(start or cfg.backtest.start)
    end_ts = pd.Timestamp(end or cfg.backtest.end)
    trading_days = prices.dates[(prices.dates >= start_ts) & (prices.dates <= end_ts)]
    if len(trading_days) == 0:
        raise ValueError("no trading days in the requested window")

    min_history = cfg.factor.momentum_lookback_days + 1
    lookback = cfg.factor.funnel_window()
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
            # Set the size-aware slippage snapshot BEFORE the §4.6 gate so its dry-run cost and the
            # executed trade use the same (causal) market-impact model.
            if dynamic_slippage:
                portfolio.slippage_model = _impact_model(prices, d, cfg)
            blacklist = governance_events.blacklisted_asof(d) if governance_events else set()
            decision = decide_rebalance(
                prices=prices,
                universe=universe,
                sector_of=sector_of,
                cfg=cfg,
                portfolio=portfolio,
                as_of=d,
                regime=regime,
                prices_dec=prices_dec,
                last_target=last_target,
                lookback=lookback,
                blacklist=blacklist,
                tax_aware=tax_aware,
                min_trade_fraction=min_trade_fraction,
                force_refresh=force_refresh,
                weighting=weighting,
                n_stocks_override=n_stocks_override,
                fundamentals=fundamentals,
            )
            if on_decision is not None:
                on_decision(decision)
            target = decision.target
            if decision.execute and target is not None and not target.empty:
                trades.extend(
                    portfolio.rebalance(
                        d, target, prices_dec, min_trade_fraction=min_trade_fraction
                    )
                )
                last_target = target
        elif day in defensive_days:
            held = [t for t, q in portfolio.positions().items() if q > 0]
            if held:
                if dynamic_slippage:
                    portfolio.slippage_model = _impact_model(prices, d, cfg)
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
