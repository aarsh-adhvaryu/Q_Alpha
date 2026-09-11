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
import os
import re
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

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
#: EX-3 (2026-09-11): **the reader is part of the label.** The prompt, parser, verification rule and
#: vocabulary are EX-2's, unchanged. What changed is that a version no longer means only "read under
#: these instructions" — it means "read under these instructions BY :data:`CORPUS_READER`". Two
#: models reading the same filing disagree the way two analysts do, and this repo already records
#: the smaller version of that: identical snippets get different labels in different batches from
#: one model at temperature zero. A corpus half-read by a local 8B and half by a cloud model is not
#: one instrument, and an event study over it would carry that confound before its first result.
#: Pinning the reader into the label makes the mixture impossible to produce rather than merely
#: discouraged — see :func:`reader_matches` and ``reports/PREREGISTRATION_EX3_CORPUS.md``.
EXTRACTION_VERSION = "EX-3"

#: The one reader EX-3 rows may come from. A row read by anything else is not an EX-3 row, however
#: good it is: ``_seen_before`` refuses it, ``pretrade`` ignores it, and the name stays uncovered.
#: Overridable for a measured comparison (``QALPHA_CORPUS_READER``), because the alternative is
#: picking a model by assertion — but the override names the corpus, so a run under it cannot be
#: mistaken for a run under the default.
#: Measured on 150 archived filings across 22 names on 2026-09-11, not assumed. Haiku returned 59
#: verified events and 86 quotes that were not in the document — a 59% discard rate — against
#: Sonnet's 109 events and 44 discards, 29%. Half the findings at twice the miss rate decided it
#: under the registration's first rule, before agreement was even consulted. Full numbers in
#: ``reports/READER_COMPARISON_EX3.md``.
CORPUS_READER_DEFAULT = "claude-sonnet-5"

#: Environment override for the corpus reader. Named so a comparison run is self-labelling.
CORPUS_READER_VAR = "QALPHA_CORPUS_READER"


def corpus_reader() -> str:
    """The model EX-3 rows must come from. Never guessed, never a fallback."""
    return os.environ.get(CORPUS_READER_VAR, "").strip() or CORPUS_READER_DEFAULT


def reader_matches(row_reader: object) -> bool:
    """Was this row produced by the corpus reader?

    **A row with no reader recorded is not a match.** Every row written before EX-3 predates the
    field, and those were read by whatever happened to be configured that evening — which is the
    mixture this version exists to prevent. Absent is unknown, and unknown is not the reader.
    """
    return isinstance(row_reader, str) and row_reader == corpus_reader()


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

#: Every counter :func:`extract` reports. Named in one place so an empty run and a busy one carry
#: the same keys — a caller reading ``usage["failed_batches"]`` on the empty path used to get a
#: KeyError's worth of nothing.
_USAGE_FIELDS = (
    "input",
    "output",
    "calls",
    "failed_batches",
    "truncated_batches",
    "retried_batches",
    #: Calls the model declined on safety grounds. Counted apart from a dead call because the
    #: fixes differ, and counted AT ALL because an empty reply is not a filing with nothing in it.
    "refused_batches",
)

#: Concurrent model calls when a caller asks for them. One is the daily default: the local reader
#: is a single GPU holding a single model, so parallel calls there queue rather than overlap.
DEFAULT_WORKERS = 1


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


#: What ``high``, ``medium`` and ``low`` mean, in one string.
#:
#: **Shared with the news reader**, which asks the same question of a headline. It is one constant
#: rather than two prompts that agree today: EX-1 rated routine results ``high`` because the
#: instruction never said material *to whom*, and 77 of 193 events came back high — good news
#: rejecting candidates. A second copy of this text is a second chance to make that mistake in one
#: place and not the other.
MATERIALITY_RUBRIC = (
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
    "about owning it. If the only thing it says is that the business did well, it is 'low'.\n\n"
)


