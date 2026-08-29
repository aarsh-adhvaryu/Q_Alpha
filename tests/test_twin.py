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
    """Four comparisons at 95% throw a false positive about one run in five."""
    gaps = compare(_marks(TWIN_FULL=5000, BASELINE=1000, TWIN_NO_AI=4000, REAL=2000))
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
    marks = _marks(TWIN_FULL=5000, BASELINE=1000, TWIN_NO_AI=4000, REAL=2000)
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
