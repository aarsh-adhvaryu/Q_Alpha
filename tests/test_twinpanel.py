"""The record, on the page — the panels that say how this has actually been doing.

The buy screen could only ever tell the user *what to do*. Whether the thing producing that basket
is beating a cheap index fund lived in `reports/twin_dashboard.md`, a file nobody opens.

What these pin is not the layout. It is that **every figure keeps the label of the thing that was
computed** — the two gaps against the fund are in different units, from different start dates, and
today they point in opposite directions — and that nothing here can be read as validation, because
nothing is validated.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from qalpha.live import twinpanel
from qalpha.live.go_gate import Evidence, build_gate
from qalpha.live.track_record import TrackRecord

TODAY = date(2026, 9, 10)

# The shape `twin.append_history` actually writes, taken from the real 2026-09-09 row: CORE_V1 is
# +₹5,389 and G is −0.0023 on the SAME comparison, because the rupee figure runs from the first cash
# flow (2026-06-15, before CORE_V1 existed) and G runs from the registered window.
ROW = {
    "as_of": "2026-09-09",
    "books": {
        "CORE_V1": {
            "value": "301289.98",
            "net_invested": "304144.01",
            "xirr": None,
            "start": "2026-06-15",
        },
        "TWIN_FULL": {
            "value": "291075.78",
            "net_invested": "304144.01",
            "xirr": -0.31,
            "start": "2026-06-15",
        },
    },
    "tracks": {
        "core_v1": {
            "pair": ["CORE_V1", "BASELINE_EW"],
            "rupees": "5389.24",
            "log_rel_wealth": -0.0023064196221094764,
            "months": 0,
            "null_p95": None,
            "authorizes": False,
        }
    },
    "gate": {"verdict": "NOT YET", "pair": None, "authorizes": False},
    "revision": 0,
}


def _history(tmp_path: Path, *rows: dict[str, object]) -> Path:
    path = tmp_path / "history.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def _record(tmp_path: Path, *rows: dict[str, object]) -> twinpanel.TwinRecord:
    record = twinpanel.latest_record(_history(tmp_path, *(rows or (ROW,))), inception={})
    assert record is not None
    return record


# --- the two gaps are two different measurements --------------------------------------------------
def test_both_gap_figures_appear_and_each_carries_its_own_label(tmp_path: Path) -> None:
    """THE POINT OF THE PANEL. A page that showed one of these would be picking the flattering one,
    and a page that showed both unlabelled would look like an arithmetic error."""
    html = twinpanel.tracks_panel(_record(tmp_path))
    assert "₹5,389" in html, "the rupee gap, positive"
    assert "-0.0023" in html, "and G, negative, on the same comparison"
    assert "since the first cash flow" in html
    assert "unitized NAVs" in html
    assert "never as the criterion" in html


def test_a_track_with_no_bar_says_the_bar_was_withdrawn(tmp_path: Path) -> None:
    """`null_p95` is None on every row today. A blank cell would read as zero, which would make
    every gap significant."""
    assert "withdrawn" in twinpanel.tracks_panel(_record(tmp_path))


def test_the_null_note_is_read_from_the_file_rather_than_restated(tmp_path: Path) -> None:
    """The p95 on the page has to be the p95 in the record, or the two drift and only one is true."""
    null = tmp_path / "null.json"
    null.write_text(
        json.dumps({"draws": 2000, "p95_abs_log_rel_wealth": 0.0718772, "withdrawn": True}),
        encoding="utf-8",
    )
    html = twinpanel.tracks_panel(_record(tmp_path), null_path=null)
    assert "2,000 random baskets" in html and "0.072" in html
    assert "withdrawn" in html and "at most 15" in html


def test_a_missing_null_file_removes_the_note_rather_than_inventing_one(tmp_path: Path) -> None:
    html = twinpanel.tracks_panel(_record(tmp_path), null_path=tmp_path / "absent.json")
    assert "random baskets" not in html


# --- the record itself ----------------------------------------------------------------------------
def test_the_latest_revision_wins_not_the_last_line_written(tmp_path: Path) -> None:
    """The history is append-only: a corrected day is a NEW row, not an edit. Reading the last line
    would show the superseded figure for any day that was ever re-marked."""
    superseded = {**ROW, "as_of": "2026-09-09", "revision": 0}
    corrected = {
        **ROW,
        "as_of": "2026-09-09",
        "revision": 1,
        "books": {"CORE_V1": {"value": "999999.00", "net_invested": "304144.01", "xirr": None}},
    }
    record = _record(tmp_path, superseded, corrected)
    assert [b.value for b in record.books] == [Decimal("999999.00")]


def test_no_history_is_a_sentence_not_a_blank(tmp_path: Path) -> None:
    """An empty space where a comparison belongs reads as 'nothing to report'."""
    assert twinpanel.latest_record(tmp_path / "absent.jsonl") is None
    html = twinpanel.books_panel(None, today=TODAY)
    assert "Nothing has been marked" in html
    assert "not the same as nothing having happened" in html


def test_a_book_carries_the_day_it_began_not_the_day_the_money_did(tmp_path: Path) -> None:
    """Every book's `start` reads 2026-06-15 because that is when the flows begin. CORE_V1 did not
    exist until 2026-09-07, and a book cannot outperform over a period it was not alive for."""
    record = twinpanel.latest_record(
        _history(tmp_path, ROW), inception={"CORE_V1": "2026-09-07", "TWIN_FULL": "2026-08-30"}
    )
    assert record is not None
    assert {b.name: b.first_marked for b in record.books} == {
        "CORE_V1": "2026-09-07",
        "TWIN_FULL": "2026-08-30",
    }
    assert "2026-09-07" in twinpanel.books_panel(record, today=TODAY)


def test_the_books_panel_says_the_hedge_ablation_is_zero_by_construction(tmp_path: Path) -> None:
    """TWIN_FULL minus TWIN_NO_HEDGE is zero whatever the market does, so it is not evidence
    about the hedge — and two identical rows side by side invite exactly that reading."""
    html = twinpanel.books_panel(_record(tmp_path), today=TODAY)
    assert "₹0 by construction" in html
    assert "not evidence about the hedge" in html


def test_a_stale_mark_says_how_old_it_is(tmp_path: Path) -> None:
    html = twinpanel.books_panel(_record(tmp_path), today=date(2026, 9, 12))
    assert "3 days ago" in html


# --- the gate -------------------------------------------------------------------------------------
def test_the_gate_renders_what_the_twin_graded(tmp_path: Path) -> None:
    """From the twin's own snapshot, so the page cannot grade a second time and disagree."""
    path = tmp_path / "gate.json"
    path.write_text(json.dumps(build_gate(Evidence(), TODAY).to_dict()), encoding="utf-8")
    html = twinpanel.gate_panel(path)
    assert html.count("⚪") >= 6, "one per criterion, none of them assessable today"
    assert "Track length" in html and "Data integrity" in html
    assert "NOT YET" in html and "6 of 6 criteria are not green" in html
    assert "not</b> validated for real money" in html
    assert "blocks a GO exactly as a red does" in html


