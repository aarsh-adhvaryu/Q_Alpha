"""Filings: fetch, archive, read. It changes no book and makes no decision.

    uv run python scripts/evidence.py daily                             # the evening's read
    uv run python scripts/evidence.py backfill --only INFY,WIPRO --workers 8   # a year, once

For every name in :func:`~qalpha.live.screen.research_scope` — what SYSTEM holds plus the
candidates the investor will be shown — it archives NSE's regulatory-indicator file and each name's
announcement index, downloads every filing in the window, extracts events with a verbatim quote
checked against the archived bytes, and records coverage per name. A name never read before is not
read in an evening: it needs a year of filings, which is the ``backfill`` command's job.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from qalpha.config import Config
from qalpha.live.announcements import (
    Announcement,
    SourceDocument,
    documents_for,
    fetch_and_archive_index,
    fetch_document,
    since,
)
from qalpha.live.console import use_utf8
from qalpha.live.evidence import (
    STALENESS_TOLERANCE_DAYS,
    Provenance,
    load_archive,
    parse_reg_ind,
    reg_ind_url,
    write_archive,
)
from qalpha.live.extraction import (
    DEFAULT_MODEL,
    EXTRACTION_VERSION,
    PROMPT_CHAR_BUDGET,
    ExtractedEvent,
    GenerateFn,
    corpus_reader,
    event_rows,
    extract,
    reader_matches,
)
from qalpha.live.localmodel import choose_backend
from qalpha.live.pretrade import AnnouncementCoverage
from qalpha.live.screen import research_scope
from qalpha.live.twin import _append_jsonl

EVENT_LOG = Path("data/evidence/events.jsonl")
#: Documents already put through the extractor, keyed on their content hash. Without it the same
#: filing is re-read every day of its window — measured at ~33 model calls a day, roughly ten times
#: what is needed, because a 10-day window re-presents the same documents ten times.
EXTRACTED_LOG = Path("data/evidence/extracted.jsonl")
COVERAGE_LOG = Path("data/evidence/coverage.jsonl")

#: How far back to look for filings. Wider than a day so a missed run is caught up rather than
#: leaving a permanent hole — GitHub drops scheduled jobs under load, and one was dropped on
#: 2026-09-05.
LOOKBACK_DAYS = 10

#: How far back to read for a name **never covered before**. Ten days of history is not a basis for
#: judging a company: an auditor resignation from day eleven would simply be invisible, and the name
#: would read clean because nobody looked. A first sighting reads a year; every day after that reads
#: :data:`LOOKBACK_DAYS`, because by then the gap is genuinely small.
BOOTSTRAP_DAYS = 365

#: Cap on documents fetched per name per run. A first run on a name with years of filings would
#: otherwise download hundreds; the window bounds it in practice and this bounds the pathological
#: case. **Hitting it makes coverage incomplete, which reads UNKNOWN — it never silently passes.**
MAX_DOCUMENTS_PER_NAME = 25  # retained: other modules import it
#: Filings fetched per name per run. Fetching is a cached GET; this only bounds a pathological name.
#:
#: **It was 200, and 200 was below a real name's window.** VEDL filed 228 documents in 365 days, so
#: the backfill fetched 200, read 194, and wrote INCOMPLETE — and `complete` requires
#: ``documents_read >= filings_in_window``, which 194 of 228 can never satisfy. The name would have
#: read "Filings NOT read" on the buy screen for ever, and every rebuild would have paid to
#: reproduce that. This is the same defect the comment two blocks down describes being fixed once
#: already, at a different cap: a fetch budget silently redefining what was filed.
#:
#: A cap still exists because an unbounded loop against a remote server is not a thing to ship, but
#: it is now well above the busiest name NSE has shown us rather than just above the quiet ones.
MAX_FETCH_PER_NAME = 1_000
#: Documents sent to the MODEL per name per run — the cap that actually costs tokens and minutes.
#: Unread documents carry over, so a 365-day bootstrap closes over several runs rather than never.
MAX_EXTRACT_PER_RUN = 25
#: The same cap during a backfill. High enough to finish any real window in one pass, and a number
#: rather than ``None`` so a pathological name still ends.
MAX_EXTRACT_BACKFILL = 2_000
#: Concurrent calls a backfill makes by default. The reads are independent and the sequential loop
#: spent nearly all its wall clock waiting on the network. Eight is deliberately unambitious: it is
#: well inside a starting rate limit, and the SDK backs off and retries a 429 rather than dropping
#: the batch.
BACKFILL_WORKERS = 8
#: A backfill stops itself after this long. Four hours is longer than the whole corpus should take
#: and short enough that a run left going wrong does not run until morning.
BACKFILL_BUDGET_SECONDS = 14_400


def _fetch_one_reg_ind(day: date) -> tuple[dict[str, dict[str, str]], Provenance | None]:
    """One day's regulatory-indicator file, archived before it is parsed."""
    import urllib.request

    from qalpha.live.announcements import REFERER, USER_AGENT

    rows, prov = load_archive(day)
    if prov is not None:
        return rows, prov
    try:
        request = urllib.request.Request(
            reg_ind_url(day), headers={"User-Agent": USER_AGENT, "Referer": REFERER}
        )
        with urllib.request.urlopen(request, timeout=45) as response:
            status, payload = int(response.status), bytes(response.read())
    except Exception:
        return {}, None
    # A partial file is worse than none: it would read as "no indicator active" for every name it
    # happens not to contain. The real file is ~600 KB.
    if status != 200 or len(payload) < 10_000:
        return {}, None
    prov = write_archive(payload, day, http_status=status)
    print(
        f"[evidence] REG1_IND {day} archived \u00b7 {prov.byte_length:,}b \u00b7 sha {prov.sha256[:16]}\u2026"
    )
    return parse_reg_ind(payload.decode("utf-8", errors="replace")), prov