def build_prompt(chunks: Sequence[DocumentChunk]) -> str:
    """The extraction prompt. It asks for description and forbids recommendation."""
    header = (
        "You are reading corporate filings from the National Stock Exchange of India.\n\n"
        "Extract material events. DO NOT recommend, rank, rate, or advise. Do not say whether a "
        "stock should be bought, held or sold — that decision is made elsewhere by rules, and an "
        "opinion here would be discarded.\n\n"
        + MATERIALITY_RUBRIC
        + "For every material event, emit one line in EXACTLY this format:\n\n"
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


def parse_fields(line: str, *, prefix: str = _EVENT_PREFIX) -> dict[str, str]:
    """Split one tagged line. ``passage="..."`` is read first so its semicolons survive.

    ``prefix`` is the tag being stripped, so the news reader splits its own lines with this parser
    rather than a second one that would drift from it — the quoting rule below is the subtle part,
    and it is worth having exactly once.
    """
    rest = line.strip()[len(prefix) :]
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
        f = parse_fields(stripped)
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


@dataclass(frozen=True)
class _Outcome:
    """One model call's result, carrying the position it must be accounted in.

    ``path`` is why a concurrent run and a sequential one produce identical output: batch 3's reply
    is accounted after batch 2's whichever finished first, and the single-document retries that a
    truncated batch 3 spawns sort to ``(3, 0), (3, 1)`` — immediately after ``(3,)``, exactly where
    the old front-of-queue re-push put them.
    """

    path: tuple[int, ...]
    batch: list[DocumentChunk]
    raw: str
    call_usage: dict[str, int]
    error: str | None


def _call_one(
    path: tuple[int, ...],
    batch: list[DocumentChunk],
    generate: GenerateFn,
    model: str,
) -> _Outcome:
    """One call, fail-soft. A raised exception is data about this batch, not the end of the run."""
    try:
        raw, call_usage = generate(model, build_prompt(batch))
    except Exception as exc:  # one dead batch must not end the read
        return _Outcome(path, batch, "", {}, f"{type(exc).__name__}: {exc}")
    return _Outcome(path, batch, raw, call_usage, None)


def _run_round(
    work: Sequence[tuple[tuple[int, ...], list[DocumentChunk]]],
    *,
    generate: GenerateFn,
    model: str,
    workers: int,
) -> list[_Outcome]:
    """Run one round of batches, returning outcomes **in the order given**, not the order finished.

    ``workers <= 1`` takes the sequential path and starts no pool at all, so the daily run behaves
    exactly as it did before concurrency existed.
    """
    if workers <= 1:
        return [_call_one(path, batch, generate, model) for path, batch in work]
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda item: _call_one(item[0], item[1], generate, model), work))


def extract(
    documents: Sequence[SourceDocument],
    *,
    generate: GenerateFn,
    model: str,
    batch_chars: int = PROMPT_CHAR_BUDGET,
    workers: int = DEFAULT_WORKERS,
) -> tuple[list[ExtractedEvent], int, str, dict[str, int]]:
    """Extract over **every character** of every document. ``(events, discarded, raw, usage)``.

    Long filings are chunked, not truncated, so "read" means read. Events found twice in
    overlapping chunks are collapsed on (ticker, type, normalised passage).

    ``batch_chars`` is how much document text may go into one call. It defaults to the cloud
    model's budget and is lowered for a local model with a smaller context — a batch that overruns
    the window is truncated by the server, silently, while coverage still counts the documents as
    read. That is the "25 of 30 filings, reported as 25 of 25" defect with a different cause.

    ``workers`` is how many of those calls may be in flight at once. **It changes the wall clock and
    nothing else**: outcomes are accounted in batch order regardless of completion order, so the
    events, the discard count, the joined raw text and every usage counter are identical to the
    sequential run. That property is the reason it is safe to turn up, and it is asserted directly
    rather than assumed. It is worth turning up only for a reader that can serve calls in parallel:
    one local GPU holding one model serialises them anyway.

    Fail-soft **per batch**: a call that raises contributes no events and its error text, and is
    counted in ``usage["failed_batches"]`` so a caller can refuse to claim coverage it did not get.
    An extraction that did not happen must look different from one that found nothing, and neither
    may look like approval. **A refusal is the same kind of nothing** — the model declined, the
    documents in that call went unread, and it is counted in ``refused_batches`` and in
    ``failed_batches`` so it can never read as a filing with no bad news in it.

    **The same is true of a reply that ran out of room.** The input fitting the window says nothing
    about the OUTPUT fitting ``max_tokens``: a batch of filings that genuinely carries a dozen events
    can be cut off mid-list, and every document after the cut has then been sent and not reported on.
    A multi-document batch is retried one document at a time, which is usually enough; a single
    document whose reply is still cut off counts in ``failed_batches`` (and in
    ``truncated_batches``), so no caller may claim coverage from it. Its verified events are still
    returned — a quote checked against the archived bytes is evidence whatever else went wrong — but
    they arrive alongside a count that stops them being read as a complete answer.
    """
    if not documents:
        return [], 0, "", dict.fromkeys(_USAGE_FIELDS, 0)
    all_chunks = [c for doc in documents for c in chunks_for(doc)]
    usage: dict[str, int] = dict.fromkeys(_USAGE_FIELDS, 0)
    # (path, raw, parseable). Collected across rounds, then sorted by path, so the transcript and
    # the event order do not depend on how many calls were in flight.
    collected: list[tuple[tuple[int, ...], str, bool]] = []
    pending: list[tuple[tuple[int, ...], list[DocumentChunk]]] = [
        ((i,), batch) for i, batch in enumerate(batch_chunks(all_chunks, budget=batch_chars))
    ]
    while pending:
        next_round: list[tuple[tuple[int, ...], list[DocumentChunk]]] = []
        for out in _run_round(pending, generate=generate, model=model, workers=workers):
            if out.error is not None:
                collected.append((out.path, f"extraction failed: {out.error}", False))
                usage["failed_batches"] += 1
                continue
            spent = {field: int(out.call_usage.get(field, 0)) for field in ("input", "output")}
            if out.call_usage.get("refused"):
                # The model declined. Nothing in this batch was read, and an empty reply parsed as
                # "no events" would put that silence on the buy screen as a clean bill.
                collected.append((out.path, "[REFUSED] the model declined this batch", False))
                usage["refused_batches"] += 1
                usage["failed_batches"] += 1
                usage["calls"] += 1
                for field, spent_tokens in spent.items():
                    usage[field] += spent_tokens
                continue
            if out.call_usage.get("truncated") and len(out.batch) > 1:
                # The reply ran out of room with several documents in the call. Splitting is the only
                # thing worth trying: temperature is zero, so asking again unchanged truncates again
                # in the same place. The tokens spent are still counted — they were spent.
                usage["retried_batches"] += 1
                usage["calls"] += 1
                for field, spent_tokens in spent.items():
                    usage[field] += spent_tokens
                collected.append((out.path, "[TRUNCATED] retried one document at a time", False))
                next_round.extend(((*out.path, j), [chunk]) for j, chunk in enumerate(out.batch))
                continue
            collected.append((out.path, out.raw, True))
            usage["calls"] += 1
            for field, spent_tokens in spent.items():
                usage[field] += spent_tokens
            if out.call_usage.get("truncated"):
                # One document, and the reply STILL ran out of room. Whatever it found is kept; what
                # it did not reach is unknown, and unknown is what the caller has to be told.
                usage["truncated_batches"] += 1
                usage["failed_batches"] += 1
        pending = next_round
    collected.sort(key=lambda item: item[0])

    events: list[ExtractedEvent] = []
    discarded = 0
    for _path, raw, parseable in collected:
        if not parseable:
            continue
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
    return unique, discarded, "\n\n".join(raw for _p, raw, _ok in collected), usage


