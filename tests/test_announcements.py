"""The announcement spine: fetch the exchange's index, keep the actual filing, verify it on read."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from qalpha.live.announcements import (
    Announcement,
    document_paths,
    documents_for,
    extract_text,
    fetch_document,
    fetch_index,
    index_url,
    load_document,
    parse_index,
    since,
    write_document,
)

ARCHIVED = Path("data/evidence/announcements/VBL")


def _row(**over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "symbol": "VBL",
        "seq_id": "106755757",
        "desc": "General Updates",
        "attchmntText": "Vardhman informed the Exchange",
        "an_dt": "25-Aug-2026 16:21:24",
        "attchmntFile": "https://nsearchives.nseindia.com/corporate/VBL_x.pdf",
        "sm_isin": "INE200M01013",
    }
    row.update(over)
    return row


def _ann(**over: object) -> Announcement:
    base: dict[str, object] = {
        "symbol": "VBL",
        "seq_id": "test-1",
        "subject": "General Updates",
        "summary": "",
        "disseminated_at": datetime(2026, 8, 25, 16, 21, tzinfo=UTC),
        "attachment_url": "https://nsearchives.nseindia.com/corporate/VBL_x.pdf",
    }
    base.update(over)
    return Announcement(**base)  # type: ignore[arg-type]


# --- parsing --------------------------------------------------------------------------------


def test_index_url_uses_the_bare_symbol() -> None:
    assert index_url("VBL.NS").endswith("symbol=VBL")


def test_parse_index_reads_a_row() -> None:
    (a,) = parse_index(json.dumps([_row()]))
    assert a.symbol == "VBL" and a.seq_id == "106755757"
    assert a.disseminated_at.date() == date(2026, 8, 25)
    assert a.has_document


def test_an_undated_row_is_dropped_not_dated_by_us() -> None:
    """A filing with no timestamp cannot be ordered against a price. Today's date would flatter it."""
    assert parse_index(json.dumps([_row(an_dt="", exchdisstime="")])) == []


def test_rows_come_back_newest_first() -> None:
    rows = [
        _row(an_dt="01-Aug-2026 10:00:00", seq_id="old"),
        _row(an_dt="25-Aug-2026 16:21:24", seq_id="new"),
    ]
    assert [a.seq_id for a in parse_index(json.dumps(rows))] == ["new", "old"]


def test_a_non_pdf_attachment_is_not_a_document() -> None:
    assert not _ann(attachment_url="https://example.com/notice.html").has_document


def test_since_filters_and_limits() -> None:
    anns = parse_index(
        json.dumps(
            [
                _row(an_dt="01-Jul-2026 10:00:00", seq_id="a"),
                _row(an_dt="20-Aug-2026 10:00:00", seq_id="b"),
                _row(an_dt="25-Aug-2026 10:00:00", seq_id="c"),
            ]
        )
    )
    assert [a.seq_id for a in since(anns, date(2026, 8, 1))] == ["c", "b"]
    assert [a.seq_id for a in since(anns, date(2026, 8, 1), limit=1)] == ["c"]


def test_garbage_payloads_yield_nothing_rather_than_raising() -> None:
    assert parse_index("not json") == [] and parse_index(json.dumps({"a": 1})) == []


# --- archival -------------------------------------------------------------------------------


def test_document_round_trips_with_provenance(tmp_path: Path) -> None:
    ann = _ann()
    prov = write_document(b"%PDF-1.7 fake", ann, http_status=200, directory=tmp_path)
    assert prov.document_date == date(2026, 8, 25) and prov.byte_length == 13
    pdf, meta = document_paths(ann, directory=tmp_path)
    assert pdf.exists() and json.loads(meta.read_text())["symbol"] == "VBL"


def test_a_tampered_document_reads_as_absent(tmp_path: Path) -> None:
    """A silently edited primary source is worse than a missing one: it still looks like evidence."""
    ann = _ann()
    write_document(b"%PDF-1.7 original", ann, http_status=200, directory=tmp_path)
    document_paths(ann, directory=tmp_path)[0].write_bytes(b"%PDF-1.7 swapped!")
    assert load_document(ann, directory=tmp_path) == ("", None)


def test_an_archived_document_is_never_refetched(tmp_path: Path) -> None:
    """Re-downloading could swap a revised filing under bytes we already reasoned about."""
    ann = _ann()
    write_document(_tiny_pdf(), ann, http_status=200, directory=tmp_path)
    calls: list[str] = []

    def _fetch(url: str) -> tuple[int, bytes]:
        calls.append(url)
        return 200, b"different"

    fetch_document(ann, fetch=_fetch, directory=tmp_path)
    assert calls == []


def test_a_failed_download_stores_nothing(tmp_path: Path) -> None:
    assert fetch_document(_ann(), fetch=lambda _u: (403, b""), directory=tmp_path) is None
    assert not document_paths(_ann(), directory=tmp_path)[0].exists()


def test_a_failed_index_fetch_is_none_not_empty() -> None:
    """``None`` = we could not check. ``[]`` = the exchange returned nothing. Different facts."""
    assert fetch_index("VBL", fetch=lambda _u: (403, b"")) is None
    assert fetch_index("VBL", fetch=lambda _u: (0, b"")) is None


def test_a_successful_empty_index_is_an_empty_list() -> None:
    assert fetch_index("VBL", fetch=lambda _u: (200, b"[]")) == []


def _tiny_pdf() -> bytes:
    return (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
    )


def test_unreadable_bytes_extract_to_empty_never_a_guess() -> None:
    assert extract_text(b"this is not a pdf at all") == ""


# --- the real archived filings ----------------------------------------------------------------


def test_the_committed_vbl_filings_read_back_and_verify() -> None:
    """End to end on documents this repo actually holds, with no network."""
    if not ARCHIVED.exists():  # pragma: no cover - archive ships with the repo
        return
    anns = []
    for meta_path in sorted(ARCHIVED.glob("*.provenance.json")):
        meta = json.loads(meta_path.read_text())
        anns.append(
            _ann(
                seq_id=meta["seq_id"],
                subject=meta["subject"],
                attachment_url=meta["source_url"],
                disseminated_at=datetime.fromisoformat(meta["document_date"]).replace(tzinfo=UTC),
            )
        )
    docs = documents_for(anns)
    assert len(docs) == len(anns), "every archived filing must hash-verify and extract"
    assert all(len(d.text) > 200 for d in docs)
    assert all(
        d.provenance.source_url.startswith("https://nsearchives.nseindia.com/") for d in docs
    )
