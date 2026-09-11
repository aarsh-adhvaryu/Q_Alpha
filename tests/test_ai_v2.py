"""AI-V2 — the veto stops being an opinion and becomes a rule over verified events.

`PR-8c` asked a web-searching model *keep or drop*, and required a DROP to cite a primary host. That
is a rule about where a link points, not about what it says: the first real veto cited a stock quote
page and passed the check that existed then. Nothing was archived, so a year later the claim could
not be re-opened — and re-opening it is the whole reason a citation is required.

What these pin is that the replacement cannot drift back: only a **filing** drops, only five event
types, only inside the window, only at the current extractor, and a headline can never do more than
leave a lead. Registered in `reports/PREREGISTRATION_AI_V2.md`.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from qalpha.live.extraction import EXTRACTION_VERSION
from qalpha.live.news import NEWS_VERSION
from qalpha.live.verdicts import (
    AI_PROMPT_VERSION,
    VETO_TYPES,
    VETO_WINDOW_DAYS,
    event_verdicts,
    verdict_calls,
)

AS_OF = date(2026, 9, 11)
BASKET = {"VBL.NS": 10, "TCS.NS": 5}


def _filing(**over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "kind": "event",
        "verified": True,
        "extraction_version": EXTRACTION_VERSION,
        "as_of": "2026-09-10",
        "ticker": "VBL.NS",
        "event_type": "regulatory_action",
        "materiality": "high",
        "summary": "interim order against the promoter",
        "doc_url": "https://nsearchives.nseindia.com/corporate/VBL_x.pdf",
        "disseminated_at": "2026-09-09T10:00:00Z",
        "_key": "doc1:VBL.NS:regulatory_action:aaaa",
    }
    row.update(over)
    return row


def _headline(**over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "kind": "news",
        "verified": True,
        "news_version": NEWS_VERSION,
        "as_of": "2026-09-10",
        "ticker": "VBL.NS",
        "event_type": "regulatory_action",
        "materiality": "high",
        "stance": "negative",
        "summary": "excise notice reported",
        "link": "https://news.google.com/x",
        "source": "Business Standard",
        "_key": "item1:VBL.NS:regulatory_action:bbbb",
    }
    row.update(over)
    return row


def _logs(tmp_path: Path, filings=(), headlines=()) -> tuple[Path, Path]:
    events = tmp_path / "events.jsonl"
    news = tmp_path / "news_events.jsonl"
    events.write_text("".join(json.dumps(r) + "\n" for r in filings), encoding="utf-8")
    news.write_text("".join(json.dumps(r) + "\n" for r in headlines), encoding="utf-8")
    return events, news


def _verdicts(tmp_path: Path, filings=(), headlines=(), **kw):
    events, news = _logs(tmp_path, filings, headlines)
    return event_verdicts(BASKET, as_of=AS_OF, events_path=events, news_path=news, **kw)


# --- what drops a name --------------------------------------------------------------------------
def test_a_high_materiality_filing_of_a_veto_type_drops_it(tmp_path: Path) -> None:
    out = _verdicts(tmp_path, filings=[_filing()])
    assert out["VBL.NS"].keep is False
    assert out["VBL.NS"].source_tier == "primary"
    assert "regulatory_action" in out["VBL.NS"].reason
    assert verdict_calls(out) == {"VBL.NS": "drop"}


@pytest.mark.parametrize("kind", VETO_TYPES)
def test_every_registered_veto_type_fires(tmp_path: Path, kind: str) -> None:
    assert _verdicts(tmp_path, filings=[_filing(event_type=kind)])["VBL.NS"].keep is False


def test_a_type_outside_the_registered_five_does_not(tmp_path: Path) -> None:
    """Results, guidance and contract wins are priced by the screen already. EX-1 proved what a
    loose rubric does: 77 of 193 events came back high, and good news rejected candidates."""
    for kind in ("results", "guidance_change", "acquisition", "dividend", "other"):
        assert _verdicts(tmp_path, filings=[_filing(event_type=kind)]) == {}, kind


def test_medium_materiality_does_not_fire(tmp_path: Path) -> None:
    assert _verdicts(tmp_path, filings=[_filing(materiality="medium")]) == {}


def test_an_unverified_event_never_acts(tmp_path: Path) -> None:
    """The quote is the guard. An event whose passage was not in the document is not an event."""
    assert _verdicts(tmp_path, filings=[_filing(verified=False)]) == {}


def test_an_older_extractor_version_never_acts(tmp_path: Path) -> None:
    """EX-1 rows stay on file as a record and cannot act — one label, one rule."""
    assert _verdicts(tmp_path, filings=[_filing(extraction_version="EX-1")]) == {}


def test_an_event_outside_the_window_does_not_act(tmp_path: Path) -> None:
    stale = (AS_OF - __import__("datetime").timedelta(days=VETO_WINDOW_DAYS + 1)).isoformat()
    assert _verdicts(tmp_path, filings=[_filing(as_of=stale)]) == {}


def test_a_name_outside_the_basket_is_ignored(tmp_path: Path) -> None:
    """The deterministic screen fixes the opportunity set. The veto can only subtract from it."""
    assert _verdicts(tmp_path, filings=[_filing(ticker="INFY.NS")]) == {}


def test_an_empty_basket_asks_nothing(tmp_path: Path) -> None:
    events, news = _logs(tmp_path, [_filing()])
    assert event_verdicts({}, as_of=AS_OF, events_path=events, news_path=news) == {}


def test_missing_logs_keep_everything(tmp_path: Path) -> None:
    """Absence is keep. Every failure path degrades TWIN_FULL to exactly TWIN_NO_AI."""
    out = event_verdicts(
        BASKET, as_of=AS_OF, events_path=tmp_path / "none.jsonl", news_path=tmp_path / "none2.jsonl"
    )
    assert out == {}


# --- what a headline may do ------------------------------------------------------------------------
def test_a_headline_leaves_a_lead_and_never_drops(tmp_path: Path) -> None:
    """A snippet read by an 8B model is secondary evidence — NEWS-1's own first run labelled the
    same headline differently in different batches. It can raise a hand; it cannot remove a name."""
    out = _verdicts(tmp_path, headlines=[_headline()])
    assert out["VBL.NS"].keep is True
    assert out["VBL.NS"].demoted is True
    assert "lead only" in out["VBL.NS"].reason
    assert verdict_calls(out) == {"VBL.NS": "keep"}


def test_a_positive_headline_is_not_even_a_lead(tmp_path: Path) -> None:
    assert _verdicts(tmp_path, headlines=[_headline(stance="positive")]) == {}


def test_an_older_news_version_never_acts(tmp_path: Path) -> None:
    assert _verdicts(tmp_path, headlines=[_headline(news_version="NEWS-0")]) == {}


def test_a_filing_outranks_a_headline_on_the_same_name(tmp_path: Path) -> None:
    """The drop stands. A headline cannot strengthen it and must not overwrite it with a lead."""
    out = _verdicts(tmp_path, filings=[_filing()], headlines=[_headline()])
    assert out["VBL.NS"].keep is False and out["VBL.NS"].demoted is False


def test_headlines_and_filings_can_flag_different_names(tmp_path: Path) -> None:
    out = _verdicts(
        tmp_path,
        filings=[_filing(ticker="TCS.NS", _key="doc2:TCS.NS:insolvency:cccc")],
        headlines=[_headline()],
    )
    assert out["TCS.NS"].keep is False
    assert out["VBL.NS"].keep is True and out["VBL.NS"].demoted


# --- the record --------------------------------------------------------------------------------------
def test_a_superseded_event_does_not_still_veto(tmp_path: Path) -> None:
    """The log is append-only: a re-read appends a lower materiality rather than replacing. Reading
    lines instead of the record is the defect this repo found in `flags` on 2026-09-10."""
    key = "doc1:VBL.NS:regulatory_action:aaaa"
    out = _verdicts(
        tmp_path,
        filings=[
            _filing(_key=key, revision=0, materiality="high"),
            _filing(_key=key, revision=1, materiality="medium"),
        ],
    )
    assert out == {}


def test_the_treatment_is_versioned_and_the_twin_imports_that_version() -> None:
    """A label spanning two rules makes every row under it unusable — it cost run 2 four days."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import twin as twin_script

    assert AI_PROMPT_VERSION == "AI-V2"
    assert twin_script.AI_PROMPT_VERSION is AI_PROMPT_VERSION


def test_the_recorded_source_names_a_rule_rather_than_a_chat_model() -> None:
    """Nothing is asked under AI-V2. A row saying `claude-haiku-4-5` would name something that did
    not happen, which is the defect family this repo is organised around."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import twin as twin_script

    assert twin_script._VERDICT_SOURCE.startswith("rule:AI-V2")
    assert "haiku" not in twin_script._VERDICT_SOURCE


def test_the_registration_exists_and_names_the_five_types() -> None:
    text = Path("reports/PREREGISTRATION_AI_V2.md").read_text(encoding="utf-8")
    for kind in VETO_TYPES:
        assert kind in text
    assert "CORE_V1" in text and "use_ai=False" in text
