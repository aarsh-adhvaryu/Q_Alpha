"""The digital twin: five books, one set of cash flows (PLAN_REDESIGN.md §1).

The properties here are the design, not the arithmetic. Each one closes a specific way a previous
forward run was lost: flows drifting apart between books, a gap being read before it could mean
anything, and an ablation being allowed to authorise something.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from qalpha.accounting.costs import Side
from qalpha.config import Config
from qalpha.live.track_record import Flow
from qalpha.live.twin import (
    ALL_BOOKS,
    BASELINE,
    BASELINE_EW,
    GATING_PAIR,
    REAL,
    TWIN_FULL,
    TWIN_NO_AI,
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
    books[TWIN_NO_AI].flows.append(Flow(on=date(2026, 9, 1), amount=Decimal("50000")))
    with pytest.raises(ValueError, match="same rupees on the same days"):
        assert_identical_flows(list(books.values()))


def test_the_flows_come_from_the_tradebook_and_nowhere_else() -> None:
    """There is no SIP schedule (§4c): a calendar injection the real account never got is the flaw."""
    books = seed_books(_trades(), Config())
    assert [f.on for f in books[TWIN_FULL].flows] == [date(2026, 6, 15), date(2026, 8, 28)]
    # 2026-08-28 nets the two same-day buys into one flow, as a day's net effect should.
    assert books[TWIN_FULL].flows[1].amount == Decimal("15") * Decimal("1140") + Decimal(
        "10"
    ) * Decimal("2340")


# ---- a twin's cash is performance; the real account's is not ------------------------------------


def test_an_undeployed_twin_is_charged_for_holding_cash() -> None:
    """Not deploying is a decision. A twin that sits in cash must not look identical to one that
    bought and broke even — unlike the REAL account, whose idle balance is next month's instalment
    and must never count (the +444% defect)."""
    books = seed_books(_trades(), Config())
    twin = books[TWIN_FULL]
    assert twin.value({}) == twin.net_invested  # all cash, nothing deployed
    assert mark(twin, {}, date(2026, 8, 29)).gain == Decimal("0")


# ---- only one comparison may gate ----------------------------------------------------------------


def _marks(**values: float) -> dict[str, BookMark]:
    out = {}
    for name, gain in values.items():
        out[name] = BookMark(
            name=name,
            as_of=date(2027, 9, 1),
            start=date(2026, 6, 15),
            net_invested=Decimal("100000"),
            value=Decimal("100000") + Decimal(str(gain)),
            rate=None,
        )
    return out


def test_exactly_one_comparison_gates() -> None:
    """Five comparisons at 95% throw a false positive about one run in four."""
    gaps = compare(
        _marks(TWIN_FULL=5000, BASELINE_EW=3000, BASELINE=1000, TWIN_NO_AI=4000, REAL=2000)
    )
    gating = [g for g in gaps if g.gates]
    assert len(gating) == 1
    assert (gating[0].left, gating[0].right) == GATING_PAIR
    assert all(not g.gates for g in gaps if (g.left, g.right) != GATING_PAIR)


def test_a_gap_is_unreadable_before_twelve_months() -> None:
    """The bar that voided forward run 1: too short is not a small result, it is no result."""
    marks = _marks(TWIN_FULL=50000, BASELINE=0)
    marks[TWIN_FULL] = BookMark(
        TWIN_FULL, date(2026, 9, 1), date(2026, 6, 15), Decimal("100000"), Decimal("150000"), None
    )
    gap = compare(marks, noise_floor=Decimal("1000"))[0]
    assert not gap.readable
    assert "No verdict before" in gap.render()


def test_a_gap_inside_the_noise_floor_is_not_a_result() -> None:
    gap = compare(_marks(TWIN_FULL=1200, BASELINE=1000), noise_floor=Decimal("5000"))[0]
    assert not gap.readable
    assert "noise floor" in gap.render()


def test_a_gap_is_readable_only_when_old_enough_and_big_enough() -> None:
    gap = compare(_marks(TWIN_FULL=90000, BASELINE=1000), noise_floor=Decimal("5000"))[0]
    assert gap.readable
    assert "clearing" in gap.render()


def test_without_a_noise_floor_nothing_is_readable() -> None:
    """Phase 4 has not run. Until it has, there is no bar — and no bar means no verdict."""
    gap = compare(_marks(TWIN_FULL=90000, BASELINE=1000))[0]
    assert gap.noise_floor is None
    assert not gap.readable
    assert "does not exist" in gap.render()


# ---- the baseline ---------------------------------------------------------------------------------


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


def test_the_panel_separates_the_gate_from_the_diagnostics() -> None:
    marks = _marks(TWIN_FULL=5000, BASELINE_EW=3000, BASELINE=1000, TWIN_NO_AI=4000, REAL=2000)
    md = comparison_markdown(marks, compare(marks, noise_floor=Decimal("100")))
    assert "The gate" in md
    assert "never gating" in md
    assert md.index("The gate") < md.index("Diagnostics")  # the gate leads


def test_the_noise_floor_is_a_measured_number_not_a_guess() -> None:
    """GO criterion 3's bar comes from 60 no-skill draws, not from judgement.

    Forward run 1 was voided because no bar existed: its System − Shadow of ₹1,541 sat under ₹1,964
    of one day's rounding noise, discovered only afterwards. This is that number, computed in
    advance — reports/PHASE4_BACKTEST.md.
    """
    from qalpha.live.twin import BACKTEST_NOISE_FLOOR

    assert Decimal("8362315") == BACKTEST_NOISE_FLOOR


def test_a_gap_smaller_than_the_measured_floor_is_not_a_result() -> None:
    """The screen's own selection edge (₹25.3L) is INSIDE this floor — which is the point.

    The floor is set by the equal-weight premium a random basket earns, so a gap has to beat luck at
    that scale, not merely beat the index.
    """
    from qalpha.live.twin import BACKTEST_NOISE_FLOOR

    marks = _marks(TWIN_FULL=2_530_813, BASELINE=0)
    marks[TWIN_FULL] = BookMark(
        TWIN_FULL,
        date(2028, 9, 1),  # comfortably past the 12-month bar, so only size is being tested
        date(2026, 6, 15),
        Decimal("100000"),
        Decimal("2630813"),
        None,
    )
    gap = compare(marks, noise_floor=BACKTEST_NOISE_FLOOR)[0]
    assert not gap.readable
    assert "noise floor" in gap.render()


def test_the_gate_is_the_purchasable_alternative_not_the_index() -> None:
    """Phase 4 moved this bar, and the move is the point.

    76% of the screen's gap over NIFTYBEES is the equal-weight premium — and that premium is
    purchasable for ~0.41%/yr. Gating against the cap-weighted index would let the system claim
    credit for something it did not create; a system that cannot beat the best cheap passive
    alternative should not run. See reports/PHASE4_BACKTEST.md.
    """
    assert GATING_PAIR == (TWIN_FULL, BASELINE_EW)
    gaps = compare(_marks(TWIN_FULL=5000, BASELINE_EW=3000, BASELINE=1000))
    (gate,) = [g for g in gaps if g.gates]
    assert gate.right == BASELINE_EW
    # NIFTYBEES is still reported — as a floor, never as the bar.
    assert any(g.right == BASELINE and not g.gates for g in gaps)


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
    before = books[TWIN_FULL].net_invested
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
    assert len(books[TWIN_FULL].flows) == 2  # still two days, one of them larger


def test_no_new_trades_credits_nothing() -> None:
    from qalpha.live.twin import sync_flows

    books = seed_books(_trades(), Config())
    assert sync_flows(books, _trades()) == []


def test_an_empty_tradebook_read_must_not_be_treated_as_an_empty_account() -> None:
    """The silent failure this guards: a failed gist read makes REAL replay to ₹0.

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
    # And it must not write a report on that path.
    abort_at = src.index("ABORT")
    write_at = src.index("REPORT.write_text")
    assert abort_at < write_at, "the abort must precede any write"
    assert "return 0" in src[abort_at : abort_at + 600], "abort must return before writing"


