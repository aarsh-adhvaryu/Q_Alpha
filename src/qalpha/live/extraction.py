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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from qalpha.live.announcements import MAX_DOCUMENT_CHARS, SourceDocument

#: Bump on any change to the prompt, the parser, the verification rule or the event vocabulary.
#: A label that spans two rules makes every row under it unusable — that already happened once, to
#: ``PR-8b``, and cost the first four days of the run.
#: EX-1 (2026-09-05): asked for "material events" and never said material *to whom*. The model read
#: it as newsworthy and returned 77 of 193 events at ``high`` — mostly routine results, "revenue up
#: 10%", "EBITDA grew 8%". Since a high-materiality event triggers ``WATCH``, **good news rejected
#: candidates**. The model was answering the question it was asked.
#: EX-2 (2026-09-08): materiality is defined as **concern to someone who owns the stock**, with the
#: routine cases named as explicitly NOT material. Nothing about the model changed; the instruction
#: did.
EXTRACTION_VERSION = "EX-2"

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

#: Characters of overlap between consecutive chunks, so a fact straddling a boundary still appears
#: whole in at least one of them.
CHUNK_OVERLAP = 500
#: Document text per model call. Chunks are packed up to this; a chunk is never split across calls.
PROMPT_CHAR_BUDGET = 24_000


@dataclass(frozen=True)
class DocumentChunk:
    """One slice of a filing, carrying the whole document with it.

    **Chunking exists so that "read" can be true.** The prompt has a character budget, so a long
    filing used to be truncated and the tail was never looked at — while the coverage accounting
    counted the document as read. Splitting it means every character reaches the model in some call.

    Verification still runs against the **full** document text, so a quote that straddles a chunk
    boundary verifies anyway.
    """

    document: SourceDocument
    text: str
    index: int
    total: int

    @property
    def label(self) -> str:
        return f"{self.index + 1} of {self.total}" if self.total > 1 else "whole"


def chunks_for(document: SourceDocument) -> list[DocumentChunk]:
    """Split one filing into overlapping chunks that fit the prompt budget."""
    text = document.text
    size = MAX_DOCUMENT_CHARS
    if len(text) <= size:
        return [DocumentChunk(document=document, text=text, index=0, total=1)]
    step = max(1, size - CHUNK_OVERLAP)
    slices = [text[i : i + size] for i in range(0, len(text), step)]
    slices = [c for c in slices if c.strip()]
    return [
        DocumentChunk(document=document, text=c, index=i, total=len(slices))
        for i, c in enumerate(slices)
    ]


def batch_chunks(
    chunks: Sequence[DocumentChunk], *, budget: int = PROMPT_CHAR_BUDGET
) -> list[list[DocumentChunk]]:
    """Pack chunks into calls without ever splitting one. A single oversized chunk gets its own call."""
    batches: list[list[DocumentChunk]] = []
    current: list[DocumentChunk] = []
    used = 0
    for chunk in chunks:
        if current and used + len(chunk.text) > budget:
            batches.append(current)
            current, used = [], 0
        current.append(chunk)
        used += len(chunk.text)
    if current:
        batches.append(current)
    return batches


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