#: Output cap per extraction call. Events are one short line each; this is generous for a batch.
MAX_OUTPUT_TOKENS = 3000
DEFAULT_MODEL = "claude-haiku-4-5"


def default_generate(
    api_key: str,
    *,
    max_tokens: int = MAX_OUTPUT_TOKENS,
    max_retries: int = 5,
    timeout: float = 120.0,
) -> GenerateFn:
    """The real model call for extraction — **with no tools, deliberately**.

    The veto path gives the model web search. This one must not have it. The whole point is that
    the model reads documents this repo fetched, hashed and kept, so that every claim it makes can
    be checked against bytes on disk. Handing it a search tool would let a passage come from
    somewhere nobody archived, and the verification guard would silently have nothing to check
    against.

    **One client, built once and shared.** It was constructed per call, which opened a fresh
    connection pool for every batch — invisible at 25 calls a night and a real cost at two thousand.
    The SDK's client is safe to call from several threads, which is what makes ``workers`` possible
    at all. ``max_retries`` is the SDK's own backoff over 429s and 5xx, raised from its default of 2
    because a long backfill will meet a rate limit and the right answer to one is to wait.

    **Built on first use, not here.** The SDK import stays inside the call because ``choose_backend``
    constructs this function merely to decide what the reader *would* be, and a missing ``ai`` extra
    must surface as a named absence on the page rather than an ImportError during selection. The
    lock is held only for the construction, so the shared client is created exactly once.
    """
    lock = threading.Lock()
    cell: dict[str, Any] = {}

    def client() -> Any:
        with lock:
            if "client" not in cell:
                import anthropic

                cell["client"] = anthropic.Anthropic(
                    api_key=api_key, max_retries=max_retries, timeout=timeout
                )
            return cell["client"]

    def generate(model_id: str, prompt: str) -> tuple[str, dict[str, int]]:
        resp = client().messages.create(
            model=model_id,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        usage = {
            "input": int(getattr(resp.usage, "input_tokens", 0) or 0),
            "output": int(getattr(resp.usage, "output_tokens", 0) or 0),
        }
        if resp.stop_reason == "refusal":
            # NOT an empty reading. The documents in this call went unread, and the caller has to
            # be able to tell that from a filing that simply carried nothing material. Returning
            # ``("", {})`` counted it as a clean call with no events — silence as a clean bill.
            return "", {**usage, "refused": 1}
        # Same defensive read as `ai_brief`. Here the client is typed `Any` so a strict checker
        # cannot object, which makes this the more dangerous of the two: nothing would have told us.
        text = "".join(
            str(getattr(b, "text", "")) for b in resp.content if getattr(b, "type", None) == "text"
        )
        return text, {
            **usage,
            # The cloud's spelling of the same fact. A cut-off reply is not a reading of the
            # documents that produced it, wherever the model ran.
            "truncated": 1 if resp.stop_reason == "max_tokens" else 0,
        }

    return generate
