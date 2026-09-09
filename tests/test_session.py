"""The local run's spine — one saved snapshot, and work that survives being interrupted.

The design these support: sync when you start it, run the whole analysis on this machine, save every
decision, and **pick up where it stopped** — whether it stopped because the laptop closed or because
you did not open it for two days.

Two properties carry the whole thing, and both are the same lesson learned twice already in this
repo: **the inputs are written before any book steps**, and **a task is recorded the moment it
finishes, not at the end of the run**. On 2026-09-08 the evidence spine was killed at its 20-minute
cap having produced 110 events and zero coverage rows, because coverage was one bulk write after the
loop. This is that fix, generalised.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from qalpha.live.session import (
    InputSnapshot,
    completed,
    history,
    load_snapshot,
    pending,
    record_task,
)

_WHEN = datetime(2026, 9, 9, 10, 30, tzinfo=UTC)


def _snap(**kw: object) -> InputSnapshot:
    base: dict[str, object] = {
        "as_of": date(2026, 9, 9),
        "taken_at": _WHEN,
        "holdings": {"VBL.NS": 147, "TCS.NS": 10},
        "cash": Decimal("201117"),
        "budget": Decimal("50000"),
        "universe": ("VBL.NS", "TCS.NS", "INFY.NS"),
        "prices_sha": "abc123",
    }
    base.update(kw)
    return InputSnapshot(**base)  # type: ignore[arg-type]


# --- the snapshot -------------------------------------------------------------------------------
def test_a_snapshot_round_trips_through_disk_unchanged(tmp_path: Path) -> None:
    """It is the thing every decision cites. If it cannot be read back exactly, nothing that cited
    it can be replayed, and a decision that cannot be replayed cannot be audited when it was wrong."""
    p = tmp_path / "snapshot.json"
    original = _snap()
    original.save(p)
    back = load_snapshot(p)
    assert back is not None
    assert back == original
    assert back.digest() == original.digest()


def test_the_digest_covers_the_inputs_and_nothing_else(tmp_path: Path) -> None:
    """Two runs on the same inputs must share a digest — that is what lets a resumed run recognise
    its own unfinished work. Change an input and the work is not the same work."""
    assert _snap().digest() == _snap(taken_at=datetime(2027, 1, 1, tzinfo=UTC)).digest(), (
        "the wall clock is not an input; re-running an hour later must resume, not restart"
    )
    assert _snap().digest() != _snap(cash=Decimal("1")).digest()
    assert _snap().digest() != _snap(holdings={"VBL.NS": 148, "TCS.NS": 10}).digest()
    assert _snap().digest() != _snap(prices_sha="different").digest()


def test_a_missing_critical_input_makes_the_snapshot_unusable() -> None:
    """Unknown is never substituted. A run on a snapshot missing something load-bearing must
    degrade to "I could not check this", never to a confident answer on yesterday's prices."""
    assert _snap().usable
    assert not _snap(missing_critical=("live prices",)).usable
    # Merely stale is not the same as missing: it is a caveat, not a stop.
    assert _snap(stale=("exchange file is 2 days old",)).usable


def test_an_unreadable_snapshot_reads_as_absent_rather_than_raising(tmp_path: Path) -> None:
    p = tmp_path / "snapshot.json"
    p.write_text("{ not json", encoding="utf-8")
    assert load_snapshot(p) is None
    assert load_snapshot(tmp_path / "never-written.json") is None


# --- "if I buy a stock in Kite, does it show up?" ------------------------------------------------
def test_a_position_added_while_the_machine_was_off_is_named_out_loud() -> None:
    """The question asked of this design in as many words. A new holding must be reported, not
    silently absorbed — the run needs to say what changed before it says what to do about it."""
    before = _snap()
    after = _snap(holdings={"VBL.NS": 147, "TCS.NS": 10, "HDFCBANK.NS": 25})
    assert "new holding HDFCBANK.NS (25)" in after.changes_against(before)


def test_a_position_sold_and_a_quantity_change_are_both_reported() -> None:
    before = _snap()
    after = _snap(holdings={"VBL.NS": 200}, cash=Decimal("150000"))
    changes = after.changes_against(before)
    assert "holding gone TCS.NS (was 10)" in changes
    assert "VBL.NS 147 → 200" in changes
    assert any("cash" in c for c in changes)


def test_nothing_changed_reports_nothing() -> None:
    """A quiet day must read as quiet. Inventing a change would be as bad as hiding one."""
    assert _snap().changes_against(_snap()) == []


def test_the_first_snapshot_says_it_has_nothing_to_compare_against() -> None:
    assert _snap().changes_against(None) == ["first snapshot — nothing to compare against"]


# --- resuming -----------------------------------------------------------------------------------
_TASKS = ["sync", "reconcile", "evidence", "screen", "decide"]


def test_an_interrupted_run_resumes_at_the_task_it_stopped_on(tmp_path: Path) -> None:
    """The whole point. Two tasks finished before the laptop closed; a restart must do the other
    three and must NOT redo the two — redoing them costs tokens and, for anything with a side
    effect, would double it."""
    led = tmp_path / "ledger.jsonl"
    snap = _snap()
    record_task(snap.digest(), "sync", "done", _WHEN, path=led)
    record_task(snap.digest(), "reconcile", "done", _WHEN, path=led)

    assert pending(snap.digest(), _TASKS, led) == ["evidence", "screen", "decide"]


