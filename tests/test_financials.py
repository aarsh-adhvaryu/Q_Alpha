"""Filed financials: point in time, or not fed at all.

The defect this exists to prevent is the oldest one in quantitative finance — showing a backtest a
number that was not public yet. Everything here is about *when* a figure became knowable, and about
refusing to pass on one that does not add up.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

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
    assert fresh is not None and "newest quarter" in fresh["how_current"]


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


def test_a_fetch_that_omits_a_filing_never_removes_it_from_the_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exchange's index is not reliable about what it lists. A quiet call must not delete history.

    One evening the index omitted TITAN's Sep-2023 quarter and the next it included it; an importer
    that replaced a name's rows with the latest fetch would have dropped a filed quarter on the
    first of those evenings.
    """
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import financials as importer

    store = tmp_path / "financials.jsonl"
    monkeypatch.setattr(facts, "FACTS_PATH", store)
    old = _parse(filed="2026-04-15T18:30:00")
    assert old is not None
    old = facts.Quarter(**{**old.__dict__, "source_url": "https://example.invalid/old.xml"})
    facts.save([old], store)

    new = _parse(filed="2026-07-15T18:30:00")
    assert new is not None
    monkeypatch.setattr(importer, "_import", lambda names: [new])
    monkeypatch.setattr(importer, "_names", lambda cfg: ["TEST.NS"])

    assert importer.main(["--import", "--only", "TEST"]) == 0
    urls = {q.source_url for q in facts.load(store)}
    assert "https://example.invalid/old.xml" in urls, (
        "a filing tonight's fetch did not list is kept"
    )
    assert new.source_url in urls


# ---- SEBI's Integrated Filing (2025 on), and banks ------------------------------------------------

INTEGRATED = """<?xml version="1.0"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance">
  <xbrli:context id="OneD"><xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate>
    <xbrli:endDate>2026-06-30</xbrli:endDate></xbrli:period></xbrli:context>
  <in-capmkt:DateOfStartOfReportingPeriod contextRef="OneD">2026-04-01</in-capmkt:DateOfStartOfReportingPeriod>
  <in-capmkt:DateOfEndOfReportingPeriod contextRef="OneD">2026-06-30</in-capmkt:DateOfEndOfReportingPeriod>
  <in-capmkt:NatureOfReportStandaloneConsolidated contextRef="OneD">Consolidated</in-capmkt:NatureOfReportStandaloneConsolidated>
  <in-capmkt:RevenueFromOperations contextRef="OneD">722750000000</in-capmkt:RevenueFromOperations>
  <in-capmkt:OtherIncome contextRef="OneD">15680000000</in-capmkt:OtherIncome>
  <in-capmkt:Income contextRef="OneD">738430000000</in-capmkt:Income>
  <in-capmkt:Expenses contextRef="OneD">552310000000</in-capmkt:Expenses>
  <in-capmkt:ProfitBeforeExceptionalItemsAndTax contextRef="OneD">186120000000</in-capmkt:ProfitBeforeExceptionalItemsAndTax>
  <in-capmkt:ProfitBeforeTax contextRef="OneD">179440000000</in-capmkt:ProfitBeforeTax>
  <in-capmkt:TaxExpense contextRef="OneD">45240000000</in-capmkt:TaxExpense>
  <in-capmkt:ProfitLossForPeriod contextRef="OneD">134200000000</in-capmkt:ProfitLossForPeriod>
</xbrli:xbrl>
"""

BANK = """<?xml version="1.0"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance">
  <xbrli:context id="OneD"><xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate>
    <xbrli:endDate>2026-06-30</xbrli:endDate></xbrli:period></xbrli:context>
  <in-capmkt:DateOfStartOfReportingPeriod contextRef="OneD">2026-04-01</in-capmkt:DateOfStartOfReportingPeriod>
  <in-capmkt:DateOfEndOfReportingPeriod contextRef="OneD">2026-06-30</in-capmkt:DateOfEndOfReportingPeriod>
  <in-capmkt:NatureOfReportStandaloneConsolidated contextRef="OneD">Consolidated</in-capmkt:NatureOfReportStandaloneConsolidated>
  <in-capmkt:InterestEarned contextRef="OneD">905753300000</in-capmkt:InterestEarned>
  <in-capmkt:OtherIncome contextRef="OneD">425350300000</in-capmkt:OtherIncome>
  <in-capmkt:Income contextRef="OneD">1331103600000</in-capmkt:Income>
  <in-capmkt:InterestExpended contextRef="OneD">476256300000</in-capmkt:InterestExpended>
  <in-capmkt:ExpenditureExcludingProvisionsAndContingencies contextRef="OneD">{expenditure}</in-capmkt:ExpenditureExcludingProvisionsAndContingencies>
  <in-capmkt:OperatingProfitBeforeProvisionAndContingencies contextRef="OneD">309960000000</in-capmkt:OperatingProfitBeforeProvisionAndContingencies>
  <in-capmkt:ProvisionsOtherThanTaxAndContingencies contextRef="OneD">38028400000</in-capmkt:ProvisionsOtherThanTaxAndContingencies>
  <in-capmkt:ExceptionalItems contextRef="OneD">0</in-capmkt:ExceptionalItems>
  <in-capmkt:ProfitLossFromOrdinaryActivitiesBeforeTax contextRef="OneD">271931600000</in-capmkt:ProfitLossFromOrdinaryActivitiesBeforeTax>
  <in-capmkt:TaxExpense contextRef="OneD">68104700000</in-capmkt:TaxExpense>
  <in-capmkt:ProfitLossForThePeriod contextRef="OneD">203826900000</in-capmkt:ProfitLossForThePeriod>
  <in-capmkt:PercentageOfGrossNpa contextRef="OneD">0</in-capmkt:PercentageOfGrossNpa>
</xbrli:xbrl>
"""


