"""Paper-trading book: the live runner on a NOTIONAL portfolio (Q_alpha.md §14 crit 6; STRATEGY S1).

The spec mandates a multi-month paper run before any real money. This drives the **same**
``decide_rebalance`` the validated backtest uses, on a persisted notional book marked against real
prices — so a track record accumulates with zero capital at risk. When the account is funded, the
only change is *who fills the orders*; the decision code is identical.

State lives in a gitignored JSON book: cash + FIFO lots + the LTCG tally (via ``Portfolio.to_state``)
plus an append-only history of approved fills. The workflow is human-in-the-loop:

* ``plan``  — show today's decision and the proposed orders (read-only, mutates nothing).
* ``apply`` — commit the approved orders to the book (after the human says go).
* ``status``— cash, holdings, equity, realized tax to date.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import cast

import pandas as pd

from qalpha.backtest.decision import RebalanceDecision, decide_rebalance
from qalpha.backtest.portfolio import Portfolio, TradeRecord, to_decimal_price
from qalpha.config import Config
from qalpha.data.prices import PriceData
from qalpha.data.universe import Universe
from qalpha.factors.regime import Regime


@dataclass(frozen=True)
class StrategyParams:
    """The validated config the paper book trades under (frozen into the book at init)."""

    band: float = 0.10
    weighting: str = "shrink"
    tax_aware: bool = True
    force_refresh: bool = True
    rebalance_freq: str = (
        "Y"  # pandas period alias; "Y" = annual (the validated low-turnover cadence)
    )

    def to_dict(self) -> dict[str, object]:
        return {
            "band": self.band,
            "weighting": self.weighting,
            "tax_aware": self.tax_aware,
            "force_refresh": self.force_refresh,
            "rebalance_freq": self.rebalance_freq,
        }

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> StrategyParams:
        return cls(
            band=float(cast(float, d["band"])),
            weighting=str(d["weighting"]),
            tax_aware=bool(d["tax_aware"]),
            force_refresh=bool(d["force_refresh"]),
            # Default to annual for books written before the cadence gate existed (their force_refresh
            # was firing daily — the bug this field fixes).
            rebalance_freq=str(d.get("rebalance_freq", "Y")),
        )


@dataclass(frozen=True)
class DailyPlan:
    """The proposal for one ``as_of``: the decision and the orders it would generate (no mutation)."""

    as_of: date
    decision: RebalanceDecision
    proposed_orders: list[TradeRecord]
    equity_before: Decimal

    @property
    def has_orders(self) -> bool:
        return bool(self.proposed_orders)


def _record_to_dict(r: TradeRecord) -> dict[str, str]:
    return {
        "date": r.date.isoformat(),
        "ticker": r.ticker,
        "side": r.side.name,
        "quantity": str(r.quantity),
        "price": str(r.price),
        "cost": str(r.cost),
        "tax": str(r.tax),
    }


def _prices_on(prices: PriceData, as_of: date) -> dict[str, Decimal]:
    """The look-ahead-safe price row at ``as_of`` (latest available on/before it), as Decimals."""
    row = prices.as_of(as_of).adj_close.iloc[-1].dropna()
    out: dict[str, Decimal] = {}
    for ticker, raw in row.to_dict().items():
        val = float(raw)
        if val > 0:
            out[str(ticker)] = to_decimal_price(val)
    return out


class PaperBook:
    """A persisted notional portfolio plus its approved-fill history."""

    def __init__(
        self,
        path: Path,
        cfg: Config,
        *,
        start_date: date,
        starting_capital: Decimal,
        portfolio: Portfolio,
        params: StrategyParams,
        history: list[dict[str, object]],
        last_target: pd.Series | None = None,
        equity_curve: list[dict[str, str]] | None = None,
    ) -> None:
        self.path = path
        self.cfg = cfg
        self.start_date = start_date
        self.starting_capital = starting_capital
        self.portfolio = portfolio
        self.params = params
        self.history = history
        # The last applied target weights — lets decide_rebalance tell a genuine first deployment
        # from a later rebalance (the §4.6 ``first`` override). Persisted across runs.
        self.last_target = last_target
        # Daily marked-to-market equity points (the track record): [{date, equity, cash}].
        self.equity_curve: list[dict[str, str]] = equity_curve or []

    # ---- lifecycle -------------------------------------------------------

    @classmethod
    def init(
        cls,
        path: Path,
        cfg: Config,
        *,
        starting_capital: Decimal,
        start_date: date,
        params: StrategyParams | None = None,
    ) -> PaperBook:
        portfolio = Portfolio(cfg.cost, cfg.tax, cash=starting_capital)
        book = cls(
            path,
            cfg,
            start_date=start_date,
            starting_capital=starting_capital,
            portfolio=portfolio,
            params=params or StrategyParams(),
            history=[],
        )
        book.save()
        return book

    @classmethod
    def load(cls, path: Path, cfg: Config) -> PaperBook:
        raw = json.loads(path.read_text())
        portfolio = Portfolio.from_state(
            cast("dict[str, object]", raw["portfolio"]), cfg.cost, cfg.tax
        )
        lt = raw.get("last_target")
        last_target = None if lt is None else pd.Series(cast("dict[str, float]", lt))
        return cls(
            path,
            cfg,
            start_date=date.fromisoformat(str(raw["start_date"])),
            starting_capital=Decimal(str(raw["starting_capital"])),
            portfolio=portfolio,
            params=StrategyParams.from_dict(cast("dict[str, object]", raw["params"])),
            history=cast("list[dict[str, object]]", raw["history"]),
            last_target=last_target,
            equity_curve=cast("list[dict[str, str]]", raw.get("equity_curve", [])),
        )

    def save(self) -> None:
        last_target = (
            None
            if self.last_target is None
            else {str(t): float(w) for t, w in self.last_target.items()}
        )
        payload = {
            "start_date": self.start_date.isoformat(),
            "starting_capital": str(self.starting_capital),
            "params": self.params.to_dict(),
            "portfolio": self.portfolio.to_state(),
            "history": self.history,
            "last_target": last_target,
            "equity_curve": self.equity_curve,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2) + "\n")

    # ---- rebalance cadence (the live mirror of engine._rebalance_dates) ---

    def _last_rebalance_date(self) -> date | None:
        """The ``as_of`` of the most recent applied rebalance (incl. the first deployment), or None."""
        for entry in reversed(self.history):
            return date.fromisoformat(str(entry["as_of"]))
        return None

    def scheduled_rebalance_due(self, as_of: date) -> bool:
        """True iff ``as_of`` falls in a later rebalance *period* than the last applied rebalance.

        The backtest only evaluates a rebalance on the last trading day of each period
        (:func:`engine._rebalance_dates`); ``force_refresh`` then always fires there. The paper cron
        instead runs *every* day, so without this gate ``force_refresh`` would rebalance daily and
        annihilate the validated low-turnover tax edge. This reproduces that cadence in an online,
        forward form — a scheduled rebalance is due the first trading day we observe in a new period
        (calendar-locked like the backtest; the month differs from Dec but the once-a-year frequency,
        the property that was validated, is identical). No prior rebalance → first deployment is due.
        """
        last = self._last_rebalance_date()
        if last is None:
            return True
        freq = self.params.rebalance_freq
        # ADAPTIVE (the "smart-rebalance" experiment book): evaluate the funnel EVERY run and let the
        # §4.6 tax-benefit gate decide whether to actually trade — i.e. self-timed, not calendar-locked
        # (rebalances only when the risk reduction beats 2× cost+tax, so realized turnover stays low).
        # Requires force_refresh=False + tax_aware=True so the gate, not force-refresh, is the decider.
        if freq == "ADAPTIVE":
            return True
        return pd.Period(as_of, freq=freq) > pd.Period(last, freq=freq)

    def next_rebalance_label(self) -> str:
        """Human-readable date the next scheduled rebalance becomes due (for the 'holding' message)."""
        last = self._last_rebalance_date()
        if last is None:
            return "now (first deployment)"
        if self.params.rebalance_freq == "ADAPTIVE":
            return "whenever the tax-benefit gate clears (self-timed)"
        nxt = (pd.Period(last, freq=self.params.rebalance_freq) + 1).start_time.date()
        return f"on/after {nxt.isoformat()}"

    # ---- the daily loop --------------------------------------------------

    def plan(
        self,
        prices: PriceData,
        universe: Universe,
        sector_of: dict[str, str],
        as_of: date,
    ) -> DailyPlan:
        """Compute the decision + proposed orders for ``as_of`` without touching the book.

        Between scheduled rebalance dates the core book is *held* (mirrors the backtest, which only
        evaluates on its cadence) — so the daily mark never proposes churn. On a scheduled day it runs
        the full funnel + §4.6 gate exactly as the backtest does.
        """
        if not self.scheduled_rebalance_due(as_of):
            return DailyPlan(
                as_of=as_of,
                decision=RebalanceDecision(
                    as_of,
                    None,
                    False,
                    f"holding — next scheduled rebalance {self.next_rebalance_label()}",
                    0,
                ),
                proposed_orders=[],
                equity_before=self.portfolio.market_value(_prices_on(prices, as_of)),
            )
        prices_dec = _prices_on(prices, as_of)
        lookback = self.cfg.factor.funnel_window()
        decision = decide_rebalance(
            prices=prices,
            universe=universe,
            sector_of=sector_of,
            cfg=self.cfg,
            portfolio=self.portfolio,
            as_of=as_of,
            regime=Regime.BULL,
            prices_dec=prices_dec,
            last_target=self.last_target,
            lookback=lookback,
            tax_aware=self.params.tax_aware,
            min_trade_fraction=self.params.band,
            force_refresh=self.params.force_refresh,
            weighting=self.params.weighting,
        )
        proposed: list[TradeRecord] = []
        if decision.actionable and decision.target is not None:
            trial = copy.deepcopy(self.portfolio)  # dry-run: orders without mutating the book
            proposed = trial.rebalance(
                as_of, decision.target, prices_dec, min_trade_fraction=self.params.band
            )
        return DailyPlan(
            as_of=as_of,
            decision=decision,
            proposed_orders=proposed,
            equity_before=self.portfolio.market_value(prices_dec),
        )

    def apply(self, prices: PriceData, plan: DailyPlan) -> list[TradeRecord]:
        """Commit a plan's orders to the book, append to history, and persist."""
        if not (plan.decision.actionable and plan.decision.target is not None):
            return []
        prices_dec = _prices_on(prices, plan.as_of)
        records = self.portfolio.rebalance(
            plan.as_of, plan.decision.target, prices_dec, min_trade_fraction=self.params.band
        )
        self.last_target = plan.decision.target
        self.history.append(
            {
                "as_of": plan.as_of.isoformat(),
                "reason": plan.decision.reason,
                "orders": [_record_to_dict(r) for r in records],
            }
        )
        self.save()
        return records

    # ---- reporting -------------------------------------------------------

    def equity(self, prices: PriceData, as_of: date) -> Decimal:
        return self.portfolio.market_value(_prices_on(prices, as_of))

    def mark(self, prices: PriceData, as_of: date, *, persist: bool = True) -> Decimal:
        """Record (idempotently) the marked-to-market equity for ``as_of`` — builds the track record.

        Pure valuation, never a trade — safe to run unattended every day. Re-marking the same date
        overwrites that point so reruns don't duplicate it.
        """
        prices_dec = _prices_on(prices, as_of)
        equity = self.portfolio.market_value(prices_dec)
        point = {
            "date": as_of.isoformat(),
            "equity": str(equity),
            "cash": str(self.portfolio.cash),
        }
        self.equity_curve = [p for p in self.equity_curve if p["date"] != point["date"]]
        self.equity_curve.append(point)
        self.equity_curve.sort(key=lambda p: p["date"])
        if persist:
            self.save()
        return equity

    def realized_tax(self) -> Decimal:
        total = Decimal("0")
        for event in self.history:
            for order in cast("list[dict[str, str]]", event["orders"]):
                total += Decimal(order["tax"])
        return total

    def total_return_pct(self, prices: PriceData, as_of: date) -> float:
        """Return since inception (%), measured against the notional starting capital."""
        if self.starting_capital <= 0:
            return 0.0
        return (
            float((self.equity(prices, as_of) - self.starting_capital) / self.starting_capital)
            * 100.0
        )
