"""The buy-screen evidence panel. Flags, never vetoes.

It exists so a warning is in front of the user at the moment he places an order, instead of in a
report nobody opens. What it must never do is change the basket — the iron rule on the buy list is
*flag, don't veto*, and the screen is the thing being measured.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from qalpha.live.evidence import load_archive
from qalpha.live.extraction import EXTRACTION_VERSION
from qalpha.live.flags import MAX_FILE_AGE_DAYS, flags_markdown, recent_concerns

AS_OF = date(2026, 8, 27)


def _event(**over: object) -> str:
    row: dict[str, object] = {
        "kind": "event",
        "as_of": "2026-08-20",
        "ticker": "VBL",
        "event_type": "regulatory_action",
        "materiality": "high",
        "summary": "a regulator has written to the company",
        "passage": "a passage long enough to have been checked",
        "doc_url": "https://nsearchives.nseindia.com/corporate/VBL.pdf",
        "verified": True,
        "extraction_version": EXTRACTION_VERSION,
    }
    row.update(over)
    return json.dumps(row)


def _log(tmp_path: Path, *rows: str) -> Path:
    p = tmp_path / "events.jsonl"
    p.write_text("\n".join(rows) + "\n")
    return p


# --- which events may be shown -------------------------------------------------------------------


def test_a_high_concern_verified_event_is_shown(tmp_path: Path) -> None:
    out = recent_concerns(["VBL.NS"], since=date(2026, 8, 1), path=_log(tmp_path, _event()))
    assert len(out["VBL"]) == 1 and out["VBL"][0]["type"] == "regulatory_action"


def test_an_unverified_event_is_never_shown(tmp_path: Path) -> None:
    """A quote that was not in the document evidences nothing, however alarming it reads."""
    log = _log(tmp_path, _event(verified=False))
    assert recent_concerns(["VBL.NS"], since=date(2026, 8, 1), path=log) == {}


def test_an_old_extraction_version_is_never_shown(tmp_path: Path) -> None:
    """EX-1 rated routine results `high` because the prompt never said material to whom.

    Those rows stay on file as a record of what was believed. They must not act.
    """
    log = _log(tmp_path, _event(extraction_version="EX-1"))
    assert recent_concerns(["VBL.NS"], since=date(2026, 8, 1), path=log) == {}


def test_medium_and_low_concern_are_not_shown(tmp_path: Path) -> None:
    log = _log(tmp_path, _event(materiality="medium"), _event(materiality="low"))
    assert recent_concerns(["VBL.NS"], since=date(2026, 8, 1), path=log) == {}


def test_an_event_older_than_the_window_is_not_shown(tmp_path: Path) -> None:
    log = _log(tmp_path, _event(as_of="2026-01-01"))
    assert recent_concerns(["VBL.NS"], since=date(2026, 8, 1), path=log) == {}


def test_a_name_not_in_the_basket_is_not_shown(tmp_path: Path) -> None:
    assert recent_concerns(["TCS.NS"], since=date(2026, 8, 1), path=_log(tmp_path, _event())) == {}


def test_a_missing_log_is_empty_not_an_error(tmp_path: Path) -> None:
    assert recent_concerns(["VBL.NS"], since=date(2026, 8, 1), path=tmp_path / "none.jsonl") == {}


# --- the panel, against the real archived exchange file ---------------------------------------------


def test_the_panel_flags_a_cautioned_name_and_blocks_nothing() -> None:
    if load_archive(AS_OF)[1] is None:  # pragma: no cover - the archive ships with the repo
        return
    panel = flags_markdown(["JIOFIN.NS", "VBL.NS", "BLISSGVS"], as_of=AS_OF)
    assert "JIOFIN" in panel and "Scrip PE is greater than 50" in panel
    assert "BLISSGVS" in panel
    assert "VBL" in panel  # listed as clear
    assert "flags, not vetoes" in panel
    assert "the decision is yours" in panel


def test_the_panel_says_how_old_the_exchange_file_is() -> None:
    """A stale file must announce itself. An absent warning and no warning are different facts."""
    if load_archive(AS_OF)[1] is None:  # pragma: no cover
        return
    fresh = flags_markdown(["VBL.NS"], as_of=AS_OF)
    stale = flags_markdown(["VBL.NS"], as_of=date(2026, 8, 29))
    assert "today's NSE file" in fresh
    assert "2-day-old" in stale


def test_no_archive_within_tolerance_reads_as_a_gap_not_a_clean_bill() -> None:
    panel = flags_markdown(["VBL.NS"], as_of=date(2030, 1, 1))
    assert "been checked" in panel and "not a clean bill" in panel
    assert f"{MAX_FILE_AGE_DAYS} days" in panel


def test_an_empty_basket_renders_nothing() -> None:
    assert flags_markdown([], as_of=AS_OF) == ""


# --- "clear" must mean the filings were read ------------------------------------------------------


def _coverage(tmp_path: Path, **over: object) -> Path:
    row: dict[str, object] = {
        "as_of": "2026-08-27",
        "ticker": "VBL.NS",
        "complete": True,
        "extraction_version": EXTRACTION_VERSION,
    }
    row.update(over)
    p = tmp_path / "coverage.jsonl"
    p.write_text(json.dumps(row) + "\n")
    return p


def test_a_fully_covered_name_counts_as_read(tmp_path: Path) -> None:
    from qalpha.live.flags import filings_read

    assert filings_read(["VBL.NS"], as_of=AS_OF, path=_coverage(tmp_path)) == {"VBL"}


def test_an_incomplete_row_does_not_count_as_read(tmp_path: Path) -> None:
    """A row is written every run, including the ones where nothing was read."""
    from qalpha.live.flags import filings_read

    path = _coverage(tmp_path, complete=False)
    assert filings_read(["VBL.NS"], as_of=AS_OF, path=path) == set()


def test_an_old_extraction_version_does_not_count_as_read(tmp_path: Path) -> None:
    from qalpha.live.flags import filings_read

    path = _coverage(tmp_path, extraction_version="EX-1")
    assert filings_read(["VBL.NS"], as_of=AS_OF, path=path) == set()


def test_a_stale_coverage_row_does_not_count_as_read(tmp_path: Path) -> None:
    from qalpha.live.flags import filings_read

    path = _coverage(tmp_path, as_of="2026-01-01")
    assert filings_read(["VBL.NS"], as_of=AS_OF, path=path) == set()


def test_an_unread_name_is_never_listed_as_clear() -> None:
    """THE DEFECT. With no current-version coverage, every name read as Clear.

    The module docstring in `flags.py` says an absent warning and no warning are different facts and
    only one of them is reassuring. The code said otherwise, on the surface the user places orders
    from.
    """
    if load_archive(AS_OF)[1] is None:  # pragma: no cover
        return
    panel = flags_markdown(["VBL.NS"], as_of=AS_OF)
    assert "Filings NOT read" in panel and "VBL" in panel
    assert "not a clean bill" in panel
    assert "Clear (exchange" not in panel
