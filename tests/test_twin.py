"""The books: one set of cash flows, four ways of using it.

The properties here are the design, not the arithmetic. Each one closes a specific way a previous
forward run was lost: flows drifting apart between books, a gap read as more than a description,
and a book reporting a lead it only has because the export behind the comparison was short.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from qalpha.accounting.costs import Side
from qalpha.config import Config
from qalpha.live.flows import Flow
from qalpha.live.nav import unitized_nav
from qalpha.live.twin import (
    ALL_BOOKS,
    BASELINE,
    BASELINE_EW,
    REAL,
    SYSTEM,
    BookMark,
    assert_identical_flows,
    baseline_mark,
    compare,
    comparison_markdown,
    mark,
    seed_books,
)


@dataclass(frozen=True)
class _T:
    trade_date: date
    ticker: str
    side: Side
    quantity: Decimal
    price: Decimal


def _trades() -> list[_T]:
    return [
        _T(date(2026, 6, 15), "INFY.NS", Side.BUY, Decimal("5"), Decimal("1136")),
        _T(date(2026, 8, 28), "INFY.NS", Side.BUY, Decimal("15"), Decimal("1140")),
        _T(date(2026, 8, 28), "TCS.NS", Side.BUY, Decimal("10"), Decimal("2340")),
    ]


# ---- the load-bearing invariant -----------------------------------------------------------------


def test_every_book_receives_the_same_rupees_on_the_same_days() -> None:
    """The comparison's entire claim. If flows drift, each book answers a different question."""
    books = seed_books(_trades(), Config())
    assert set(books) == set(ALL_BOOKS)
    reference = [(f.on, f.amount) for f in books[REAL].flows]
    for name in ALL_BOOKS:
        assert [(f.on, f.amount) for f in books[name].flows] == reference
    assert_identical_flows(list(books.values()))  # must not raise


def test_drifted_flows_are_refused_loudly() -> None:
    """A predecessor run was lost to exactly this — silently, because nothing checked."""
    books = seed_books(_trades(), Config())
    books[SYSTEM].flows.append(Flow(on=date(2026, 9, 1), amount=Decimal("50000")))
    with pytest.raises(ValueError, match="same rupees on the same days"):
        assert_identical_flows(list(books.values()))


def test_with_no_ledger_the_flows_come_from_the_tradebook_and_nowhere_else() -> None:
    """There is no SIP schedule (§4c): a calendar injection the real account never got is the flaw.

    The ledger, when imported, replaces this with the dated deposits themselves — the same property,
    on a better source. What is never allowed is money no statement records.
    """
    books = seed_books(_trades(), Config())
    assert [f.on for f in books[SYSTEM].flows] == [date(2026, 6, 15), date(2026, 8, 28)]
    # 2026-08-28 nets the two same-day buys into one flow, as a day's net effect should.
    assert books[SYSTEM].flows[1].amount == Decimal("15") * Decimal("1140") + Decimal(
        "10"
    ) * Decimal("2340")


# ---- a twin's cash is performance; the real account's is not ------------------------------------


def test_an_undeployed_twin_is_charged_for_holding_cash() -> None:
    """Not deploying is a decision. A twin that sits in cash must not look identical to one that
    bought and broke even — unlike the REAL account, whose idle balance is next month's instalment
    and must never count (the +444% defect)."""
    books = seed_books(_trades(), Config())
    twin = books[SYSTEM]
    assert twin.value({}) == twin.net_invested  # all cash, nothing deployed
    assert mark(twin, {}, date(2026, 8, 29)).gain == Decimal("0")


# ---- only one comparison may gate ----------------------------------------------------------------


def _marks(**values: float) -> dict[str, BookMark]:
    out = {}
    for name, gain in values.items():
        out[name] = BookMark(
            name=name,
            as_of=date(2027, 9, 14),
            start=date(2026, 6, 15),
            net_invested=Decimal("100000"),
            value=Decimal("100000") + Decimal(str(gain)),
            rate=None,
        )
    return out


def test_the_comparison_is_the_system_against_the_purchasable_fund() -> None:
    """Three comparisons, and the one that matters leads.

    It used to be eight, one of them flagged as gating. The gate is gone — the verdict it graded
    needed two hundred years of data — and with it the ablations, whose question was harder still.
    What is left is the system against a fund anyone can buy, the do-nothing floor, and what the
    user actually did. None of them authorises anything and the render says so.
    """
    gaps = compare(_marks(SYSTEM=5000, BASELINE_EW=3000, BASELINE=1000, REAL=2000))
    assert [(g.left, g.right) for g in gaps] == [
        (SYSTEM, BASELINE_EW),
        (SYSTEM, BASELINE),
        (SYSTEM, REAL),
    ]


