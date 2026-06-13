"""Replay harness: run the production decision over history (Q_alpha.md §13, STRATEGY.md Stage 1).

The forward paper-trading run cannot be simulated away, but it *can* be de-risked. This harness
drives the **exact same** ``decide_rebalance`` the live runner will call (via ``run_backtest`` with
an observation hook — no parallel copy of the loop) across the full price history, and surfaces:

* the **per-rebalance decision feed** — date, # candidates, execute/hold, the why-string, and the
  resulting orders — i.e. what a human-in-the-loop would have approved each rebalance; and
* a **determinism check** — the same inputs must yield a byte-identical trade stream.

This is the credential-free half of the live build. The live day-by-day runner (broker I/O) will be
held to a stronger bar once built: its trade stream over history must equal this harness's.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from qalpha.backtest.decision import RebalanceDecision
from qalpha.backtest.engine import BacktestResult, run_backtest
from qalpha.backtest.portfolio import TradeRecord
from qalpha.config import Config
from qalpha.data.prices import PriceData
from qalpha.data.universe import Universe


@dataclass(frozen=True)
class ReplayedRebalance:
    """One rebalance as the human would see it: the decision plus the orders it produced."""

    as_of: date
    n_candidates: int
    execute: bool
    reason: str
    orders: list[TradeRecord]

    def render(self) -> str:
        head = f"{self.as_of}  [{self.n_candidates:>2} candidates]  {'TRADE' if self.execute else 'HOLD '}  {self.reason}"
        if not self.orders:
            return head
        lines = [head]
        for o in self.orders:
            lines.append(f"      {o.side.name:<4} {o.ticker:<14} {o.quantity} @ ₹{o.price}")
        return "\n".join(lines)


@dataclass(frozen=True)
class ReplayResult:
    rebalances: list[ReplayedRebalance]
    result: BacktestResult

    @property
    def n_decisions(self) -> int:
        return len(self.rebalances)

    @property
    def n_executed(self) -> int:
        return sum(1 for r in self.rebalances if r.orders)


def replay(
    prices: PriceData,
    sector_of: dict[str, str],
    universe: Universe,
    cfg: Config,
    **run_kwargs: object,
) -> ReplayResult:
    """Run the backtest while capturing every per-rebalance decision and the orders it produced."""
    decisions: list[RebalanceDecision] = []
    result = run_backtest(
        prices,
        sector_of,
        universe,
        cfg,
        on_decision=decisions.append,
        **run_kwargs,  # type: ignore[arg-type]  # forwarded verbatim to run_backtest's kwargs
    )
    orders_by_date: dict[date, list[TradeRecord]] = defaultdict(list)
    for t in result.trades:
        orders_by_date[t.date].append(t)
    rebalances = [
        ReplayedRebalance(
            as_of=d.as_of,
            n_candidates=d.n_candidates,
            execute=d.execute,
            reason=d.reason,
            orders=orders_by_date.get(d.as_of, []),
        )
        for d in decisions
    ]
    return ReplayResult(rebalances=rebalances, result=result)


def verify_determinism(
    prices: PriceData,
    sector_of: dict[str, str],
    universe: Universe,
    cfg: Config,
    **run_kwargs: object,
) -> bool:
    """Run the backtest twice and confirm the trade stream is byte-identical (no hidden state/RNG)."""
    a = run_backtest(prices, sector_of, universe, cfg, **run_kwargs)  # type: ignore[arg-type]
    b = run_backtest(prices, sector_of, universe, cfg, **run_kwargs)  # type: ignore[arg-type]
    return a.trades == b.trades
