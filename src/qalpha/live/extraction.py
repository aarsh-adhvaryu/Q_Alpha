"""The AI reads supplied filings and extracts events. **It does not decide anything.**

**The change this makes.** Until now the model was asked a question with an answer in it — *should
this name be kept or dropped?* — and it answered from four web searches for a whole basket, citing
whatever URL it landed on. The judgement was the model's, the evidence was unverifiable, and the
result was a veto that cited a stock quote page.

Here the model is asked only to *report what a document says*. Deterministic policy elsewhere
decides what that means. Splitting those two jobs is the difference between an analyst who reads for
you and an oracle you have to trust.

**The structural guard: a passage must be findable in the document.** Every extracted event carries
a verbatim quote, and :func:`verify_passage` checks it against the archived bytes the extraction was
run on. A quote that is not in the document is not an event — it is discarded and counted. That
check is cheap, mechanical and impossible to argue with, and it is the thing a hostname allowlist
could never do: it tests whether the source *supports the claim* rather than whether the URL looks
respectable.

Nothing here is wired into any decision path. Events are recorded and consumed by nobody. Shadow
first, and for a while.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from qalpha.live.announcements import SourceDocument

#: Bump on any change to the prompt, the parser, the verification rule or the event vocabulary.
#: A label that spans two rules makes every row under it unusable — that already happened once, to
#: ``PR-8b``, and cost the first four days of the run.
EXTRACTION_VERSION = "EX-1"

EVENT_LOG = Path("data/evidence/events.jsonl")

#: What the model may return. Anything else is dropped: an open vocabulary cannot be reasoned about
#: by deterministic policy, and policy is what turns these into PASS/WATCH/BLOCK later.
EVENT_TYPES: tuple[str, ...] = (
    "regulatory_action",
    "litigation",
    "insolvency",
    "auditor_change",
    "board_change",
    "promoter_pledge",
    "related_party",
    "fundraise",
    "acquisition",
    "divestment",
    "credit_rating",
    "guidance_change",
    "results",
    "dividend",
    "operational_disruption",
    "other",
)

MATERIALITY = ("high", "medium", "low")

GenerateFn = Callable[[str, str], tuple[str, dict[str, int]]]

_EVENT_PREFIX = "EVENT:"
_MIN_PASSAGE_CHARS = 20


@dataclass(frozen=True)
class ExtractedEvent:
    """One thing a filing says, with the quote that says it and the document that carries it."""

    ticker: str
    event_type: str
    event_date: date | None
    materiality: str
    passage: str
    summary: str
    uncertainty: str
    doc_sha256: str
    doc_url: str
    disseminated_at: datetime
    model: str
    extraction_version: str
    #: Did the quoted passage actually appear in the archived document? A ``False`` here is a
    #: fabrication and the event must never reach policy.
    verified: bool = False

    def render(self) -> str:
        mark = "✓" if self.verified else "✗ UNVERIFIED"
        when = self.event_date.isoformat() if self.event_date else "undated"
        return (
            f"{mark} {self.ticker} · {self.event_type} · {when} · {self.materiality}\n"
            f'    "{self.passage[:160]}"\n'
            f"    {self.doc_url} · sha256 {self.doc_sha256[:16]}…"
        )


def normalise(text: str) -> str:
    """Collapse whitespace and case so a quote survives PDF line-wrapping.

    PDF extraction inserts newlines and runs of spaces wherever the layout had them, so an otherwise
    exact quote fails a naive substring test. Normalising **both sides identically** keeps the check
    strict about words while forgiving about typography.
    """
    return re.sub(r"\s+", " ", text).strip().lower()


def verify_passage(passage: str, document_text: str) -> bool:
    """Is this quote actually in this document? The whole guard, in one line of logic."""
    if len(passage.strip()) < _MIN_PASSAGE_CHARS:
        return False
    return normalise(passage) in normalise(document_text)


def build_prompt(documents: Sequence[SourceDocument]) -> str:
    """The extraction prompt. It asks for description and forbids recommendation."""
    header = (
        "You are reading corporate filings from the National Stock Exchange of India.\n\n"
        "Extract material events. DO NOT recommend, rank, rate, or advise. Do not say whether a "
        "stock should be bought, held or sold — that decision is made elsewhere by rules, and an "
        "opinion here would be discarded.\n\n"
        "For every material event, emit one line in EXACTLY this format:\n\n"
        "EVENT: ticker=<SYMBOL>; type=<TYPE>; date=<YYYY-MM-DD or ->; materiality=<high|medium|low>; "
        'passage="<VERBATIM QUOTE FROM THE DOCUMENT>"; summary=<one clause>; uncertainty=<one clause or ->\n\n'
        f"TYPE must be one of: {', '.join(EVENT_TYPES)}\n\n"
        "RULES ON THE QUOTE, which is the part that matters:\n"
        "- It must be copied VERBATIM from the document text below. It is checked against the "
        "stored document automatically; an invented or paraphrased quote is discarded.\n"
        "- At least 20 characters, and it must actually contain the fact you are reporting.\n"
        "- If a document says nothing material, emit no line for it. Silence is a valid answer and "
        "is preferred over a weak event.\n\n"
    )
    body = []
    for i, doc in enumerate(documents, 1):
        ann = doc.announcement
        body.append(
            f"--- DOCUMENT {i} ---\n"
            f"ticker: {ann.symbol}\n"
            f"subject: {ann.subject}\n"
            f"disseminated: {ann.disseminated_at:%Y-%m-%d %H:%M}\n"
            f"sha256: {doc.provenance.sha256}\n"
            f"text:\n{doc.excerpt}\n" + ("[document truncated]\n" if doc.truncated else "")
        )
    return header + "\n".join(body)


def _parse_fields(line: str) -> dict[str, str]:
    """Split one EVENT line. ``passage="..."`` is read first so its semicolons survive."""
    rest = line.strip()[len(_EVENT_PREFIX) :]
    fields: dict[str, str] = {}
    quoted = re.search(r'passage\s*=\s*"(.*?)"\s*(?:;|$)', rest, flags=re.DOTALL)
    if quoted:
        fields["passage"] = quoted.group(1)
        rest = rest[: quoted.start()] + rest[quoted.end() :]
    for part in rest.split(";"):
        key, _, value = part.partition("=")
        if value:
            fields[key.strip().lower()] = value.strip()
    return fields


def _parse_date(raw: str) -> date | None:
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def parse_events(
    text: str, documents: Sequence[SourceDocument], *, model: str
) -> tuple[list[ExtractedEvent], int]:
    """Parse the response into events, verifying every quote. Returns ``(kept, discarded)``.

    An event is kept only when its ticker is one we supplied a document for **and** its quote is
    found in that ticker's documents. A model cannot introduce a name it was not given, and cannot
    attribute a real quote from one company to another.
    """
    by_ticker: dict[str, list[SourceDocument]] = {}
    for doc in documents:
        by_ticker.setdefault(doc.announcement.symbol.upper(), []).append(doc)

    kept: list[ExtractedEvent] = []
    discarded = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith(_EVENT_PREFIX):
            continue
        f = _parse_fields(stripped)
        ticker = f.get("ticker", "").upper().removesuffix(".NS")
        docs = by_ticker.get(ticker)
        if not docs:
            discarded += 1  # a name we did not supply — the model cannot add one
            continue
        event_type = f.get("type", "").lower()
        if event_type not in EVENT_TYPES:
            event_type = "other"
        passage = f.get("passage", "")
        source = next((d for d in docs if verify_passage(passage, d.text)), None)
        if source is None:
            discarded += 1  # the quote is not in any document we gave it for this name
            continue
        materiality = f.get("materiality", "").lower()
        kept.append(
            ExtractedEvent(
                ticker=ticker,
                event_type=event_type,
                event_date=_parse_date(f.get("date", "")),
                materiality=materiality if materiality in MATERIALITY else "low",
                passage=passage.strip()[:1000],
                summary=f.get("summary", "")[:300],
                uncertainty=f.get("uncertainty", "")[:300],
                doc_sha256=source.provenance.sha256,
                doc_url=source.provenance.source_url,
                disseminated_at=source.announcement.disseminated_at,
                model=model,
                extraction_version=EXTRACTION_VERSION,
                verified=True,
            )
        )
    return kept, discarded


def event_rows(events: Sequence[ExtractedEvent], *, as_of: date) -> list[dict[str, object]]:
    """Append-only rows. Keyed on document hash + ticker + type, so a re-run corrects rather than
    duplicates while the earlier revision stays on file."""
    rows: list[dict[str, object]] = []
    for e in events:
        rows.append(
            {
                "as_of": as_of.isoformat(),
                "ticker": e.ticker,
                "event_type": e.event_type,
                "event_date": e.event_date.isoformat() if e.event_date else "",
                "materiality": e.materiality,
                "passage": e.passage,
                "summary": e.summary,
                "uncertainty": e.uncertainty,
                "doc_sha256": e.doc_sha256,
                "doc_url": e.doc_url,
                "disseminated_at": e.disseminated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "model": e.model,
                "extraction_version": e.extraction_version,
                "verified": e.verified,
                "kind": "event",
                # The passage digest is in the key because a single filing can carry two events
                # of the same type — two separate litigations, two board changes. Keyed on
                # (document, ticker, type) alone they collided, and the second silently superseded
                # the first as a "correction" that corrected nothing.
                "_key": (
                    f"{e.doc_sha256[:16]}:{e.ticker}:{e.event_type}:"
                    f"{hashlib.sha256(normalise(e.passage).encode()).hexdigest()[:8]}"
                ),
            }
        )
    return rows


def extract(
    documents: Sequence[SourceDocument],
    *,
    generate: GenerateFn,
    model: str,
) -> tuple[list[ExtractedEvent], int, str, Mapping[str, int]]:
    """Run one extraction. Returns ``(events, discarded, raw_response, usage)``.

    Fail-soft: any error yields no events and the raw error text, because an extraction that did not
    happen must look different from one that found nothing, and neither may look like approval.
    """
    if not documents:
        return [], 0, "", {}
    prompt = build_prompt(documents)
    try:
        raw, usage = generate(model, prompt)
    except Exception as exc:
        return [], 0, f"extraction failed: {exc}", {}
    events, discarded = parse_events(raw, documents, model=model)
    return events, discarded, raw, usage
