"""The research desk — every name in scope, and everything this system actually knows about it.

### What this is for

Until now the page answered two questions well ("what do I own", "what does the screen propose")
and left the reasoning on disk in five different files: NSE's surveillance flags in
``data/evidence/``, the extracted filing events beside them, the price history in a parquet panel,
the model book's marks in ``reports/``. A person who wanted to know *why* a name was in or out had
to go and read them.

This assembles one row per name from those files, so the page can show the working.

### The rule that shapes every field

**Unknown is never substituted, and unread is never clean.** Every field here has a third state
between good and bad, and it is load-bearing:

    health      healthy / watch / breaking — and **"too little history"**, which is not healthy
    exchange    CLEAR / WATCH / BLOCK      — and **UNKNOWN**, which is not CLEAR
    filings     read / **not read**        — and a name nobody read has no concerns *reported*,
                                             which is a different fact from having none

The worst defect this repo has recorded in this area was a panel calling a name "clear" when its
filings had never been opened. Every ``None`` and every ``"unknown"`` below exists so that cannot
be written again.

### What it does not do

It computes no new judgement. Every number here is produced by a module that already owned it —
:mod:`~qalpha.live.position_health` for the trend, :mod:`~qalpha.live.evidence` for the exchange's
own file, :mod:`~qalpha.live.flags` for what the filings said. This module owns the *assembly*, and
deliberately owns no analysis, because a new number invented on a display surface is exactly how the
labelling defects in this codebase have always started.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from qalpha.live import evidence

#: How far back a filing event still counts as something you would want to see under a holding.
CONCERN_LOOKBACK_DAYS = 30

#: The three states a trend reading can be in, plus the one that matters most.
UNREADABLE = "too little history"


@dataclass(frozen=True)
class NameView:
    """One name, as the desk knows it. Every optional field is an honest absence."""

    ticker: str
    held: bool = False
    quantity: int = 0
    mark: Decimal | None = None
    cost_basis: Decimal | None = None

    #: Return over the health lookback window. ``None`` when the panel cannot support the window.
    trailing_return: float | None = None
    #: Fall from this name's own trailing high, ≤ 0.
    drawdown: float | None = None
    #: Trailing return minus the cross-sectional median — the part that is about the company.
    excess: float | None = None
    #: ``healthy`` | ``watch`` | ``breaking`` | :data:`UNREADABLE`.
    health: str = UNREADABLE
    health_note: str = ""

    #: The exchange's own verdict, spelled as :mod:`qalpha.live.evidence` spells it:
    #: ``PASS`` | ``WATCH`` | ``BLOCK`` | ``UNKNOWN`` | ``NOT_COVERED``. Defaults to UNKNOWN, which
    #: is the honest state for a name no file was read for — never to PASS.
    exchange: str = "UNKNOWN"
    #: Raw NSE indicator lines, published values not our interpretation of them. The P/E caution
    #: ("Scrip PE is greater than 50") arrives here, from the exchange, rather than being
    #: recomputed from a vendor feed that measures a different earnings basis.
    indicators: tuple[str, ...] = ()

    #: Whether anybody has actually read this company's filings recently, at the current extractor.
    filings_read: bool = False
    #: High-materiality verified events. Empty means *no concern was reported*, which is only
    #: reassuring when :attr:`filings_read` is true.
    concerns: tuple[str, ...] = ()

    #: True when this name is in the basket the screen proposed today.
    proposed: bool = False
    #: True when this name is here to be watched rather than because it is held or proposed. It
    #: carries no quantity and no money, and the page must never let it read as a recommendation.
    watching: bool = False

    @property
    def value(self) -> Decimal | None:
        return None if self.mark is None else self.mark * self.quantity

    @property
    def unrealised(self) -> Decimal | None:
        if self.mark is None or self.cost_basis is None:
            return None
        return (self.mark - self.cost_basis) * self.quantity

    @property
    def unrealised_pct(self) -> float | None:
        if self.mark is None or not self.cost_basis:
            return None
        return float((self.mark - self.cost_basis) / self.cost_basis * 100)

    @property
    def evidence_state(self) -> str:
        """One phrase for the whole evidence picture, honest about what was never looked at."""
        if not self.filings_read:
            return "filings not read"
        if self.concerns:
            return (
                f"{len(self.concerns)} concern{'s' if len(self.concerns) != 1 else ''} in filings"
            )
        return "filings read, nothing flagged"

    @property
    def attention(self) -> bool:
        """Does a person need to look at this name? Unknown counts; that is the point."""
        return (
            self.health in ("breaking", "watch")
            # Anything that is not the exchange's PASS wants a person: WATCH and BLOCK obviously,
            # and UNKNOWN because "we could not check" is not "we checked and it was fine".
            or self.exchange != evidence.PASS
            or not self.filings_read
            or bool(self.concerns)
        )


@dataclass(frozen=True)
class Desk:
    """Every name in scope on one day, with the provenance of what was used to judge them."""

    as_of: date
    rows: tuple[NameView, ...] = ()
    #: How old the exchange's regulatory-indicator file is, in days. ``None`` when there is none.
    exchange_file_age: int | None = None
    #: Sentences about what could not be assembled. Shown, never swallowed.
    notes: tuple[str, ...] = ()

    @property
    def held(self) -> tuple[NameView, ...]:
        return tuple(r for r in self.rows if r.held)

    @property
    def candidates(self) -> tuple[NameView, ...]:
        return tuple(r for r in self.rows if not r.held)

    @property
    def watching(self) -> tuple[NameView, ...]:
        """Names on the page for research only — not held, not proposed, not a suggestion."""
        return tuple(r for r in self.rows if r.watching)

    @property
    def needing_attention(self) -> tuple[NameView, ...]:
        return tuple(r for r in self.rows if r.attention)

    @property
    def unread(self) -> tuple[NameView, ...]:
        return tuple(r for r in self.rows if not r.filings_read)

    def coverage_line(self) -> str:
        """One sentence on how much of this page is founded on documents somebody read."""
        total = len(self.rows)
        if not total:
            return "No names in scope."
        read = total - len(self.unread)
        if read == total:
            return f"All {total} names had their filings read at the current extractor."
        names = ", ".join(r.ticker.removesuffix(".NS") for r in self.unread[:6])
        more = f" (+{len(self.unread) - 6} more)" if len(self.unread) > 6 else ""
        return (
            f"{read} of {total} names had their filings read. NOT read: {names}{more} — "
            "no concern is reported for those because nobody looked, which is not the same as clean."
        )


def _health_rows(report: Any) -> dict[str, Any]:
    return {h.ticker: h for h in getattr(report, "holdings", ())}


def assemble(
    *,
    as_of: date,
    positions: Mapping[str, int],
    prices: Mapping[str, Decimal],
    cost_basis: Mapping[str, Decimal],
    proposal: Sequence[str] = (),
    watchlist: Sequence[str] = (),
    health: Any = None,
    assessments: Mapping[str, Any] | None = None,
    filings_read: Sequence[str] = (),
    concerns: Mapping[str, Sequence[Mapping[str, str]]] | None = None,
    exchange_file_age: int | None = None,
    notes: Sequence[str] = (),
) -> Desk:
    """Build the desk view. Every argument is already-computed output from a module that owns it.

    Nothing is derived here that a caller could not have derived, and nothing is filled in when an
    argument is absent — a missing health report leaves every row :data:`UNREADABLE`, a missing
    assessment leaves it ``UNKNOWN``, and an empty ``filings_read`` means nobody read anything.
    """
    assessments = dict(assessments or {})
    concerns = dict(concerns or {})
    read = {t.removesuffix(".NS") for t in filings_read}
    proposed = set(proposal)
    by_health = _health_rows(health)

    # THE WATCHLIST BELONGS IN SCOPE EVEN WHEN NOTHING IS PROPOSED. With an empty book and a closed
    # gate the desk was blank, which reads as "nothing to see" on the run where the gate was shut
    # precisely because something was wrong. These names carry no quantity and no rupees — they are
    # research rows, not a basket, and the page labels them as such.
    scope = sorted(set(positions) | set(proposed) | set(watchlist) | set(assessments))
    rows: list[NameView] = []
    for ticker in scope:
        bare = ticker.removesuffix(".NS")
        quantity = int(positions.get(ticker, 0))
        h = by_health.get(ticker)
        assessment = assessments.get(ticker) or assessments.get(bare)
        found = concerns.get(bare, ())
        rows.append(
            NameView(
                ticker=ticker,
                held=quantity > 0,
                quantity=quantity,
                mark=prices.get(ticker),
                cost_basis=cost_basis.get(ticker),
                trailing_return=None if h is None else float(h.trailing_return),
                drawdown=None if h is None else float(h.drawdown_from_high),
                excess=None if h is None else float(h.excess_vs_market),
                health=UNREADABLE if h is None else str(h.level),
                health_note="" if h is None else str(h.note),
                exchange="UNKNOWN" if assessment is None else str(assessment.state),
                indicators=(
                    ()
                    if assessment is None
                    else tuple(
                        f"{i.column} = {i.raw_value}" for i in getattr(assessment, "indicators", ())
                    )
                ),
                filings_read=bare in read,
                concerns=tuple(
                    f"{e.get('type', 'event')}: {e.get('summary', '')}".strip(": ") for e in found
                ),
                proposed=ticker in proposed,
                watching=quantity == 0 and ticker not in proposed,
            )
        )
    return Desk(
        as_of=as_of,
        rows=tuple(rows),
        exchange_file_age=exchange_file_age,
        notes=tuple(notes),
    )


def gather(
    *,
    as_of: date,
    positions: Mapping[str, int],
    prices: Mapping[str, Decimal],
    cost_basis: Mapping[str, Decimal],
    proposal: Sequence[str] = (),
    watchlist: Sequence[str] = (),
    panel_path: str | None = None,
) -> Desk:
    """:func:`assemble`, with the on-disk artefacts read for you. Fail-soft **and loud**.

    Each source is read in its own ``try``: one unreadable file must degrade one column, not the
    page. Every failure becomes a note, because a silently empty column reads as "nothing to see".
    """
    from qalpha.live.panels import SCREEN_PANEL

    panel_path = panel_path or str(SCREEN_PANEL)
    notes: list[str] = []
    scope = sorted(set(positions) | set(proposal) | set(watchlist))

    health = None
    marks = dict(prices)
    try:
        import pandas as pd  # noqa: F401

        from qalpha.data.ingest import load_parquet
        from qalpha.live.buygate import MAX_PRICE_AGE_DAYS
        from qalpha.live.position_health import position_health

        adj = load_parquet(panel_path).adj_close
        readable = [t for t in scope if t in adj.columns]
        if readable:
            health = position_health(adj, readable, as_of)
        missing = [t for t in scope if t not in adj.columns]
        if missing:
            notes.append(
                "no price history for "
                + ", ".join(t.removesuffix(".NS") for t in missing)
                + " — their trend reads 'too little history', not 'healthy'."
            )

        # LAST CLOSE FOR THE ROWS NOBODY ASKED THE BROKER ABOUT. `_prices` is called for holdings,
        # so a watchlist row arrived here with no mark and the page said "unpriced" — which is a
        # named absence for something that is not absent at all, and reads as "we could not price
        # this" when the truth is "we did not ask". A supplied mark is never overwritten: the
        # broker's number wins where there is one, and this only fills the gap.
        panel_end = adj.index[-1].date()
        for ticker in scope:
            if ticker in marks or ticker not in adj.columns:
                continue
            series = adj[ticker].dropna()
            if not len(series):
                continue
            # The same per-name staleness rule the marking path uses: a panel dated today can carry
            # a column whose last print is weeks old, and that price is not what it is worth today.
            if (panel_end - series.index[-1].date()).days > MAX_PRICE_AGE_DAYS:
                continue
            marks[ticker] = Decimal(str(float(series.iloc[-1])))
    except Exception as exc:
        notes.append(
            f"the trend column could not be computed ({type(exc).__name__}: {exc}) — every name "
            "reads 'too little history' rather than healthy."
        )

    assessments: dict[str, Any] = {}
    age: int | None = None
    try:
        from qalpha.live.evidence import assess
        from qalpha.live.flags import _latest_exchange_file

        rows, provenance, back = _latest_exchange_file(as_of)
        age = None if back < 0 else back
        if provenance is None:
            notes.append(
                "the exchange's regulatory-indicator file could not be found for any recent day — "
                "every name reads UNKNOWN on surveillance, which is not CLEAR."
            )
        for ticker in scope:
            assessments[ticker] = assess(ticker, rows, provenance, as_of=as_of)
    except Exception as exc:
        notes.append(f"exchange surveillance unavailable ({type(exc).__name__}: {exc}).")

    read: set[str] = set()
    found: dict[str, list[dict[str, str]]] = {}
    try:
        from qalpha.live.flags import filings_read as _read
        from qalpha.live.flags import recent_concerns

        read = _read(scope, as_of=as_of)
        found = recent_concerns(scope, since=as_of - timedelta(days=CONCERN_LOOKBACK_DAYS))
    except Exception as exc:
        notes.append(
            f"the filings log could not be read ({type(exc).__name__}: {exc}) — every name reads "
            "'filings not read'."
        )

    return assemble(
        as_of=as_of,
        positions=positions,
        prices=marks,
        cost_basis=cost_basis,
        proposal=proposal,
        watchlist=watchlist,
        health=health,
        assessments=assessments,
        filings_read=sorted(read),
        concerns=found,
        exchange_file_age=age,
        notes=notes,
    )