def test_holdings_frame_survives_a_book_with_nothing_in_it() -> None:
    """An empty frame has no columns, so sorting by name raises KeyError.

    This took the live dashboard down: `_twin_panel` charts REAL and TWIN_FULL side by side, and a
    book holding nothing — or whose names the deployed panel could not price — crashed the page
    rather than drawing an empty chart.
    """
    from qalpha.live.twin import holdings_frame

    empty = seed_books(_trades(), Config())[TWIN_FULL]
    frame = holdings_frame(empty, {})  # no prices at all
    assert frame.empty
    assert list(frame.columns) == ["Ticker", "Value", "Share %"], "shape must survive"


def test_holdings_frame_skips_names_it_cannot_price() -> None:
    """A holding with no price is omitted, never valued at zero — that would understate the book."""
    from qalpha.live.twin import holdings_frame

    books = seed_books(_trades(), Config())
    book = books[TWIN_FULL]
    book.portfolio.buy(date(2026, 8, 28), "INFY.NS", Decimal("10"), Decimal("1140"))
    book.portfolio.buy(date(2026, 8, 28), "TCS.NS", Decimal("5"), Decimal("2340"))
    frame = holdings_frame(book, {"INFY.NS": Decimal("1140")})  # TCS unpriced
    assert list(frame["Ticker"]) == ["INFY"]
    assert abs(frame["Share %"].sum() - 100.0) < 1e-6, "shares are of what could be priced"
