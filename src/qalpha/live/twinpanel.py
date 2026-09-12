"""The record, on the page: the model books, the two tracks, and what is trusted.

**The GO gate was removed on 2026-09-12.** It graded six criteria toward a verdict that could
never arrive: the edge is 0.42%/yr against 5.3%/yr of drift, so separating it from chance needs
roughly two hundred years. Six criteria reading CANNOT ASSESS for ever is not honesty, it is a
surface that teaches its reader to stop looking. The gaps remain and are labelled descriptive,
which is what they always were.

### Why any of this is on the buy screen

The page answered *what do I own* and *what does the screen propose*, and the evidence for whether
any of it works lived in `reports/twin_dashboard.md` — a file nobody opens. So the one surface the
user actually reads carried a basket and no way to ask whether the thing producing it is beating a
cheap index fund. That is a page that can only tell you what to do, never how it has been doing.

### The rule that shapes it

**Every figure here is read from a file that already computed it.** This module owns the assembly
and owns no arithmetic: :func:`qalpha.live.twin.append_history` wrote the books and the tracks,
:func:`qalpha.live.go_gate.build_gate` graded the criteria, :func:`qalpha.live.track_record.
track_record` measured the account against the index. A number invented on a display surface is how
every labelling defect in this repo has started, and this is the surface with the most numbers.

### The one thing it must never do

Nothing here may read as validation. `AUTHORIZING_PAIR` is ``None``, the matched null was withdrawn,
and six of six gate criteria say CANNOT ASSESS. The panels say so in words, every time, because a
table of green-looking rupee figures beside a basket is exactly how a system that has proven nothing
comes to look proven.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from qalpha.live import ui
from qalpha.live.track_record import MIN_MONTHS_FOR_A_VERDICT, TrackRecord
from qalpha.live.twin import TWIN_HISTORY

#: The day's gate, snapshotted beside the report the twin writes. A snapshot, not a second record:
#: `history.jsonl` stays the append-only evidence and this is overwritten daily, like `marks.json`.
GATE_JSON = Path("data/twin/gate.json")

#: **Every path below is resolved when the function runs, never in its signature.** A default
#: argument binds at import, and no test can reach past one: `scripts/local_run.py` carries the same
#: note for the same reason, after six defects survived a PR whose tests could not drive `main()`.

#: What the withdrawn null measured. Read rather than restated, so the page cannot drift from it.
NULL_MATCHED = Path("reports/NULL_MATCHED.json")

_VERDICT_TONE: dict[str, ui.Tone] = {
    "GREEN": "good",
    "AMBER": "warn",
    "RED": "bad",
    "CANNOT_ASSESS": "neutral",
}
_VERDICT_ICON = {"GREEN": "🟢", "AMBER": "🟡", "RED": "🔴", "CANNOT_ASSESS": "⚪"}


@dataclass(frozen=True)
class BookRow:
    """One book on one day, exactly as the twin recorded it."""

    name: str
    value: Decimal
    net_invested: Decimal
    xirr: float | None
    first_marked: str = ""

    @property
    def gain(self) -> Decimal:
        return self.value - self.net_invested


@dataclass(frozen=True)
class TrackRow:
    """One track's statistic, with the pair it was computed from. Both spellings of the gap."""

    track: str
    pair: tuple[str, str] | None
    rupees: Decimal | None
    log_rel_wealth: float | None
    months: int | None
    null_p95: float | None
    authorizes: bool


@dataclass(frozen=True)
class TwinRecord:
    as_of: str
    books: tuple[BookRow, ...]
    tracks: tuple[TrackRow, ...]


def _decimal(raw: object) -> Decimal | None:
    try:
        return Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return None


