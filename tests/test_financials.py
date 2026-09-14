"""Filed financials: point in time, or not fed at all.

The defect this exists to prevent is the oldest one in quantitative finance — showing a backtest a
number that was not public yet. Everything here is about *when* a figure became knowable, and about
refusing to pass on one that does not add up.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from qalpha.live import financials as facts

XBRL = """<?xml version="1.0"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance">
  <xbrli:context id="OneD">
    <xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate>
    <xbrli:endDate>2026-06-30</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="SegD">
    <xbrli:entity><xbrli:segment><xbrldi:explicitMember dimension="x:ReportableSegmentsAxis"
      >x:OneMember</xbrldi:explicitMember></xbrli:segment></xbrli:entity>
    <xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate>
    <xbrli:endDate>2026-06-30</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <in-bse-fin:DateOfStartOfReportingPeriod contextRef="OneD">2026-04-01</in-bse-fin:DateOfStartOfReportingPeriod>
  <in-bse-fin:DateOfEndOfReportingPeriod contextRef="OneD">2026-06-30</in-bse-fin:DateOfEndOfReportingPeriod>
  <in-bse-fin:NatureOfReportStandaloneConsolidated contextRef="OneD">Consolidated</in-bse-fin:NatureOfReportStandaloneConsolidated>
  <in-bse-fin:WhetherResultsAreAuditedOrUnaudited contextRef="OneD">Unaudited</in-bse-fin:WhetherResultsAreAuditedOrUnaudited>
  <in-bse-fin:RevenueFromOperations contextRef="OneD">1000000000.00</in-bse-fin:RevenueFromOperations>
  <in-bse-fin:OtherIncome contextRef="OneD">100000000.00</in-bse-fin:OtherIncome>
  <in-bse-fin:Income contextRef="OneD">{income}</in-bse-fin:Income>
  <in-bse-fin:Expenses contextRef="OneD">700000000.00</in-bse-fin:Expenses>
  <in-bse-fin:ProfitBeforeExceptionalItemsAndTax contextRef="OneD">400000000.00</in-bse-fin:ProfitBeforeExceptionalItemsAndTax>
  <in-bse-fin:ProfitBeforeTax contextRef="OneD">400000000.00</in-bse-fin:ProfitBeforeTax>
  <in-bse-fin:TaxExpense contextRef="OneD">100000000.00</in-bse-fin:TaxExpense>
  <in-bse-fin:ProfitLossForPeriod contextRef="OneD">300000000.00</in-bse-fin:ProfitLossForPeriod>
  <in-bse-fin:RevenueFromOperations contextRef="SegD">9999000000.00</in-bse-fin:RevenueFromOperations>
</xbrli:xbrl>
"""


def _parse(
    income: str = "1100000000.00", *, filed: str = "2026-07-15T18:30:00"
) -> facts.Quarter | None:
    return facts.parse(
        XBRL.format(income=income),
        ticker="TEST.NS",
        filed_at=datetime.fromisoformat(filed),
        url="https://example.invalid/x.xml",
        sha256="deadbeef",
    )


def test_the_headline_statement_is_read_not_one_segment() -> None:
    """A dimensioned context is one segment. Taking it would report a division as the company."""
    q = _parse()
    assert q is not None
    assert q.get("revenue") == Decimal("1000000000.00"), "the segment's number must not win"
    assert q.basis == "Consolidated"
    assert q.period_end == date(2026, 6, 30)


def test_a_filing_that_adds_up_reconciles() -> None:
    q = _parse()
    assert q is not None and q.reconciled and q.breaks == ()


def test_a_filing_that_does_not_add_up_is_named_and_refused() -> None:
    """Income is tagged separately from its own parts. When they disagree, the parse is not trusted."""
    q = _parse(income="1234000000.00")
    assert q is not None
    assert not q.reconciled
    assert any("total income" in b for b in q.breaks)
    assert facts.known_on([q], "TEST.NS", date(2026, 12, 31)) == [], (
        "an unreconciled quarter must never reach a packet"
    )


def test_a_filing_is_invisible_until_the_day_it_was_filed() -> None:
    """The whole point. A result disseminated on the 15th did not exist to the market on the 14th."""
    q = _parse(filed="2026-07-15T18:30:00")
    assert q is not None
    assert facts.known_on([q], "TEST.NS", date(2026, 7, 14)) == []
    assert facts.known_on([q], "TEST.NS", date(2026, 7, 15)) == [q]
    assert facts.known_on([q], "TEST.NS", date(2026, 9, 1)) == [q]


def test_a_restatement_supersedes_only_from_the_day_it_was_filed() -> None:
    """Two filings for one period. Before the second exists, the first is what was known."""
    first = _parse(filed="2026-07-15T18:30:00")
    second = _parse(filed="2026-08-20T18:30:00")
    assert first is not None and second is not None
    assert facts.known_on([first, second], "TEST.NS", date(2026, 8, 1)) == [first]
    assert facts.known_on([first, second], "TEST.NS", date(2026, 8, 20)) == [second]
    assert len(facts.known_on([first, second], "TEST.NS", date(2026, 9, 1))) == 1, (
        "one row per period — a restatement is not a second quarter"
    )


def test_growth_needs_the_same_quarter_a_year_earlier_and_is_absent_otherwise() -> None:
    """Year-on-year against the nearest available quarter is a different statistic, same name."""
    latest = _parse()
    assert latest is not None
    alone = facts.summarise([latest], as_of=date(2026, 9, 14))
    assert alone is not None and alone["revenue_growth_yoy_pct"] is None
    assert alone["year_ago_quarter"] is None

    class _Q:
        pass

    year_ago = facts.Quarter(
        ticker="TEST.NS",
        period_start=date(2025, 4, 1),
        period_end=date(2025, 6, 30),
        filed_at=datetime(2025, 7, 15, 18, 30),
        basis="Consolidated",
        audited="Unaudited",
        facts={"revenue": Decimal("800000000"), "profit_after_tax": Decimal("200000000")},
        source_url="",
        sha256="",
    )
    both = facts.summarise([latest, year_ago], as_of=date(2026, 9, 14))
    assert both is not None
    assert both["revenue_growth_yoy_pct"] == 25.0
    assert both["year_ago_quarter"] == "2025-06-30"


def test_stale_figures_say_how_old_they_are() -> None:
    """A two-year-old quarter presented without its age reads as current. This one says."""
    q = _parse(filed="2024-07-15T18:30:00")
    assert q is not None
    summary = facts.summarise([q], as_of=date(2026, 9, 14))
    assert summary is not None
    assert summary["days_since_filed"] > 700
    assert "MONTHS OLD" in summary["how_current"]
    fresh = facts.summarise([_parse(filed="2026-08-15T18:30:00")], as_of=date(2026, 9, 14))  # type: ignore[list-item]
    assert fresh is not None and "within the last quarter" in fresh["how_current"]


def test_the_store_survives_a_round_trip(tmp_path: Path) -> None:
    q = _parse()
    assert q is not None
    path = tmp_path / "financials.jsonl"
    facts.save([q], path)
    back = facts.load(path)
    assert len(back) == 1
    assert back[0].get("revenue") == q.get("revenue")
    assert back[0].filed_at == q.filed_at
    assert back[0].reconciled


def test_a_missing_store_is_no_financials_never_an_empty_company(tmp_path: Path) -> None:
    assert facts.load(tmp_path / "absent.jsonl") == []
    assert facts.summarise([]) is None
