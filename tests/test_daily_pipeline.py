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


# --- the entry points must let a failure out ------------------------------------------------------
#
# `run_pipeline` records what happened, and it can only record what it is told. Two of the entry
# points it calls used to catch every exception and `return 0` so a GitHub Actions run would not go
# red. There is no Actions run any more, and that swallow would now make the ledger write "done"
# against a step that did nothing — after which the resume logic would never run it again for these
# inputs. These assert the behaviour rather than the absence of a try block.
def test_the_twin_entry_point_lets_a_failure_reach_its_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import twin

    def _boom(cfg: object) -> int:
        raise RuntimeError("the price panel was empty")

    monkeypatch.setattr(twin, "cmd_daily", _boom)
    with pytest.raises(RuntimeError, match="price panel was empty"):
        twin.main(["daily"])


def test_the_brief_entry_point_lets_a_failure_reach_its_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import ai_brief

    monkeypatch.setattr(ai_brief.Path, "exists", lambda self: True)
    monkeypatch.setattr(ai_brief, "load_watchlist_lines", lambda p: ["INFY | 1100"])

    def _boom(watchlist: object) -> object:
        raise RuntimeError("the API refused")

    monkeypatch.setattr(ai_brief, "generate_brief", _boom)
    with pytest.raises(RuntimeError, match="API refused"):
        ai_brief.main(["daily"])


def test_a_step_that_swallows_its_failure_would_be_recorded_as_done(tmp_path: Path) -> None:
    """The consequence, made explicit: this is what those swallows were buying.

    A step that catches its own exception and returns normally is INDISTINGUISHABLE from success
    here, and there is no way for the runner to know better. That is precisely why the swallow had
    to be removed at the source rather than worked around at the caller.
    """
    ledger = tmp_path / "l.jsonl"

    def _quietly_fails() -> None:
        try:
            raise RuntimeError("something broke")
        except RuntimeError:
            return  # what `return 0` inside a bare except amounts to

    result = daily.run_pipeline(
        "d1",
        plan=[daily.Step("twin", "stepping", _quietly_fails)],
        ledger=ledger,
        log=Progress(),
        now=lambda: AT,
    )
    assert result.complete, "the runner has no way to see through a swallowed exception"
    assert _ledger_rows(ledger)[0]["state"] == "done"


def test_a_refusal_reported_by_exit_code_is_recorded_as_a_failure(tmp_path: Path) -> None:
    """The twin's abort, generalised.

    These entry points are CLI programs: a refusal arrives as an exit code, not an exception. On
    2026-09-10 a real run hit exactly this — the twin declined to write because the tradebook read
    empty while the books held ₹304,144 of flows (a failed read, not an empty account) — and the
    evening was recorded as complete with the model book standing still.
    """
    ledger = tmp_path / "l.jsonl"

    def _refuses() -> None:
        daily._checked("twin", 2)

    result = daily.run_pipeline(
        "d1",
        plan=[daily.Step("twin", "stepping", _refuses)],
        ledger=ledger,
        log=Progress(),
        now=lambda: AT,
    )
    assert not result.complete
    assert [o.name for o in result.failed] == ["twin"]
    assert "declined to write" in _ledger_rows(ledger)[0]["detail"]
    assert any("is unchanged" in n for n in result.notes())


def test_a_zero_exit_is_left_alone(tmp_path: Path) -> None:
    """The evidence step stops itself at its time budget and exits 0 — that is a real completion."""
    daily._checked("evidence", 0)  # must not raise


def test_the_twin_signals_its_abort_with_a_distinct_code() -> None:
    """Distinct from 1 so a refusal is tellable from a crash, and from 0 so neither reads as done."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import twin

    assert twin.ABORTED not in (0, 1)
