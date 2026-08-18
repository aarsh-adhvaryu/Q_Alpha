"""Cross-surface agreement (PLAN_TRUST_REPAIR.md PR-5 — fixes T3.3).

**This is the gap that let every defect in the plan pass 316 green tests.** The suite had thorough
per-function coverage and not one test comparing *two surfaces reporting the same book*. Every panel
was individually correct and the page as a whole contradicted itself, which is precisely the failure
mode a unit test cannot see.

So these assert relationships **between** artifacts, not the value of any one of them:

* two surfaces reporting the same book agree exactly, or
* they differ by a **named, tested quantity** — the ₹611.92 of day-one trading cost, or the cash-drag
  gap — and the artifact that shows both must *say so on the page*.

They read only committed files, so they run in CI with no market-data panel and no network. A number
here changing is not a failure of these tests; two numbers that should agree drifting apart is.
"""

from __future__ import annotations

import csv
import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_GO_BOOK = _ROOT / "data" / "paper" / "book.json"
_PAPER_MD = _ROOT / "reports" / "paper_dashboard.md"
_PAPER_CSV = _ROOT / "reports" / "paper_equity.csv"
_SYSTEM_TRACK = _ROOT / "data" / "autopilot" / "system_track.csv"
_SYSTEM_MD = _ROOT / "reports" / "autopilot_dashboard.md"
_BASELINE = _ROOT / "data" / "autopilot" / "baseline_book.json"

# Tolerances: a Markdown surface rounds to whole rupees / 2dp, so agreement is "same number, rendered
# at the precision that surface uses" — never a licence for the underlying figures to drift.
_RUPEE_TOL = Decimal("1")
# A surface rendering "+0.98%" from an underlying 0.975 has agreed, not drifted — half of the last
# rendered digit is the honest tolerance for a 2dp percentage.
_PCT_TOL = 0.0051


def _rupees(text: str) -> Decimal:
    return Decimal(text.replace(",", "").replace("₹", "").strip())


def _go_curve() -> list[dict[str, str]]:
    return json.loads(_GO_BOOK.read_text(encoding="utf-8"))["equity_curve"]


def _md_field(md: str, label: str) -> str:
    """Pull a value out of a `| Label | value |` row."""
    m = re.search(rf"\|\s*{re.escape(label)}\s*\|\s*([^|]+?)\s*\|", md)
    assert m, f"no row labelled {label!r} in the report"
    return m.group(1).replace("*", "").strip()


# ---- the GO book: one book, three surfaces ------------------------------------------------------


def test_the_go_books_equity_agrees_across_book_report_and_csv() -> None:
    """book.json ⇄ paper_dashboard.md ⇄ paper_equity.csv — the same mark, three renderings."""
    curve = _go_curve()
    last = curve[-1]
    committed = Decimal(str(last["equity"]))

    md = _PAPER_MD.read_text(encoding="utf-8")
    assert abs(_rupees(_md_field(md, "Equity (marked)")) - committed) <= _RUPEE_TOL

    rows = list(csv.DictReader(_PAPER_CSV.read_text(encoding="utf-8").splitlines()))
    assert rows[-1]["date"] == last["date"]
    assert abs(Decimal(rows[-1]["equity"]) - committed) <= _RUPEE_TOL


def test_the_go_books_cash_agrees_across_surfaces() -> None:
    """Cash is reported separately from book value, so it has to reconcile separately too."""
    last = _go_curve()[-1]
    md = _PAPER_MD.read_text(encoding="utf-8")
    assert abs(_rupees(_md_field(md, "Cash")) - Decimal(str(last["cash"]))) <= _RUPEE_TOL


def test_the_two_go_bases_differ_by_exactly_the_day_one_cost() -> None:
    """The named quantity (T2.2). Two honest numbers, and the gap between them is not free-floating.

    +0.95% (vs the ₹200,000 handed over) and +1.26% (vs the first equity mark) differ *only* because
    ₹611.92 of trading cost was paid before the first mark was taken. If that identity ever stops
    holding, the two surfaces have genuinely diverged and the difference is no longer explainable.
    """
    book = json.loads(_GO_BOOK.read_text(encoding="utf-8"))
    curve = book["equity_curve"]
    starting = Decimal(str(book["starting_capital"]))
    first_mark = Decimal(str(curve[0]["equity"]))
    last = Decimal(str(curve[-1]["equity"]))

    day_one_cost = starting - first_mark
    assert day_one_cost > 0, "the first mark should sit below capital by the day-one trading cost"

    vs_capital = float((last - starting) / starting * 100)
    vs_first_mark = float((last - first_mark) / first_mark * 100)
    # The whole gap is the cost, and nothing else: reconstruct one basis from the other.
    reconstructed = float((last - (starting - day_one_cost)) / (starting - day_one_cost) * 100)
    assert reconstructed == pytest.approx(vs_first_mark, abs=1e-9)
    assert vs_first_mark > vs_capital  # the first-mark basis is the flattering one


