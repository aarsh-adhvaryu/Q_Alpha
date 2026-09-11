"""EX-3: one corpus, one reader, and a backfill that goes fast without going different.

Three properties carry this change, and each one is here because the alternative is a defect this
repo has already shipped once:

* **Concurrency changes the clock and nothing else.** A faster read that returns different events is
  not a faster read, it is a second instrument. Asserted by running the same documents at one worker
  and at eight and demanding identical output — events, discards, transcript and every token
  counter.
* **A reading has a reader.** A version label that names only the instructions lets a corpus be half
  one model's work and half another's, and nothing downstream can tell. Asserted by feeding the
  gates a complete, current, verified row from the wrong reader and requiring it to count for
  nothing.
* **Nothing to do is not something done.** ``cmd_daily`` returns 0 when it covers no names, which is
  how two runs on 2026-09-10 were recorded ``done`` having written no coverage at all. The backfill
  refuses instead.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, "scripts")

from qalpha.live.announcements import Announcement, SourceDocument
from qalpha.live.evidence import Provenance
from qalpha.live.extraction import (
    EXTRACTION_VERSION,
    corpus_reader,
    extract,
    reader_matches,
)

LONG_TEXT = (
    "The Board of Directors has approved the acquisition of a 51% stake in Acme Bottling "
    "Private Limited for a consideration of INR 4,200 million, subject to regulatory approvals. "
)


def _doc(symbol: str, text: str, sha: str) -> SourceDocument:
    ann = Announcement(
        symbol=symbol,
        seq_id="1",
        subject="General Updates",
        summary="",
        disseminated_at=datetime(2026, 8, 25, 16, 21, tzinfo=UTC),
        attachment_url=f"https://nsearchives.nseindia.com/corporate/{symbol}_x.pdf",
    )
    prov = Provenance(
        source_url=ann.attachment_url,
        retrieved_at_utc=datetime(2026, 9, 5, tzinfo=UTC),
        http_status=200,
        sha256=sha,
        byte_length=len(text),
        document_date=date(2026, 8, 25),
    )
    return SourceDocument(announcement=ann, text=text, provenance=prov)


def _corpus() -> list[SourceDocument]:
    """Enough documents, and one long enough to chunk, that batching actually has work to do."""
    return [
        _doc("VBL", LONG_TEXT * 60, "a" * 64),
        _doc("VBL", LONG_TEXT * 200, "b" * 64),
        _doc("VBL", LONG_TEXT * 5, "c" * 64),
        _doc("VBL", LONG_TEXT * 120, "d" * 64),
    ]


def _quote(doc: SourceDocument) -> str:
    return " ".join(doc.text.split())[40:180]


# --- concurrency is a speed change, not a behaviour change -------------------------------------


def _reply_for(documents: list[SourceDocument]):
    """A generator that answers with a real quote from whichever document it was shown."""
    quotes = {" ".join(d.text.split())[:300]: _quote(d) for d in documents}

    def generate(model: str, prompt: str) -> tuple[str, dict[str, int]]:
        for head, quote in quotes.items():
            if head[:120] in " ".join(prompt.split()):
                return (
                    "EVENT: ticker=VBL; type=acquisition; date=2026-08-25; materiality=high; "
                    f'passage="{quote}"; summary=a real quote; uncertainty=-',
                    {"input": 100, "output": 20},
                )
        return "", {"input": 100, "output": 1}

    return generate


def test_eight_workers_and_one_worker_produce_identical_output() -> None:
    """The property that makes ``workers`` safe to turn up at all.

    If this ever fails, the backfill is not a faster version of the nightly read — it is a different
    reading wearing the same version label, which is exactly what EX-3 exists to prevent.
    """
    docs = _corpus()
    serial = extract(docs, generate=_reply_for(docs), model=corpus_reader(), workers=1)
    parallel = extract(docs, generate=_reply_for(docs), model=corpus_reader(), workers=8)

    assert [e.render() for e in serial[0]] == [e.render() for e in parallel[0]]
    assert serial[1] == parallel[1]  # discarded
    assert serial[2] == parallel[2]  # the raw transcript, in batch order
    assert serial[3] == parallel[3]  # every token and batch counter
    assert serial[3]["calls"] > 1, "the fixture must actually produce several batches"


def test_a_truncated_batch_retries_the_same_way_concurrently() -> None:
    """The retry re-queues split work. Its results must still sort back into batch order."""
    docs = _corpus()

    def generate(model: str, prompt: str) -> tuple[str, dict[str, int]]:
        # Always claim the reply was cut off, so every multi-document batch splits.
        return "", {"input": 10, "output": 3000, "truncated": 1}

    serial = extract(docs, generate=generate, model=corpus_reader(), workers=1)
    parallel = extract(docs, generate=generate, model=corpus_reader(), workers=8)
    assert serial[2] == parallel[2]
    assert serial[3] == parallel[3]
    assert serial[3]["retried_batches"] > 0, "the fixture must exercise the retry path"
    assert serial[3]["failed_batches"] > 0, "a reply still cut off is not a reading"


# --- a refusal is not a filing with nothing in it ----------------------------------------------


def test_a_refused_batch_is_counted_as_unread_not_as_clean() -> None:
    """``("", {})`` used to mean "called fine, found nothing". Silence is not a clean bill."""
    docs = _corpus()[:1]

    def refuses(model: str, prompt: str) -> tuple[str, dict[str, int]]:
        return "", {"input": 100, "output": 0, "refused": 1}

    events, discarded, raw, usage = extract(docs, generate=refuses, model=corpus_reader())
    assert events == [] and discarded == 0
    assert usage["refused_batches"] >= 1
    # The caller decides coverage on `failed_batches`, so a refusal has to reach that counter or
    # `extraction_ran` stays True and the name reads as fully read.
    assert usage["failed_batches"] >= usage["refused_batches"]
    assert "REFUSED" in raw
    assert usage["input"] == 100, "tokens spent on a refusal were still spent"


# --- a reading has a reader ----------------------------------------------------------------------


def test_the_reader_gate_is_exact_and_absence_never_passes() -> None:
    assert reader_matches(corpus_reader())
    assert not reader_matches("some-other-model")
    assert not reader_matches(None), (
        "a row written before the field existed is unknown, not a match"
    )
    assert not reader_matches("")


def test_the_corpus_reader_can_be_named_so_a_comparison_run_labels_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QALPHA_CORPUS_READER", "claude-sonnet-5")
    assert corpus_reader() == "claude-sonnet-5"
    assert reader_matches("claude-sonnet-5")
    assert not reader_matches("claude-haiku-4-5"), "the default must not still satisfy the override"


def _coverage_row(tmp_path: Path, **over: object) -> Path:
    row: dict[str, object] = {
        "as_of": "2026-09-11",
        "ticker": "VBL.NS",
        "complete": True,
        "extraction_version": EXTRACTION_VERSION,
        "reader": corpus_reader(),
    }
    row.update(over)
    p = tmp_path / "coverage.jsonl"
    p.write_text(json.dumps(row) + "\n", encoding="utf-8")
    return p


def test_a_complete_row_from_another_reader_does_not_make_a_name_read(tmp_path: Path) -> None:
    """The buy screen's "clear" must mean *this* corpus read it, not that somebody did."""
    from qalpha.live.flags import filings_read

    as_of = date(2026, 9, 11)
    ours = _coverage_row(tmp_path, reader=corpus_reader())
    assert filings_read(["VBL.NS"], as_of=as_of, path=ours) == {"VBL"}

    theirs = _coverage_row(tmp_path, reader="qwen3-8b-32k")
    assert filings_read(["VBL.NS"], as_of=as_of, path=theirs) == set()

    legacy = _coverage_row(tmp_path)
    json_row = json.loads(legacy.read_text(encoding="utf-8"))
    del json_row["reader"]
    legacy.write_text(json.dumps(json_row) + "\n", encoding="utf-8")
    assert filings_read(["VBL.NS"], as_of=as_of, path=legacy) == set(), (
        "a row from before the field existed says nothing about who read it"
    )


