"""Integration repair, 2026-09-05 — the defects a second reviewer found after #94 merged.

The critical one is the shape this codebase keeps producing and this time I produced it: I fixed
``next(g for g in gaps if g.gates)`` in ``scripts/twin.py`` and left the identical line in
``src/qalpha/live/twin.py``. CLAUDE.md's rule 1 says, in as many words, *when you fix a defect grep
for every other caller of the thing you fixed.* Twice before it had been broken. Now three times.

Once ``CORE_V1`` existed the history writer would have taken the **core** comparison — first in the
pairs list — and written its numbers under the label ``["TWIN_FULL", "BASELINE_EW"]`` beside run 2's
verdict, into the append-only record, starting with the first post-merge cron.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from qalpha.backtest.portfolio import Portfolio
from qalpha.config import Config
from qalpha.live.evidence import (
    STALENESS_TOLERANCE_DAYS,
    UNKNOWN,
    Provenance,
    assess,
    parse_reg_ind,
)
from qalpha.live.twin import (
    BASELINE_EW,
    CORE_V1,
    TWIN_FULL,
    BookMark,
    TwinBook,
    append_history,
    compare,
    load_books,
    load_history,
    save_books,
)

AS_OF = date(2026, 10, 1)


def _mark(name: str, value: str) -> BookMark:
    return BookMark(
        name=name,
        as_of=AS_OF,
        start=date(2026, 9, 8),
        net_invested=Decimal("300000"),
        value=Decimal(value),
        rate=None,
    )


def _marks() -> dict[str, BookMark]:
    return {
        TWIN_FULL: _mark(TWIN_FULL, "296000"),
        CORE_V1: _mark(CORE_V1, "310000"),
        BASELINE_EW: _mark(BASELINE_EW, "300000"),
    }


# --- the critical defect ------------------------------------------------------------------------


def test_each_track_is_recorded_under_its_own_pair(tmp_path: Path) -> None:
    marks = _marks()
    gaps = compare(marks)
    append_history(marks, gaps, as_of=AS_OF, gate_verdict="NOT YET", path=tmp_path / "h.jsonl")
    row = json.loads((tmp_path / "h.jsonl").read_text().splitlines()[0])
    tracks = row["tracks"]
    assert tracks["run2"]["pair"] == [TWIN_FULL, BASELINE_EW]
    assert tracks["core_v1"]["pair"] == [CORE_V1, BASELINE_EW]
    # and the numbers are each track's own, not one pair's numbers under the other's label
    assert tracks["run2"]["rupees"] != tracks["core_v1"]["rupees"]


def test_the_gate_row_names_the_pair_it_was_actually_computed_from(tmp_path: Path) -> None:
    """It used to write the module constant GATING_PAIR regardless of which gap it had read."""
    marks = _marks()
    append_history(
        marks, compare(marks), as_of=AS_OF, gate_verdict="NOT YET", path=tmp_path / "h.jsonl"
    )
    gate = json.loads((tmp_path / "h.jsonl").read_text().splitlines()[0])["gate"]
    assert gate["pair"] == [CORE_V1, BASELINE_EW]
    assert gate["authorizes"] is True


def test_the_gate_numbers_match_the_authorising_track_exactly(tmp_path: Path) -> None:
    marks = _marks()
    append_history(
        marks, compare(marks), as_of=AS_OF, gate_verdict="NOT YET", path=tmp_path / "h.jsonl"
    )
    row = json.loads((tmp_path / "h.jsonl").read_text().splitlines()[0])
    core = row["tracks"]["core_v1"]
    assert (row["gate"]["rupees"], row["gate"]["months"]) == (core["rupees"], core["months"])


def test_a_rehearsal_never_authorises() -> None:
    """An experiment declared methodologically invalid must never later produce a GO."""
    gaps = compare(_marks())
    run2 = next(g for g in gaps if g.track == "run2" and g.gates)
    core = next(g for g in gaps if g.track == "core_v1" and g.gates)
    assert run2.gates and not run2.authorizes
    assert core.gates and core.authorizes
    assert len([g for g in gaps if g.authorizes]) == 1


def test_without_the_core_book_nothing_authorises(tmp_path: Path) -> None:
    """Before CORE_V1 exists the gate has no gap and says so, rather than borrowing run 2's."""
    marks = {k: v for k, v in _marks().items() if k != CORE_V1}
    append_history(
        marks, compare(marks), as_of=AS_OF, gate_verdict="NOT YET", path=tmp_path / "h.jsonl"
    )
    gate = json.loads((tmp_path / "h.jsonl").read_text().splitlines()[0])["gate"]
    assert gate["pair"] is None and gate["rupees"] is None and gate["authorizes"] is False