def _fetch_reg_ind(as_of: date) -> tuple[dict[str, dict[str, str]], Provenance | None]:
    """The most recent regulatory-indicator file **within the staleness tolerance**.

    The exchange publishes on trading days, so a weekend or holiday run has no file of its own and
    must read back to the last session. Walking back further than
    :data:`~qalpha.live.evidence.STALENESS_TOLERANCE_DAYS` is refused rather than stretched:
    ``assess`` would reject the file anyway, and a caller that quietly widened the window would be
    substituting an old fact for a missing one.
    """
    for back in range(STALENESS_TOLERANCE_DAYS + 1):
        day = as_of - timedelta(days=back)
        rows, prov = _fetch_one_reg_ind(day)
        if prov is not None:
            if back:
                print(
                    f"[evidence] no file for {as_of} (non-trading day) \u2014 using {day}, {back}d old"
                )
            return rows, prov
    print(
        f"[evidence] no REG1_IND within {STALENESS_TOLERANCE_DAYS} days of {as_of} \u2014 "
        "the exchange dimension reads UNKNOWN, which blocks every PASS"
    )
    return {}, None


def _already_extracted() -> set[str]:
    """Document hashes whose findings are **on file** at the current extractor version.

    A version bump re-reads everything on purpose: EX-1 rated routine results `high` because the
    prompt never said material to whom, so its findings are not the findings EX-2 would produce.

    **A row alone is not enough.** It must carry ``events_recorded`` — written only after the events
    it counts were durably appended (see :func:`_mark_extracted`). Rows without that field were
    written by the version of this script that marked documents read *before* persisting anything,
    so they attest to nothing; they are re-read, which costs tokens and loses no evidence.

    That is not hypothetical. On 2026-09-08 ``extracted.jsonl`` carried **199 rows at EX-2 while
    events.jsonl held 193 events, every one of them EX-1** — 199 documents recorded as read whose
    findings existed nowhere. Under the old rule every one of them was a permanent cache hit.
    """
    if not EXTRACTED_LOG.exists():
        return set()
    out: set[str] = set()
    for line in EXTRACTED_LOG.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            row.get("extraction_version") == EXTRACTION_VERSION
            and reader_matches(row.get("reader"))
            and "events_recorded" in row
        ):
            out.add(str(row.get("sha256", "")))
    return out


def _mark_extracted(hashes: Iterable[str], *, events_recorded: int, reader: str) -> None:
    """Record that these documents were read **and that their findings reached the log**.

    Call this LAST — after the events and the coverage row are on disk. The receipt is written after
    the thing it is a receipt for, so an interruption can only ever lose the receipt, never the
    evidence. The reverse ordering is what produced the 199 orphaned rows above: the mark was
    durable per name inside the loop while the events waited in memory for the loop to finish, and
    anything that stopped the run in between turned unread documents into permanent cache hits.

    ``events_recorded`` is the count for this batch, and **zero is a real answer** — a filing that
    genuinely says nothing a shareholder need worry about is a no-event receipt, which is different
    from a document nobody read.

    ``reader`` is **the model that actually read it**, passed in from the backend that ran, never
    :func:`corpus_reader`. Those two are the same thing only when the configured corpus reader is
    the one that ran, and the whole point of the field is to be able to tell when they are not: a
    row stamped with the reader we *meant* to use would be the labelling defect this repo keeps
    finding, written by the very mechanism built to prevent it.
    """
    rows = [
        {
            "sha256": h,
            "extraction_version": EXTRACTION_VERSION,
            # WHO READ IT, not just under which instructions. A receipt that names only the version
            # would let a document read by the local 8B satisfy a corpus defined as one reader's
            # work — the mixture EX-3 exists to make impossible.
            "reader": reader,
            "events_recorded": events_recorded,
            "_key": f"{EXTRACTION_VERSION}:{reader}:{h}",
        }
        for h in hashes
    ]
    if not rows:
        return
    try:
        _append_jsonl(EXTRACTED_LOG, rows, key="_key")
    except Exception as exc:
        print(f"[evidence] WARNING: extraction ledger not updated ({exc})", file=sys.stderr)


