"""The buy-screen evidence panel. Flags, never vetoes.

It exists so a warning is in front of the user at the moment he places an order, instead of in a
report nobody opens. What it must never do is change the basket — the iron rule on the buy list is
*flag, don't veto*, and the screen is the thing being measured.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from qalpha.live import flags, news
from qalpha.live.evidence import load_archive
from qalpha.live.extraction import EXTRACTION_VERSION, corpus_reader
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
        "model": corpus_reader(),
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
        "reader": corpus_reader(),
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


# --- headlines on the buy screen --------------------------------------------------------------------
#
# The panel's oldest defect was calling a name "clear" when nobody had read its filings. The same
# trap is open one layer out: with no news rows on file — the state after every version bump — an
# "any bad headlines?" test would call every name clean.
def _news_row(**over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "kind": "news",
        "verified": True,
        "news_version": news.NEWS_VERSION,
        "as_of": "2026-09-10",
        "ticker": "VBL.NS",
        "event_type": "regulatory_action",
        "stance": "negative",
        "materiality": "high",
        "summary": "excise notice in Rajasthan",
        "passage": "Varun Beverages hit by excise notice in Rajasthan",
        "link": "https://news.google.com/x",
        "source": "Business Standard",
    }
    row.update(over)
    return row


def _news_logs(tmp_path, rows, coverage=True):
    import json

    events = tmp_path / "news_events.jsonl"
    events.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    cov = tmp_path / "news_coverage.jsonl"
    cov.write_text(
        json.dumps(
            {
                "as_of": "2026-09-10",
                "ticker": "VBL.NS",
                "extraction_ran": coverage,
                "news_version": news.NEWS_VERSION,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return events, cov


def test_a_high_negative_item_is_returned_with_its_link_and_source(tmp_path) -> None:
    events, _cov = _news_logs(tmp_path, [_news_row()])
    found = flags.recent_news(["VBL.NS"], since=date(2026, 9, 4), path=events)
    assert found["VBL"][0]["source"] == "Business Standard"
    assert found["VBL"][0]["link"].startswith("https://news.google.com")


def test_a_positive_item_is_returned_for_counting_but_is_not_a_concern(tmp_path) -> None:
    events, _cov = _news_logs(tmp_path, [_news_row(stance="positive")])
    found = flags.recent_news(["VBL.NS"], since=date(2026, 9, 4), path=events)
    negative, positive = flags.news_counts(found["VBL"])
    assert (negative, positive) == (0, 1)


def test_counts_are_two_integers_and_not_a_score(tmp_path) -> None:
    events, _cov = _news_logs(
        tmp_path, [_news_row(), _news_row(stance="positive"), _news_row(stance="neutral")]
    )
    found = flags.recent_news(["VBL.NS"], since=date(2026, 9, 4), path=events)
    assert flags.news_counts(found["VBL"]) == (1, 1)


def test_an_older_news_version_never_shows(tmp_path) -> None:
    events, _cov = _news_logs(tmp_path, [_news_row(news_version="NEWS-0")])
    assert flags.recent_news(["VBL.NS"], since=date(2026, 9, 4), path=events) == {}


def test_an_unverified_item_never_shows(tmp_path) -> None:
    events, _cov = _news_logs(tmp_path, [_news_row(verified=False)])
    assert flags.recent_news(["VBL.NS"], since=date(2026, 9, 4), path=events) == {}


def test_a_medium_item_is_not_shown_beside_a_basket(tmp_path) -> None:
    events, _cov = _news_logs(tmp_path, [_news_row(materiality="medium")])
    assert flags.recent_news(["VBL.NS"], since=date(2026, 9, 4), path=events) == {}


def test_names_whose_headlines_were_never_read_are_not_counted_as_read(tmp_path) -> None:
    _events, cov = _news_logs(tmp_path, [], coverage=False)
    assert flags.news_read(["VBL.NS"], as_of=date(2026, 9, 10), path=cov) == set()


def test_a_read_name_is_named(tmp_path) -> None:
    _events, cov = _news_logs(tmp_path, [])
    assert flags.news_read(["VBL.NS"], as_of=date(2026, 9, 10), path=cov) == {"VBL"}


def test_a_stale_coverage_row_cannot_speak_for_today(tmp_path) -> None:
    import json

    cov = tmp_path / "news_coverage.jsonl"
    cov.write_text(
        json.dumps(
            {
                "as_of": "2026-08-01",
                "ticker": "VBL.NS",
                "extraction_ran": True,
                "news_version": news.NEWS_VERSION,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert flags.news_read(["VBL.NS"], as_of=date(2026, 9, 10), path=cov) == set()


# --- an append-only log is read at its CURRENT revision --------------------------------------------
#
# Found in a scratch run on 2026-09-10, before any of this shipped. The first archived news run left
# 99 lines carrying 90 distinct events; nine had been re-read in a later batch and come back at a
# lower materiality. Counting lines gave 12 high-materiality negative items, and counting the record
# gives 4 — a number three times the one the log holds, under a label that says what the log holds.
def _superseded(tmp_path, kind: str, first: dict, second: dict):
    import json

    path = tmp_path / f"{kind}.jsonl"
    path.write_text(
        json.dumps(first) + "\n" + json.dumps(second) + "\n",
        encoding="utf-8",
    )
    return path


def test_a_re_read_that_lowered_the_materiality_wins(tmp_path) -> None:
    """The same headline can come back differently in a different batch — the prompt is not the
    same prompt. The latest read is what the record says; the earlier one stays on file."""
    key = "item1:VBL.NS:regulatory_action:abcd1234"
    path = _superseded(
        tmp_path,
        "news_events",
        _news_row(_key=key, revision=0, materiality="high"),
        _news_row(_key=key, revision=1, materiality="medium"),
    )
    assert flags.recent_news(["VBL.NS"], since=date(2026, 9, 4), path=path) == {}


def test_the_superseded_copy_is_not_deleted_only_outranked(tmp_path) -> None:
    key = "item1:VBL.NS:regulatory_action:abcd1234"
    path = _superseded(
        tmp_path,
        "news_events",
        _news_row(_key=key, revision=0, materiality="medium"),
        _news_row(_key=key, revision=1, materiality="high"),
    )
    found = flags.recent_news(["VBL.NS"], since=date(2026, 9, 4), path=path)
    assert len(found["VBL"]) == 1, "one event, not two"
    assert path.read_text(encoding="utf-8").count("\n") == 2, "both revisions stay on file"


def test_a_coverage_row_superseded_by_an_incomplete_one_is_not_read(tmp_path) -> None:
    """RULE 1: the same defect was in the filings reader, which predates the news one."""
    import json

    path = tmp_path / "coverage.jsonl"
    base = {
        "ticker": "VBL.NS",
        "as_of": "2026-09-10",
        "extraction_version": EXTRACTION_VERSION,
        "_key": "2026-09-10:VBL.NS",
    }
    path.write_text(
        json.dumps({**base, "complete": True, "revision": 0})
        + "\n"
        + json.dumps({**base, "complete": False, "revision": 1})
        + "\n",
        encoding="utf-8",
    )
    assert flags.filings_read(["VBL.NS"], as_of=date(2026, 9, 10), path=path) == set()