def test_history_still_loads_after_the_row_shape_changed(tmp_path: Path) -> None:
    marks = _marks()
    append_history(
        marks, compare(marks), as_of=AS_OF, gate_verdict="NOT YET", path=tmp_path / "h.jsonl"
    )
    rows = load_history(tmp_path / "h.jsonl")
    assert len(rows) == 1 and "tracks" in rows[0]


# --- same-day idempotence -------------------------------------------------------------------------


def test_stepped_through_survives_a_save_and_reload(tmp_path: Path) -> None:
    """The guard is only worth having if it is on the file the retry reads back."""
    cfg = Config()
    from qalpha.live.track_record import Flow

    flows = [Flow(on=date(2026, 9, 1), amount=Decimal("100000"))]
    books = {
        n: TwinBook(
            name=n,
            portfolio=Portfolio(cfg.cost, cfg.tax, cash=Decimal("100000")),
            flows=list(flows),
            stepped_through=date(2026, 9, 5) if n == CORE_V1 else None,
        )
        for n in (CORE_V1, TWIN_FULL)
    }
    path = tmp_path / "books.json"
    save_books(books, path)
    back = load_books(cfg, path)
    assert back[CORE_V1].stepped_through == date(2026, 9, 5)
    assert back[TWIN_FULL].stepped_through is None


def test_a_book_with_no_marker_is_treated_as_unstepped(tmp_path: Path) -> None:
    """Existing books.json files predate the field; absent must mean "not yet", never "already"."""
    cfg = Config()
    from qalpha.live.track_record import Flow

    books = {
        CORE_V1: TwinBook(
            name=CORE_V1,
            portfolio=Portfolio(cfg.cost, cfg.tax, cash=Decimal("1")),
            flows=[Flow(on=date(2026, 9, 1), amount=Decimal("1"))],
        )
    }
    path = tmp_path / "b.json"
    save_books(books, path)
    raw = json.loads(path.read_text())
    del raw["books"][CORE_V1]["stepped_through"]
    path.write_text(json.dumps(raw))
    assert load_books(cfg, path)[CORE_V1].stepped_through is None


# --- future data ------------------------------------------------------------------------------------


def _prov(document_date: date) -> Provenance:
    return Provenance(
        source_url="u",
        retrieved_at_utc=datetime(2026, 9, 5, tzinfo=UTC),
        http_status=200,
        sha256="a" * 64,
        byte_length=1,
        document_date=document_date,
    )


_ROWS = parse_reg_ind("ScripCode,Symbol,Nse Exclusive,Status,Series,GSM\nNA,VBL,N,A,EQ,100\n")


def test_a_file_dated_after_the_decision_is_refused_as_future_data() -> None:
    a = assess("VBL", _ROWS, _prov(date(2026, 9, 10)), as_of=date(2026, 9, 5))
    assert a.state == UNKNOWN and "future data" in a.detail


def test_same_day_is_not_future() -> None:
    assert assess("VBL", _ROWS, _prov(date(2026, 9, 5)), as_of=date(2026, 9, 5)).state != UNKNOWN


@pytest.mark.parametrize("age", [1, STALENESS_TOLERANCE_DAYS])
def test_a_file_inside_tolerance_still_decides(age: int) -> None:
    as_of = date(2026, 9, 5)
    prov = _prov(date.fromordinal(as_of.toordinal() - age))
    assert assess("VBL", _ROWS, prov, as_of=as_of).state != UNKNOWN


# --- truncation is not a read -------------------------------------------------------------------------


def test_a_truncated_filing_is_not_covered() -> None:
    from qalpha.live.evidence import PASS, Assessment
    from qalpha.live.pretrade import AnnouncementCoverage, assess_candidate

    partial = AnnouncementCoverage(
        filings_in_window=1,
        documents_read=1,
        documents_truncated=1,
        extraction_ran=True,
        index_fetched=True,
    )
    a = assess_candidate(
        "X", exchange=Assessment("X", PASS, (), _prov(date(2026, 9, 5)), "clear"), coverage=partial
    )
    assert a.state == UNKNOWN
    assert "exceeded the prompt budget" in a.render()
