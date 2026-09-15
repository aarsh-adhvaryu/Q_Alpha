"""Attention: which names deserve a review tonight, and why — decided by code, every evening.

Reviewing every name every evening with a strong model is the cost that ran the key dry; reviewing
nothing unless asked misses the evening something happened. So code watches everything, cheaply,
and names what changed. A name with a trigger is reviewed; a name without one keeps its last decision
record and is shown as **"not reviewed tonight: no trigger"** — never given a fresh HOLD it did not get.

Triggers, each with the evidence that raised it:

* ``event`` — a high-materiality verified event known since the last review.
* ``results`` — a quarterly result filed since the last review.
* ``price_move`` — today's move is at least :data:`SIGMA` of its own daily volatility.
* ``valuation`` — P/E at or beyond its own 10th/90th percentile of the last three years.
* ``thesis`` — evidence recorded as contradicting the name's thesis, or a price below the level the
  investor itself said would prove it wrong.
* ``chain`` — a high-materiality event at a company this name **supplies**, found through the graph.
* ``concentration`` — the name or its sector above the review limit; above the address limit, the
  weekly review must take a position on it.
* ``feed`` — a step of tonight's run failed, or this name's filings were not read: **a missing input
  is itself a reason to look**, never a reason to assume nothing happened.
* ``idle_cash`` — cash above its limit for too long while candidates exist (portfolio level).

A **full review** of every holding happens weekly (Friday, or whenever seven days have passed since
the last one) and whenever a portfolio-level trigger fires.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from qalpha.live import graph as g
from qalpha.live.mandate import Sizing

SIGMA = 2.0
LOW_PCT, HIGH_PCT = 10.0, 90.0
FULL_REVIEW_DAYS = 7

EVENT, RESULTS, PRICE, VALUATION, THESIS, CHAIN, CONCENTRATION, FEED, IDLE = (
    "event",
    "results",
    "price_move",
    "valuation",
    "thesis",
    "chain",
    "concentration",
    "feed",
    "idle_cash",
)


@dataclass(frozen=True)
class Trigger:
    kind: str
    detail: str
    #: Ids the review may cite for this trigger: evidence ids, quant ids, graph assertion ids.
    cites: tuple[str, ...] = ()
    #: For a chain: the path with its quotes, and what is known of how much it matters.
    context: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "detail": self.detail,
            "cites": list(self.cites),
            **({"context": dict(self.context)} if self.context else {}),
        }


@dataclass
class Attention:
    as_of: date
    by_name: dict[str, list[Trigger]] = field(default_factory=dict)
    portfolio: list[Trigger] = field(default_factory=list)
    full_review: bool = False
    full_review_why: str = ""

    def add(self, ticker: str, trigger: Trigger) -> None:
        self.by_name.setdefault(ticker, []).append(trigger)

    def reviewed(self, held: Sequence[str]) -> list[str]:
        """Holdings under review tonight."""
        if self.full_review:
            return sorted(held)
        return sorted(t for t in held if self.by_name.get(t))

    def as_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "full_review": self.full_review,
            "full_review_why": self.full_review_why,
            "portfolio": [t.as_dict() for t in self.portfolio],
            "by_name": {k: [t.as_dict() for t in v] for k, v in sorted(self.by_name.items())},
        }


def _bare(ticker: str) -> str:
    return ticker.removesuffix(".NS")


def evidence_triggers(
    attention: Attention,
    names: Sequence[str],
    events: Mapping[str, Sequence[Mapping[str, str]]],
    *,
    since: date | None,
) -> None:
    """High-materiality verified events dated after the last review (or ever, on a first review)."""
    for ticker in names:
        for e in events.get(_bare(ticker), []):
            if e.get("materiality") != "high":
                continue
            if since is not None and str(e.get("date", "")) <= since.isoformat():
                continue
            attention.add(
                ticker, Trigger(EVENT, f"{e.get('type')}: {e.get('summary')}", (str(e["id"]),))
            )


def results_triggers(
    attention: Attention,
    names: Sequence[str],
    stored: Sequence[Any],
    *,
    since: date | None,
    known: date,
) -> None:
    for ticker in names:
        for q in stored:
            if _bare(q.ticker) != _bare(ticker) or not q.reconciled:
                continue
            filed = q.filed_at.date()
            if filed <= known and (since is None or filed > since):
                attention.add(
                    ticker,
                    Trigger(
                        RESULTS,
                        f"results for the quarter ending {q.period_end} filed {filed}",
                        (f"quant:{ticker}",),
                    ),
                )
                break


def card_triggers(attention: Attention, cards: Mapping[str, Mapping[str, Any]]) -> None:
    """Price move and valuation extremes, from tonight's quant cards."""
    for ticker, card in cards.items():
        move = card.get("risk", {}).get("move_today_in_sigma", {}).get("value")
        if isinstance(move, int | float) and abs(move) >= SIGMA:
            attention.add(
                ticker,
                Trigger(
                    PRICE,
                    f"today's move is {move:+.1f}σ of its own daily volatility",
                    (f"quant:{ticker}",),
                ),
            )
        pct = card.get("valuation", {}).get("pe_vs_own_3y", {}).get("percentile")
        if isinstance(pct, int | float) and (pct <= LOW_PCT or pct >= HIGH_PCT):
            attention.add(
                ticker,
                Trigger(
                    VALUATION,
                    f"P/E is at the {pct:.0f}th percentile of its own three years",
                    (f"quant:{ticker}",),
                ),
            )