def _read(xml: str, ticker: str = "TEST.NS") -> facts.Quarter | None:
    return facts.parse(
        xml,
        ticker=ticker,
        filed_at=datetime(2026, 7, 9, 18, 36),
        url="https://example.invalid/if.xml",
        sha256="s",
    )


def test_an_integrated_filing_is_read_under_its_own_prefix() -> None:
    """From 2025 results are tagged in-capmkt:, not in-bse-fin:. One prefix read them as empty."""
    q = _read(INTEGRATED)
    assert q is not None, "a 2025-format filing must parse"
    assert q.get("revenue") == Decimal("722750000000")
    assert q.reconciled, q.breaks


def test_a_bank_reports_interest_earned_as_its_revenue_and_adds_up_its_own_way() -> None:
    q = _read(BANK.format(expenditure="1021143600000"), "BANK.NS")
    assert q is not None and q.is_bank
    assert q.get("revenue") == Decimal("905753300000"), "interest earned is a bank's revenue"
    assert q.get("profit_after_tax") == Decimal("203826900000")
    assert q.reconciled, q.breaks
    summary = facts.summarise([q], as_of=date(2026, 9, 14))
    assert summary is not None
    assert summary["bank"]["net_interest_income"] == "429497000000"


def test_a_bank_whose_statement_does_not_add_up_is_refused() -> None:
    q = _read(BANK.format(expenditure="999999999999"), "BANK.NS")
    assert q is not None and not q.reconciled
    assert any("operating profit" in b for b in q.breaks)


def test_a_zero_npa_in_a_consolidated_filing_is_not_reported_rather_than_no_bad_loans() -> None:
    """The regulator requires NPA ratios only in the standalone accounts. A 0 there is a blank."""
    q = _read(BANK.format(expenditure="1021143600000"), "BANK.NS")
    assert q is not None
    assert q.get("gross_npa_pct") is None
    summary = facts.summarise([q], as_of=date(2026, 9, 14))
    assert summary is not None and summary["bank"]["gross_npa_pct"] is None


def test_a_full_year_is_never_stored_as_a_quarter() -> None:
    """A year stored as a quarter reports four quarters of revenue as one and 300% 'growth'."""
    yearly = INTEGRATED.replace(
        '<in-capmkt:DateOfStartOfReportingPeriod contextRef="OneD">2026-04-01',
        '<in-capmkt:DateOfStartOfReportingPeriod contextRef="OneD">2025-07-01',
    )
    assert _read(yearly) is None


def test_absent_figures_are_absent_not_the_word_none() -> None:
    q = _read(INTEGRATED)
    assert q is not None
    summary = facts.summarise([q], as_of=date(2026, 9, 14))
    assert summary is not None
    assert summary["eps_basic"] is None, "an untagged EPS must be null, never the string 'None'"


def test_the_importer_reads_both_the_old_feed_and_the_integrated_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reading only the old feed is why every name's newest quarter was December 2024."""
    import json
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import financials as importer

    legacy = [
        {
            "toDate": "31-Dec-2024",
            "broadCastDate": "09-Jan-2025 21:39:43",
            "consolidated": "Consolidated",
            "xbrl": "https://example.invalid/old.xml",
        }
    ]
    integrated = {
        "data": [
            {
                "qe_Date": "30-JUN-2026",
                "broadcast_Date": "09-Jul-2026 18:36:12",
                "consolidated": "Consolidated",
                "xbrl": "https://example.invalid/new.xml",
            }
        ],
        "totalCount": 1,
    }

    def fetch(url: str, **_: object) -> tuple[int, bytes]:
        body = integrated if "integrated-filing" in url else legacy
        return 200, json.dumps(body).encode()

    monkeypatch.setattr(importer, "_urlopen_fetch", fetch)
    listed = importer._filings("TEST")
    periods = sorted(str(f["period"]) for f in listed)
    assert periods == ["2024-12-31", "2026-06-30"]
    newest = next(f for f in listed if str(f["period"]) == "2026-06-30")
    assert newest["filed_at"] == datetime(2026, 7, 9, 18, 36, 12)
    assert newest["consolidated"] is True