def build_prompt(chunks: Sequence[DocumentChunk]) -> str:
    """The extraction prompt. It asks for description and forbids recommendation."""
    header = (
        "You are reading corporate filings from the National Stock Exchange of India.\n\n"
        "Extract material events. DO NOT recommend, rank, rate, or advise. Do not say whether a "
        "stock should be bought, held or sold — that decision is made elsewhere by rules, and an "
        "opinion here would be discarded.\n\n"
        "WHAT 'MATERIALITY' MEANS HERE — read this before rating anything:\n"
        "Materiality is **how much this should worry someone who already owns the shares**. It is "
        "NOT how newsworthy, how large, or how interesting the item is.\n\n"
        "  high   — a reason to stop and think before buying more: a regulator or court acting "
        "against the company or its officers, insolvency, an auditor resigning or qualifying, a "
        "default or downgrade, promoter pledges rising sharply, a large related-party transaction, "
        "a plant or business shut down, guidance withdrawn or cut sharply, a restatement.\n"
        "  medium — worth knowing, not alarming on its own: a change of key management, a "
        "moderate acquisition or divestment, a fundraise, an ordinary rating affirmation.\n"
        "  low    — routine disclosure.\n\n"
        "THESE ARE NOT MATERIAL, whatever the numbers involved. Rate them 'low' or omit them:\n"
        "  - quarterly or annual results, however good or bad the growth\n"
        "  - revenue, EBITDA, margin or profit figures on their own\n"
        "  - dividends, bonuses, splits and record dates\n"
        "  - analyst or investor meet intimations, presentations, transcripts\n"
        "  - trading-window closures, newspaper publications, compliance certificates\n"
        "  - a contract win, expansion or investment, however large\n\n"
        "**Good news is never high materiality.** A company growing 10% is not a reason to worry "
        "about owning it. If the only thing a filing says is that the business did well, it is "
        "'low'.\n\n"
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
    for i, chunk in enumerate(chunks, 1):
        ann = chunk.document.announcement
        body.append(
            f"--- DOCUMENT {i} (part {chunk.label}) ---\n"
            f"ticker: {ann.symbol}\n"
            f"subject: {ann.subject}\n"
            f"disseminated: {ann.disseminated_at:%Y-%m-%d %H:%M}\n"
            f"sha256: {chunk.document.provenance.sha256}\n"
            f"text:\n{chunk.text}\n"
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
) -> tuple[list[ExtractedEvent], int, str, dict[str, int]]:
    """Extract over **every character** of every document. ``(events, discarded, raw, usage)``.

    Long filings are chunked, not truncated, so "read" means read. Events found twice in
    overlapping chunks are collapsed on (ticker, type, normalised passage).

    Fail-soft **per batch**: a call that raises contributes no events and its error text, and is
    counted in ``usage["failed_batches"]`` so a caller can refuse to claim coverage it did not get.
    An extraction that did not happen must look different from one that found nothing, and neither
    may look like approval.
    """
    if not documents:
        return [], 0, "", {"input": 0, "output": 0, "calls": 0, "failed_batches": 0}
    all_chunks = [c for doc in documents for c in chunks_for(doc)]
    events: list[ExtractedEvent] = []
    discarded = 0
    raws: list[str] = []
    usage: dict[str, int] = {"input": 0, "output": 0, "calls": 0, "failed_batches": 0}
    for batch in batch_chunks(all_chunks):
        try:
            raw, call_usage = generate(model, build_prompt(batch))
        except Exception as exc:
            raws.append(f"extraction failed: {exc}")
            usage["failed_batches"] += 1
            continue
        raws.append(raw)
        usage["calls"] += 1
        for field in ("input", "output"):
            usage[field] += int(call_usage.get(field, 0))
        # Verified against the WHOLE documents, never just this batch's slices, so a quote spanning
        # a chunk boundary still resolves to the document it came from.
        found, dropped = parse_events(raw, documents, model=model)
        events.extend(found)
        discarded += dropped
    seen: set[tuple[str, str, str]] = set()
    unique: list[ExtractedEvent] = []
    for event in events:
        key = (event.ticker, event.event_type, normalise(event.passage))
        if key not in seen:
            seen.add(key)
            unique.append(event)
    return unique, discarded, "\n\n".join(raws), usage


#: Output cap per extraction call. Events are one short line each; this is generous for a batch.
MAX_OUTPUT_TOKENS = 3000
DEFAULT_MODEL = "claude-haiku-4-5"


def default_generate(api_key: str, *, max_tokens: int = MAX_OUTPUT_TOKENS) -> GenerateFn:
    """The real model call for extraction — **with no tools, deliberately**.

    The veto path gives the model web search. This one must not have it. The whole point is that
    the model reads documents this repo fetched, hashed and kept, so that every claim it makes can
    be checked against bytes on disk. Handing it a search tool would let a passage come from
    somewhere nobody archived, and the verification guard would silently have nothing to check
    against.

    Lazy-imports the SDK so the module and its pure tests load without the ``ai`` extra installed.
    """

    def generate(model_id: str, prompt: str) -> tuple[str, dict[str, int]]:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model_id,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        if resp.stop_reason == "refusal":
            return "", {}
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        return text, {
            "input": int(getattr(resp.usage, "input_tokens", 0) or 0),
            "output": int(getattr(resp.usage, "output_tokens", 0) or 0),
        }

    return generate