def test_the_baseline_replays_the_same_flows_into_the_index() -> None:
    books = seed_books(_trades(), Config())
    idx = pd.bdate_range("2026-06-01", "2026-09-01")
    series = pd.Series([100.0] * len(idx), index=idx)
    bm = baseline_mark(books[REAL].flows, series, date(2026, 8, 31))
    assert bm is not None
    assert bm.name == BASELINE
    assert bm.net_invested == books[REAL].net_invested
    assert bm.gain == Decimal("0")  # a flat index returns exactly what went in


def test_the_baseline_refuses_rather_than_inventing_a_number() -> None:
    """No index price at or before the first flow → None. An invented baseline is worse than none."""
    idx = pd.bdate_range("2027-01-01", "2027-02-01")
    series = pd.Series([100.0] * len(idx), index=idx)
    assert (
        baseline_mark(seed_books(_trades(), Config())[REAL].flows, series, date(2027, 1, 15))
        is None
    )


def test_the_panel_says_a_gap_is_a_description_and_leads_with_the_fund() -> None:
    marks = _marks(SYSTEM=5000, BASELINE_EW=3000, BASELINE=1000, REAL=2000)
    md = comparison_markdown(marks, compare(marks))
    assert "not evidence of skill" in md
    # Read the gap lines, not the books table above them: REAL heads that table.
    gap_lines = [ln for ln in md.splitlines() if ln.startswith("- ")]
    assert BASELINE_EW in gap_lines[0], "the fund anyone can buy leads the comparison"


def test_relative_wealth_is_unmeasured_without_a_window_never_zero() -> None:
    """No registered window means no NAVs. The gap must say so, not print +0.00%."""
    gap = compare(_marks(SYSTEM=5000, BASELINE_EW=3000))[0]
    assert gap.log_rel_wealth is None
    assert "not measurable yet" in gap.render() and "0.00%" not in gap.render()
    with_navs = compare(_marks(SYSTEM=5000, BASELINE_EW=3000), navs={SYSTEM: 1.1, BASELINE_EW: 1.0})
    assert with_navs[0].log_rel_wealth == pytest.approx(math.log(1.1))


def test_the_relative_wealth_statistic_survives_a_contribution() -> None:
    """The property the old test claimed and did not prove.

    ``log_rel_wealth`` was once ``ln(V_left / V_right)`` on raw book values, described as
    "scale-free". It is not. Identical contributions do not cancel in a ratio, they dilute it::

        ln(110 / 100)             = 0.0953
        ln((110+100) / (100+100)) = 0.0488

    Nothing happened in the market and the measured lead halved — so a monthly SIP would have walked
    the statistic toward zero all year. The old test multiplied two finished marks by ten and passed,
    because that proves invariance under *multiplicative* scaling, which is not what a deposit does.

    Both legs are now unitized NAVs, which are invariant to contributions by construction. This test
    asserts the real property and, in its first half, demonstrates the failure it replaces.
    """
    # The defect, stated as arithmetic: raw values are NOT invariant to a shared deposit.
    assert math.log(110 / 100) == pytest.approx(0.09531, abs=1e-5)
    assert math.log(210 / 200) == pytest.approx(0.04879, abs=1e-5)

    # A NAV is unmoved by money arriving: deposits buy units, they do not move the price per unit.
    idx = pd.bdate_range("2026-09-01", periods=6)
    flat_prices = pd.Series(1.0, index=idx)
    no_flow = unitized_nav(flat_prices * 100.0, [])
    # Same flat market, but ₹100 lands on day 3 — the book jumps, the NAV must not.
    with_flow_values = pd.Series([100.0, 100.0, 200.0, 200.0, 200.0, 200.0], index=idx)
    with_flow = unitized_nav(with_flow_values, [(idx[2].date(), 100.0)])
    assert with_flow.iloc[-1] == pytest.approx(no_flow.iloc[-1])
    assert with_flow.iloc[-1] == pytest.approx(with_flow.iloc[0]), "a deposit is not a return"


def test_an_unregistered_start_means_the_book_never_decides() -> None:
    """``None`` is not a date in the past. If it ever compared as "already begun", a book with no
    registered window would start deciding on its own."""
    from qalpha.live.twin import is_autonomous, navs_from_history

    for day in (date(2026, 9, 14), date(2026, 9, 15), date(2030, 1, 1)):
        assert is_autonomous(day, start=None) is False
    rows = [{"as_of": "2026-09-15", "books": {"SYSTEM": {"value": "100", "net_invested": "100"}}}]
    assert navs_from_history(rows, start=None) == {}, "no window: unmeasured, never a NAV of 1.0"