def latest_record(
    path: Path | None = None, *, inception: dict[str, str] | None = None
) -> TwinRecord | None:
    """The most recent day in the append-only history, at its highest revision.

    ``None`` when there is no history — which the panel renders as a sentence. A blank space where a
    comparison should be reads as "nothing to report"; the truth is that nothing was recorded.
    """
    from qalpha.live.twin import inceptions, load_history

    path = path or TWIN_HISTORY
    rows = load_history(path)
    if not rows:
        return None
    row = rows[-1]
    first_marked = inception if inception is not None else inceptions(path)

    books: list[BookRow] = []
    raw_books = row.get("books")
    for name, mark in sorted((raw_books or {}).items()) if isinstance(raw_books, dict) else []:
        value = _decimal(mark.get("value"))
        invested = _decimal(mark.get("net_invested"))
        if value is None or invested is None:
            continue
        rate = mark.get("xirr")
        books.append(
            BookRow(
                name=str(name),
                value=value,
                net_invested=invested,
                xirr=float(rate) if isinstance(rate, int | float) else None,
                first_marked=str(first_marked.get(str(name), "")),
            )
        )

    tracks: list[TrackRow] = []
    raw_tracks = row.get("tracks")
    for name, stat in sorted((raw_tracks or {}).items()) if isinstance(raw_tracks, dict) else []:
        pair = stat.get("pair")
        g = stat.get("log_rel_wealth")
        months = stat.get("months")
        null = stat.get("null_p95")
        tracks.append(
            TrackRow(
                track=str(name),
                pair=(str(pair[0]), str(pair[1]))
                if isinstance(pair, list) and len(pair) == 2
                else None,
                rupees=_decimal(stat.get("rupees")),
                log_rel_wealth=float(g) if isinstance(g, int | float) else None,
                months=int(months) if isinstance(months, int) else None,
                null_p95=float(null) if isinstance(null, int | float) else None,
                authorizes=bool(stat.get("authorizes")),
            )
        )
    return TwinRecord(as_of=str(row.get("as_of", "")), books=tuple(books), tracks=tuple(tracks))


def _age_note(as_of: str, today: date) -> str:
    try:
        days = (today - date.fromisoformat(as_of)).days
    except ValueError:
        return "marked on an unreadable date"
    if days <= 0:
        return f"marked {as_of}"
    return f"marked {as_of} — {days} day{'s' if days != 1 else ''} ago"


def books_panel(record: TwinRecord | None, *, today: date) -> str:
    """Every book, on the day it was last marked. Fake money, identical flows, one difference each."""
    if record is None or not record.books:
        return (
            ui.section("The model books")
            + '<div class="qa-empty">No twin history on file. Nothing has been marked, which is '
            "not the same as nothing having happened.</div>"
        )
    rows = [
        ui.Row(
            cells=[
                ui.Cell(b.name, strong=True),
                ui.Cell(ui.inr(b.net_invested)),
                ui.Cell(ui.inr(b.value)),
                ui.Cell(
                    f"{ui.delta_glyph(b.gain)} {ui.signed_inr(b.gain)}", tone=ui.tone_for(b.gain)
                ),
                ui.Cell(ui.pct(b.xirr * 100) if b.xirr is not None else "—"),
                ui.Cell(b.first_marked or "—", tone="neutral" if b.first_marked else "warn"),
            ]
        )
        for b in record.books
    ]
    return (
        ui.section("The model books", note=_age_note(record.as_of, today))
        + ui.table(
            [
                ui.Column("Book"),
                ui.Column("Money in", "right"),
                ui.Column("Worth", "right"),
                ui.Column("Gain", "right"),
                ui.Column("XIRR", "right"),
                ui.Column("First marked"),
            ],
            rows,
        )
        + '<p class="qa-foot"><b>Fake money.</b> Every book receives the same rupees on the same '
        "days, from your tradebook, and differs in exactly one decision — that is the only reason a "
        "gap between two of them means anything. <b>REAL</b> is your own account replayed. "
        "<b>First marked</b> is when a book began, not when the money did: a book cannot outperform "
        "over a period it did not exist for, and <b>TWIN_FULL &minus; TWIN_NO_HEDGE</b> is ₹0 by "
        "construction, so it is not evidence about the hedge.</p>"
    )