def _record_coverage(
    as_of: date, ticker: str, cov: AnnouncementCoverage, window_days: int, reader: str
) -> None:
    """Write one name's coverage row the moment that name is finished.

    This was a single bulk write after the whole loop, which meant a run that did not reach the end
    recorded no coverage for any name — including the ones it had fully read. On 2026-09-08 the step
    was killed at its 20-minute cap having produced 110 events, and **not one coverage row was
    written**, so every name kept reading "Filings NOT read" on the buy screen while its findings sat
    in ``events.jsonl``. Same disease as the extraction receipt, one file over.

    ``_append_jsonl`` supersedes by revision rather than replacing, so a row written here can be
    corrected by a later run and never lost — including the incomplete rows a killed run leaves,
    which is what ``_seen_before`` needs in order not to burn a name's 365-day bootstrap.

    ``reader`` is the model that actually ran, and is empty when none did. Never
    :func:`corpus_reader`: stamping the reader we intended would make a local read look like a
    corpus read, which is the one thing the field exists to catch.
    """
    try:
        _append_jsonl(
            COVERAGE_LOG,
            [
                {
                    "as_of": as_of.isoformat(),
                    "ticker": ticker,
                    "filings_in_window": cov.filings_in_window,
                    "documents_read": cov.documents_read,
                    "extraction_ran": cov.extraction_ran,
                    "index_fetched": cov.index_fetched,
                    "complete": cov.complete,
                    # The window this verdict actually covers. Without it a reader cannot tell a
                    # ten-day look from a year's, and both would print the same word.
                    "window_days": window_days,
                    "extraction_version": EXTRACTION_VERSION,
                    #: Which model produced this verdict. A reader is part of what a reading IS.
                    "reader": reader,
                    "_key": f"{as_of.isoformat()}:{ticker}",
                }
            ],
            key="_key",
        )
    except Exception as exc:
        print(f"[evidence] WARNING: coverage not recorded for {ticker} ({exc})", file=sys.stderr)


def _recall_events(hashes: set[str], path: Path = EVENT_LOG) -> list[ExtractedEvent]:
    """Reload the findings already on file for these documents. **The cache must not lose warnings.**

    A cached document counted toward coverage and returned NOTHING to the assessment, so the same
    archived filing produced ``WATCH`` on the run that read it and ``PASS`` on every run after:

        first run   coverage complete · 1 verified concern · WATCH
        cached run  coverage complete · 0 findings         · PASS

    The event was on disk the whole time. The cached path simply never read it back — which turns a
    real auditor-resignation warning into a clean bill on the second day, silently. Reading the
    document again would cost the tokens the cache exists to save; reading its FINDINGS costs a file
    scan.

    Only current-version, verified rows are returned, for the same reasons the live path applies:
    EX-1 rated routine results ``high``, and an unverified quote is a fabrication.
    """
    if not hashes or not path.exists():
        return []
    out: list[ExtractedEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("kind") != "event" or str(row.get("doc_sha256", "")) not in hashes:
            continue
        if (
            row.get("extraction_version") != EXTRACTION_VERSION
            or not reader_matches(row.get("model"))
            or not row.get("verified")
        ):
            continue
        try:
            out.append(
                ExtractedEvent(
                    ticker=str(row["ticker"]),
                    event_type=str(row.get("event_type", "")),
                    event_date=(
                        date.fromisoformat(str(row["event_date"]))
                        if row.get("event_date")
                        else None
                    ),
                    materiality=str(row.get("materiality", "")),
                    passage=str(row.get("passage", "")),
                    summary=str(row.get("summary", "")),
                    uncertainty=str(row.get("uncertainty", "")),
                    doc_sha256=str(row.get("doc_sha256", "")),
                    doc_url=str(row.get("doc_url", "")),
                    disseminated_at=datetime.fromisoformat(
                        str(row.get("disseminated_at", "1970-01-01T00:00:00+00:00"))
                    ),
                    model=str(row.get("model", "")),
                    extraction_version=str(row.get("extraction_version", "")),
                    verified=True,
                )
            )
        except (KeyError, ValueError):
            continue
    return out


def _persist_events(events: list[ExtractedEvent], as_of: date) -> bool:
    """Append one name's events to the log. ``True`` only if they are durably on disk.

    Returns True for an empty list: nothing to write is not a failure, and the caller still needs to
    write a no-event receipt for the documents it read.
    """
    if not events:
        return True
    try:
        _append_jsonl(EVENT_LOG, event_rows(events, as_of=as_of), key="_key")
        return True
    except Exception as exc:
        print(f"[evidence] WARNING: events not recorded ({exc})", file=sys.stderr)
        return False


def _seen_before(ticker: str) -> bool:
    """Has this name ever been **successfully** covered at the current extractor?

    Not "does a row exist". A row is written every run including the failed ones — no API key, an
    extraction that errored, a document cap that left the window unread. Counting those as seen
    means the 365-day bootstrap is skipped for a name nobody ever finished reading, which is the
    only chance that name gets at a year of history.

    Sixteen incomplete rows written during local testing on 2026-09-08 would have done exactly that
    to sixteen names.
    """
    if not COVERAGE_LOG.exists():
        return False
    for line in COVERAGE_LOG.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            row.get("ticker") == ticker
            and row.get("complete")
            and row.get("extraction_version") == EXTRACTION_VERSION
            # AND BY THE CORPUS READER. Without this a name fully read by yesterday's local model
            # would count as seen, the 365-day bootstrap would be skipped, and the corpus would
            # quietly become two readers' work wearing one label.
            and reader_matches(row.get("reader"))
        ):
            return True
    return False