def test_the_start_in_the_code_is_the_start_in_the_registration() -> None:
    """A start date is a registered fact. The two must not be able to drift apart."""
    import re

    from qalpha.live.twin import EVALUATION_START

    recorded = Path(__file__).resolve().parents[1] / "reports/PREREGISTRATION_AI_PM2.md"
    rows = re.findall(r"^\| Start \| \*\*([^*]+)\*\*", recorded.read_text(encoding="utf-8"), re.M)
    assert len(rows) == 1, "the registration must state exactly one start"
    expected = None if rows[0] == "none" else rows[0]
    assert (EVALUATION_START.isoformat() if EVALUATION_START else None) == expected, (
        "the registration must record the start date the code runs on"
    )


def test_a_start_holds_across_a_holiday() -> None:
    """A start on Ganesh Chaturthi. A book is stepped on the day its prices come from, so the first
    review lands on the first session on or after it — not on Friday's close twice."""
    from qalpha.live import calendar as nse
    from qalpha.live.twin import is_autonomous

    start = date(2026, 9, 14)
    assert nse.closure_reason(start), "this test is about a start on a closed day"
    assert is_autonomous(date(2026, 9, 11), start=start) is False, "Friday is before the window"
    assert is_autonomous(date(2026, 9, 15), start=start) is True, "the first session after decides"


def test_the_daily_caller_asks_the_registered_start() -> None:
    """Rule 4: test the caller. `scripts/twin.py` decides mirror-or-choose every evening; if it held
    its own copy of the date, changing it here would change nothing there."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import twin as runner_script

    from qalpha.live import twin as twin_module

    assert runner_script.is_autonomous is twin_module.is_autonomous
    for day in (date(2026, 9, 11), date(2026, 9, 15)):
        assert runner_script.is_autonomous(day) == twin_module.is_autonomous(day)


def test_the_bar_is_the_purchasable_alternative_not_the_index() -> None:
    """Phase 4 moved this bar, and the move is the point.

    76% of the screen's gap over NIFTYBEES is the equal-weight premium — and that premium is
    purchasable for ~0.41%/yr. Gating against the cap-weighted index would let the system claim
    credit for something it did not create; a system that cannot beat the best cheap passive
    alternative should not run. See reports/PHASE4_BACKTEST.md.
    """
    gaps = compare(_marks(SYSTEM=5000, BASELINE_EW=3000, BASELINE=1000))
    assert gaps[0].right == BASELINE_EW, "the fund anyone can buy leads the comparison"
    # NIFTYBEES is still reported — as a floor, never as the bar.
    assert any(g.right == BASELINE for g in gaps)


def test_the_ew_fund_baseline_charges_its_fee() -> None:
    """The premium is only worth what it is worth AFTER the cost of buying it."""
    from qalpha.live.twin import EW_FUND_FEE, ew_fund_mark

    flows = [Flow(on=date(2020, 1, 1), amount=Decimal("100000"))]
    idx = pd.bdate_range("2019-12-01", "2026-01-01")
    flat = pd.Series([100.0] * len(idx), index=idx)
    m = ew_fund_mark(flows, flat, date(2026, 1, 1))
    assert m is not None
    # A flat index returns the money; the fee must still bite, so the mark is BELOW what went in.
    assert m.value < m.net_invested
    assert EW_FUND_FEE > 0


def test_new_trades_are_credited_to_every_book() -> None:
    """The twin's flows must not freeze at seed time while REAL is replayed fresh each run.

    Otherwise the user's next purchase lands in REAL and in none of the books it is compared
    against, and the identical-flow invariant breaks **silently, on the next SIP**.
    """
    from qalpha.live.twin import sync_flows

    books = seed_books(_trades(), Config())
    before = books[SYSTEM].net_invested
    later = [*_trades(), _T(date(2026, 9, 15), "TCS.NS", Side.BUY, Decimal("5"), Decimal("2400"))]

    deltas = sync_flows(books, later)
    assert len(deltas) == 1
    assert deltas[0].amount == Decimal("12000")
    for name in ALL_BOOKS:
        assert books[name].net_invested == before + Decimal("12000"), name
    assert_identical_flows(list(books.values()))


def test_an_amended_day_is_credited_as_a_delta_not_missed() -> None:
    """A new trade on a day already seen AMENDS that day's flow — a length check would miss it."""
    from qalpha.live.twin import sync_flows

    books = seed_books(_trades(), Config())
    same_day = [
        *_trades(),
        _T(date(2026, 8, 28), "WIPRO.NS", Side.BUY, Decimal("10"), Decimal("180")),
    ]

    deltas = sync_flows(books, same_day)
    assert len(deltas) == 1, "same number of flow-days, but the amount changed"
    assert deltas[0].on == date(2026, 8, 28)
    assert deltas[0].amount == Decimal("1800")
    assert len(books[SYSTEM].flows) == 2  # still two days, one of them larger