def thesis_triggers(
    attention: Attention,
    held: Sequence[str],
    view: g.GraphView,
    *,
    last_theses: Mapping[str, Mapping[str, Any]],
    closes: Mapping[str, Decimal],
) -> None:
    """Contradicting evidence recorded against a thesis; a price past the investor's own stop-thinking level."""
    for ticker in held:
        bare = _bare(ticker)
        thesis = last_theses.get(ticker) or {}
        tid = f"thesis:{bare}:{thesis.get('as_of', '')}"
        for edge in view.contradictions(tid):
            attention.add(
                ticker,
                Trigger(
                    THESIS, f"{edge.subject} is recorded as contradicting your thesis", (edge.id,)
                ),
            )
        level, decided_at = thesis.get("invalidate_drawdown_pct"), thesis.get("price_at_decision")
        close = closes.get(ticker)
        if level not in (None, "") and decided_at not in (None, "") and close is not None:
            floor = Decimal(str(decided_at)) * (1 - Decimal(str(level)) / 100)
            if close <= floor:
                attention.add(
                    ticker,
                    Trigger(
                        THESIS,
                        f"price ₹{close} is below ₹{floor:.2f}, the level you said would prove the thesis wrong ({level}% under ₹{decided_at})",
                        (f"price:{ticker}",),
                    ),
                )


def chain_triggers(
    attention: Attention, held: Sequence[str], view: g.GraphView, *, since: datetime | None
) -> None:
    """A high-materiality event at a customer: every holding that supplies it, with the quotes.

    How much it matters is taken from the disclosed revenue share on the supply edge. When no share
    was disclosed that is recorded as MISSING — never estimated.
    """
    for event_id, node in view.nodes.items():
        if node.label not in ("Event", "Headline") or node.props.get("materiality") != "high":
            continue
        if since is not None and node.known_from <= since:
            continue
        customers = [
            e.object
            for e in view.facts()
            if e.label == "ABOUT" and e.subject == event_id and e.object
        ]
        for customer in customers:
            for edge in view.suppliers_of(customer):
                supplier = edge.subject.removeprefix("company:")
                ticker = next((h for h in held if _bare(h) == supplier), None)
                if ticker is None:
                    continue
                share = edge.props.get("pct")
                about = view.facts()
                event_edge = next(
                    (
                        e
                        for e in about
                        if e.label == "ABOUT" and e.subject == event_id and e.object == customer
                    ),
                    None,
                )
                attention.add(
                    ticker,
                    Trigger(
                        CHAIN,
                        f"{customer.removeprefix('company:')} — which you supply — has a high-materiality event: {node.props.get('summary', '')}",
                        tuple(
                            x
                            for x in (
                                edge.id,
                                None if event_edge is None else event_edge.id,
                                str(node.props.get("evidence_id") or ""),
                            )
                            if x
                        ),
                        {
                            "path": [
                                {
                                    "assertion": edge.id,
                                    "relationship": "SUPPLIER_TO",
                                    "from": edge.subject,
                                    "to": customer,
                                    "passage": edge.source.get("passage"),
                                },
                                {
                                    "assertion": None if event_edge is None else event_edge.id,
                                    "relationship": "ABOUT",
                                    "from": event_id,
                                    "to": customer,
                                    "passage": node.source.get("passage"),
                                },
                            ],
                            "materiality": (
                                {
                                    "revenue_share_pct": share,
                                    "basis": "DISCLOSED on the supply connection",
                                }
                                if share is not None
                                else {
                                    "revenue_share_pct": None,
                                    "status": g.MISSING,
                                    "why": "the filing that disclosed this customer did not state its share of revenue",
                                }
                            ),
                        },
                    ),
                )


