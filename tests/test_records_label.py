"""Numbers labelled as what was computed — three records that said something else.

- A filing event with no event date was dated by the evening it was *read*: a filing published a
  year earlier and backfilled on 2026-09-12 appeared as a 12 September event.
- The ``filings`` research tool answered "0 verified events" to every request.
- The evaluation harness never counted a purchase against the monthly limit, and counted the manager
  store's receipts, where AI-PM-3 writes none.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from qalpha.live import evidence_log, manager
from qalpha.live import tools as research
from qalpha.live.extraction import EXTRACTION_VERSION, corpus_reader

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


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
def events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "events.jsonl"
    path.write_text(
        json.dumps(_event("backfilled", as_of="2026-09-12", disseminated_at="2025-10-02T09:00:00Z"))
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(evidence_log, "EVENT_LOG", path)
    monkeypatch.setattr(evidence_log, "NEWS_EVENT_LOG", tmp_path / "news.jsonl")
    return path


def test_an_event_is_dated_when_it_became_public_not_when_it_was_read(events: Path) -> None:
    found = evidence_log.events(["AAA.NS"], as_of=date(2026, 9, 15), per_ticker=5)
    assert [e["date"] for e in found["AAA"]] == ["2025-10-02"]


def test_the_filings_tool_returns_the_events_on_file(events: Path) -> None:
    known = date(2026, 9, 15)
    days = pd.bdate_range("2025-01-01", known)
    out = research.answer(
        [{"tool": "filings", "ticker": "AAA.NS", "months": 12}],
        known=known,
        adj=pd.DataFrame({"AAA.NS": 1.0}, index=days),
        names=["AAA.NS"],
    )
    assert [e["id"] for e in out[0]["result"]["events"]] == ["backfilled"]
    assert out[0]["result"]["note"].startswith("1 verified event")


def test_the_harness_counts_purchases_and_ai_pm3_evenings(tmp_path: Path) -> None:
    import evaluate

    store = manager.Store(tmp_path / "manager")
    receipts = tmp_path / "agent" / "receipts"
    receipts.mkdir(parents=True)
    for name in (
        "2026-09-16-review-aaa.json",
        "2026-09-16-review-bbb.json",  # the same evening's second pass, after research
        "2026-09-16-confirm-ccc.json",
        "2026-09-17-review-ddd.failed-101010.json",
    ):
        (receipts / name).write_text("{}", encoding="utf-8")
    store.root.mkdir(parents=True)
    fill = {"action": "BUY", "filled": 300, "price": "100", "cost": "36", "on": "2026-09-17"}
    store.fills.write_text(
        "".join(json.dumps(r) + "\n" for r in (fill, {**fill, "on": "2026-09-18"})),
        encoding="utf-8",
    )
    lines, problems = evaluate._operation(store, receipts)
    text = "\n".join(lines)
    assert "Evenings with a saved review receipt: **1**" in text
    assert "₹60,072" in text and "**OVER**" in text
    assert problems == 1