def _window_days(ticker: str) -> int:
    """The assessment window for this name, in days. Recorded, never assumed by a reader."""
    return LOOKBACK_DAYS if _seen_before(ticker) else BOOTSTRAP_DAYS


def _cover_name(
    ticker: str,
    as_of: date,
    cutoff: date,
    generate: GenerateFn | None,
    model: str,
    batch_chars: int = PROMPT_CHAR_BUDGET,
    max_extract: int = MAX_EXTRACT_PER_RUN,
    workers: int = 1,
    show_progress: bool = False,
) -> tuple[AnnouncementCoverage, list[ExtractedEvent], int]:
    """Fetch, archive, read and extract one name. Returns ``(coverage, events, unverified)``.

    ``max_extract`` and ``workers`` are the two dials the backfill turns. The nightly run keeps the
    defaults — 25 documents, one call at a time — because it is metered against a local GPU and a
    fifteen-minute window. The backfill lifts both because it is a different job: read everything
    once, against a reader that can take the load.
    """
    anns, index_prov = fetch_and_archive_index(ticker, as_of)
    if anns is None:
        print(f"  {ticker:<16} index UNREACHABLE — dimension reads UNKNOWN")
        return AnnouncementCoverage(), [], 0

    # COUNT THE WHOLE WINDOW, FETCH ONLY A CAPPED SLICE OF IT. The previous version sliced and
    # counted the same list, so a name with 30 filings reported "25 read of 25" and read as fully
    # covered. The cap is a fetch budget, never a redefinition of what was filed — and a name that
    # exceeds it is INCOMPLETE, which is UNKNOWN, which is the honest answer.
    in_window = [a for a in since(anns, cutoff) if a.has_document]

    # FETCH THE WHOLE WINDOW; CAP ONLY THE MODEL CALLS. Fetching is a cached HTTP GET and costs
    # nothing after the first time; extraction is what costs tokens and minutes. The old code capped
    # the FETCH at the newest 25, which made a name with more filings than that **permanently
    # incomplete**: `complete` requires documents_read >= filings_in_window, documents_read could
    # never exceed 25, and every run re-selected the same newest 25. Thirty filings meant UNKNOWN
    # for ever, and the buy screen said "Filings NOT read" for that name until the end of time.
    stored: list[Announcement] = []
    for ann in in_window[:MAX_FETCH_PER_NAME]:
        if fetch_document(ann) is not None:
            stored.append(ann)
    docs = documents_for(stored)

    truncated = 0  # chunking means nothing is truncated; kept as a guard, not an expectation
    events: list[ExtractedEvent] = []
    unverified = 0
    extraction_ran = False
    done = _already_extracted()
    # Documents already carrying a current-version receipt have been read on an earlier run. They
    # count toward coverage without costing a token again — that is what makes the window close
    # ACROSS runs instead of restarting every day (gate 3: "bootstrap the declared filing window
    # across capped runs").
    already = [d for d in docs if d.provenance.sha256 in done]
    fresh = [d for d in docs if d.provenance.sha256 not in done]
    if len(fresh) > max_extract:
        print(
            f"  {ticker:<16} {len(fresh)} unread of {len(in_window)} filed — extracting "
            f"{max_extract} this run, the rest resume tomorrow"
        )
        fresh = fresh[:max_extract]
    # WHAT THE CACHE ALREADY KNOWS. Without this the findings of a cached document never reach the
    # assessment, and a filing that produced WATCH on Monday produces PASS on Tuesday.
    recalled = _recall_events({d.provenance.sha256 for d in already})
    if recalled:
        print(f"  {ticker:<16} {len(recalled)} concern(s) recalled from earlier runs")
    read_docs: list[SourceDocument] = []
    if docs and not fresh:
        # Every document in this window carries a receipt proving its findings reached events.jsonl
        # (``_already_extracted`` only counts rows that do). Re-reading would cost the same tokens
        # for the same answer. This branch used to assume that rather than check it, so a poisoned
        # cache produced `complete: true` with no events on file — unread reading as clean, which is
        # the fifteenth row of the table in CLAUDE.md.
        extraction_ran = True
        docs_to_read: list[SourceDocument] = []
    else:
        docs_to_read = fresh
    if generate is not None and docs_to_read:
        # A LONG RUN THAT PRINTS NOTHING IS INDISTINGUISHABLE FROM A HUNG ONE. VEDL's 228
        # filings took most of an hour in silence while the bill ran. One line, rewritten in
        # place, so a name's progress is visible without a thousand lines of log.
        def _tick(done: int, total: int, events: int) -> None:
            if not show_progress:
                return
            pct = 100 * done / max(1, total)
            print(
                f"\r  {ticker:<16} reading… batch {done}/{total} ({pct:3.0f}%) · "
                f"{events} reply(s) in",
                end="",
                flush=True,
            )

        # RESUMABILITY, and it is worth the indirection. Receipts used to be written once, after
        # every document in the name had been read — so VEDL's 228 filings, an hour of reading,
        # survived only if nothing interrupted them. Twice on 2026-09-11 something did (an API
        # credit outage, then a Ctrl-C) and the whole name was paid for again. Now each finished
        # document is made durable as it finishes, in the same order as before: events first, then
        # the receipt that attests to them, and no receipt at all if the events did not land.
        checkpointed: list[str] = []

        def _checkpoint(events_so_far: list[ExtractedEvent], finished: frozenset[str]) -> None:
            if not _persist_events(events_so_far, as_of):
                return  # the findings are not on file, so nothing may attest that they are
            _mark_extracted(sorted(finished), events_recorded=len(events_so_far), reader=model)
            checkpointed.extend(finished)

        found, discarded, _raw, usage, unread = extract(
            docs_to_read,
            generate=generate,
            model=model,
            batch_chars=batch_chars,
            workers=workers,
            progress=_tick if show_progress else None,
            checkpoint=_checkpoint,
        )
        if show_progress:
            print()  # close the rewritten line before anything else prints
        _TOKENS["input"] += usage.get("input", 0)
        _TOKENS["output"] += usage.get("output", 0)
        _TOKENS["calls"] += usage.get("calls", 0)
        if usage.get("refused_batches"):
            print(
                f"  {ticker:<16} {usage['refused_batches']} batch(es) DECLINED by the model — "
                "those documents are unread, not clean"
            )
        # PER DOCUMENT, NOT PER NAME. This was `failed_batches == 0`, so one cut-off reply among
        # six hundred calls marked every document in the name unread — VEDL lost all 228 on
        # 2026-09-11 having paid for every one, and would have every run after. A document whose
        # batches all succeeded has been read; only the ones in a failed batch have not.
        read_docs = [d for d in docs_to_read if d.provenance.sha256 not in unread]
        extraction_ran = usage.get("calls", 0) > 0
        events, unverified = found, discarded
        if usage.get("failed_batches", 0):
            cut = usage.get("truncated_batches", 0)
            # "The call died" and "the reply ran out of room" are different problems with different
            # fixes — a dead server against a token cap that cannot hold the batch it was given.
            why = f"{usage['failed_batches']} failed batch(es)"
            if cut:
                why += f", {cut} of them cut off at the model's token cap"
            print(f"  {ticker:<16} extraction had {why}")
        # NOT `elif`. A failed batch is a warning about the documents IN that batch; it is not a
        # reason to throw away the findings of the ones that succeeded. Written as `elif`, VEDL read
        # 128 of 228 documents on 2026-09-11, found their events, and discarded every one of them
        # because 100 others failed during an API credit outage — while coverage went on claiming
        # 128 read. A count asserting a reading whose evidence is not on file is the defect this
        # module exists to prevent, and no receipt meant paying to read those 128 again.
        #
        # ORDER IS THE WHOLE FIX. Events first, receipt second — and no receipt at all if the events
        # did not land. An interruption here can lose a receipt, which costs one re-read tomorrow.
        # It can no longer lose the evidence while keeping the receipt, which cost 199 documents.
        if _persist_events(found, as_of):
            # Receipts ONLY for documents this run actually read. A receipt over a document in a
            # failed batch would turn an unread filing into a permanent cache hit — the 199-row
            # defect, one file over.
            _mark_extracted(
                [d.provenance.sha256 for d in read_docs],
                events_recorded=len(found),
                reader=model,
            )
        else:
            extraction_ran = False  # the findings are not on file, so this name is NOT covered
    elif generate is None:
        pass  # reported once for the whole run, not once per name
    else:
        extraction_ran = True  # nothing filed: there was nothing to extract, and that is complete

    # Read = carries a receipt. `already` were read on earlier runs; the fresh batch joins them only
    # if this run's extraction actually landed. Counting len(docs) counted FETCHED, not read, which
    # is the same "listing is not reading" defect AnnouncementCoverage was created to stop.
    read_now = len(already) + (len(read_docs) if extraction_ran else 0)
    coverage = AnnouncementCoverage(
        # The true window size, not the capped slice. This is the number that decides completeness.
        filings_in_window=len(in_window),
        documents_read=read_now,
        documents_truncated=truncated,
        extraction_ran=extraction_ran,
        index_fetched=True,
    )
    flag = "✓" if coverage.complete else "…"
    print(
        f"  {ticker:<16} {flag} {len(in_window):>3} filed · {read_now:>3} read "
        f"({len(already)} cached + {len(fresh) if extraction_ran else 0} new) · "
        f"{len(events):>2} event(s) · {unverified} discarded"
        + (f" · index sha {index_prov.sha256[:12]}…" if index_prov else "")
    )
    # Recalled first: they are the older findings, and the order a reader sees them in should be
    # the order they were found in.
    return coverage, [*recalled, *events], unverified


