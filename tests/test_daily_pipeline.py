"""Tests for the local evening pipeline (:mod:`qalpha.live.daily`).

These are caller tests, not function tests. The cron's failure was never that a step was broken —
it was that the *runner* around the steps reported success regardless, and that nothing resumed. So
what is asserted here is the runner's bookkeeping: what it records, what it refuses to record, and
what it says afterwards.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from qalpha.live import daily
from qalpha.live.progress import Progress
from qalpha.live.session import record_task

AT = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


def _step(
    name: str, calls: list[str], *, boom: bool = False, needs: tuple[str, ...] = ()
) -> daily.Step:
    def run() -> None:
        calls.append(name)
        if boom:
            raise RuntimeError("the panel was empty")

    return daily.Step(name, f"doing {name}", run, needs=needs)


def _ledger_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_steps_run_in_order(tmp_path: Path) -> None:
    calls: list[str] = []
    plan = [_step("one", calls), _step("two", calls), _step("three", calls)]
    daily.run_pipeline("d1", plan=plan, ledger=tmp_path / "l.jsonl", log=Progress(), now=lambda: AT)
    assert calls == ["one", "two", "three"]


def test_a_failed_step_does_not_stop_the_evening(tmp_path: Path) -> None:
    calls: list[str] = []
    plan = [_step("one", calls), _step("two", calls, boom=True), _step("three", calls)]
    result = daily.run_pipeline(
        "d1", plan=plan, ledger=tmp_path / "l.jsonl", log=Progress(), now=lambda: AT
    )
    assert calls == ["one", "two", "three"]
    assert [o.name for o in result.failed] == ["two"]


def test_a_failure_is_written_down_and_reaches_the_page(tmp_path: Path) -> None:
    """The cron's defect exactly: a step died and the run still reported success.

    Two things must be true — the ledger carries the failure, and :meth:`notes` says it in a
    sentence the user reads.
    """
    ledger = tmp_path / "l.jsonl"
    result = daily.run_pipeline(
        "d1", plan=[_step("evidence", [], boom=True)], ledger=ledger, log=Progress(), now=lambda: AT
    )
    rows = _ledger_rows(ledger)
    assert [(r["task"], r["state"]) for r in rows] == [("evidence", "failed")]
    assert "the panel was empty" in rows[0]["detail"]
    assert not result.complete
    assert any("evidence FAILED" in n for n in result.notes())


def test_a_failed_step_is_pending_again_on_the_next_run(tmp_path: Path) -> None:
    ledger = tmp_path / "l.jsonl"
    calls: list[str] = []
    daily.run_pipeline(
        "d1", plan=[_step("one", calls, boom=True)], ledger=ledger, log=Progress(), now=lambda: AT
    )
    daily.run_pipeline(
        "d1", plan=[_step("one", calls)], ledger=ledger, log=Progress(), now=lambda: AT
    )
    assert calls == ["one", "one"], "a failure must not count as done"


def test_finished_work_is_not_redone(tmp_path: Path) -> None:
    """'Say I don't run for two days, then it continues' — the whole point of the ledger."""
    ledger = tmp_path / "l.jsonl"
    calls: list[str] = []
    record_task("d1", "one", "done", AT, path=ledger)
    result = daily.run_pipeline(
        "d1",
        plan=[_step("one", calls), _step("two", calls)],
        ledger=ledger,
        log=Progress(),
        now=lambda: AT,
    )
    assert calls == ["two"]
    assert result.complete, "an already-done step still counts toward a complete evening"


def test_changing_the_inputs_makes_everything_pending_again(tmp_path: Path) -> None:
    """Work finished against yesterday's prices is not work finished against today's."""
    ledger = tmp_path / "l.jsonl"
    calls: list[str] = []
    record_task("yesterday", "one", "done", AT, path=ledger)
    daily.run_pipeline(
        "today", plan=[_step("one", calls)], ledger=ledger, log=Progress(), now=lambda: AT
    )
    assert calls == ["one"]


def test_force_reruns_a_step_the_ledger_calls_done(tmp_path: Path) -> None:
    ledger = tmp_path / "l.jsonl"
    calls: list[str] = []
    record_task("d1", "one", "done", AT, path=ledger)
    daily.run_pipeline(
        "d1", plan=[_step("one", calls)], ledger=ledger, log=Progress(), force=True, now=lambda: AT
    )
    assert calls == ["one"]


def test_a_missing_credential_skips_without_running_and_without_recording(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A skip must not be a completion, or the step never runs again once the key arrives."""
    monkeypatch.delenv("SOME_KEY", raising=False)
    ledger = tmp_path / "l.jsonl"
    calls: list[str] = []
    result = daily.run_pipeline(
        "d1",
        plan=[_step("brief", calls, needs=("SOME_KEY",))],
        ledger=ledger,
        log=Progress(),
        now=lambda: AT,
    )
    assert calls == []
    assert _ledger_rows(ledger) == [], "a skip is not a completion"
    assert [o.name for o in result.skipped] == ["brief"]
    assert not result.complete, "an evening with a skipped step is not a complete evening"


def test_the_skipped_step_runs_once_the_credential_is_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "l.jsonl"
    calls: list[str] = []
    monkeypatch.delenv("SOME_KEY", raising=False)
    daily.run_pipeline(
        "d1",
        plan=[_step("brief", calls, needs=("SOME_KEY",))],
        ledger=ledger,
        log=Progress(),
        now=lambda: AT,
    )
    monkeypatch.setenv("SOME_KEY", "value")
    daily.run_pipeline(
        "d1",
        plan=[_step("brief", calls, needs=("SOME_KEY",))],
        ledger=ledger,
        log=Progress(),
        now=lambda: AT,
    )
    assert calls == ["brief"]


def test_a_blank_credential_counts_as_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SOME_KEY", "   ")
    calls: list[str] = []
    daily.run_pipeline(
        "d1",
        plan=[_step("brief", calls, needs=("SOME_KEY",))],
        ledger=tmp_path / "l.jsonl",
        log=Progress(),
        now=lambda: AT,
    )
    assert calls == []


def test_the_skip_reason_names_the_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SOME_KEY", raising=False)
    result = daily.run_pipeline(
        "d1",
        plan=[_step("brief", [], needs=("SOME_KEY",))],
        ledger=tmp_path / "l.jsonl",
        log=Progress(),
        now=lambda: AT,
    )
    assert "SOME_KEY" in result.notes()[0]


def test_the_real_plan_reads_filings_before_the_twin_steps() -> None:
    """The autonomous books must step ON the evidence, not ahead of it."""
    names = [s.name for s in daily.steps()]
    assert names.index("prices") < names.index("mark")
    assert names.index("evidence") < names.index("twin")


def test_the_brief_is_the_only_step_that_needs_a_cloud_key() -> None:
    """Everything except the web-searched brief must run with no credential at all."""
    needing = {s.name for s in daily.steps() if "ANTHROPIC_API_KEY" in s.needs}
    assert needing == {"brief"}