def concentration_triggers(
    attention: Attention,
    held_values: Mapping[str, Decimal],
    cash: Decimal,
    sectors: Mapping[str, str],
    rules: Sizing,
) -> list[str]:
    """Flags; returns names the weekly review must address (above the address limit)."""
    nav = cash + sum(held_values.values(), Decimal("0"))
    must_address: list[str] = []
    if nav <= 0:
        return must_address
    by_sector: dict[str, Decimal] = {}
    for t, v in held_values.items():
        by_sector[sectors.get(t, "unknown")] = (
            by_sector.get(sectors.get(t, "unknown"), Decimal("0")) + v
        )
    for t, v in held_values.items():
        share = v / nav
        if share > rules.review_name_above:
            attention.add(
                t,
                Trigger(
                    CONCENTRATION,
                    f"{share:.1%} of the book, above {rules.review_name_above:.0%}: buying is paused; review it",
                    (f"quant:{t}",),
                ),
            )
        if share > rules.address_name_above:
            must_address.append(t)
        sector = sectors.get(t, "unknown")
        if by_sector[sector] / nav > rules.review_sector_above:
            attention.add(
                t,
                Trigger(
                    CONCENTRATION,
                    f"sector {sector} is {by_sector[sector] / nav:.1%}, above {rules.review_sector_above:.0%}",
                    (f"quant:{t}",),
                ),
            )
    return must_address


def feed_triggers(
    attention: Attention,
    names: Sequence[str],
    *,
    failed_steps: Sequence[str],
    unread: Sequence[str],
) -> None:
    for step in failed_steps:
        attention.portfolio.append(
            Trigger(FEED, f"tonight's '{step}' step failed: its inputs are missing or stale")
        )
    for ticker in names:
        if _bare(ticker) in {_bare(u) for u in unread}:
            attention.add(
                ticker,
                Trigger(FEED, "this name's filings were not read tonight: unknown, not quiet"),
            )


def idle_cash_trigger(
    attention: Attention,
    *,
    cash_share_by_month: Mapping[str, Decimal],
    rules: Sizing,
    candidates_exist: bool,
) -> None:
    recent = sorted(cash_share_by_month)[-rules.idle_months :]
    if (
        candidates_exist
        and len(recent) == rules.idle_months
        and all(cash_share_by_month[m] > rules.idle_cash_above for m in recent)
    ):
        attention.portfolio.append(
            Trigger(
                IDLE,
                f"cash has been above {rules.idle_cash_above:.0%} of the book for {rules.idle_months} months while candidates qualify",
            )
        )


def decide_full_review(attention: Attention, *, last_full: date | None) -> None:
    if attention.portfolio:
        attention.full_review, attention.full_review_why = True, "a portfolio-level trigger fired"
    elif attention.as_of.weekday() == 4:
        attention.full_review, attention.full_review_why = True, "the weekly review (Friday)"
    elif last_full is None:
        attention.full_review, attention.full_review_why = True, "no full review on record"
    elif (attention.as_of - last_full).days >= FULL_REVIEW_DAYS:
        attention.full_review, attention.full_review_why = (
            True,
            f"{(attention.as_of - last_full).days} days since the last full review",
        )