def cmd_daily(cfg: Config, as_of: date, *, bootstrap: bool = False) -> int:
    print(f"[evidence] reading filings for {as_of} — records evidence, changes no book")
    _fetch_reg_ind(as_of)  # archived for the record; read by the page and the investor's packet
    tickers = research_scope(as_of)
    if not tickers:
        print("[evidence] no holdings and no candidates — nothing to cover", file=sys.stderr)
        return 2
    print(
        f"[evidence] covering {len(tickers)} name(s) · filings since "
        f"{as_of - timedelta(days=LOOKBACK_DAYS)}"
    )

    # WHICH MODEL READS THE FILINGS IS A DECISION, NOT A DEFAULT. `choose_backend` prefers a local
    # model when one is configured and NEVER silently falls back to the cloud when it is
    # unreachable — sending documents over the network on the one evening the user believed
    # nothing was would be the worst kind of quiet substitution.
    backend = choose_backend()
    model = backend.model or (os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL)
    generate = backend.generate
    batch_chars = backend.batch_chars or PROMPT_CHAR_BUDGET
    print(f"[evidence] {backend.note}")
    if generate is None:
        print(
            "[evidence] coverage stays incomplete and every name reads UNKNOWN, which is the "
            "honest answer. Unread is not clean."
        )
    elif not reader_matches(model):
        # SAY IT, DO NOT SILENTLY WASTE THE EVENING. Under EX-3 a row only counts toward the corpus
        # when the reader that produced it IS the corpus reader. A nightly run under any other model
        # still reads real filings and still records real events — it simply cannot make a name read
        # on the buy screen, and without this line the user would watch a GPU work for an hour and
        # then see "Filings NOT read" against every name with nothing explaining why.
        print(
            f"[evidence] NOTE: {model} is not the corpus reader ({corpus_reader()}). These rows are "
            "a real reading and are kept, but they do not count toward EX-3 coverage, so the buy "
            "screen will keep saying the filings were not read. Point both at one reader — see "
            "reports/PREREGISTRATION_EX3_CORPUS.md."
        )

    coverage: dict[str, AnnouncementCoverage] = {}
    #: Names never covered before. Named at the end with the command that fixes them — never
    #: silently skipped, because a name nobody read must not look like a name with nothing to read.
    deferred: list[str] = []
    windows: dict[str, int] = {}
    events: dict[str, list[ExtractedEvent]] = {}
    unverified: dict[str, int] = {}
    # A BUDGET, NOT A CAP. The workflow gives this step 20 minutes and SIGKILLs it at the boundary,
    # and `continue-on-error` then reports the corpse as "success" — which is exactly what happened
    # on 2026-09-08 (16:44:54 → 17:05:06, killed at 20m12s, step green, no coverage written at all).
    # Stopping ourselves a little early means the run ends by choice: everything done is on disk,
    # the names not reached are named, and the exit says so. Being killed loses the summary and the
    # in-flight name's work; stopping loses neither.
    budget = timedelta(seconds=int(os.environ.get("EVIDENCE_BUDGET_SECONDS", "900")))
    started = datetime.now(UTC)
    # `covered` is the count already finished — at the break it equals the loop index, because
    # every earlier iteration wrote its coverage row before incrementing.
    for covered, ticker in enumerate(tickers):
        if datetime.now(UTC) - started > budget:
            print(
                f"[evidence] time budget {budget} reached after {covered}/{len(tickers)} name(s). "
                f"Stopping cleanly — everything read so far is on disk, and the receipts mean "
                f"tomorrow's run resumes past it rather than starting again."
            )
            break
        days = _window_days(ticker)
        if days != LOOKBACK_DAYS and not bootstrap:
            # A FIRST SIGHTING IS A BACKFILL, AND A BACKFILL IS NOT AN EVENING JOB. Reading a year
            # of one name's filings at one call at a time is the deliberate `backfill` command --
            # it has workers, a long budget and a progress bar. Doing it inline made a double-click
            # sit on a 365-day read, per unseen name, before the login button was usable.
            #
            # NOTHING IS ASSUMED IN ITS PLACE. No coverage row is written, so `_seen_before` stays
            # false and the buy screen keeps printing "Filings NOT read -- that is a gap, not a
            # clean bill". The alternative -- covering it on the 10-day window -- is the defect
            # BOOTSTRAP_DAYS exists to prevent: an auditor resignation from day eleven would be
            # invisible and the name would read CLEAN because nobody looked.
            deferred.append(ticker)
            continue
        windows[ticker] = days
        if days != LOOKBACK_DAYS:
            print(
                f"  {ticker:<16} first sighting — reading {days} days of filings, not {LOOKBACK_DAYS}"
            )
        cov, found, bad = _cover_name(
            ticker, as_of, as_of - timedelta(days=days), generate, model, batch_chars
        )
        coverage[ticker] = cov
        events[ticker] = found
        unverified[ticker] = bad
        # DURABLE PER NAME, for the same reason the events are. This was one bulk write after the
        # loop, so the 2026-09-08 timeout produced 110 events and ZERO coverage rows — every name
        # still reading "Filings NOT read" on the buy screen while its findings sat in events.jsonl.
        # A row written here can only be superseded by a later revision, never lost.
        _record_coverage(as_of, ticker, cov, windows[ticker], backend.model if generate else "")

    # Events are already on disk — ``_cover_name`` persists each name's findings before it writes
    # that name's receipt. This used to be the single bulk write for the whole run, which is what
    # made every event in the run depend on the last name finishing.
    all_events = [e for found in events.values() for e in found]
    if all_events:
        print(f"[evidence] {len(all_events)} event(s) recorded → {EVENT_LOG}")

    if deferred:
        # NAMED, WITH THE COMMAND THAT FIXES IT. A deferred name reads UNKNOWN on the buy screen,
        # which is correct and also indistinguishable from a name whose filings were read and were
        # clean -- unless the run says which it is, in words, here.
        print(
            f"[evidence] {len(deferred)} name(s) have never been covered and were NOT read "
            f"tonight: {', '.join(t.removesuffix('.NS') for t in deferred)}."
        )
        print(
            "[evidence] each needs a year of filings read once, which is a job with its own "
            "command and not something an evening should do one call at a time:"
        )
        # The flag is `--only`, comma-separated. Printed from the real parser's spelling because a
        # suggested command that errors is worse than no suggestion at all.
        names = ",".join(t.removesuffix(".NS") for t in deferred)
        print(
            f"[evidence]     uv run python scripts/evidence.py backfill --only {names} --workers 8"
        )
        print(
            "[evidence] until then they read UNKNOWN on the buy screen, which is the honest "
            "answer. Unread is not clean."
        )

    complete = sum(1 for c in coverage.values() if c.complete)
    print(f"[evidence] {complete} of {len(tickers)} name(s) fully covered")
    return 0


