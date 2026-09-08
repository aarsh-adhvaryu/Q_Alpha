"""The extraction receipt must never outlive the evidence it attests to.

**Found on 2026-09-08, in the first scheduled run that carried EX-2.** ``extracted.jsonl`` held 199
rows at EX-2 while ``events.jsonl`` held 193 events, **every one of them EX-1** — 199 documents
recorded as read whose findings existed nowhere.

The cause was write ordering. ``_mark_extracted`` was durable per name, inside the loop; the events
were accumulated in memory and written **once, after the whole loop**. Anything that stopped the run
in between — the workflow's 20-minute cap on this step, a crash, a Ctrl-C during local testing —
left every document already read marked "done at EX-2" with its findings nowhere. The next run then
saw a cache hit, skipped the document, and set ``extraction_ran = True`` on the *assumption*, stated
in a comment, that "its findings are on file in events.jsonl". Nothing checked. A poisoned cache
produced ``complete: true`` with no events at all: unread reading as clean, which is the fifteenth
row of the table in CLAUDE.md.

These tests pin the ordering, not the implementation: **a receipt is written after the thing it is a
receipt for, and a receipt that cannot prove its events landed does not count.**
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, "scripts")

import evidence


def _log(tmp_path: Path, *rows: dict[str, object]) -> Path:
    p = tmp_path / "extracted.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return p


def test_a_receipt_without_proof_its_events_landed_does_not_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """This is the exact shape of the 199 orphaned rows, reproduced.

    They are indistinguishable from a good receipt by version and hash alone — which is why the old
    rule accepted them and skipped those documents forever.
    """
    orphan = {"sha256": "abc", "extraction_version": evidence.EXTRACTION_VERSION, "_key": "k"}
    monkeypatch.setattr(evidence, "EXTRACTED_LOG", _log(tmp_path, orphan))
    assert evidence._already_extracted() == set(), (
        "a row with no events_recorded attests to nothing and must be re-read"
    )


def test_a_receipt_that_proves_its_events_landed_does_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = {
        "sha256": "abc",
        "extraction_version": evidence.EXTRACTION_VERSION,
        "events_recorded": 3,
        "_key": "k",
    }
    monkeypatch.setattr(evidence, "EXTRACTED_LOG", _log(tmp_path, good))
    assert evidence._already_extracted() == {"abc"}


def test_zero_events_is_a_real_answer_and_still_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A filing that genuinely says nothing a shareholder need worry about is a no-event receipt.

    That is a different thing from a document nobody read, and conflating them would re-read every
    quiet filing forever — the cost the cache exists to avoid.
    """
    monkeypatch.setattr(evidence, "EXTRACTED_LOG", tmp_path / "extracted.jsonl")
    evidence._mark_extracted(["quiet"], events_recorded=0)
    assert evidence._already_extracted() == {"quiet"}


def test_a_receipt_from_a_superseded_extractor_still_does_not_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EX-1 rated routine results `high`, so its findings are not the findings EX-2 would produce."""
    stale = {"sha256": "abc", "extraction_version": "EX-1", "events_recorded": 3, "_key": "k"}
    monkeypatch.setattr(evidence, "EXTRACTED_LOG", _log(tmp_path, stale))
    assert evidence._already_extracted() == set()


def test_the_receipt_records_the_count_it_was_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "extracted.jsonl"
    monkeypatch.setattr(evidence, "EXTRACTED_LOG", path)
    evidence._mark_extracted(["a", "b"], events_recorded=2)
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert {r["sha256"] for r in rows} == {"a", "b"}
    assert all(r["events_recorded"] == 2 for r in rows)
    assert all(r["extraction_version"] == evidence.EXTRACTION_VERSION for r in rows)


def test_a_failed_event_write_reports_failure_so_no_receipt_is_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The half that turns an interruption into lost evidence. If the events cannot be persisted,
    ``_persist_events`` must say so, and the caller must then write no receipt at all."""
    from datetime import date

    def _boom(*_a: object, **_k: object) -> int:
        raise OSError("disk full")

    monkeypatch.setattr(evidence, "_append_jsonl", _boom)
    fake_event = object()
    monkeypatch.setattr(evidence, "event_rows", lambda *_a, **_k: [{"_key": "x"}])
    assert evidence._persist_events([fake_event], date(2026, 9, 8)) is False  # type: ignore[list-item]


def test_nothing_to_write_is_not_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty list must return True — the caller still owes a no-event receipt for the documents
    it read, and returning False would suppress it and re-read them tomorrow."""
    from datetime import date

    assert evidence._persist_events([], date(2026, 9, 8)) is True


def test_events_are_persisted_before_the_receipt_is_written() -> None:
    """The ordering itself, asserted at the call site.

    A property test cannot see ordering inside a function that talks to disk, so this reads the
    source of the one place it matters. It is deliberately narrow: it asserts that the receipt call
    is guarded by the event-persist call, not how either is written.
    """
    import inspect

    src = inspect.getsource(evidence._cover_name)
    persist_at = src.index("_persist_events")
    mark_at = src.index("_mark_extracted")
    assert persist_at < mark_at, "the receipt must be written after the evidence, never before"
    assert "extraction_ran = False" in src[mark_at:], (
        "a failed persist must mark the name NOT covered, or it reads as complete with no events"
    )
