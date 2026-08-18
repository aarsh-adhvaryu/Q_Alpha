"""Labelled return measurement (PLAN_TRUST_REPAIR.md PR-4 — fixes T2.1, T2.2).

The audit found eight return numbers on four bases over two windows, unlabelled, on one screen. None
was arithmetically wrong; the reader simply could not tell why they disagreed. These tests pin the
vocabulary that makes them readable — a number must arrive with its basis and its window, and the two
cases that actually confused the user (one series over two windows; one book on two bases) must
produce an explanation rather than a contradiction.
"""

from __future__ import annotations

from datetime import date

from qalpha.live.measures import (
    BASES,
    ReturnMeasure,
    cash_drag_note,
    measures_table,
    window_mismatch_note,
)


def test_a_measure_renders_its_basis_and_window() -> None:
    m = ReturnMeasure(
        "System book",
        2.034,
        "contributed",
        date(2026, 7, 10),
        date(2026, 8, 14),
        denominator="₹400,000",
    )
    out = m.render()
    assert "+2.03%" in out
    assert BASES["contributed"] in out  # "money put in", not the bare key
    assert "₹400,000" in out
    assert "2026-07-10 → 2026-08-14" in out


def test_a_measure_without_a_window_still_states_its_basis() -> None:
    """Degrade to less information, never to an unlabelled number."""
    m = ReturnMeasure("Book", 1.0, "starting_capital")
    assert BASES["starting_capital"] in m.render()
    assert m.window_text() == ""


def test_the_cash_drag_gap_is_named_not_left_as_a_contradiction() -> None:
    """The real case: +2.03% and +2.73% for one book, 0.70pp apart, both correct."""
    contributed = ReturnMeasure("System", 2.034, "contributed")
    deployed = ReturnMeasure("System", 2.73, "deployed")
    note = cash_drag_note(contributed, deployed)
    assert "cash drag" in note
    assert "+0.70pp" in note
    assert "Both are correct" in note


def test_no_cash_drag_claimed_when_the_bases_agree() -> None:
    a = ReturnMeasure("System", 2.0, "contributed")
    b = ReturnMeasure("System", 2.0, "deployed")
    assert "no cash drag" in cash_drag_note(a, b)


def test_differing_windows_are_flagged_when_numbers_sit_side_by_side() -> None:
    """+0.98% and +3.92% were the same NIFTYBEES series 28 days apart, shown as two baselines."""
    note = window_mismatch_note(
        [
            ReturnMeasure(
                "System baseline", 0.98, "contributed", date(2026, 7, 10), date(2026, 8, 14)
            ),
            ReturnMeasure(
                "Core book", 3.92, "starting_capital", date(2026, 6, 12), date(2026, 8, 14)
            ),
        ]
    )
    assert "different windows" in note
    assert "2026-07-10" in note and "2026-06-12" in note


def test_no_window_warning_when_the_windows_match() -> None:
    same = date(2026, 7, 10)
    assert (
        window_mismatch_note(
            [
                ReturnMeasure("A", 1.0, "contributed", same, date(2026, 8, 14)),
                ReturnMeasure("B", 2.0, "contributed", same, date(2026, 8, 14)),
            ]
        )
        == ""
    )


def test_measures_table_lists_every_basis_with_its_window() -> None:
    table = measures_table(
        [
            ReturnMeasure(
                "Headline", 0.95, "starting_capital", date(2026, 6, 12), date(2026, 8, 14)
            ),
            ReturnMeasure(
                "Since first mark", 1.26, "first_mark", date(2026, 6, 12), date(2026, 8, 14)
            ),
        ]
    )
    assert "+0.95%" in table and "+1.26%" in table
    assert BASES["starting_capital"] in table and BASES["first_mark"] in table
    assert table.count("\n") == 3  # header + separator + two rows
    assert measures_table([]) == ""


def test_the_window_warning_survives_a_missing_end_date() -> None:
    """Two live books have starts but no end yet — the sentence must still name both windows.

    Filtering on `end` too produced an empty span list and a dangling "— ." on the real page.
    """
    note = window_mismatch_note(
        [
            ReturnMeasure("The System book above", 0.0, "contributed", date(2026, 7, 10), None),
            ReturnMeasure("This validated core", 0.0, "starting_capital", date(2026, 6, 12), None),
        ]
    )
    assert "from 2026-07-10" in note
    assert "from 2026-06-12" in note
    assert "— ." not in note