#: Tokens billed across this process, for the one figure a backfill is asked about afterwards.
_TOKENS: dict[str, int] = {"input": 0, "output": 0, "calls": 0}

#: List prices in USD per million tokens, for an *estimate* printed at the end of a backfill.
#: Copied from the published price list on 2026-09-11 and never fetched at runtime, so it is a
#: figure to sanity-check the bill against, not the bill. A reader missing from this table prints
#: its token counts and no money.
_LIST_PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-5": (5.00, 25.00),
}


def _spend_note(reader: str) -> str:
    """What this run cost, labelled as what it is: metered tokens, estimated money."""
    price = _LIST_PRICES.get(reader)
    tokens = (
        f"{_TOKENS['calls']:,} call(s) · {_TOKENS['input']:,} input + "
        f"{_TOKENS['output']:,} output tokens billed"
    )
    if price is None:
        return f"{tokens}. No list price on file for {reader}, so no cost is estimated here."
    dollars = _TOKENS["input"] / 1e6 * price[0] + _TOKENS["output"] / 1e6 * price[1]
    return (
        f"{tokens}. At {reader}'s list price that is about ${dollars:,.2f} — an ESTIMATE from a "
        "hard-coded price table, not a figure read from your invoice."
    )


def cmd_backfill(
    cfg: Config,
    as_of: date,
    *,
    workers: int,
    budget_seconds: int,
    only: Sequence[str] = (),
) -> int:
    """Read the whole declared window for every name, once, with one reader.

    **This is not the nightly run with bigger numbers.** The nightly run is metered: 25 documents a
    name, fifteen minutes a run, a local model, and a name that overruns ends the run. Those caps
    are right for an evening on one GPU and wrong for building a corpus — at 25 documents a name and
    one name a run, the fifteen names in scope needed roughly eighty-four evenings.

    What makes it a different job rather than the same job impatient:

    * **One reader, named in the label.** ``EX-3`` means these instructions read by
      :func:`~qalpha.live.extraction.corpus_reader`. A row from anything else is not part of this
      corpus and cannot satisfy it — see ``reports/PREREGISTRATION_EX3_CORPUS.md``.
    * **The cloud, explicitly.** ``prefer_local=False`` is passed here and nowhere else, so the one
      place document text leaves this machine is the one place that says it does.
    * **No per-name document cap**, because the point is to finish a window rather than nibble it.
    * **Concurrency**, which is the whole speed-up: the reads are independent, and the sequential
      loop was idle waiting on the network for almost all of its wall clock.

    The time budget stays, raised. A backfill that has to be killed is one that loses its in-flight
    name's work and its summary; one that stops itself keeps both, and every finished name is
    already durable.
    """
    reader = corpus_reader()
    print(f"[backfill] corpus read for {as_of} — extractor {EXTRACTION_VERSION}, reader {reader}")
    _rows, exchange_prov = _fetch_reg_ind(as_of)
    tickers = [
        t for t in research_scope(as_of) if not only or t in only or t.removesuffix(".NS") in only
    ]
    if not tickers:
        # NOT a completion. The nightly command returns 0 here, which is how two runs on 2026-09-10
        # were recorded `done` having covered nothing at all.
        print(
            "[backfill] no names to cover. With holdings on the book that means the book or the "
            "price panel could not be read — not that there was nothing to do.",
            file=sys.stderr,
        )
        return 2
    backend = choose_backend(prefer_local=False, workers=workers)
    print(f"[backfill] {backend.note}")
    if backend.generate is None:
        print(
            "[backfill] no cloud reader available, so nothing would be read. Set ANTHROPIC_API_KEY.",
            file=sys.stderr,
        )
        return 2
    if exchange_prov is None:
        print("[backfill] note: the exchange indicator file was not reachable; filings still read.")

    budget = timedelta(seconds=budget_seconds)
    started = datetime.now(UTC)
    covered = 0
    for index, ticker in enumerate(tickers, start=1):
        if datetime.now(UTC) - started > budget:
            print(
                f"[backfill] time budget {budget} reached after {covered}/{len(tickers)} name(s). "
                "Stopping cleanly — every finished name is on disk with its receipts, so the next "
                "run resumes past it instead of starting again."
            )
            break
        days = _window_days(ticker)
        print(f"  {ticker:<16} [{index}/{len(tickers)}] reading {days} days of filings")
        cov, found, bad = _cover_name(
            ticker,
            as_of,
            as_of - timedelta(days=days),
            backend.generate,
            backend.model,
            backend.batch_chars or PROMPT_CHAR_BUDGET,
            max_extract=MAX_EXTRACT_BACKFILL,
            workers=workers,
            show_progress=True,
        )
        _record_coverage(as_of, ticker, cov, days, backend.model)
        covered += 1
        print(
            f"  {ticker:<16} {'complete' if cov.complete else 'INCOMPLETE'} — "
            f"{cov.documents_read}/{cov.filings_in_window} read, {len(found)} event(s), "
            f"{bad} unverified quote(s) discarded"
        )
    elapsed = (datetime.now(UTC) - started).total_seconds()
    print(f"[backfill] {covered}/{len(tickers)} name(s) in {elapsed / 60:.1f} min.")
    print(f"[backfill] {_spend_note(backend.model)}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    # UTF-8 FIRST, before anything prints. Windows falls back to cp1252 when stdout is a pipe,
    # and `uv run` pipes its child: on 2026-09-11 the `mark` step died on a rupee sign.
    use_utf8()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["daily", "backfill"])
    ap.add_argument("--as-of", default=None, help="override the date (default: today, UTC)")
    ap.add_argument(
        "--workers",
        type=int,
        default=BACKFILL_WORKERS,
        help="concurrent model calls during a backfill (default: %(default)s)",
    )
    ap.add_argument(
        "--budget-seconds",
        type=int,
        default=BACKFILL_BUDGET_SECONDS,
        help="stop a backfill cleanly after this long (default: %(default)s)",
    )
    ap.add_argument(
        "--only",
        default="",
        help="comma-separated tickers to back-fill, instead of the whole research scope",
    )
    ap.add_argument(
        "--bootstrap",
        action="store_true",
        help=(
            "daily only: read a never-seen name's full 365-day window inline instead of deferring "
            "it to `backfill`. Off by default — an evening should not sit on a year of one name's "
            "filings at one call at a time before the page is usable."
        ),
    )
    args = ap.parse_args(argv)
    as_of = date.fromisoformat(args.as_of) if args.as_of else datetime.now(UTC).date()
    if args.cmd == "backfill":
        return cmd_backfill(
            Config(),
            as_of,
            workers=max(1, int(args.workers)),
            budget_seconds=max(60, int(args.budget_seconds)),
            only=tuple(t.strip() for t in args.only.split(",") if t.strip()),
        )
    return cmd_daily(Config(), as_of, bootstrap=bool(args.bootstrap))


if __name__ == "__main__":
    raise SystemExit(main())
