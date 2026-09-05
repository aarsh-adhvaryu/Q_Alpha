"""PreTradeAssessment — may Q-Alpha buy this stock? (reports/PREREGISTRATION_PRETRADE_V1.md)

The rules were frozen before this module existed. Two of these tests carry the whole design:

``test_an_unverified_event_cannot_move_the_state`` — fixture 6. If an unverified event can change
the answer, the passage-verification guard is decorative.

``test_an_extracted_event_can_never_block`` — a verified quote proves the document contains that
sentence, not that the model classified it correctly. Only the exchange's published lists exclude.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from qalpha.live.evidence import (
    BLOCK,
    PASS,
    UNKNOWN,
    WATCH,
    Assessment,
    Indicator,
    Provenance,
    load_archive,
)
from qalpha.live.evidence import (
    assess as exchange_assess,
)
from qalpha.live.extraction import ExtractedEvent
from qalpha.live.pretrade import (
    ANNOUNCEMENTS,
    NOT_COVERED_DIMENSIONS,
    AnnouncementCoverage,
    assess_basket,
    assess_candidate,
    basket_markdown,
    worst,
)

PURCHASE_DATE = date(2026, 8, 27)
FULL = AnnouncementCoverage(
    filings_in_window=2, documents_read=2, extraction_ran=True, index_fetched=True
)
NOTHING_FILED = AnnouncementCoverage(index_fetched=True, extraction_ran=True)


def _prov() -> Provenance:
    return Provenance(
        source_url="https://nsearchives.nseindia.com/content/cm/REG1_IND270826.csv",
        retrieved_at_utc=datetime(2026, 9, 5, tzinfo=UTC),
        http_status=200,
        sha256="a" * 64,
        byte_length=1,
        document_date=PURCHASE_DATE,
    )


def _exchange(state: str = PASS, detail: str = "clear") -> Assessment:
    return Assessment(
        "X", state, (Indicator("col", "0"),) if state != PASS else (), _prov(), detail
    )


def _event(materiality: str = "high", verified: bool = True) -> ExtractedEvent:
    return ExtractedEvent(
        ticker="X",
        event_type="regulatory_action",
        event_date=PURCHASE_DATE,
        materiality=materiality,
        passage="a passage long enough to be checked",
        summary="a regulator has written to the company",
        uncertainty="-",
        doc_sha256="b" * 64,
        doc_url="https://nsearchives.nseindia.com/corporate/X.pdf",
        disseminated_at=datetime(2026, 8, 25, tzinfo=UTC),
        model="m",
        extraction_version="EX-1",
        verified=verified,
    )


# --- the two rules that carry the design -----------------------------------------------------


def test_an_unverified_event_cannot_move_the_state() -> None:
    """FIXTURE 6. If this fails, the passage-verification guard is decorative."""
    a = assess_candidate(
        "X",
        exchange=_exchange(),
        events=[_event(verified=False)],
        coverage=FULL,
        unverified_events=1,
    )
    assert a.state == PASS
    assert a.flagged_events == ()
    assert a.unverified_events == 1
    assert "never acted on" in a.render()


def test_an_extracted_event_can_never_block() -> None:
    """A verified quote proves the document says it, not that the model read it correctly."""
    a = assess_candidate("X", exchange=_exchange(), events=[_event()], coverage=FULL)
    assert a.state == WATCH and not a.blocked


def test_block_without_a_hard_exchange_condition_is_a_programming_error() -> None:
    """Asserted rather than trusted to review: nothing but the exchange may exclude a name."""
    import qalpha.live.pretrade as m

    original = m._announcement_dimension
    m._announcement_dimension = lambda *a, **k: (m.Dimension(ANNOUNCEMENTS, BLOCK, "rogue"), ())
    try:
        with pytest.raises(AssertionError, match="hard exchange condition"):
            assess_candidate("X", exchange=_exchange(), coverage=FULL)
    finally:
        m._announcement_dimension = original


# --- precedence -------------------------------------------------------------------------------


def test_precedence_is_block_then_unknown_then_watch_then_pass() -> None:
    assert worst([PASS, WATCH, UNKNOWN, BLOCK]) == BLOCK
    assert worst([PASS, WATCH, UNKNOWN]) == UNKNOWN
    assert worst([PASS, WATCH]) == WATCH
    assert worst([PASS, PASS]) == PASS


def test_no_consulted_dimension_at_all_is_unknown_not_pass() -> None:
    assert worst([]) == UNKNOWN


# --- the coverage floor -------------------------------------------------------------------------


def test_a_pass_requires_the_exchange_feed() -> None:
    """Nothing may answer PASS having looked at nothing."""
    a = assess_candidate("X", exchange=None, coverage=FULL)
    assert a.state == UNKNOWN
    assert "requires it" in a.dimensions[0].detail


def test_listing_filings_is_not_reading_them() -> None:
    """The defect caught before this shipped: eight unread filings reported as 'nothing material'."""
    listed_only = AnnouncementCoverage(filings_in_window=8, documents_read=0, index_fetched=True)
    a = assess_candidate("X", exchange=_exchange(), coverage=listed_only)
    assert a.state == UNKNOWN
    ann = next(d for d in a.dimensions if d.name == ANNOUNCEMENTS)
    assert ann.detail == "8 filing(s) in the window, 8 unread"


def test_archiving_without_extracting_is_also_unknown() -> None:
    archived = AnnouncementCoverage(
        filings_in_window=3, documents_read=3, extraction_ran=False, index_fetched=True
    )
    a = assess_candidate("X", exchange=_exchange(), coverage=archived)
    assert a.state == UNKNOWN


def test_partial_coverage_is_not_coverage() -> None:
    partial = AnnouncementCoverage(
        filings_in_window=5, documents_read=3, extraction_ran=True, index_fetched=True
    )
    assert assess_candidate("X", exchange=_exchange(), coverage=partial).state == UNKNOWN


def test_an_unreachable_index_is_unknown() -> None:
    a = assess_candidate("X", exchange=_exchange(), coverage=AnnouncementCoverage())
    ann = next(d for d in a.dimensions if d.name == ANNOUNCEMENTS)
    assert ann.state == UNKNOWN and "unreachable" in ann.detail


def test_nothing_filed_is_a_pass_not_an_unknown() -> None:
    """A name that filed nothing is clear. Only "we did not look" is UNKNOWN."""
    a = assess_candidate("X", exchange=_exchange(), coverage=NOTHING_FILED)
    ann = next(d for d in a.dimensions if d.name == ANNOUNCEMENTS)
    assert a.state == PASS and ann.detail == "nothing filed in the window"


# --- materiality --------------------------------------------------------------------------------


@pytest.mark.parametrize("materiality", ["medium", "low"])
def test_only_high_materiality_raises_a_flag(materiality: str) -> None:
    a = assess_candidate("X", exchange=_exchange(), events=[_event(materiality)], coverage=FULL)
    assert a.state == PASS and a.flagged_events == ()


def test_a_high_materiality_verified_event_watches() -> None:
    """FIXTURE 5."""
    a = assess_candidate("X", exchange=_exchange(), events=[_event()], coverage=FULL)
    assert a.state == WATCH and len(a.flagged_events) == 1
    assert "regulatory_action" in a.render() and "b" * 16 in a.render()


# --- eligibility is not a view on return ----------------------------------------------------------


def test_only_pass_is_eligible() -> None:
    for state, eligible in ((PASS, True), (WATCH, False), (UNKNOWN, False), (BLOCK, False)):
        a = assess_candidate("X", exchange=_exchange(state), coverage=NOTHING_FILED)
        assert a.eligible is eligible


def test_not_covered_is_always_named() -> None:
    a = assess_candidate("X", exchange=_exchange(), coverage=NOTHING_FILED)
    assert a.not_covered == NOT_COVERED_DIMENSIONS
    assert "liquidity and ADV" in a.render()


def test_the_panel_names_what_is_blocked_and_what_needs_a_human() -> None:
    out = assess_basket(
        ["A", "B", "C"],
        exchange={"A": _exchange(), "B": _exchange(WATCH), "C": _exchange(BLOCK)},
        coverage=dict.fromkeys(["A", "B", "C"], NOTHING_FILED),
    )
    md = basket_markdown(out, as_of=PURCHASE_DATE)
    assert "**BLOCK — excluded deterministically:** C" in md
    assert "**HUMAN_REQUIRED:** B" in md
    assert "Not a view on return" in md


# --- the frozen fixtures, against the archived exchange file ---------------------------------------


def _live(ticker: str) -> str:
    rows, prov = load_archive(PURCHASE_DATE)
    if prov is None:  # pragma: no cover - the archive ships with the repo
        pytest.skip("archived REG1_IND270826 not present")
    return assess_candidate(
        ticker,
        exchange=exchange_assess(ticker, rows, prov, as_of=PURCHASE_DATE),
        coverage=NOTHING_FILED,
    ).state


def test_fixture_1_jiofin_watches_on_the_pe_caution() -> None:
    assert _live("JIOFIN.NS") == WATCH


def test_fixture_2_vbl_passes_on_the_purchase_date() -> None:
    """Not an endorsement. It means no consulted dimension objected on that date."""
    assert _live("VBL.NS") == PASS


def test_fixture_3_an_asm_stage_two_name_blocks() -> None:
    assert _live("BLISSGVS") == BLOCK


def test_fixture_4_a_missing_exchange_file_is_unknown_even_when_filings_are_clean() -> None:
    assert assess_candidate("VBL.NS", exchange=None, coverage=NOTHING_FILED).state == UNKNOWN
