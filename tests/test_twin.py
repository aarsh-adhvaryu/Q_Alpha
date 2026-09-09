"""The digital twin: five books, one set of cash flows (PLAN_REDESIGN.md §1).

The properties here are the design, not the arithmetic. Each one closes a specific way a previous
forward run was lost: flows drifting apart between books, a gap being read before it could mean
anything, and an ablation being allowed to authorise something.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from qalpha.accounting.costs import Side
from qalpha.config import Config
from qalpha.live.nav import unitized_nav
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
    gap = compare(marks, null_p95=0.01)[0]
    assert not gap.readable
    assert "No verdict before" in gap.render()


def test_a_gap_inside_the_null_band_is_not_a_result() -> None:
    gap = compare(
        _marks(TWIN_FULL=1200, BASELINE=1000),
        null_p95=0.05,
        navs={TWIN_FULL: 1.012, BASELINE: 1.010},
    )[0]
    assert not gap.readable
    assert "null band" in gap.render()


def test_a_gap_is_readable_only_when_old_enough_and_big_enough() -> None:
    gap = compare(
        _marks(TWIN_FULL=90000, BASELINE=1000),
        null_p95=0.05,
        navs={TWIN_FULL: 1.90, BASELINE: 1.01},
    )[0]
    assert gap.readable
    assert "clearing" in gap.render()


def test_without_a_null_nothing_is_readable() -> None:
    """The matched null has not been run. No bar means no verdict — never a bar of zero."""
    gap = compare(_marks(TWIN_FULL=90000, BASELINE=1000), navs={TWIN_FULL: 1.9, BASELINE: 1.0})[0]
    assert gap.null_p95 is None
    assert not gap.readable
    assert "has not been run" in gap.render()


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
    md = comparison_markdown(marks, compare(marks, null_p95=0.001))
    assert "The gate" in md
    assert "never gating" in md
    assert md.index("The gate") < md.index("Diagnostics")  # the gate leads


def test_the_gating_statistic_survives_a_contribution() -> None:
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


def test_the_gate_reads_the_registered_window_not_the_first_flow_ever() -> None:
    """``months`` counted from the earliest flow on file — which predates the experiment.

    The tradebook reaches back to 2026-06-15 (two IPO-era trades). A window opening 2026-09-01 would
    therefore have reported "12 months" around June 2027 — months early, and partly on evidence from
    before anything was registered.
    """
    from qalpha.live.twin import EVALUATION_START, evaluation_months

    assert date(2026, 9, 1) == EVALUATION_START
    assert evaluation_months(date(2026, 8, 31)) == 0, "before the window opens, nothing has elapsed"
    assert evaluation_months(date(2027, 6, 15)) == 9, "the June-2026 flow must not buy extra months"
    assert evaluation_months(date(2027, 9, 1)) == 12


def test_the_null_matches_the_committed_report() -> None:
    """The bar in code and the bar in the record must be the same number.

    The previous version of this test asserted ``NULL_P95_LOG_REL_WEALTH is None`` — a test of a
    *state*, which went red the moment the state legitimately changed and would have gone green
    again if someone deleted the value. This asserts the *property*: whatever the constant says, it
    is what ``scripts/exp_null.py`` actually produced and committed.
    """
    import json
    from pathlib import Path as _Path

    from qalpha.live.twin import NULL_P95_LOG_REL_WEALTH

    report = _Path("reports/NULL_MATCHED.json")
    if not report.exists():  # pragma: no cover - the report ships with the repo
        pytest.skip("null report not present")
    recorded = json.loads(report.read_text())
    if NULL_P95_LOG_REL_WEALTH is None:
        # A withdrawn or ungenerated bar is a valid state: it reads CANNOT ASSESS and blocks.
        return
    assert not recorded.get("withdrawn"), (
        "the constant is set from a report marked withdrawn — a bar that was found not to match "
        "the experiment must never be in force"
    )
    assert abs(NULL_P95_LOG_REL_WEALTH - recorded["p95_abs_log_rel_wealth"]) < 5e-7
    assert recorded["draws"] >= 1000, "the specification requires at least 1,000 draws"


def test_a_withdrawn_null_is_not_in_force() -> None:
    """The invariant that matters: a withdrawn bar and a live constant cannot coexist.

    On 2026-09-06 a value was set and withdrawn hours later, because it was matched to *a*
    specification and not to ``CORE_V1``'s — the null diversified into ~50 of 51 index members
    while ``CORE_V1`` holds a capped basket, making the bar 1.5–2.3× too low. Too low is the
    dangerous direction: it makes noise look like skill.
    """
    import json
    from pathlib import Path as _Path

    from qalpha.live.twin import NULL_P95_LOG_REL_WEALTH

    report = _Path("reports/NULL_MATCHED.json")
    if not report.exists():  # pragma: no cover
        pytest.skip("null report not present")
    if json.loads(report.read_text()).get("withdrawn"):
        assert NULL_P95_LOG_REL_WEALTH is None


def test_the_null_is_a_null_and_not_a_bug() -> None:
    """Random selection must beat the fund about half the time and average about zero.

    The first run of the generator returned mean G = −0.68 with **0 of 20** draws beating the fund,
    because the value series applied the final basket across the whole window. A null where nothing
    ever wins is not a null; it is a bug reporting itself. These are the two numbers that catch it.
    """
    import json
    from pathlib import Path as _Path

    report = _Path("reports/NULL_MATCHED.json")
    if not report.exists():  # pragma: no cover
        pytest.skip("null report not present")
    r = json.loads(report.read_text())
    assert 0.40 <= r["fraction_beating_the_fund"] <= 0.60
    assert abs(r["mean_log_rel_wealth"]) < 0.01


def test_a_missing_null_still_blocks() -> None:
    """``None`` remains CANNOT ASSESS, never a silent bar of zero. Forward run 1 died of this."""
    from qalpha.live.go_gate import CANNOT_ASSESS, Evidence, build_gate

    gate = build_gate(
        Evidence(months_of_flows=12, log_rel_wealth=0.5, null_p95=None, gap_vs_ew_baseline=None),
        as_of=date(2027, 9, 8),
    )
    beats = next(c for c in gate.criteria if "equal-weight fund" in c.name)
    assert beats.verdict == CANNOT_ASSESS


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


def test_the_twin_prices_merge_every_panel_rather_than_taking_the_first() -> None:
    """Live on 2026-09-09: "Your account — what it holds: nothing priced yet", rendered directly
    beneath a table valuing that same book at ₹297,352.

    ``_twin_prices`` returned the FIRST panel that yielded anything, and the watchlist panel does not
    carry every name the real account holds — so ``holdings_frame`` correctly skipped the names it
    could not price, which was all of them, and the chart said nothing was held. One book, two
    answers, one screen. Merging the panels is the fix; the earlier panel still wins on conflict.
    """
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import dashboard_app

    marks = dashboard_app._twin_prices()
    if not marks:
        pytest.skip("no price panels on this host")

    import inspect

    src = inspect.getsource(dashboard_app._twin_prices)
    assert "if out:\n            return out" not in src, (
        "returning the first panel that works is what left the real account's names unpriced"
    )
    # The merged view must be at least as large as either panel alone could give.
    from qalpha.data.ingest import load_parquet

    sizes = []
    for path in (
        "data/historical/prices_watchlist.parquet",
        "data/historical/prices_pit_2026.parquet",
    ):
        try:
            sizes.append(len(load_parquet(path).adj_close.columns))
        except (OSError, ValueError):
            continue
    if sizes:
        assert len(marks) >= max(sizes), (
            f"merged marks ({len(marks)}) smaller than the largest panel ({max(sizes)})"
        )


def test_a_book_younger_than_the_fund_gets_no_gap_column() -> None:
    """A book cannot out- or under-perform over a period it did not exist for.

    Found 2026-09-09 by asking why CORE_V1 was "working". It was not. Its first mark in
    ``history.jsonl`` is 2026-09-07 and every lot it holds is dated that day — it was constituted
    last Monday, while TWIN_FULL had been accumulating since 08-29 and fell ₹10,627 in between. It
    entered the record **already ₹10,293 ahead**, and in the one day both books had been alive they
    diverged by ₹475. The dashboard was rendering that as "The screen ▲ +₹6,109 vs the fund".

    Every book's ``start`` field says 2026-06-15 — that is when the CASH FLOWS begin, not when the
    book existed — so the inception has to be read from the first day the book was actually marked.
    """
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import dashboard_app

    born = dashboard_app._twin_inceptions()
    if not born:
        pytest.skip("no twin history on this host")
    assert "BASELINE_EW" in born
    # The real record: the fund predates CORE_V1, which is the whole point.
    if "CORE_V1" in born:
        assert born["CORE_V1"] >= born["BASELINE_EW"]
    # And inception must never be read off the shared `start` field, which is identical for all.
    assert len(set(born.values())) > 1 or len(born) == 1, (
        "if every book shares an inception the guard is inert — check it is reading first-mark, "
        "not the seeding date every book carries"
    )


def test_inception_is_the_first_marked_day_not_the_first_row() -> None:
    """A book present in a row but carrying no value was not marked, and is not yet alive."""
    import json
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import dashboard_app

    rows = [
        {"as_of": "2026-09-01", "revision": 0, "books": {"A": {}, "B": {"value": "100"}}},
        {"as_of": "2026-09-02", "revision": 0, "books": {"A": {"value": "90"}}},
    ]
    path = Path("data/twin/_inception_probe.jsonl")
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    try:
        old = dashboard_app.TWIN_HISTORY_JSONL
        dashboard_app.TWIN_HISTORY_JSONL = path
        born = dashboard_app._twin_inceptions()
    finally:
        dashboard_app.TWIN_HISTORY_JSONL = old
        path.unlink(missing_ok=True)
    assert born == {"B": "2026-09-01", "A": "2026-09-02"}, (
        "a book listed with no value that day has not been marked and is not alive yet"
    )
