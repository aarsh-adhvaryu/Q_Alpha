"""Tests for the research desk (:mod:`qalpha.live.desk`).

Every defect this repo has recorded was a number labelled as something it was not, on a surface
where the label became an order. The desk is such a surface. So what these assert is not that the
arithmetic works — it is that **the three states stay three**: healthy is not the same as unmeasured,
CLEAR is not the same as UNKNOWN, and "no concern reported" is not the same as "nothing wrong" when
nobody opened the filings.

The worst version of this bug already shipped once: a panel called a name *clear* whenever the
exchange passed and no current-version event mentioned it — which, with zero events on file after a
version bump, made every name clear including names whose filings had never been read.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from qalpha.live import evidence
from qalpha.live.desk import UNREADABLE, NameView, assemble

AS_OF = date(2026, 9, 10)


@dataclass(frozen=True)
class _Health:
    ticker: str
    trailing_return: float
    excess_vs_market: float
    drawdown_from_high: float
    level: str
    note: str = ""


@dataclass(frozen=True)
class _Report:
    holdings: list[_Health]


@dataclass(frozen=True)
class _Ind:
    column: str
    raw_value: str


@dataclass(frozen=True)
class _Assessment:
    state: str
    indicators: tuple[_Ind, ...] = ()


def _desk(**kw: object):
    base: dict[str, object] = {
        "as_of": AS_OF,
        "positions": {"VBL.NS": 147},
        "prices": {"VBL.NS": Decimal("420")},
        "cost_basis": {"VBL.NS": Decimal("400")},
    }
    base.update(kw)
    return assemble(**base)  # type: ignore[arg-type]


def _row(desk, ticker: str = "VBL.NS"):
    return next(r for r in desk.rows if r.ticker == ticker)


# --- the third state, column by column ------------------------------------------------------------
def test_no_health_reading_is_unreadable_not_healthy() -> None:
    """A name with too little price history must not be shown as fine."""
    row = _row(_desk(health=None))
    assert row.health == UNREADABLE
    assert row.health != "healthy"
    assert row.trailing_return is None, "absence must not become a zero return"
    assert row.drawdown is None


def test_no_assessment_is_unknown_not_clear() -> None:
    row = _row(_desk(assessments={}))
    assert row.exchange == "UNKNOWN"


def test_unread_filings_never_read_as_clean() -> None:
    """THE ONE THAT ALREADY SHIPPED. No events on file plus nobody reading is not 'nothing found'."""
    row = _row(_desk(filings_read=[], concerns={}))
    assert row.filings_read is False
    assert row.concerns == ()
    assert row.evidence_state == "filings not read"
    assert "nothing flagged" not in row.evidence_state


def test_read_filings_with_nothing_found_say_so_differently() -> None:
    row = _row(_desk(filings_read=["VBL"], concerns={}))
    assert row.evidence_state == "filings read, nothing flagged"


def test_a_concern_is_surfaced_with_what_it_was() -> None:
    row = _row(
        _desk(
            filings_read=["VBL"],
            concerns={"VBL": [{"type": "litigation", "summary": "SEBI show-cause notice"}]},
        )
    )
    assert row.concerns == ("litigation: SEBI show-cause notice",)
    assert "1 concern" in row.evidence_state


# --- what makes a person look --------------------------------------------------------------------
def test_an_unknown_name_needs_attention() -> None:
    """Unknown is not a quiet pass. If the system could not check, a person must."""
    assert _row(_desk()).attention is True


def test_a_fully_clean_read_name_does_not_need_attention() -> None:
    row = _row(
        _desk(
            health=_Report([_Health("VBL.NS", 0.08, 0.02, -0.05, "healthy")]),
            assessments={"VBL.NS": _Assessment(evidence.PASS)},
            filings_read=["VBL"],
        )
    )
    assert row.attention is False, "everything checked and nothing found is the one quiet case"


def test_a_breaking_name_needs_attention_even_when_everything_else_passed() -> None:
    row = _row(
        _desk(
            health=_Report([_Health("VBL.NS", -0.42, -0.30, -0.55, "breaking", "down 42%")]),
            assessments={"VBL.NS": _Assessment(evidence.PASS)},
            filings_read=["VBL"],
        )
    )
    assert row.attention is True
    assert row.health_note == "down 42%"


def test_an_exchange_block_reaches_the_row_with_the_published_value() -> None:
    """NSE's own P/E caution, as NSE published it — not recomputed from a vendor's earnings basis."""
    row = _row(
        _desk(
            assessments={
                "VBL.NS": _Assessment(
                    "WATCH", (_Ind("Scrip PE is greater than 50 (4 trailing quarters)", "Y"),)
                )
            }
        )
    )
    assert row.exchange == "WATCH"
    assert row.indicators == ("Scrip PE is greater than 50 (4 trailing quarters) = Y",)


# --- money ----------------------------------------------------------------------------------------
def test_an_unpriced_holding_reports_no_pnl_rather_than_zero() -> None:
    """A 0% gain on a name that moved is worse than saying nothing."""
    row = _row(_desk(prices={}))
    assert row.mark is None
    assert row.unrealised is None
    assert row.unrealised_pct is None
    assert row.value is None


def test_pnl_is_computed_from_the_lot_cost_not_the_mark() -> None:
    row = _row(_desk())
    assert row.unrealised == Decimal("20") * 147
    assert row.unrealised_pct == 5.0


def test_a_holding_without_a_cost_basis_reports_no_pnl() -> None:
    assert _row(_desk(cost_basis={})).unrealised is None


# --- scope and coverage ---------------------------------------------------------------------------
def test_a_proposed_name_that_is_not_held_still_gets_a_row() -> None:
    desk = _desk(proposal=["INFY.NS"])
    row = _row(desk, "INFY.NS")
    assert row.proposed is True
    assert row.held is False
    assert row.quantity == 0
    assert [r.ticker for r in desk.candidates] == ["INFY.NS"]


def test_the_coverage_line_names_who_was_not_read() -> None:
    desk = _desk(proposal=["INFY.NS"], filings_read=["VBL"])
    line = desk.coverage_line()
    assert "1 of 2" in line
    assert "INFY" in line
    assert "not the same as clean" in line


def test_the_coverage_line_is_unambiguous_when_everything_was_read() -> None:
    desk = _desk(filings_read=["VBL"])
    assert desk.coverage_line().startswith("All 1 names")


def test_an_empty_scope_says_so_rather_than_claiming_full_coverage() -> None:
    desk = assemble(as_of=AS_OF, positions={}, prices={}, cost_basis={})
    assert desk.coverage_line() == "No names in scope."
    assert desk.rows == ()


def test_a_missing_surveillance_file_is_recorded_as_an_age_of_none() -> None:
    assert _desk(exchange_file_age=None).exchange_file_age is None


def test_notes_survive_onto_the_desk() -> None:
    """A source that could not be read must produce a sentence, not a silently empty column."""
    desk = _desk(notes=["the filings log could not be read"])
    assert desk.notes == ("the filings log could not be read",)


def test_the_passing_state_is_the_one_evidence_actually_emits() -> None:
    """A guard against the slip that already happened here once.

    The first version of the desk's tone map spelled the passing state ``"CLEAR"``. That is not one
    of :mod:`qalpha.live.evidence`'s states — the real one is ``PASS``, and ``CLEAR`` is a column
    code meaning something else entirely — so every clean name fell through to the warn tone and
    was rendered amber on a real-money page. Constants get imported; they do not get retyped.
    """
    assert evidence.PASS == "PASS"
    row = _row(_desk(assessments={"VBL.NS": _Assessment(evidence.PASS)}, filings_read=["VBL"]))
    assert row.exchange == evidence.PASS
    assert row.attention is False


def test_not_covered_still_asks_for_a_person() -> None:
    """A dimension v1 does not cover is not a dimension that came back clean."""
    row = _row(
        _desk(
            assessments={"VBL.NS": _Assessment(evidence.NOT_COVERED)},
            filings_read=["VBL"],
            health=_Report([_Health("VBL.NS", 0.08, 0.02, -0.05, "healthy")]),
        )
    )
    assert row.attention is True


# --- the News column, and its third state -----------------------------------------------------------
#
# Same rule as every other column here: a blank cell reads as "fine". "Nobody read the headlines" and
# "the headlines carried nothing" are different facts, and only one of them is reassuring.
def test_news_not_read_is_a_gap_not_a_quiet_week() -> None:
    view = NameView(ticker="VBL.NS")
    assert view.news_state == "news not read"
    assert view.attention


def test_no_item_matched_is_a_real_answer() -> None:
    view = NameView(ticker="VBL.NS", news_read=True, news_items=0)
    assert view.news_state == "no item matched"


def test_items_read_with_nothing_flagged_says_how_many() -> None:
    view = NameView(ticker="VBL.NS", news_read=True, news_items=4)
    assert view.news_state == "4 read, none flagged"


def test_the_column_is_counts_and_never_a_score() -> None:
    """A number in [0, 1] invites being ranked and optimised against. Two integers can be checked
    by opening the items behind them."""
    view = NameView(
        ticker="VBL.NS",
        news_read=True,
        news_items=6,
        news=(("negative", "regulatory_action: excise notice"), ("positive", "results: strong")),
    )
    assert view.news_state == "1 neg / 1 pos"
    assert view.news_concerns == ("regulatory_action: excise notice",)


def test_a_negative_headline_puts_the_name_on_the_attention_list() -> None:
    view = NameView(
        ticker="VBL.NS",
        filings_read=True,
        exchange=evidence.PASS,
        health="healthy",
        news_read=True,
        news=(("negative", "litigation: a suit was filed"),),
    )
    assert view.attention


def test_a_positive_headline_does_not() -> None:
    view = NameView(
        ticker="VBL.NS",
        filings_read=True,
        exchange=evidence.PASS,
        health="healthy",
        news_read=True,
        news=(("positive", "results: strong quarter"),),
    )
    assert not view.attention


def test_the_desk_says_how_many_names_had_their_headlines_read() -> None:
    desk = assemble(
        as_of=date(2026, 9, 10),
        positions={"VBL.NS": 10},
        prices={},
        cost_basis={},
        watchlist=["TCS.NS"],
        news_read=["VBL"],
        news={"VBL": [{"stance": "negative", "type": "litigation", "summary": "a suit"}]},
        news_matched={"VBL": 3},
    )
    line = desk.news_line()
    assert "1 of 2" in line and "1 high-materiality negative" in line
    assert "not a score" in line


def test_no_headlines_read_at_all_says_gap_rather_than_quiet() -> None:
    desk = assemble(as_of=date(2026, 9, 10), positions={"VBL.NS": 10}, prices={}, cost_basis={})
    assert "a gap, not a quiet week" in desk.news_line()
