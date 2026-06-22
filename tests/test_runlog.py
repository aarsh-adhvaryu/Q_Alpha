"""Tests for the autonomous run log (live/runlog.py)."""

from __future__ import annotations

from qalpha.live.runlog import (
    RunLogEntry,
    append_run,
    health_markdown,
    load_runs,
    now_utc_iso,
)


def _entry(as_of: str, *, go: str = "NOT YET", warnings: list[str] | None = None) -> RunLogEntry:
    return RunLogEntry(
        ran_at=now_utc_iso(),
        as_of=as_of,
        command="daily",
        action="held — no action",
        decision_reason="holding — next scheduled rebalance on/after 2027-01-01",
        equity="201234.56",
        return_pct=0.62,
        go_verdict=go,
        freshness="✓ Up to date — last marked " + as_of,
        warnings=warnings or [],
    )


def test_append_and_load_roundtrip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "run_log.jsonl"
    append_run(_entry("2026-06-20"), path)
    append_run(_entry("2026-06-21", go="READY"), path)
    runs = load_runs(path)
    assert len(runs) == 2
    assert runs[0].as_of == "2026-06-20" and runs[1].as_of == "2026-06-21"
    assert runs[1].go_verdict == "READY"
    assert runs[1].return_pct == 0.62


def test_load_missing_is_empty(tmp_path) -> None:  # type: ignore[no-untyped-def]
    assert load_runs(tmp_path / "nope.jsonl") == []


def test_load_limit_returns_most_recent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "run_log.jsonl"
    for d in range(10, 15):
        append_run(_entry(f"2026-06-{d}"), path)
    recent = load_runs(path, limit=2)
    assert [r.as_of for r in recent] == ["2026-06-13", "2026-06-14"]


def test_health_markdown_empty() -> None:
    md = health_markdown([])
    assert "No autonomous runs recorded yet" in md


def test_health_markdown_healthy_and_attention() -> None:
    healthy = health_markdown([_entry("2026-06-20")])
    assert "🟢 healthy" in healthy
    assert "GO: **NOT YET**" in healthy

    attention = health_markdown([_entry("2026-06-21", warnings=["stale feed — cron missed a day"])])
    assert "🟠 attention" in attention
    assert "stale feed" in attention


def test_entry_dict_roundtrip() -> None:
    e = _entry("2026-06-20", warnings=["w1", "w2"])
    assert RunLogEntry.from_dict(e.to_dict()) == e