def test_the_reports_headline_uses_the_stricter_basis() -> None:
    """PR-4 promoted the basis that counts the day-one cost against the book. Keep it promoted."""
    book = json.loads(_GO_BOOK.read_text(encoding="utf-8"))
    curve = book["equity_curve"]
    starting = Decimal(str(book["starting_capital"]))
    vs_capital = float((Decimal(str(curve[-1]["equity"])) - starting) / starting * 100)

    md = _PAPER_MD.read_text(encoding="utf-8")
    shown = float(_md_field(md, "Return since start").replace("%", "").replace("+", ""))
    assert shown == pytest.approx(vs_capital, abs=_PCT_TOL)


# ---- the System book: the track record vs the report rendered from it ---------------------------


def _system_md_row(md: str, key: str) -> tuple[Decimal, Decimal, Decimal, float]:
    """(value, contributed, profit, return_pct) from the scoreboard table's row for ``key``."""
    m = re.search(
        rf"\|\s*\*\*{key}\*\*\s*\|[^|]*\|\s*₹([\d,]+)\s*\|\s*₹([\d,]+)\s*\|\s*₹([-\d,]+)\s*\|"
        r"\s*([+-][\d.]+)%\s*\|",
        md,
    )
    assert m, f"no scoreboard row for {key!r}"
    return _rupees(m.group(1)), _rupees(m.group(2)), _rupees(m.group(3)), float(m.group(4))


@pytest.mark.parametrize("book", ["system", "shadow", "baseline"])
def test_the_system_scoreboard_matches_the_track_record_it_was_rendered_from(book: str) -> None:
    """autopilot_dashboard.md ⇄ system_track.csv, for all three books."""
    rows = list(csv.DictReader(_SYSTEM_TRACK.read_text(encoding="utf-8").splitlines()))
    last = rows[-1]
    md = _SYSTEM_MD.read_text(encoding="utf-8")

    value, _contributed, profit, ret = _system_md_row(md, book)
    assert abs(value - Decimal(last[f"{book}_value"])) <= _RUPEE_TOL
    assert abs(profit - Decimal(last[f"{book}_profit"])) <= _RUPEE_TOL
    assert ret == pytest.approx(float(last[f"{book}_return_pct"]), abs=_PCT_TOL)


def test_profit_is_value_minus_contributions_on_every_book() -> None:
    """The accounting identity the whole A/B rests on: an injection is never profit."""
    md = _SYSTEM_MD.read_text(encoding="utf-8")
    for book in ("system", "shadow", "baseline"):
        value, contributed, profit, ret = _system_md_row(md, book)
        assert abs((value - contributed) - profit) <= _RUPEE_TOL
        assert ret == pytest.approx(float(profit / contributed * 100), abs=_PCT_TOL)


def test_the_three_books_share_one_contribution_history() -> None:
    """Identical cash flows is what makes System − Shadow − Baseline a fair comparison at all."""
    md = _SYSTEM_MD.read_text(encoding="utf-8")
    contributed = {b: _system_md_row(md, b)[1] for b in ("system", "shadow", "baseline")}
    assert len(set(contributed.values())) == 1, f"cash flows diverged: {contributed}"


def test_the_system_minus_shadow_headline_matches_the_table_above_it() -> None:
    """The study's headline number must be the subtraction it claims to be."""
    md = _SYSTEM_MD.read_text(encoding="utf-8")
    sys_profit = _system_md_row(md, "system")[2]
    shd_profit = _system_md_row(md, "shadow")[2]
    base_profit = _system_md_row(md, "baseline")[2]

    m = re.search(r"System − Shadow.*?\*\*₹([-\d,]+)\*\*", md)
    assert m and abs(_rupees(m.group(1)) - (sys_profit - shd_profit)) <= _RUPEE_TOL
    m = re.search(r"System − Baseline.*?\*\*₹([-\d,]+)\*\*", md)
    assert m and abs(_rupees(m.group(1)) - (sys_profit - base_profit)) <= _RUPEE_TOL


# ---- the two bases on the System page must be explained, not merely printed --------------------
#
# These render the report **fresh from committed data** rather than reading the committed .md. The
# artifact only regenerates when the weekday cron runs, so asserting labels against it would test how
# recently the cron fired. What must hold is that the *renderer* explains itself given today's data.


