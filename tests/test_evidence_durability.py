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

ROOT_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(ROOT_SCRIPTS))

import evidence  # noqa: E402


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
        "reader": evidence.corpus_reader(),
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
    evidence._mark_extracted(["quiet"], events_recorded=0, reader=evidence.corpus_reader())
    assert evidence._already_extracted() == {"quiet"}


def test_a_receipt_from_a_superseded_extractor_still_does_not_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EX-1 rated routine results `high`, so its findings are not the findings EX-2 would produce."""
    # The right reader on purpose, so the VERSION is the only thing that can reject this row.
    stale = {
        "sha256": "abc",
        "extraction_version": "EX-1",
        "reader": evidence.corpus_reader(),
        "events_recorded": 3,
        "_key": "k",
    }
    monkeypatch.setattr(evidence, "EXTRACTED_LOG", _log(tmp_path, stale))
    assert evidence._already_extracted() == set()


def test_the_receipt_records_the_count_it_was_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "extracted.jsonl"
    monkeypatch.setattr(evidence, "EXTRACTED_LOG", path)
    evidence._mark_extracted(["a", "b"], events_recorded=2, reader=evidence.corpus_reader())
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


# --- the same disease, one file over ------------------------------------------------------------
def test_a_coverage_row_is_written_the_moment_its_name_is_finished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Found on 2026-09-08, in the run that verified the fix above.

    The evidence step was killed at its 20-minute cap having produced **110 events and zero coverage
    rows** — because coverage was still one bulk write after the whole loop. Every name kept reading
    "Filings NOT read" on the buy screen while its findings sat in ``events.jsonl``.
    """
    from datetime import date

    from qalpha.live.pretrade import AnnouncementCoverage

    path = tmp_path / "coverage.jsonl"
    monkeypatch.setattr(evidence, "COVERAGE_LOG", path)
    cov = AnnouncementCoverage(
        filings_in_window=2, documents_read=2, extraction_ran=True, index_fetched=True
    )
    evidence._record_coverage(date(2026, 9, 9), "VBL.NS", cov, 10, evidence.corpus_reader())

    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(rows) == 1
    assert rows[0]["ticker"] == "VBL.NS"
    assert rows[0]["complete"] is True
    assert rows[0]["window_days"] == 10
    assert rows[0]["extraction_version"] == evidence.EXTRACTION_VERSION


def test_a_later_run_supersedes_a_coverage_row_without_erasing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A correction never deletes what it corrects. An incomplete row from a killed run must stay on
    file — ``_seen_before`` reads it to decide whether a name has already spent its 365-day
    bootstrap, and an erased failure would silently send that name down the ten-day path."""
    from datetime import date

    from qalpha.live.pretrade import AnnouncementCoverage

    path = tmp_path / "coverage.jsonl"
    monkeypatch.setattr(evidence, "COVERAGE_LOG", path)
    partial = AnnouncementCoverage(
        filings_in_window=5, documents_read=1, extraction_ran=False, index_fetched=True
    )
    whole = AnnouncementCoverage(
        filings_in_window=5, documents_read=5, extraction_ran=True, index_fetched=True
    )
    evidence._record_coverage(date(2026, 9, 9), "VBL.NS", partial, 365, evidence.corpus_reader())
    evidence._record_coverage(date(2026, 9, 9), "VBL.NS", whole, 365, evidence.corpus_reader())

    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(rows) == 2, "the failed attempt must survive its own correction"
    assert [r["revision"] for r in rows] == [0, 1]
    assert [r["complete"] for r in rows] == [False, True]


def test_coverage_is_recorded_inside_the_loop_not_after_it() -> None:
    """The ordering, at the one call site where it decides whether a killed run leaves anything."""
    import inspect

    src = inspect.getsource(evidence.cmd_daily)
    loop = src.index("for covered, ticker in enumerate(tickers)")
    assert "_record_coverage(" in src[loop:], "coverage must be written inside the loop"
    after_loop = src.index("all_events = [", loop)
    assert "_record_coverage(" in src[loop:after_loop], (
        "the coverage write must happen per name, before the loop can be interrupted"
    )
    assert "COVERAGE_LOG," not in src, "no bulk coverage write may survive in cmd_daily()"


def test_nothing_can_kill_the_evidence_step_from_outside_any_more() -> None:
    """The budget's reason for existing changed when the cron was retired; the budget did not.

    It used to have to be strictly inside GitHub's ``timeout-minutes``, because the runner SIGKILLed
    the step at the boundary and ``continue-on-error`` reported the corpse as success — a 20m12s run
    on 2026-09-08 went green having written no coverage at all. There is no runner now: the step
    stops itself, on this machine, and a stop is clean where a kill was not.

    What still has to be true is that the stop is **the step's own choice** and that nothing
    external imposes a deadline it cannot see. So: the budget exists, it is finite, and no workflow
    file has come back to cap it.
    """
    import re

    src = (ROOT_SCRIPTS / "evidence.py").read_text(encoding="utf-8")
    budget_s = int(re.search(r'EVIDENCE_BUDGET_SECONDS", "(\d+)"', src).group(1))
    assert 0 < budget_s <= 3600, "the step must stop itself, and within an evening"
    assert "Stopping cleanly" in src, "the stop must say what it did and did not reach"

    workflows = ROOT_SCRIPTS.parent / ".github/workflows"
    scheduled = [
        f.name for f in workflows.glob("*.yml") if "schedule:" in f.read_text(encoding="utf-8")
    ]
    assert scheduled == [], (
        f"{scheduled} is scheduled again. The record is produced on the desktop now; a cron that "
        "quietly resumes writing to the same ledgers would put two systems on one set of books."
    )


def test_a_first_sighting_is_deferred_out_of_the_evening() -> None:
    """A 365-day read is a backfill, and a backfill is not an evening job.

    Three of the user's own holdings were never in the corpus, so every double-click sat on a
    year of filings per name, one API call at a time, before the login button was usable.
    """
    import inspect

    import evidence

    src = inspect.getsource(evidence.cmd_daily)
    assert "deferred.append(ticker)" in src, "first sightings are read inline again"
    assert "bootstrap" in inspect.signature(evidence.cmd_daily).parameters


def test_a_deferred_name_writes_no_coverage_row() -> None:
    """The safety property. No row means `_seen_before` stays false and the screen says UNKNOWN.

    Covering it on the 10-day window instead would be the exact defect `BOOTSTRAP_DAYS` exists to
    prevent: an auditor resignation from day eleven is invisible, and the name reads CLEAN because
    nobody looked. Deferred must mean unread, never read-badly.
    """
    import inspect

    import evidence

    src = inspect.getsource(evidence.cmd_daily)
    deferral = src[src.index("deferred.append(ticker)") :]
    body = deferral[: deferral.index("windows[ticker]")]
    assert "continue" in body, "a deferred name must not fall through into _cover_name"
    assert "coverage[ticker]" not in body, "a deferred name must not be recorded as covered"


def test_the_suggested_backfill_command_is_one_the_parser_accepts() -> None:
    """A suggested command that errors is worse than no suggestion.

    The first version of this message printed `--names A B C`. The real flag is `--only A,B,C`.
    """
    import inspect

    import evidence

    src = inspect.getsource(evidence.cmd_daily)
    assert "backfill --only" in src
    assert "--names" not in src
