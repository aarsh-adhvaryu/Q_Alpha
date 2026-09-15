"""What a replayed evening may know from the filing corpus — and three defects found building it.

- A filing is knowable on the date it was **published**, even when it was read later; a row with no
  publication time is not knowable at all. The evening run's rule is unchanged.
- Coverage on a replayed date counts the exchange's own listing for that window and names every
  document without a reading, including one that was listed and never fetched.
- The ``filings`` research tool answered "0 events" for every request; the evaluation harness never
  counted a purchase against the monthly limit; a failed receipt counted as a review.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from qalpha.live import evidence_log, manager
from qalpha.live import tools as research
from qalpha.live.evidence_log import Corpus
from qalpha.live.extraction import EXTRACTION_VERSION, corpus_reader

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

T = date(2026, 9, 1)


def _event(key: str, **fields: Any) -> dict[str, Any]:
    return {
        "_key": key,
        "ticker": "AAA",
        "verified": True,
        "model": corpus_reader(),
        "extraction_version": EXTRACTION_VERSION,
        "materiality": "high",
        **fields,
    }


@pytest.fixture
def logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(evidence_log, "NEWS_EVENT_LOG", tmp_path / "news.jsonl")
    monkeypatch.setattr(evidence_log, "ANNOUNCEMENTS", tmp_path / "announcements")
    events = tmp_path / "events.jsonl"
    events.write_text(
        "".join(
            json.dumps(r) + "\n"
            for r in (
                _event(
                    "before-read-later", as_of="2026-09-12", disseminated_at="2026-08-20T09:00:00Z"
                ),
                _event("after", as_of="2026-09-12", disseminated_at="2026-09-03T09:00:00Z"),
                _event("undated", as_of="2026-09-12"),
                _event("read-then", as_of="2026-08-30", disseminated_at="2026-08-29T09:00:00Z"),
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(evidence_log, "EVENT_LOG", events)
    return tmp_path


def _ids(found: dict[str, list[dict[str, str]]]) -> set[str]:
    return {e["id"] for items in found.values() for e in items}


def test_the_evening_run_knows_only_what_had_been_read_by_that_evening(logs: Path) -> None:
    assert _ids(evidence_log.events(["AAA.NS"], as_of=T, per_ticker=10)) == {"read-then"}


def test_a_replay_knows_what_was_published_by_then_even_if_read_later(logs: Path) -> None:
    found = evidence_log.events(["AAA.NS"], as_of=T, per_ticker=10, recorded_by=date(2026, 9, 15))
    assert _ids(found) == {"before-read-later", "read-then"}, "published after, or undated: unknown"
    assert _ids(
        evidence_log.events(["AAA.NS"], as_of=T, per_ticker=10, recorded_by=date(2026, 9, 1))
    ) == {"read-then"}, "a row recorded after the corpus date is not in that corpus"


def test_an_event_is_dated_when_it_became_public_not_when_it_was_read(logs: Path) -> None:
    found = evidence_log.events(["AAA.NS"], as_of=T, per_ticker=10, recorded_by=date(2026, 9, 15))
    dated = {e["id"]: e["date"] for e in found["AAA"]}
    assert dated["before-read-later"] == "2026-08-20"


def _archive(root: Path) -> Corpus:
    """Five listed filings for AAA: before the window, read, unread-with-text, never fetched, after."""
    base = root / "announcements" / "AAA"
    (base / "index").mkdir(parents=True)

    def row(seq: str, when: str, desc: str) -> dict[str, str]:
        return {
            "an_dt": when,
            "seq_id": seq,
            "desc": desc,
            "attchmntFile": f"https://x/{seq}.pdf",
            "symbol": "AAA",
        }

    listing = [
        row("1", "10-Aug-2026 10:00:00", "old"),
        row("2", "25-Aug-2026 10:00:00", "read"),
        row("3", "28-Aug-2026 10:00:00", "fetched, not read"),
        row("4", "30-Aug-2026 10:00:00", "listed only"),
        row("5", "05-Sep-2026 10:00:00", "after the session"),
    ]
    # Two index snapshots: the later one has dropped filing 3, which was still filed.
    (base / "index" / "2026-09-06.json").write_text(json.dumps(listing), encoding="utf-8")
    (base / "index" / "2026-09-12.json").write_text(
        json.dumps([r for r in listing if r["seq_id"] != "3"]), encoding="utf-8"
    )
    for seq in ("1", "2", "3", "5"):
        (base / f"{seq}.provenance.json").write_text(json.dumps({"sha256": f"h{seq}"}))
    (base / "3.txt.gz").write_bytes(b"")
    coverage = root / "coverage.jsonl"
    coverage.write_text(
        json.dumps(
            {
                "_key": "k",
                "as_of": "2026-09-12",
                "ticker": "AAA.NS",
                "window_days": 10,
                "extraction_version": EXTRACTION_VERSION,
                "reader": corpus_reader(),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return Corpus(date(2026, 9, 15), read=frozenset({"h1", "h2", "h5"}), declined=frozenset())


def test_replay_coverage_counts_the_window_and_names_each_unread_filing(logs: Path) -> None:
    corpus = _archive(logs)
    cov = evidence_log.coverage(
        ["AAA.NS", "ZZZ.NS"], as_of=T, path=logs / "coverage.jsonl", corpus=corpus
    )["AAA"]
    assert cov.opened and cov.filed == 3 and cov.read == 1
    assert [(u["subject"], u["why"]) for u in cov.unread] == [
        ("fetched, not read", "not read yet"),
        ("listed only", "listed by the exchange but never fetched"),
    ]


def test_a_name_first_opened_after_the_corpus_date_is_unopened(logs: Path) -> None:
    corpus = _archive(logs)
    early = Corpus(date(2026, 9, 10), corpus.read, corpus.declined)
    cov = evidence_log.coverage(["AAA.NS"], as_of=T, path=logs / "coverage.jsonl", corpus=early)
    assert not cov["AAA"].opened
    unopened = evidence_log.coverage(
        ["ZZZ.NS"], as_of=T, path=logs / "coverage.jsonl", corpus=corpus
    )["ZZZ"]
    assert not unopened.opened, "nobody having looked at a company still stops a review"


def test_the_filings_tool_returns_the_events_on_file(logs: Path) -> None:
    days = pd.bdate_range("2026-01-01", "2026-09-14")
    out = research.answer(
        [{"tool": "filings", "ticker": "AAA.NS", "months": 12}],
        known=T,
        adj=pd.DataFrame({"AAA.NS": 1.0}, index=days),
        names=["AAA.NS"],
    )
    result = out[0]["result"]
    assert [e["id"] for e in result["events"]] == ["read-then"]
    assert result["note"].startswith("1 verified event")


def test_the_harness_counts_purchases_against_the_monthly_limit(tmp_path: Path) -> None:
    import evaluate

    store = manager.Store(tmp_path)
    store.receipts.mkdir(parents=True)
    (store.receipts / "2026-09-01-abc.json").write_text("{}")
    (store.receipts / "2026-09-02-def.failed-101010.json").write_text("{}")
    fill = {"action": "BUY", "filled": 300, "price": "100", "cost": "36", "on": "2026-09-02"}
    fill["version"] = manager.VERSION
    store.fills.write_text(
        "".join(json.dumps(r) + "\n" for r in (fill, {**fill, "on": "2026-09-03"})),
        encoding="utf-8",
    )
    lines, problems = evaluate._operation(store)
    text = "\n".join(lines)
    assert "Reviews with a saved receipt: **1**" in text
    assert "₹60,072" in text and "**OVER**" in text
    assert problems == 1
    assert manager.spent_this_month(date(2026, 9, 30), store) == Decimal("60072")