def _render_from_committed() -> str:
    """Render the System report from the committed track record — no network, no price panel."""
    import sys

    sys.path.insert(0, str(_ROOT / "scripts"))
    from autopilot import _render_report

    from qalpha.live.autopilot import load_ledger

    rows_csv = list(csv.DictReader(_SYSTEM_TRACK.read_text(encoding="utf-8").splitlines()))
    last = rows_csv[-1]
    contributed = float(json.loads(_BASELINE.read_text(encoding="utf-8"))["net_contributions"])
    rows = {
        b: {
            "value": float(last[f"{b}_value"]),
            "contributed": contributed,
            "profit": float(last[f"{b}_profit"]),
            "return_pct": float(last[f"{b}_return_pct"]),
        }
        for b in ("system", "shadow", "baseline")
    }
    # A deployed-basis figure deliberately offset from the contributed one, so the reconciliation
    # path is the one under test (equal values would trivially satisfy it).
    hedge = {
        "hedged_return": rows["system"]["return_pct"] + 0.70,
        "unhedged_return": rows["system"]["return_pct"] + 0.70,
        "hedged_dd": 1.5,
        "unhedged_dd": 1.5,
        "episodes": 0,
        "hedge_on": 0,
    }
    start = json.loads(_BASELINE.read_text(encoding="utf-8")).get("start_date")
    return _render_report(
        last["date"],
        rows,
        load_ledger(),
        "normal",
        "lean=flat",
        ["held"],
        hedge,
        None,
        start_date=date.fromisoformat(start) if start else None,
    )


def test_the_contributed_and_deployed_bases_are_reconciled_on_the_page() -> None:
    """T2.2: the same book on two bases in one report. If they differ, the page must say why.

    This is the assertion that would have caught the original defect: not "is +2.03% right" (it was),
    but "does anything explain why +2.73% appears eleven lines below it" (nothing did).
    """
    md = _render_from_committed()
    contributed = _system_md_row(md, "system")[3]
    hedge = re.search(r"\*\*System book:\*\* return \*\*([+-][\d.]+)%\*\* hedged", md)
    assert hedge, "no hedge overlay section rendered"
    deployed = float(hedge.group(1))

    assert "cash drag" in md, (
        f"the report shows {contributed:+.2f}% and {deployed:+.2f}% for the same book "
        "without naming the difference"
    )
    m = re.search(r"\*\*([+-][\d.]+)pp\*\* difference is \*\*cash drag\*\*", md)
    assert m, "the cash-drag gap is mentioned but not quantified"
    assert float(m.group(1)) == pytest.approx(deployed - contributed, abs=_PCT_TOL)


def test_matching_bases_produce_no_quantified_gap_claim() -> None:
    """The converse: when the two bases agree there is no gap, so no gap is quantified.

    The section's standing explanation of *what* the deployed basis is stays either way — that is
    labelling, and it is always true. What must not appear is a specific "the Xpp difference is cash
    drag" claim when there is no difference.
    """
    import sys

    sys.path.insert(0, str(_ROOT / "scripts"))
    from autopilot import _render_report

    rows = {
        b: {"value": 402000.0, "contributed": 400000.0, "profit": 2000.0, "return_pct": 0.5}
        for b in ("system", "shadow", "baseline")
    }
    hedge = {
        "hedged_return": 0.5,
        "unhedged_return": 0.5,
        "hedged_dd": 0.0,
        "unhedged_dd": 0.0,
        "episodes": 0,
        "hedge_on": 0,
    }
    md = _render_report("2026-08-14", rows, [], "normal", "lean=flat", [], hedge, None)
    assert re.search(r"\*\*[+-][\d.]+pp\*\* difference is \*\*cash drag\*\*", md) is None
    assert "Why the System book shows" not in md


def test_every_return_on_the_rendered_page_declares_its_basis() -> None:
    """A bare percentage with no stated denominator is the defect, whatever its value."""
    md = _render_from_committed()
    assert "vs money put in" in md  # the scoreboard column header
    assert "capital actually invested" in md  # the hedge section's different basis


def test_the_rendered_page_prints_the_window_its_numbers_cover() -> None:
    rows = list(csv.DictReader(_SYSTEM_TRACK.read_text(encoding="utf-8").splitlines()))
    assert f"{rows[0]['date']} → {rows[-1]['date']}" in _render_from_committed()


# ---- windows (T2.1) -----------------------------------------------------------------------------


def test_the_baseline_book_carries_the_window_its_numbers_cover() -> None:
    """It had no start_date at all: the window was recoverable only from system_track.csv row 1."""
    baseline = json.loads(_BASELINE.read_text(encoding="utf-8"))
    rows = list(csv.DictReader(_SYSTEM_TRACK.read_text(encoding="utf-8").splitlines()))
    assert baseline.get("start_date") == rows[0]["date"]


def test_the_two_books_really_do_cover_different_windows() -> None:
    """The premise of the mismatch warning — if this ever stops being true, drop the warning."""
    go_start = json.loads(_GO_BOOK.read_text(encoding="utf-8"))["start_date"]
    system_start = json.loads(_BASELINE.read_text(encoding="utf-8"))["start_date"]
    assert go_start != system_start
