"""One day, one answer — and ordinary company-level uncertainty never reaches the user.

**What changed on 2026-09-06, and why.** The first version of this module had five exit paths and
**four of them were `HUMAN_REQUIRED`**. A rejected candidate was dropped with nothing taking its
place, and leftover cash sat idle. Run against the live basket it asked the user to adjudicate
nineteen companies and deployed nothing. That is honest and useless at the same time, and honest is
not a defence.

The user is not a trader, does not want to become one, and does not have time to decide what an
unread filing means. So the loop now resolves company-level uncertainty **by moving on**:

```
ranked candidates ─▶ assess one ─▶ PASS and fits the caps? take it
                          │                    else log why, take the next
                          ▼
                  basket full, or ranking exhausted
                          │
                          ▼
              leftover cash ─▶ the anchor, never idle
```

`HUMAN_REQUIRED` is now reserved for problems with the **account or the feed**, not with a company:
a holding nobody can price, an evidence feed that is wholly dead, a broker mismatch. Those are
things only a human can resolve. "I could not read one filing about one candidate" is not.

**The governor filters, it does not stop.** A name that would breach a cap is skipped and the next
one is considered, because refusing the whole basket over one name's sector is how a guard turns
into an obstacle and then into something people switch off.

**Every candidate considered is recorded** — taken or skipped, with its rank, price and reason. One
portfolio a year is one observation; 15 names × 12 deployments is 180. That is the difference
between an experiment that can never conclude and one that might, and it costs a log line.

Nothing here resizes an order. A survivor is bought in exactly the quantity the deterministic screen
assigned it, so every layer downstream of the screen can only ever subtract or substitute.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Protocol

from qalpha.live.evidence import BLOCK, PASS, UNKNOWN, WATCH, Assessment
from qalpha.live.extraction import ExtractedEvent
from qalpha.live.governor import (
    MAX_SECTOR_WEIGHT,
    ConcentrationReport,
    sector_concentration,
)
from qalpha.live.pretrade import AnnouncementCoverage, PreTradeAssessment, assess_candidate

#: The only three things a day may produce.
NO_ACTION = "NO_ACTION"
EXECUTE = "EXECUTE"
HUMAN_REQUIRED = "HUMAN_REQUIRED"

#: What to do about a name **already held** when the evidence turns. Buying and holding are
#: different decisions and must not share a rule: refusing to buy more costs nothing, while selling
#: realises tax and, on this screen, sells exactly what it just bought.
HOLD_STEADY = "HOLD_STEADY"
FREEZE_ADDITIONS = "FREEZE_ADDITIONS"
PROPOSE_EXIT = "PROPOSE_EXIT"

#: Where leftover cash goes so it is never idle. A broad, liquid, low-cost exchange-traded fund the
#: user can buy in the same Kite window as everything else. **Being invested in the obvious thing
#: beats waiting for certainty that may not arrive** — the proven results in this repo are about
#: cost, tax and staying invested, not about selection.
ANCHOR_TICKER = "NIFTYBEES.NS"


class _HasOrderFields(Protocol):
    ticker: str
    quantity: Decimal
    price: Decimal


@dataclass(frozen=True)
class ProposedOrder:
    ticker: str
    quantity: int
    price: Decimal
    #: Rank in the screen's ordering. 0 is the screen's first choice; a high rank means this name
    #: was reached only because better-ranked ones were skipped, which is worth seeing.
    rank: int = 0
    #: True when this is the anchor rather than a screened pick.
    is_anchor: bool = False

    @property
    def value(self) -> Decimal:
        return Decimal(self.quantity) * self.price


@dataclass(frozen=True)
class Considered:
    """One candidate the loop looked at, and what happened to it. The cohort record."""

    ticker: str
    rank: int
    price: Decimal
    state: str
    taken: bool
    reason: str


@dataclass(frozen=True)
class HoldingReview:
    """What the evidence says about something already owned."""

    ticker: str
    action: str
    state: str
    reason: str


@dataclass(frozen=True)
class DayProposal:
    as_of: date
    outcome: str
    reason: str
    orders: tuple[ProposedOrder, ...] = ()
    considered: tuple[Considered, ...] = ()
    holdings_review: tuple[HoldingReview, ...] = ()
    concentration: ConcentrationReport | None = None
    unpriced_holdings: tuple[str, ...] = ()
    anchor_value: Decimal = Decimal("0")
    assessments: Mapping[str, PreTradeAssessment] = field(default_factory=dict)

    @property
    def value(self) -> Decimal:
        return sum((o.value for o in self.orders), Decimal("0"))

    @property
    def skipped(self) -> tuple[Considered, ...]:
        return tuple(c for c in self.considered if not c.taken)

    def render(self) -> str:
        lines = [f"# {self.as_of} — **{self.outcome}**", "", self.reason, ""]
        if self.orders:
            lines += ["| Buy | Qty | Price | Value |", "|---|---:|---:|---:|"]
            for o in self.orders:
                tag = " _(anchor)_" if o.is_anchor else ""
                lines.append(
                    f"| {o.ticker}{tag} | {o.quantity} | ₹{o.price:,.2f} | ₹{o.value:,.2f} |"
                )
            lines += ["", f"**Total ₹{self.value:,.2f}**", ""]
        if self.skipped:
            lines.append(
                f"**{len(self.skipped)} candidate(s) skipped and replaced automatically:**"
            )
            lines += [f"- {c.ticker} — {c.reason}" for c in self.skipped]
            lines.append("")
        for review in self.holdings_review:
            if review.action != HOLD_STEADY:
                lines.append(f"**{review.ticker} (held)** — {review.action}: {review.reason}")
        if self.unpriced_holdings:
            lines.append(
                "⚠️ **Unpriced holdings, so the book cannot be measured:** "
                + ", ".join(self.unpriced_holdings)
            )
        if self.concentration is not None:
            lines += ["", self.concentration.render()]
        return "\n".join(lines)


def _why(verdict: PreTradeAssessment) -> str:
    """Name the dimension that actually produced the verdict, not the first one in the list.

    ``dimensions[0]`` is always the exchange feed, so quoting it produced lines like
    *"UNKNOWN — no active regulatory indicator on this date"*: a verdict of not-knowing followed by
    a reason that reads clean. The reason must name the thing that decided.
    """
    for dimension in verdict.dimensions:
        if dimension.state == verdict.state:
            return f"{verdict.state} — {dimension.name}: {dimension.detail}"
    return verdict.state


def review_holding(ticker: str, assessment: PreTradeAssessment | None) -> HoldingReview:
    """What to do about a name already owned. **Buying and holding get different rules.**

    Refusing to buy more costs nothing. Selling realises tax, and on a screen that buys names which
    have already fallen, an automatic sell disposes of exactly what was just bought at exactly the
    wrong moment. So only a **hard exchange condition** proposes an exit; a warning freezes
    additions, and not knowing freezes additions too. Nothing here sells on its own — the exit is
    proposed and the user approves it.
    """
    if assessment is None:
        return HoldingReview(ticker, FREEZE_ADDITIONS, UNKNOWN, "no assessment on file")
    if assessment.state == BLOCK:
        return HoldingReview(ticker, PROPOSE_EXIT, BLOCK, _why(assessment))
    if assessment.state in {WATCH, UNKNOWN}:
        return HoldingReview(
            ticker,
            FREEZE_ADDITIONS,
            assessment.state,
            "no additions while this is unresolved; not sold, because selling costs tax and this "
            "screen buys names that are already down",
        )
    return HoldingReview(ticker, HOLD_STEADY, PASS, "clear")


#: A 30% sector cap needs at least four sectors to be satisfiable at all: with three, one of them
#: is 33%. Below that the cap cannot discriminate between a diversified basket and a concentrated
#: one, so enforcing it would reject **every** name — including the first purchase into an empty
#: book, which is 100% of its sector by definition.
MIN_SECTORS_FOR_CAP = 4


def _would_breach(
    order: ProposedOrder,
    taken: Sequence[ProposedOrder],
    holdings: Mapping[str, int],
    prices: Mapping[str, Decimal],
    sector_of: Mapping[str, str],
) -> str | None:
    """Would adding this order push its sector past the cap on the **resulting book**?

    **Only asked once the cap is satisfiable.** On a book spanning fewer than
    :data:`MIN_SECTORS_FOR_CAP` sectors the answer is always yes for arithmetic reasons, and a guard
    that fires on everything is a guard nobody can act on. Below that threshold the basket is built
    on evidence alone and the concentration is reported rather than enforced — which is the honest
    position, because there is nothing to enforce yet.
    """
    proposed = [(o.ticker, o.quantity, o.price) for o in [*taken, order] if not o.is_anchor]
    report = sector_concentration(holdings, proposed, prices, sector_of)
    if len(report.exposures) < MIN_SECTORS_FOR_CAP:
        return None
    sector = sector_of.get(order.ticker, "UNKNOWN")
    if sector in [e.sector for e in report.breaches]:
        return f"would take {sector} past the {MAX_SECTOR_WEIGHT:.0%} cap on the resulting book"
    return None


def propose(
    *,
    as_of: date,
    candidates: Sequence[ProposedOrder],
    target_names: int,
    holdings: Mapping[str, int],
    prices: Mapping[str, Decimal],
    sector_of: Mapping[str, str],
    exchange: Mapping[str, Assessment],
    budget: Decimal = Decimal("0"),
    anchor_price: Decimal | None = None,
    anchor_ticker: str = ANCHOR_TICKER,
    events: Mapping[str, Sequence[ExtractedEvent]] | None = None,
    coverage: Mapping[str, AnnouncementCoverage] | None = None,
    unverified: Mapping[str, int] | None = None,
    account_ok: bool = True,
    account_detail: str = "",
) -> DayProposal:
    """Walk the ranking, fill the basket, park the remainder. One outcome.

    ``candidates`` is the screen's **ranked and over-provisioned** list: more names than
    ``target_names``, each already sized by the screen. The loop takes the first ``target_names``
    that clear evidence and the caps, in rank order.
    """
    assessments: dict[str, PreTradeAssessment] = {}

    def assess(ticker: str) -> PreTradeAssessment:
        if ticker not in assessments:
            assessments[ticker] = assess_candidate(
                ticker,
                exchange=exchange.get(ticker),
                events=(events or {}).get(ticker, ()),
                coverage=(coverage or {}).get(ticker),
                unverified_events=(unverified or {}).get(ticker, 0),
            )
        return assessments[ticker]

    review = tuple(
        review_holding(t, assess(t) if t in exchange else None)
        for t, q in sorted(holdings.items())
        if q > 0
    )

    # --- the only things that are genuinely a human's problem ------------------------------
    if not account_ok:
        return DayProposal(
            as_of,
            HUMAN_REQUIRED,
            account_detail or "account integrity check failed",
            holdings_review=review,
        )
    unpriced = tuple(sorted(t for t, q in holdings.items() if q > 0 and t not in prices))
    if unpriced:
        return DayProposal(
            as_of,
            HUMAN_REQUIRED,
            f"{len(unpriced)} holding(s) have no mark, so the book cannot be measured. "
            "A missing price is not a zero.",
            holdings_review=review,
            unpriced_holdings=unpriced,
        )
    if candidates and not exchange:
        return DayProposal(
            as_of,
            HUMAN_REQUIRED,
            "the exchange evidence feed returned nothing for any candidate — that is a dead feed, "
            "not a clean bill of health, and no order should rest on it",
            holdings_review=review,
        )

    # --- walk the ranking ------------------------------------------------------------------
    taken: list[ProposedOrder] = []
    considered: list[Considered] = []
    for order in candidates:
        if len(taken) >= target_names:
            break
        verdict = assess(order.ticker)
        if verdict.state != PASS:
            considered.append(
                Considered(
                    order.ticker,
                    order.rank,
                    order.price,
                    verdict.state,
                    False,
                    _why(verdict),
                )
            )
            continue
        breach = _would_breach(order, taken, holdings, prices, sector_of)
        if breach is not None:
            considered.append(
                Considered(order.ticker, order.rank, order.price, verdict.state, False, breach)
            )
            continue
        taken.append(order)
        considered.append(
            Considered(order.ticker, order.rank, order.price, PASS, True, "cleared every check")
        )

    # --- the remainder never sits idle ------------------------------------------------------
    spent = sum((o.value for o in taken), Decimal("0"))
    remainder = budget - spent
    anchor_value = Decimal("0")
    if anchor_price is not None and anchor_price > 0 and remainder >= anchor_price:
        qty = int(remainder / anchor_price)
        if qty > 0:
            taken.append(
                ProposedOrder(anchor_ticker, qty, anchor_price, rank=9_999, is_anchor=True)
            )
            anchor_value = Decimal(qty) * anchor_price

    report = sector_concentration(
        holdings,
        [(o.ticker, o.quantity, o.price) for o in taken if not o.is_anchor],
        prices,
        sector_of,
    )
    if not taken:
        return DayProposal(
            as_of,
            NO_ACTION,
            "nothing to deploy today."
            if not candidates
            else f"no candidate cleared, and there is no anchor price to park ₹{remainder:,.0f} in.",
            considered=tuple(considered),
            holdings_review=review,
            concentration=report,
            assessments=assessments,
        )
    skipped = len([c for c in considered if not c.taken])
    picked = len([o for o in taken if not o.is_anchor])
    reason = f"{picked} name(s) cleared every check"
    if skipped:
        reason += f", {skipped} skipped and replaced automatically"
    if anchor_value > 0:
        reason += f", ₹{anchor_value:,.0f} to the anchor"
    return DayProposal(
        as_of,
        EXECUTE,
        reason + ".",
        orders=tuple(taken),
        considered=tuple(considered),
        holdings_review=review,
        concentration=report,
        anchor_value=anchor_value,
        assessments=assessments,
    )


def decision_rows(proposal: DayProposal) -> list[dict[str, object]]:
    """One row per candidate considered — the cohort record.

    A portfolio produces one observation a year. Fifteen names across twelve deployments produce
    180. With ``price_at_decision`` on every row, the outcome of a name the screen *passed over* is
    a lookup against any later price panel, so the skipped names become the control group rather
    than disappearing. That is the only route this project has to enough observations to learn
    anything, and it costs a log line.
    """
    return [
        {
            "as_of": proposal.as_of.isoformat(),
            "ticker": c.ticker,
            "rank": c.rank,
            "price_at_decision": str(c.price),
            "state": c.state,
            "taken": c.taken,
            "reason": c.reason[:300],
            "outcome": proposal.outcome,
            "kind": "decision",
            "_key": f"{proposal.as_of.isoformat()}:{c.ticker}",
        }
        for c in proposal.considered
    ]


def orders_from_advice(buy_orders: Sequence[_HasOrderFields]) -> list[ProposedOrder]:
    """Adapt the deploy advisor's ``TradeRecord`` list, preserving the screen's ranking."""
    return [
        ProposedOrder(
            ticker=str(o.ticker), quantity=int(o.quantity), price=Decimal(str(o.price)), rank=i
        )
        for i, o in enumerate(buy_orders)
    ]


__all__ = [
    "ANCHOR_TICKER",
    "EXECUTE",
    "FREEZE_ADDITIONS",
    "HOLD_STEADY",
    "HUMAN_REQUIRED",
    "NO_ACTION",
    "PASS",
    "PROPOSE_EXIT",
    "Considered",
    "DayProposal",
    "HoldingReview",
    "ProposedOrder",
    "decision_rows",
    "orders_from_advice",
    "propose",
    "review_holding",
]
