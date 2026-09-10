"""The desk, on the page — the caller test for what the user actually reads.

:mod:`tests.test_desk` establishes that the desk's *fields* keep their third state. That is not
enough: this repo's defects have always been a correct value rendered under a wrong label, or a
correct value that never reached the surface at all. Eleven tests once passed while the scheduled
caller fed the screen alphabetical one-share baskets.

So these render the real page and read it back.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

pytest.importorskip("pandas")

from qalpha.accounting.costs import Side
from qalpha.config import Config
from qalpha.live import evidence
from qalpha.live.account import reconcile
from qalpha.live.commitments import allowance
from qalpha.live.desk import assemble
from qalpha.live.report import render
from qalpha.live.tradebook import TradebookTrade

AS_OF = date(2026, 9, 10)
WHEN = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
PRICES = {"VBL.NS": Decimal("420")}


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


def _account():
    trade = TradebookTrade(
        trade_date=date(2026, 8, 29),
        ticker="VBL.NS",
        side=Side.BUY,
        quantity=Decimal("147"),
        price=Decimal("400"),
        exec_time="10:00:00",
        trade_id="t1",
    )
    return reconcile([trade], {"VBL.NS": Decimal("147")}, Decimal("201117"), Config(), AS_OF)


def _page(desk=None, proposal=()) -> str:
    return render(
        account=_account(),
        prices=PRICES,
        allowance=allowance(Decimal("50000"), [], period=AS_OF),
        commitments=[],
        generated_at=WHEN,
        proposal=proposal,
        desk=desk,
    )


def _desk(**kw: object):
    base: dict[str, object] = {
        "as_of": AS_OF,
        "positions": {"VBL.NS": 147},
        "prices": PRICES,
        "cost_basis": {"VBL.NS": Decimal("400")},
    }
    base.update(kw)
    return assemble(**base)  # type: ignore[arg-type]


def test_the_desk_reaches_the_page_at_all() -> None:
    page = _page(_desk())
    assert "The desk" in page
    assert "VBL" in page


def test_an_absent_desk_is_a_sentence_not_a_blank_section() -> None:
    """A missing research layer must read as missing, not as nothing to report."""
    page = _page(None)
    assert "The desk" in page
    assert "not the same as nothing being wrong" in page


def test_an_unmeasurable_trend_renders_as_a_dash_and_never_as_zero() -> None:
    """A 0.00% in this column would say 'flat'. Unmeasured and flat are different markets."""
    page = _page(_desk(health=None))
    assert "too little history" in page
    assert "does not mean flat" in page


def test_an_unknown_exchange_verdict_is_visible_as_unknown() -> None:
    page = _page(_desk(assessments={}))
    assert "UNKNOWN" in page
    assert "it is not CLEAR" in page


def test_a_name_nobody_read_says_so_on_the_page() -> None:
    page = _page(_desk(filings_read=[]))
    assert "filings not read" in page
    assert "not evidence of one" in page


def test_the_exchange_indicator_text_reaches_the_page_verbatim() -> None:
    """NSE's published caution, in NSE's words — the P/E screen a trader would look for."""
    page = _page(
        _desk(
            assessments={
                "VBL.NS": _Assessment(
                    "WATCH", (_Ind("Scrip PE is greater than 50 (4 trailing quarters)", "Y"),)
                )
            }
        )
    )
    assert "Scrip PE is greater than 50" in page


def test_a_verified_filing_concern_is_quoted_in_its_own_panel() -> None:
    page = _page(
        _desk(
            filings_read=["VBL"],
            concerns={"VBL": [{"type": "litigation", "summary": "SEBI show-cause notice"}]},
        )
    )
    assert "What the filings said" in page
    assert "SEBI show-cause notice" in page


def test_the_concerns_panel_is_absent_when_nothing_was_found() -> None:
    """An empty 'concerns' heading would imply somebody checked and found nothing."""
    assert "What the filings said" not in _page(_desk(filings_read=["VBL"]))


def test_names_needing_attention_sort_above_quiet_ones() -> None:
    """The page is read top-down; a breaking holding must not be below a healthy one."""
    desk = _desk(
        positions={"VBL.NS": 147, "TCS.NS": 10},
        prices={"VBL.NS": Decimal("420"), "TCS.NS": Decimal("3000")},
        cost_basis={"VBL.NS": Decimal("400"), "TCS.NS": Decimal("2800")},
        health=_Report(
            [
                _Health("VBL.NS", 0.08, 0.02, -0.05, "healthy"),
                _Health("TCS.NS", -0.42, -0.30, -0.55, "breaking"),
            ]
        ),
        assessments={"VBL.NS": _Assessment(evidence.PASS), "TCS.NS": _Assessment(evidence.PASS)},
        filings_read=["VBL", "TCS"],
    )
    # Scope to the desk section: the Holdings table above it has its own ordering, and a
    # comparison spanning both would assert nothing about either.
    section = _page(desk).split("The desk", 1)[1].split("basket", 1)[0]
    assert "TCS" in section and "VBL" in section
    assert section.index("TCS") < section.index("VBL")


def test_a_gather_failure_note_is_printed_rather_than_swallowed() -> None:
    page = _page(_desk(notes=["exchange surveillance unavailable (OSError: refused)"]))
    assert "exchange surveillance unavailable" in page


def test_the_page_still_says_nothing_here_trades() -> None:
    """The iron rule is on the surface, on every version of this page."""
    assert "nothing here trades" in _page(_desk())


# --- watch rows: on the page, but never as a suggestion -------------------------------------------
#
# A blank page when the gate is shut reads as "nothing to see" on exactly the run where something
# was wrong enough to shut it. So the watchlist gets research rows. The risk this creates is the
# repo's oldest one — a list of names on a money surface being read as a list to buy — so the rows
# carry no quantity, no rupee figure, and a word saying what they are.
def test_a_watch_row_is_never_shown_as_a_position_or_a_basket() -> None:
    desk = _desk(positions={}, prices={}, cost_basis={}, watchlist=["INFY.NS"])
    row = next(r for r in desk.rows if r.ticker == "INFY.NS")
    assert row.watching is True
    assert row.held is False and row.proposed is False
    assert row.quantity == 0
    assert row.value is None and row.unrealised is None

    page = _page(desk)
    assert "watching" in page
    assert "it is not a suggestion" in page


def test_a_proposed_name_is_not_a_watch_row() -> None:
    desk = _desk(positions={}, prices={}, cost_basis={}, proposal=["INFY.NS"])
    row = next(r for r in desk.rows if r.ticker == "INFY.NS")
    assert row.proposed is True and row.watching is False
    assert "in basket" in _page(desk)


def test_a_held_name_is_not_a_watch_row_even_when_also_on_the_watchlist() -> None:
    desk = _desk(watchlist=["VBL.NS"])
    assert _row_of(desk, "VBL.NS").watching is False
    assert _row_of(desk, "VBL.NS").held is True


def test_the_page_points_at_the_basket_as_the_only_proposal() -> None:
    """One place proposes. The desk explains, it does not recommend."""
    page = _page(_desk(watchlist=["INFY.NS"]))
    assert "The only thing this system ever proposes" in page


def _row_of(desk, ticker: str):
    return next(r for r in desk.rows if r.ticker == ticker)