def _null_note(path: Path | None = None) -> str:
    """What the generated null measured, and why it is not the bar. Read from the file."""
    try:
        data = json.loads((path or NULL_MATCHED).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    p95 = data.get("p95_abs_log_rel_wealth")
    draws = data.get("draws")
    if not isinstance(p95, int | float) or not isinstance(draws, int):
        return ""
    withdrawn = (
        " It was <b>withdrawn</b> on the day it was generated: it was matched to a different "
        "specification, and to baskets of about 50 names where these books hold at most 15 — whose "
        "spread is wider still. So there is no bar, and a G this small is noise either way "
        "(reports/NULL_MATCHED.md §6)."
        if data.get("withdrawn")
        else ""
    )
    return (
        f'<p class="qa-foot">For scale: {draws:,} random baskets run through the same machinery '
        f"put 95% of |G| below {p95:.3f}.{withdrawn}</p>"
    )


def tracks_panel(record: TwinRecord | None, *, null_path: Path | None = None) -> str:
    """The two gaps against the fund — **in both of the units they exist in**.

    They can disagree in sign, and today they do: the rupee gap runs from the first cash flow, which
    includes the day each book was constituted, while G is the registered statistic measured from
    that track's own start on unitized NAVs. Neither is wrong; they answer different questions, and
    the page shows both labelled rather than picking the flattering one.
    """
    if record is None or not record.tracks:
        return ""
    rows = []
    for t in record.tracks:
        pair = f"{t.pair[0]} vs {t.pair[1]}" if t.pair else "—"
        window = (
            f"{t.months} of {MIN_MONTHS_FOR_A_VERDICT} months"
            if t.months is not None
            else "not measured"
        )
        rows.append(
            ui.Row(
                cells=[
                    ui.Cell(t.track, strong=True),
                    ui.Cell(pair),
                    ui.Cell(ui.signed_inr(t.rupees) if t.rupees is not None else "—"),
                    ui.Cell(f"{t.log_rel_wealth:+.4f}" if t.log_rel_wealth is not None else "—"),
                    ui.Cell(
                        window,
                        tone="warn" if (t.months or 0) < MIN_MONTHS_FOR_A_VERDICT else "neutral",
                    ),
                    ui.Cell(
                        f"{t.null_p95:.3f}" if t.null_p95 is not None else "none — withdrawn",
                        tone="neutral" if t.null_p95 is not None else "warn",
                    ),
                    ui.Cell(
                        "yes" if t.authorizes else "no", tone="warn" if t.authorizes else "neutral"
                    ),
                ]
            )
        )
    return (
        ui.section("Against the fund", note="the equal-weight index fund anyone can buy")
        + ui.table(
            [
                ui.Column("Track"),
                ui.Column("Pair"),
                ui.Column("₹ gap", "right"),
                ui.Column("G", "right"),
                ui.Column("Window"),
                ui.Column("Bar"),
                ui.Column("Authorises"),
            ],
            rows,
        )
        + '<p class="qa-foot"><b>₹ gap</b> is value minus value since the first cash flow, and it '
        "includes the days before a book existed. <b>G</b> is ln(NAV ÷ NAV) on unitized NAVs from "
        "that track's own registered start — the statistic the experiment is actually about, and "
        "the only one that is unaffected by how much money went in. <b>They can point opposite "
        "ways, and today they do.</b> The ₹ figure is here for reading, never as the criterion."
        "</p>" + _null_note(null_path)
    )


def capability_panel() -> str:
    from qalpha.live.extraction import EXTRACTION_VERSION
    from qalpha.live.localmodel import MODEL_VAR
    from qalpha.live.twin import AUTHORIZING_PAIR
    from qalpha.live.verdicts import AI_PROMPT_VERSION

    authorises = "nothing authorizes a GO today" if AUTHORIZING_PAIR is None else "authorising"
    rows = [
        (
            "The screen",
            "picks and sizes the basket you place",
            "in-sample only — never backtested out of sample; worst backtested fall −47.5%",
            "twelve months of forward record, and a question that can be answered",
        ),
        (
            "The exchange feed",
            "NSE's own surveillance and caution file",
            "deterministic lookup of a published file — flags, never a veto",
            "nothing; it is a lookup, and it says when it is stale",
        ),
        (
            f"The filing reader ({EXTRACTION_VERSION})",
            "reports what a filing says",
            f"every quote is checked against the archived bytes; set {MODEL_VAR} and it reads here",
            "it will not earn a veto — the model classifies, and classification is not evidence",
        ),
        (
            f"The AI arm ({AI_PROMPT_VERSION})",
            "may drop a name from a fake-money book",
            f"a rule over verified filing events — no model is asked; {authorises}",
            "a measured gap between TWIN_FULL and TWIN_NO_AI over a registered window",
        ),
        (
            "The hedge",
            "signal only",
            "moves no money; TWIN_FULL − TWIN_NO_HEDGE is ₹0 by construction",
            "an instrument this book is large enough to trade",
        ),
        (
            "The executor",
            "places every order",
            "you, in Kite — no code path here can place one",
            "nothing. This one does not change.",
        ),
    ]
    return ui.section(
        "What is trusted, and what is not", note="trust is per component, never global"
    ) + ui.table(
        [
            ui.Column("Component"),
            ui.Column("What it does"),
            ui.Column("What it has earned"),
            ui.Column("What would earn more"),
        ],
        [
            ui.Row(cells=[ui.Cell(a, strong=True), ui.Cell(b), ui.Cell(c), ui.Cell(d)])
            for a, b, c, d in rows
        ],
    )


def account_panel(record: TrackRecord | None) -> str:
    """Your own account beside the same money in the index. **It must be able to say you are behind.**

    Every figure comes from :class:`~qalpha.live.track_record.TrackRecord`, which computed them;
    nothing is recomputed here. Below twelve months it is labelled noise, because it is.
    """
    if record is None:
        return (
            ui.section("Your account vs the index")
            + '<div class="qa-empty">No track record yet — that needs a tradebook export in '
            "<code>data/tradebooks/</code>. Until then there are no dated flows to measure against."
            "</div>"
        )
    ahead = record.ahead_by
    mine, theirs = record.measure(), record.benchmark_measure()
    rows = [
        ui.Row(
            cells=[
                ui.Cell("Your account", strong=True),
                ui.Cell(ui.inr(record.value)),
                ui.Cell(ui.pct(mine.pct) if mine else "—"),
                ui.Cell(ui.pct(record.rate * 100) if record.rate is not None else "—"),
            ]
        ),
        ui.Row(
            cells=[
                ui.Cell("Same money in NIFTYBEES", strong=True),
                ui.Cell(ui.inr(record.benchmark_value) if record.benchmark_value else "—"),
                ui.Cell(ui.pct(theirs.pct) if theirs else "—"),
                ui.Cell(
                    ui.pct(record.benchmark_rate * 100)
                    if record.benchmark_rate is not None
                    else "—"
                ),
            ]
        ),
    ]
    head = ui.section(
        "Your account vs the index",
        note=f"{record.start} → {record.as_of} · {record.months} month(s), "
        f"{record.n_flows} cash flow(s)",
    )
    verdict = (
        '<div class="qa-note"><p>'
        + (
            f"<b>{'Ahead' if ahead > 0 else 'Behind'} by {ui.inr(abs(ahead))}</b> against the same "
            "money in the index."
            if ahead is not None
            else "<b>No comparison</b> — the benchmark series does not cover this window."
        )
        + (
            f" Read it as noise, not as a verdict: {record.months} of "
            f"{MIN_MONTHS_FOR_A_VERDICT} months, and a gap this short is dominated by <i>when</i> "
            "the money went in rather than by what was picked."
            if record.too_early
            else ""
        )
        + "</p></div>"
    )
    return (
        head
        + verdict
        + ui.table(
            [
                ui.Column("Leg"),
                ui.Column("Worth", "right"),
                ui.Column("On money in", "right"),
                ui.Column("XIRR", "right"),
            ],
            rows,
        )
        + '<p class="qa-foot">Shares only — cash waiting for the next instalment is not performance. '
        "Both legs receive the same rupees on the same days, so the difference is what was bought "
        "rather than how much.</p>"
    )


def panels(
    *,
    today: date,
    account: TrackRecord | None = None,
    history: Path | None = None,
) -> str:
    """Everything this module renders, in reading order. Each piece degrades to a sentence."""
    record = latest_record(history)
    return (
        account_panel(account)
        + books_panel(record, today=today)
        + tracks_panel(record)
        + capability_panel()
    )
