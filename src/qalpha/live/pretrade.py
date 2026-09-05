"""One question per candidate, answered before an order is sized: **may Q-Alpha buy this stock?**

Rules frozen in ``reports/PREREGISTRATION_PRETRADE_V1.md`` before this file existed.

**Why this object.** Every input to the buy decision was a price. The screen ranks names by how far
they sit below a *trailing* one-year high, and a trailing high walks down behind a falling stock, so
a two-year re-rating and an ordinary pullback produce the same number. This is where things that are
not prices get to speak.

**It answers eligibility, never attractiveness.** No score, no rank, no size. Those stay with the
deterministic screen, which is frozen for the ``CORE_V1`` clock and is not touched by anything here.

### The rule that carries the design: an extracted event may never BLOCK

A verified quote proves the document *contains that sentence*. It does not prove the model
classified it correctly, judged its materiality correctly, or read it in context. The verification
guard in :mod:`qalpha.live.extraction` tests the **citation**, not the reasoning.

So only the exchange's own published lists — suspension, trade-to-trade series, ASM/GSM stage ≥ 2,
active insolvency — can exclude a name without a human. A language model that reads filings has not
earned a veto, and granting it one because its citation checked out would be precisely the mistake
the citation check exists to prevent.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from qalpha.live.evidence import (
    BLOCK,
    NOT_COVERED,
    PASS,
    UNKNOWN,
    WATCH,
    Assessment,
)
from qalpha.live.extraction import ExtractedEvent

#: Worst wins. ``UNKNOWN`` outranks ``WATCH`` on purpose: a known warning can be read and weighed,
#: an unmeasured dimension cannot, and the report must lead with the gap rather than the finding.
#: Both route to a human, so the ordering decides emphasis, not authority.
_PRECEDENCE = {BLOCK: 3, UNKNOWN: 2, WATCH: 1, PASS: 0, NOT_COVERED: -1}

#: Only this materiality raises a flag. It is the model's own label and may do nothing more.
_FLAGGING_MATERIALITY = "high"

#: Named so that silence is never read as approval. The last two belong to the risk governor, which
#: sees the resulting book; this object only ever sees one name.
NOT_COVERED_DIMENSIONS: tuple[str, ...] = (
    "fundamentals",
    "earnings quality",
    "debt and cash flow",
    "promoter pledges",
    "related-party transactions",
    "auditor changes",
    "liquidity and ADV",
    "settled cash and duplicate orders",
)

EXCHANGE_INDICATORS = "exchange regulatory indicators"
ANNOUNCEMENTS = "corporate announcements"


def worst(states: Sequence[str]) -> str:
    """The governing state of a set of dimensions. ``NOT_COVERED`` never governs anything."""
    ranked = [s for s in states if _PRECEDENCE.get(s, -1) >= 0]
    if not ranked:
        return UNKNOWN
    return max(ranked, key=lambda s: _PRECEDENCE[s])


@dataclass(frozen=True)
class Dimension:
    """One thing that was consulted, what it said, and what it was reading."""

    name: str
    state: str
    detail: str = ""
    sources: tuple[str, ...] = ()

    def render(self) -> str:
        line = f"  {self.state:<12} {self.name}"
        if self.detail:
            line += f" — {self.detail}"
        return line


@dataclass(frozen=True)
class PreTradeAssessment:
    """May we buy this name? The state, every dimension behind it, and what was not looked at."""

    ticker: str
    state: str
    dimensions: tuple[Dimension, ...] = ()
    #: Verified events that raised the flag. Never the reason for a ``BLOCK`` — see the module note.
    flagged_events: tuple[ExtractedEvent, ...] = ()
    #: Events the model returned whose quote was **not** in the document. Reported, never acted on.
    unverified_events: int = 0
    not_covered: tuple[str, ...] = field(default=NOT_COVERED_DIMENSIONS)

    @property
    def blocked(self) -> bool:
        return self.state == BLOCK

    @property
    def needs_human(self) -> bool:
        return self.state in {WATCH, UNKNOWN}

    @property
    def eligible(self) -> bool:
        """``PASS`` only. Neither a warning nor a gap is an approval."""
        return self.state == PASS

    def render(self) -> str:
        out = [f"{self.ticker}: {self.state}"]
        out += [d.render() for d in self.dimensions]
        for event in self.flagged_events:
            out.append(f"  flag         {event.event_type} ({event.materiality}) — {event.summary}")
            out.append(f'               "{event.passage[:120]}"')
            out.append(f"               {event.doc_url} · sha256 {event.doc_sha256[:16]}…")
        if self.unverified_events:
            out.append(
                f"  discarded    {self.unverified_events} event(s) whose quote was not in the "
                "document — reported, never acted on"
            )
        out.append(f"  not covered  {', '.join(self.not_covered)}")
        return "\n".join(out)


@dataclass(frozen=True)
class AnnouncementCoverage:
    """How much of a name's filing record was actually read, as opposed to merely listed.

    **This exists because of a defect caught on 2026-09-05, in this module, before it shipped.** The
    first version took a boolean "consulted", the caller set it after fetching the *index*, and the
    dimension then reported **"nothing material filed in the window"** for eight names carrying
    between 8 and 17 unread filings each. Listing a document is not reading it. Anything less than
    full coverage is ``UNKNOWN``.
    """

    #: Filings the exchange lists for this name inside the window.
    filings_in_window: int = 0
    #: Filings archived, hash-verified and text-extracted.
    documents_read: int = 0
    #: Did an extraction actually run over those documents? Archiving is not reading either.
    extraction_ran: bool = False
    #: Was the index reachable at all? ``False`` means we know nothing, not that nothing was filed.
    index_fetched: bool = False

    @property
    def complete(self) -> bool:
        return (
            self.index_fetched
            and self.extraction_ran
            and self.documents_read >= self.filings_in_window
        )


def _announcement_dimension(
    events: Sequence[ExtractedEvent], *, coverage: AnnouncementCoverage, unverified: int
) -> tuple[Dimension, tuple[ExtractedEvent, ...]]:
    """Announcements read for this name. **Empty is not the same as unread.**

    A name that filed nothing in the window is clear here. A name whose filings we listed but never
    opened is ``UNKNOWN``. Collapsing those two is how "we did not look" becomes "there was nothing
    to find", which is the defect this whole module exists to stop.
    """
    if not coverage.index_fetched:
        return Dimension(ANNOUNCEMENTS, UNKNOWN, "announcement index unreachable"), ()
    if not coverage.complete:
        unread = max(0, coverage.filings_in_window - coverage.documents_read)
        why = (
            f"{coverage.filings_in_window} filing(s) in the window, {unread} unread"
            if unread
            else "documents archived but no extraction ran"
        )
        return Dimension(ANNOUNCEMENTS, UNKNOWN, why), ()
    verified = [e for e in events if e.verified]
    flagged = tuple(e for e in verified if e.materiality == _FLAGGING_MATERIALITY)
    if flagged:
        kinds = ", ".join(sorted({e.event_type for e in flagged}))
        return (
            Dimension(ANNOUNCEMENTS, WATCH, f"{len(flagged)} high-materiality event(s): {kinds}"),
            flagged,
        )
    if coverage.filings_in_window == 0:
        detail = "nothing filed in the window"
    else:
        detail = (
            f"{coverage.documents_read} filing(s) read, {len(verified)} verified event(s), "
            "none high-materiality"
        )
    if unverified:
        detail += f"; {unverified} discarded for an unverifiable quote"
    return Dimension(ANNOUNCEMENTS, PASS, detail), ()


def assess_candidate(
    ticker: str,
    *,
    exchange: Assessment | None,
    events: Sequence[ExtractedEvent] = (),
    coverage: AnnouncementCoverage | None = None,
    unverified_events: int = 0,
    not_covered: Sequence[str] = NOT_COVERED_DIMENSIONS,
) -> PreTradeAssessment:
    """Combine what the exchange publishes with what verified filings say.

    ``exchange`` is :func:`qalpha.live.evidence.assess`'s answer, and it is the **only** input that
    can produce ``BLOCK``. Passing ``None`` means that feed was never consulted, which is
    ``UNKNOWN`` — the coverage floor, so nothing can answer ``PASS`` having looked at nothing.
    """
    if exchange is None:
        exchange_dim = Dimension(
            EXCHANGE_INDICATORS, UNKNOWN, "feed not consulted — a PASS requires it"
        )
    else:
        exchange_dim = Dimension(
            EXCHANGE_INDICATORS,
            exchange.state,
            exchange.detail,
            sources=(exchange.provenance.source_url,) if exchange.provenance else (),
        )

    ann_dim, flagged = _announcement_dimension(
        events, coverage=coverage or AnnouncementCoverage(), unverified=unverified_events
    )
    dimensions = (exchange_dim, ann_dim)
    state = worst([d.state for d in dimensions])

    # The exchange is the only source of a hard exclusion. If anything else ever produced BLOCK,
    # a model's classification would be vetoing a trade — assert rather than trust review.
    if state == BLOCK and exchange_dim.state != BLOCK:
        raise AssertionError(
            "BLOCK reached without a hard exchange condition. Only NSE's published lists may "
            "exclude a name; an extracted event may raise WATCH and nothing more."
        )
    return PreTradeAssessment(
        ticker=ticker,
        state=state,
        dimensions=dimensions,
        flagged_events=flagged,
        unverified_events=unverified_events,
        not_covered=tuple(not_covered),
    )


def assess_basket(
    tickers: Sequence[str],
    *,
    exchange: Mapping[str, Assessment],
    events: Mapping[str, Sequence[ExtractedEvent]] | None = None,
    coverage: Mapping[str, AnnouncementCoverage] | None = None,
    unverified: Mapping[str, int] | None = None,
) -> dict[str, PreTradeAssessment]:
    """Assess a whole basket, preserving the caller's order so a report reads in basket order."""
    return {
        t: assess_candidate(
            t,
            exchange=exchange.get(t),
            events=(events or {}).get(t, ()),
            coverage=(coverage or {}).get(t),
            unverified_events=(unverified or {}).get(t, 0),
        )
        for t in tickers
    }


def basket_markdown(assessments: Mapping[str, PreTradeAssessment], *, as_of: date) -> str:
    """The panel. Leads with what is not eligible, because that is the actionable half."""
    rows = ["| Name | Verdict | Exchange | Announcements |", "|---|---|---|---|"]
    for ticker, a in assessments.items():
        by_name = {d.name: d.state for d in a.dimensions}
        rows.append(
            f"| {ticker} | **{a.state}** | {by_name.get(EXCHANGE_INDICATORS, '—')} | "
            f"{by_name.get(ANNOUNCEMENTS, '—')} |"
        )
    blocked = [t for t, a in assessments.items() if a.blocked]
    human = [t for t, a in assessments.items() if a.needs_human]
    tail = [f"\n_Pre-trade eligibility as of {as_of}. Not a view on return._"]
    if blocked:
        tail.append(f"\n**BLOCK — excluded deterministically:** {', '.join(blocked)}")
    if human:
        tail.append(f"\n**HUMAN_REQUIRED:** {', '.join(human)}")
    if not blocked and not human:
        tail.append("\nEvery candidate cleared every dimension this version consults.")
    return "\n".join(rows) + "\n" + "".join(tail)
