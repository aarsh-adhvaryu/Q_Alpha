"""A cached filing must return the same warning it returned the first time.

**Reproduced in review 2026-09-09 and again on 09-10.** The same archived auditor-resignation
document produced:

    first run   coverage complete · 1 verified concern · WATCH
    cached run  coverage complete · 0 findings         · PASS

The event was on disk the whole time. A cached document counted toward coverage and returned nothing
to the assessment, so a real warning became a clean bill on the second day — silently, and on the
surface whose entire job is to say what the filings found.

Re-reading the document would cost the tokens the cache exists to save. Reading its **findings**
costs a file scan, and that is the fix.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(ROOT_SCRIPTS))

import evidence  # noqa: E402

from qalpha.live.extraction import EXTRACTION_VERSION  # noqa: E402

SHA = "a" * 64


def _row(**kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "kind": "event",
        "ticker": "VBL",
        "event_type": "auditor_resignation",
        "event_date": "2026-09-01",
        "materiality": "high",
        "passage": "the statutory auditor has resigned with immediate effect",
        "summary": "auditor resigned",
        "uncertainty": "low",
        "doc_sha256": SHA,
        "doc_url": "https://example/doc.pdf",
        "disseminated_at": datetime(2026, 9, 1, tzinfo=UTC).isoformat(),
        "model": "claude-haiku-4-5",
        "extraction_version": EXTRACTION_VERSION,
        "verified": True,
    }
    base.update(kw)
    return base


def _log(tmp_path: Path, *rows: dict[str, object]) -> Path:
    p = tmp_path / "events.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return p


def test_a_cached_document_still_returns_its_concern(tmp_path: Path) -> None:
    """The defect itself. WATCH on Monday must be WATCH on Tuesday."""
    log = _log(tmp_path, _row())
    recalled = evidence._recall_events({SHA}, log)
    assert len(recalled) == 1
    assert recalled[0].materiality == "high"
    assert recalled[0].event_type == "auditor_resignation"
    assert recalled[0].verified


def test_a_document_with_no_findings_recalls_nothing_and_that_is_correct(tmp_path: Path) -> None:
    """A quiet filing is quiet. Recalling nothing for it is the right answer, not a failure — the
    defect was recalling nothing for a filing that HAD a finding."""
    assert evidence._recall_events({"b" * 64}, _log(tmp_path, _row())) == []
    assert evidence._recall_events(set(), _log(tmp_path, _row())) == []


def test_an_unverified_quote_is_never_recalled(tmp_path: Path) -> None:
    """An unverified passage is a fabrication and must not reach policy — the same rule the live
    path applies, applied to the cache. Recall must not be a way around a safeguard."""
    assert evidence._recall_events({SHA}, _log(tmp_path, _row(verified=False))) == []


def test_a_superseded_extractors_findings_are_never_recalled(tmp_path: Path) -> None:
    """EX-1 rated routine results `high` — 77 of 193 — so recalling its findings under EX-2 would
    reintroduce the exact judgements the version bump exists to discard."""
    assert evidence._recall_events({SHA}, _log(tmp_path, _row(extraction_version="EX-1"))) == []


def test_a_corrupt_row_costs_one_finding_not_the_file(tmp_path: Path) -> None:
    p = tmp_path / "events.jsonl"
    p.write_text(
        json.dumps(_row(doc_sha256="c" * 64)) + "\n{ half writ\n" + json.dumps(_row()) + "\n",
        encoding="utf-8",
    )
    assert len(evidence._recall_events({SHA}, p)) == 1


def test_an_absent_log_recalls_nothing_rather_than_raising(tmp_path: Path) -> None:
    assert evidence._recall_events({SHA}, tmp_path / "never-written.jsonl") == []


def test_the_caller_returns_recalled_findings_alongside_fresh_ones() -> None:
    """The ordering that matters at the call site: a name whose documents are ALL cached must still
    hand its concerns to the assessment, or coverage reads complete with nothing behind it."""
    import inspect

    src = inspect.getsource(evidence._cover_name)
    recall_at = src.index("_recall_events(")
    return_at = src.rindex("return coverage,")
    assert recall_at < return_at
    assert "*recalled" in src[return_at:], "recalled findings must reach the caller"


@pytest.mark.parametrize("field", ["ticker", "doc_sha256"])
def test_a_row_missing_a_required_field_is_skipped_and_the_good_one_survives(
    tmp_path: Path, field: str
) -> None:
    """One malformed row must cost one finding, never the warning sitting next to it."""
    broken = _row()
    del broken[field]
    recalled = evidence._recall_events({SHA}, _log(tmp_path, broken, _row()))
    assert len(recalled) == 1, "the intact row must still come back"
    assert recalled[0].materiality == "high"
