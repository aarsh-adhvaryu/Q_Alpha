"""The evening's task ledger — work keyed to its inputs, recorded as it finishes, never redone.

Two properties carry it: **a task is recorded the moment it finishes, not at the end of the run**,
and **changed inputs make the work pending again**. On 2026-09-08 the evidence spine was killed at
its cap having produced 110 events and zero coverage rows, because coverage was one bulk write
after the loop. This is that fix, generalised.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from qalpha.live.session import completed, history, pending, record_task, research_digest

_WHEN = datetime(2026, 9, 9, 10, 30, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _panel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    Path("panel.parquet").write_bytes(b"prices-v1")


def _digest(
    *,
    as_of: date = date(2026, 9, 9),
    names: Sequence[str] = ("VBL.NS", "TCS.NS"),
    panels: Sequence[Path] = (Path("panel.parquet"),),
    version: str = "EX-3",
) -> str:
    return research_digest(as_of=as_of, names=names, panels=panels, extraction_version=version)


# --- the digest ----------------------------------------------------------------------------------


def test_the_same_inputs_give_the_same_digest_whatever_order_the_names_arrive_in() -> None:
    assert _digest(names=("TCS.NS", "VBL.NS")) == _digest(names=("VBL.NS", "TCS.NS"))


def test_a_new_holding_makes_the_research_pending_again() -> None:
    """A name bought today is a name whose filings nobody has read."""
    assert _digest(names=("VBL.NS", "TCS.NS", "INFY.NS")) != _digest()


def test_new_prices_anywhere_in_the_panel_make_the_research_pending_again() -> None:
    """A candidate's rank depends on a year of its prices, not only the last row."""
    before = _digest()
    Path("panel.parquet").write_bytes(b"prices-v2")
    assert _digest() != before


def test_a_new_extraction_version_or_date_makes_everything_pending_again() -> None:
    assert _digest(version="EX-4") != _digest()
    assert _digest(as_of=date(2026, 9, 10)) != _digest()


def test_work_done_while_a_panel_was_missing_is_reconsidered_when_it_arrives() -> None:
    blind = _digest(panels=(Path("absent.parquet"),))
    Path("absent.parquet").write_bytes(b"arrived")
    assert _digest(panels=(Path("absent.parquet"),)) != blind


# --- resuming -----------------------------------------------------------------------------------
_TASKS = ["sync", "reconcile", "evidence", "screen", "decide"]


def test_an_interrupted_run_resumes_at_the_task_it_stopped_on(tmp_path: Path) -> None:
    """The whole point. Two tasks finished before the laptop closed; a restart must do the other
    three and must NOT redo the two — redoing them costs tokens and, for anything with a side
    effect, would double it."""
    led = tmp_path / "ledger.jsonl"
    record_task(_digest(), "sync", "done", _WHEN, path=led)
    record_task(_digest(), "reconcile", "done", _WHEN, path=led)

    assert pending(_digest(), _TASKS, led) == ["evidence", "screen", "decide"]


def test_a_failed_task_is_retried_and_its_failure_stays_on_file(tmp_path: Path) -> None:
    """An append-only ledger that erased failures would hide the thing most worth seeing — that a
    task needed three attempts, or has been failing quietly for a week."""
    led = tmp_path / "ledger.jsonl"
    d = _digest()
    record_task(d, "evidence", "failed", _WHEN, detail="no API key", path=led)
    assert "evidence" in pending(d, _TASKS, led), "a failure is not a completion"

    record_task(d, "evidence", "done", _WHEN, path=led)
    assert "evidence" not in pending(d, _TASKS, led)
    states = [r.state for r in history(led) if r.task == "evidence"]
    assert states == ["failed", "done"], "the failed attempt must survive its own success"


def test_changed_inputs_start_fresh_work_rather_than_inheriting_it(tmp_path: Path) -> None:
    """You bought something while it was off. Work finished against the old holdings is not work
    finished against these, and quietly counting it as done would skip the analysis of the new
    position entirely."""
    led = tmp_path / "ledger.jsonl"
    record_task(_digest(), "screen", "done", _WHEN, path=led)

    assert completed(_digest(names=("VBL.NS", "TCS.NS", "HDFCBANK.NS")), led) == set()
    assert pending(_digest(names=("VBL.NS", "TCS.NS", "HDFCBANK.NS")), _TASKS, led) == _TASKS


def test_pending_preserves_the_order_it_was_given(tmp_path: Path) -> None:
    """Tasks have dependencies — reconcile before screen, screen before decide. A resume that
    reordered them would produce a plan from a book it had not yet reconciled."""
    led = tmp_path / "ledger.jsonl"
    d = _digest()
    record_task(d, "screen", "done", _WHEN, path=led)
    assert pending(d, _TASKS, led) == ["sync", "reconcile", "evidence", "decide"]


def test_a_corrupt_ledger_line_does_not_lose_the_rest(tmp_path: Path) -> None:
    """A half-written line from a killed process must cost one row, not the file. Being killed
    mid-write is the normal case here, not the exotic one."""
    led = tmp_path / "ledger.jsonl"
    d = _digest()
    record_task(d, "sync", "done", _WHEN, path=led)
    with led.open("a", encoding="utf-8") as fh:
        fh.write('{"digest": "half-writ\n')
    record_task(d, "reconcile", "done", _WHEN, path=led)

    assert completed(d, led) == {"sync", "reconcile"}


def test_an_absent_ledger_means_everything_is_pending(tmp_path: Path) -> None:
    assert pending(_digest(), _TASKS, tmp_path / "none.jsonl") == _TASKS
    assert history(tmp_path / "none.jsonl") == []


def test_a_torn_write_does_not_swallow_the_next_completion(tmp_path: Path) -> None:
    """FOUND IN REVIEW 2026-09-09, and my own test had passed over it.

    A process killed mid-write leaves a line with **no trailing newline**. The next append lands on
    that line, both records fuse into one unparseable string, and the completion just recorded is
    lost — so its task silently runs again.

    The original test wrote a partial line *with* a newline, which is not a torn write at all. It
    passed, and the bug shipped. This writes a real one.
    """
    led = tmp_path / "ledger.jsonl"
    d = _digest()
    record_task(d, "sync", "done", _WHEN, path=led)
    with led.open("a", encoding="utf-8") as fh:
        fh.write('{"digest": "' + d + '", "task": "evid')  # no newline — killed mid-write
    record_task(d, "screen", "done", _WHEN, path=led)

    assert completed(d, led) == {"sync", "screen"}, "the record after the tear was swallowed"
