"""One day, one answer: ``NO_ACTION``, ``EXECUTE`` or ``HUMAN_REQUIRED`` (PLAN_SYSTEM §1).

This is the composition the parts were built for. Until now the screen, the evidence adapters, the
pre-trade assessment and the risk governor each existed and none of them met: `governor.py` and
`valuation.py` had no production caller at all, and every defect this project has shipped was an
**integration** failure — the right function reached the wrong argument, or a constant stood in for
a measurement. Seven hundred unit tests caught none of them, because a unit test asks whether a
function works, not whether the right data got to it.

``propose`` is the join, and ``tests/test_golden_day.py`` replays it end to end against real
archived exchange bytes and asserts the resulting portfolio exactly.

**It is not wired into the twin.** ``CORE_V1``'s treatment resets only on a screen change, and this
is not one — the screen it calls is the same frozen screen. Wiring happens after the shadow record
shows coverage is real, and that is a separate, registered decision.

### The order of authority, and why it runs this way round

```
screen ─▶ evidence ─▶ pre-trade ─▶ governor ─▶ one outcome
(what to buy)  (may we?)   (per name)   (what the BOOK becomes)
```

The screen is optimistic by construction — its whole job is to find things worth buying. Every gate
after it exists to ask a question the screen was never asked, and each one can only ever *subtract*.
Nothing downstream may add a name, resize an order, or overturn a `BLOCK`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Protocol

from qalpha.live.evidence import BLOCK, PASS, UNKNOWN, WATCH, Assessment
from qalpha.live.extraction import ExtractedEvent
from qalpha.live.governor import ConcentrationReport, sector_concentration
from qalpha.live.pretrade import AnnouncementCoverage, PreTradeAssessment, assess_basket

#: The only three things a day may produce. The user is not a trader and must not become one.
NO_ACTION = "NO_ACTION"
EXECUTE = "EXECUTE"
HUMAN_REQUIRED = "HUMAN_REQUIRED"


@dataclass(frozen=True)
class ProposedOrder:
    """One bounded buy. Quantity and price come from the screen and are never re-derived here."""

    ticker: str
    quantity: int
    price: Decimal

    @property
    def value(self) -> Decimal:
        return Decimal(self.quantity) * self.price


@dataclass(frozen=True)
class DayProposal:
    """What the system says today, and everything needed to check it."""

    as_of: date
    outcome: str
    reason: str
    orders: tuple[ProposedOrder, ...] = ()
    assessments: Mapping[str, PreTradeAssessment] = field(default_factory=dict)
    concentration: ConcentrationReport | None = None
    #: ticker → why it was set aside. Never silently dropped; the reader sees the whole basket.
    excluded: Mapping[str, str] = field(default_factory=dict)
    unpriced_holdings: tuple[str, ...] = ()

    @property
    def value(self) -> Decimal:
        return sum((o.value for o in self.orders), Decimal("0"))

    def render(self) -> str:
        lines = [f"# {self.as_of} — **{self.outcome}**", "", self.reason, ""]
        if self.orders:
            lines += ["| Buy | Qty | Price | Value |", "|---|---:|---:|---:|"]
            lines += [
                f"| {o.ticker} | {o.quantity} | ₹{o.price:,.2f} | ₹{o.value:,.2f} |"
                for o in self.orders
            ]
            lines += ["", f"**Total ₹{self.value:,.2f}**", ""]
        if self.excluded:
            lines.append("**Set aside:**")
            lines += [f"- {t} — {why}" for t, why in sorted(self.excluded.items())]
            lines.append("")
        if self.unpriced_holdings:
            lines.append(
                "⚠️ **Unpriced holdings, so concentration CANNOT BE ASSESSED:** "
                + ", ".join(self.unpriced_holdings)
            )
            lines.append("")
        if self.concentration is not None:
            lines.append(self.concentration.render())
        return "\n".join(lines)


def propose(
    *,
    as_of: date,
    candidates: Sequence[ProposedOrder],
    holdings: Mapping[str, int],
    prices: Mapping[str, Decimal],
    sector_of: Mapping[str, str],
    exchange: Mapping[str, Assessment],
    events: Mapping[str, Sequence[ExtractedEvent]] | None = None,
    coverage: Mapping[str, AnnouncementCoverage] | None = None,
    unverified: Mapping[str, int] | None = None,
) -> DayProposal:
    """Join the screen's basket to the evidence and the governor. Returns one outcome.

    ``candidates`` are the screen's orders, already sized. **Nothing here resizes them** — the
    no-resize guard is a real safety property: a survivor is bought in exactly the quantity the
    deterministic screen assigned it, so the AI and evidence layers can only ever subtract.
    """
    tickers = [o.ticker for o in candidates]
    assessments = assess_basket(
        tickers,
        exchange=exchange,
        events=events,
        coverage=coverage,
        unverified=unverified,
    )

    excluded: dict[str, str] = {}
    survivors: list[ProposedOrder] = []
    for order in candidates:
        state = assessments[order.ticker].state
        if state == BLOCK:
            excluded[order.ticker] = f"BLOCK — {assessments[order.ticker].dimensions[0].detail}"
        elif state in {WATCH, UNKNOWN}:
            excluded[order.ticker] = f"{state} — not bought without a human"
        else:
            survivors.append(order)

    # An unpriced holding cannot be valued, so the sector weights it belongs to are unknown — and an
    # unknown denominator makes every other sector's weight wrong in the safe-looking direction.
    # It is reported, and it forces a human; it is never quietly excluded from the measurement.
    unpriced = tuple(sorted(t for t, q in holdings.items() if q > 0 and t not in prices))

    report = sector_concentration(
        holdings,
        [(o.ticker, o.quantity, o.price) for o in survivors],
        prices,
        sector_of,
    )

    if unpriced:
        return DayProposal(
            as_of=as_of,
            outcome=HUMAN_REQUIRED,
            reason=(
                f"{len(unpriced)} holding(s) have no mark, so the book's sector weights cannot be "
                "computed. A missing price is not a zero."
            ),
            assessments=assessments,
            concentration=report,
            excluded=excluded,
            unpriced_holdings=unpriced,
        )
    if not survivors:
        return DayProposal(
            as_of=as_of,
            outcome=NO_ACTION if not excluded else HUMAN_REQUIRED,
            reason=(
                "The screen produced no candidate today."
                if not excluded
                else f"Every candidate was set aside: {', '.join(sorted(excluded))}."
            ),
            assessments=assessments,
            concentration=report,
            excluded=excluded,
        )
    if not report.clear:
        names = ", ".join(e.sector for e in report.breaches)
        return DayProposal(
            as_of=as_of,
            outcome=HUMAN_REQUIRED,
            reason=f"This basket pushes {names} past the house cap on the resulting book.",
            orders=tuple(survivors),
            assessments=assessments,
            concentration=report,
            excluded=excluded,
        )
    if excluded:
        return DayProposal(
            as_of=as_of,
            outcome=HUMAN_REQUIRED,
            reason=(
                f"{len(survivors)} name(s) cleared every check and "
                f"{len(excluded)} were set aside. Approve the cleared orders or review the rest."
            ),
            orders=tuple(survivors),
            assessments=assessments,
            concentration=report,
            excluded=excluded,
        )
    return DayProposal(
        as_of=as_of,
        outcome=EXECUTE,
        reason=f"{len(survivors)} name(s) cleared every check this version consults.",
        orders=tuple(survivors),
        assessments=assessments,
        concentration=report,
    )


class _HasOrderFields(Protocol):
    """What the pipeline needs from an order, structurally."""

    ticker: str
    quantity: Decimal
    price: Decimal


def orders_from_advice(buy_orders: Sequence[_HasOrderFields]) -> list[ProposedOrder]:
    """Adapt the deploy advisor's ``TradeRecord`` list without importing the advisor here.

    Structural, not nominal: the pipeline must not depend on the advisor module, because the
    dependency that matters runs the other way — the screen is frozen and everything here is not.
    """
    return [
        ProposedOrder(ticker=str(o.ticker), quantity=int(o.quantity), price=Decimal(str(o.price)))
        for o in buy_orders
    ]


__all__ = [
    "EXECUTE",
    "HUMAN_REQUIRED",
    "NO_ACTION",
    "PASS",
    "DayProposal",
    "ProposedOrder",
    "orders_from_advice",
    "propose",
]