def test_an_event_from_another_reader_cannot_flag_a_candidate() -> None:
    """Selection stays deterministic, but a WATCH still has to come from the corpus's own reader."""
    from qalpha.live.evidence import PASS, Assessment, Provenance
    from qalpha.live.extraction import ExtractedEvent
    from qalpha.live.pretrade import AnnouncementCoverage, assess_candidate

    prov = Provenance(
        source_url="https://nsearchives.nseindia.com/x.csv",
        retrieved_at_utc=datetime(2026, 9, 11, tzinfo=UTC),
        http_status=200,
        sha256="f" * 64,
        byte_length=10,
        document_date=date(2026, 9, 11),
    )

    def event(model: str) -> ExtractedEvent:
        return ExtractedEvent(
            ticker="VBL",
            event_type="regulatory_action",
            event_date=date(2026, 9, 10),
            materiality="high",
            passage="a passage long enough to be checked against the document",
            summary="a regulator has written to the company",
            uncertainty="-",
            doc_sha256="b" * 64,
            doc_url="https://nsearchives.nseindia.com/corporate/VBL.pdf",
            disseminated_at=datetime(2026, 9, 10, tzinfo=UTC),
            model=model,
            extraction_version=EXTRACTION_VERSION,
            verified=True,
        )

    exchange = Assessment("VBL", PASS, provenance=prov, detail="clean")
    full = AnnouncementCoverage(index_fetched=True, extraction_ran=True)

    ours = assess_candidate(
        "VBL", exchange=exchange, events=[event(corpus_reader())], coverage=full
    )
    theirs = assess_candidate(
        "VBL", exchange=exchange, events=[event("qwen3-8b-32k")], coverage=full
    )

    assert ours.flagged_events, "the corpus reader's own high event must still flag"
    assert not theirs.flagged_events, (
        "another reader's event is a record, not this corpus's finding"
    )