def test_an_absent_gate_is_not_a_pass(tmp_path: Path) -> None:
    html = twinpanel.gate_panel(tmp_path / "never-written.json")
    assert "Not graded is not passed" in html
    assert "GO" not in html.replace("The GO gate", "")


def test_the_gate_snapshot_round_trips_every_criterion() -> None:
    """The dict the page reads must carry everything the markdown says, including the remedy."""
    data = build_gate(Evidence(), TODAY).to_dict()
    assert data["verdict"] == "NOT YET"
    criteria = data["criteria"]
    assert isinstance(criteria, list) and len(criteria) == 6
    assert all(set(c) == {"name", "verdict", "reading", "settles_it"} for c in criteria)
    assert all(c["verdict"] == "CANNOT_ASSESS" for c in criteria)


# --- the capability register ----------------------------------------------------------------------
def test_the_register_reads_its_versions_from_the_code_not_from_prose() -> None:
    """A hand-written trust table drifts from the thing it describes the moment either moves."""
    from qalpha.live.extraction import EXTRACTION_VERSION

    html = twinpanel.capability_panel()
    assert EXTRACTION_VERSION in html
    assert "nothing authorizes a GO today" in html, "derived from AUTHORIZING_PAIR being None"
    assert "no matched bar exists" in html


def test_the_register_names_the_user_as_the_executor() -> None:
    html = twinpanel.capability_panel()
    assert "you, in Kite" in html
    assert "no code path here can place one" in html


def test_the_register_does_not_promise_the_reader_a_veto() -> None:
    """The model classifies. Classification is not evidence, and a verified quote proves only that
    the document contains that sentence."""
    html = twinpanel.capability_panel()
    assert "flags, never a veto" in html
    assert "it will not earn a veto" in html