def test_no_new_trades_credits_nothing() -> None:
    from qalpha.live.twin import sync_flows

    books = seed_books(_trades(), Config())
    assert sync_flows(books, _trades()) == []


def test_an_empty_tradebook_read_must_not_be_treated_as_an_empty_account() -> None:
    """The silent failure this guards: a failed tradebook read makes REAL replay to ₹0.

    With flows stored per book, REAL would show ₹0 against ₹3,04,144 of net money in — a −100% line,
    with every twin appearing to beat it by three lakh, written to the dashboard as a verdict. The
    runner must refuse to write rather than publish that.
    """
    import inspect
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import twin as runner_script

    src = inspect.getsource(runner_script.cmd_daily)
    assert "if not trades and books[REAL].flows:" in src
    assert "ABORT" in src
    # And it must not write a report on that path. THE PROPERTY, NOT THE LINE: this used to name
    # `REPORT.write_text`, and broke the day that writer became atomic — pinning the spelling of a
    # call rather than the fact that the abort comes first.
    abort_at = src.index("ABORT")
    write_at = min(
        src.index(name) for name in ("REPORT", "MARKS", "DECISIONS_LOG") if name in src[abort_at:]
    )
    assert abort_at < write_at, "the abort must precede any write"
    assert "return ABORTED" in src[abort_at : abort_at + 900], "abort must return before writing"


def test_an_export_that_starts_after_trading_is_known_to_have_begun_is_refused() -> None:
    from qalpha.live.twin import partial_export_reason

    reason = partial_export_reason(_trades()[1:], date(2026, 6, 15))
    assert reason is not None
    assert "2026-06-15" in reason and "2026-08-28" in reason
    assert "data/tradebooks/" in reason


def test_an_export_reaching_back_to_the_watermark_is_accepted() -> None:
    from qalpha.live.twin import partial_export_reason

    assert partial_export_reason(_trades(), date(2026, 6, 15)) is None
    # Earlier than the first flow is fine too — extra history is not a gap.
    assert partial_export_reason(_trades(), date(2026, 7, 1)) is None


def test_no_flows_and_no_trades_are_not_this_guard_s_business() -> None:
    """The empty read has its own refusal, with its own message. Two guards, two sentences."""
    from qalpha.live.twin import partial_export_reason

    assert partial_export_reason([], date(2026, 6, 15)) is None
    assert partial_export_reason(_trades(), None) is None


def test_the_twin_reads_the_same_folder_the_page_does(tmp_path, monkeypatch) -> None:
    """The integration, not the function. Both readers were correct and read different places."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import twin as twin_script

    from qalpha.live import tradebook

    (tmp_path / "export.csv").write_text(
        "symbol,trade_date,trade_type,quantity,price,trade_id\nINFY,2026-06-15,buy,5,1136,11\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(twin_script, "EXPORT_DIR", tmp_path)
    assert twin_script.EXPORT_DIR is not tradebook.EXPORT_DIR  # patched for this test only
    trades, notes = twin_script._tradebook()
    assert [t.ticker for t in trades] == ["INFY.NS"]  # type: ignore[attr-defined]
    assert notes == []


def test_the_abort_tells_the_user_about_the_folder_not_about_a_job() -> None:
    """The thing to actually go and do is drop a Console export in a folder — say that."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import inspect

    import twin as twin_script

    source = inspect.getsource(twin_script.cmd_daily)
    assert "data/tradebooks/" in source


def test_an_annual_rate_is_not_extrapolated_from_a_few_months() -> None:
    """Three months of -2.7% printed as -53.0%/yr on the page. Under a year, the rate is withheld."""
    young = BookMark(
        SYSTEM, date(2026, 9, 13), date(2026, 6, 15), Decimal("100"), Decimal("97"), -0.53
    )
    old = BookMark(
        SYSTEM, date(2027, 9, 13), date(2026, 6, 15), Decimal("100"), Decimal("97"), -0.02
    )
    assert "-53.0%/yr" not in comparison_markdown({SYSTEM: young}, [])
    assert "under a year" in comparison_markdown({SYSTEM: young}, [])
    assert "-2.0%/yr" in comparison_markdown({SYSTEM: old}, [])