# --- the backfill is a different job, and says so when it did nothing ---------------------------


def test_the_backfill_lifts_the_caps_the_nightly_run_needs() -> None:
    """If these ever converge, the nightly run got slower or the backfill stopped being one."""
    import evidence

    assert evidence.MAX_EXTRACT_BACKFILL > evidence.MAX_EXTRACT_PER_RUN * 10
    assert evidence.BACKFILL_WORKERS > 1
    assert evidence.BACKFILL_BUDGET_SECONDS > 900


def test_a_backfill_that_covered_nothing_is_not_a_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 2026-09-10 defect, at the one place it can be caught.

    Two runs were recorded ``done`` after 216s and 147s having written no coverage row for any name,
    because "no candidates and no holdings" returns 0. On a book with holdings that sentence means
    the book or the panel could not be read — which is a failure, and has to exit like one.
    """
    import evidence

    from qalpha.config import Config

    monkeypatch.setattr(evidence, "_fetch_reg_ind", lambda as_of: ({}, None))
    monkeypatch.setattr(
        evidence,
        "_screen_basket",
        lambda cfg, as_of: evidence.ScreenBasket(
            [], [], __import__("decimal").Decimal("0"), {}, {}
        ),
    )
    code = evidence.cmd_backfill(Config(), date(2026, 9, 11), workers=2, budget_seconds=60)
    assert code != 0, "covering nothing must not look like covering everything"


def test_the_recorded_reader_is_the_one_that_ran_not_the_one_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The defect this change nearly shipped, caught before it was committed.

    ``_record_coverage`` and ``_mark_extracted`` first stamped ``corpus_reader()`` — the model we
    *intend* the corpus to use. On the user's machine the local 8B does the nightly reading, so
    every local row would have been stamped ``claude-haiku-4-5`` and then matched the gate it exists
    to fail. A label asserting work that a different model did is the exact class of defect
    ``CLAUDE.md`` opens with, written by the mechanism built to prevent it.
    """
    import evidence

    from qalpha.live.pretrade import AnnouncementCoverage

    monkeypatch.setattr(evidence, "COVERAGE_LOG", tmp_path / "coverage.jsonl")
    monkeypatch.setattr(evidence, "EXTRACTED_LOG", tmp_path / "extracted.jsonl")
    covered = AnnouncementCoverage(
        filings_in_window=2, documents_read=2, extraction_ran=True, index_fetched=True
    )

    evidence._record_coverage(date(2026, 9, 11), "VBL.NS", covered, 10, "qwen3-8b-32k")
    evidence._mark_extracted(["abc"], events_recorded=0, reader="qwen3-8b-32k")

    row = json.loads((tmp_path / "coverage.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert row["reader"] == "qwen3-8b-32k", "the row must name what actually read"
    assert row["complete"], "it is a real, complete reading — by a different reader"
    assert not evidence._seen_before("VBL.NS"), "and so it must not satisfy the corpus"
    assert evidence._already_extracted() == set(), "nor count that document as corpus-read"