def test_nothing_on_these_panels_reads_as_validated(tmp_path: Path) -> None:
    """The whole surface, checked at once: a table of rupee figures beside a basket is exactly how a
    system that has proven nothing comes to look proven."""
    gate = tmp_path / "gate.json"
    gate.write_text(json.dumps(build_gate(Evidence(), TODAY).to_dict()), encoding="utf-8")
    html = twinpanel.panels(today=TODAY, history=_history(tmp_path, ROW), gate=gate)
    assert "in-sample only" in html
    assert "Fake money." in html
    # The only claim of validation anywhere on it must be a denial of one.
    for claim in ("validated for real money", "validated"):
        for fragment in html.split(claim)[:-1]:
            assert fragment.rstrip().endswith(("not</b>", "not", "<b>not")), fragment[-60:]


# --- your account against the index ---------------------------------------------------------------
def _track(months: int, value: str, benchmark: str | None) -> TrackRecord:
    start = date(2026, 6, 15)
    elapsed = start.month - 1 + months
    return TrackRecord(
        start=start,
        as_of=date(start.year + elapsed // 12, elapsed % 12 + 1, start.day),
        net_invested=Decimal("300000"),
        value=Decimal(value),
        benchmark_value=Decimal(benchmark) if benchmark else None,
        benchmark_exhausted=False,
        rate=-0.12,
        benchmark_rate=-0.05,
        n_flows=3,
    )


def test_the_account_panel_can_say_you_are_behind() -> None:
    """A tracker that can only report good news is marketing, not evidence."""
    html = twinpanel.account_panel(_track(3, "290000", "295000"))
    assert "Behind by ₹5,000" in html


def test_the_account_panel_says_ahead_when_it_is_ahead() -> None:
    assert "Ahead by ₹5,000" in twinpanel.account_panel(_track(3, "300000", "295000"))


def test_a_short_record_is_labelled_noise_rather_than_a_verdict() -> None:
    html = twinpanel.account_panel(_track(3, "290000", "295000"))
    assert "noise, not as a verdict" in html
    assert "dominated by <i>when</i>" in html


def test_a_long_record_drops_the_noise_caveat() -> None:
    assert "noise, not as a verdict" not in twinpanel.account_panel(_track(18, "290000", "295000"))


def test_no_tradebook_is_a_sentence_naming_the_folder() -> None:
    html = twinpanel.account_panel(None)
    assert "data/tradebooks/" in html
    assert "No track record yet" in html


def test_the_account_panel_says_the_figure_excludes_cash() -> None:
    """Parked SIP cash counted as performance is the +444% defect, and this is the one panel where
    it would be quoted back as a track record."""
    assert "Shares only" in twinpanel.account_panel(_track(3, "290000", "295000"))


def test_a_benchmark_that_does_not_cover_the_window_is_named_not_zeroed() -> None:
    html = twinpanel.account_panel(_track(3, "290000", None))
    assert "No comparison" in html
    assert "₹0" not in html


@pytest.mark.parametrize("panel", ["books", "tracks"])
def test_a_malformed_row_does_not_take_the_page_down(tmp_path: Path, panel: str) -> None:
    """The history is written by another program. A page that raises on a bad row shows nothing at
    all, which is worse than showing the rest."""
    bad = {"as_of": "2026-09-09", "books": "not a mapping", "tracks": None}
    record = twinpanel.latest_record(_history(tmp_path, bad), inception={})
    assert record is not None and record.books == () and record.tracks == ()
    rendered = (
        twinpanel.books_panel(record, today=TODAY)
        if panel == "books"
        else twinpanel.tracks_panel(record)
    )
    assert isinstance(rendered, str)


def test_the_panels_read_their_files_when_called_not_when_imported(tmp_path, monkeypatch) -> None:
    """A default argument binds at import, and then no test can reach past it.

    This is not hypothetical: the first version of this module bound the history and gate paths in
    the signatures, and the page-level test that pointed them at a fixture silently kept reading the
    developer's own data. `scripts/local_run.py` carries the same note after six defects survived a
    PR whose tests could not drive `main()`.
    """
    monkeypatch.setattr(twinpanel, "TWIN_HISTORY", tmp_path / "nothing.jsonl")
    monkeypatch.setattr(twinpanel, "GATE_JSON", tmp_path / "nothing.json")
    monkeypatch.setattr(twinpanel, "NULL_MATCHED", tmp_path / "nothing.json")
    html = twinpanel.panels(today=TODAY)
    assert "Nothing has been marked" in html
    assert "Not graded is not passed" in html