def test_a_failed_task_is_retried_and_its_failure_stays_on_file(tmp_path: Path) -> None:
    """An append-only ledger that erased failures would hide the thing most worth seeing — that a
    task needed three attempts, or has been failing quietly for a week."""
    led = tmp_path / "ledger.jsonl"
    d = _snap().digest()
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
    old = _snap()
    record_task(old.digest(), "screen", "done", _WHEN, path=led)

    new = _snap(holdings={"VBL.NS": 147, "TCS.NS": 10, "HDFCBANK.NS": 25})
    assert completed(new.digest(), led) == set()
    assert pending(new.digest(), _TASKS, led) == _TASKS


def test_pending_preserves_the_order_it_was_given(tmp_path: Path) -> None:
    """Tasks have dependencies — reconcile before screen, screen before decide. A resume that
    reordered them would produce a plan from a book it had not yet reconciled."""
    led = tmp_path / "ledger.jsonl"
    d = _snap().digest()
    record_task(d, "screen", "done", _WHEN, path=led)
    assert pending(d, _TASKS, led) == ["sync", "reconcile", "evidence", "decide"]


def test_a_corrupt_ledger_line_does_not_lose_the_rest(tmp_path: Path) -> None:
    """A half-written line from a killed process must cost one row, not the file. Being killed
    mid-write is the normal case here, not the exotic one."""
    led = tmp_path / "ledger.jsonl"
    d = _snap().digest()
    record_task(d, "sync", "done", _WHEN, path=led)
    with led.open("a", encoding="utf-8") as fh:
        fh.write('{"digest": "half-writ\n')
    record_task(d, "reconcile", "done", _WHEN, path=led)

    assert completed(d, led) == {"sync", "reconcile"}


def test_an_absent_ledger_means_everything_is_pending(tmp_path: Path) -> None:
    assert pending(_snap().digest(), _TASKS, tmp_path / "none.jsonl") == _TASKS
    assert history(tmp_path / "none.jsonl") == []


# --- the three defects found in review, after PR #120 merged -------------------------------------
def test_a_torn_write_does_not_swallow_the_next_completion(tmp_path: Path) -> None:
    """FOUND IN REVIEW 2026-09-09, and my own test had passed over it.

    A process killed mid-write leaves a line with **no trailing newline**. The next append lands on
    that line, both records fuse into one unparseable string, and the completion just recorded is
    lost — so its task silently runs again.

    The original test wrote a partial line *with* a newline, which is not a torn write at all. It
    passed, and the bug shipped. This writes a real one.
    """
    led = tmp_path / "ledger.jsonl"
    d = _snap().digest()
    record_task(d, "sync", "done", _WHEN, path=led)
    with led.open("a", encoding="utf-8") as fh:
        fh.write('{"digest": "' + d + '", "task": "evid')  # no newline — killed mid-write
    record_task(d, "screen", "done", _WHEN, path=led)

    assert completed(d, led) == {"sync", "screen"}, "the record after the tear was swallowed"


def test_work_done_while_an_input_was_missing_is_reconsidered_when_it_arrives() -> None:
    """Availability IS an input. A run that finished "evidence" while the exchange file was missing
    has not checked the same thing as a run with it — leaving these out of the digest meant an
    improved input never triggered a re-check, and the answer obtained while blind was kept."""
    blind = _snap(missing_critical=("exchange file",))
    seeing = _snap()
    assert blind.digest() != seeing.digest()
    assert _snap(stale=("filings 2 days old",)).digest() != seeing.digest()


def test_a_rule_change_reopens_the_work_it_would_have_changed() -> None:
    """A task completed under EX-1 is not a task completed under EX-2 — that exact version bump is
    why 193 events had to be re-read. A plan made under one policy is not a plan under the next."""
    assert _snap(extraction_version="EX-1").digest() != _snap(extraction_version="EX-2").digest()
    assert _snap(policy_version="v1").digest() != _snap(policy_version="v2").digest()


def test_every_snapshot_is_kept_so_an_old_decision_stays_replayable(tmp_path: Path) -> None:
    """The first version replaced snapshot.json each run — destroying the thing the file exists for.
    A decision cites a digest; if that snapshot was overwritten the citation points at nothing."""
    pointer, archive = tmp_path / "snapshot.json", tmp_path / "snapshots"
    first = _snap()
    second = _snap(cash=Decimal("151117"))
    first.save(pointer, archive=archive)
    second.save(pointer, archive=archive)

    kept = {p.stem for p in archive.glob("*.json")}
    assert kept == {first.digest(), second.digest()}, "an overwritten snapshot is an unciteable one"
    assert load_snapshot(pointer) == second, "the pointer tracks the current one"
    assert (
        InputSnapshot.from_dict(
            json.loads((archive / f"{first.digest()}.json").read_text(encoding="utf-8"))
        )
        == first
    )
