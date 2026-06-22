"""Autonomous run log — the durable audit trail proving the daily pipeline actually ran (and what it did).

The system is designed to work **headless**: the weekday cron runs ``scripts/paper.py daily`` (refresh
prices → mark the book → auto-apply a scheduled rebalance → regenerate the dashboard) with no human and
no Streamlit open. This module records one structured entry per run to a committed JSONL file, so you
can *see* — on GitHub or in the dashboard's Logs tab — that it fired, on which date, what it decided and
why, the equity, the GO verdict, and any health warnings. "Trust nothing you can't inspect": this is the
inspection trail for the autonomous half.

It is append-only and tracked (``data/paper/`` is committed on purpose, like the book), so the history
survives across cron runs and fresh checkouts. Pure file I/O + dataclasses; no engine coupling.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

RUN_LOG_PATH = Path("data/paper/run_log.jsonl")


@dataclass(frozen=True)
class RunLogEntry:
    """One autonomous-pipeline run, captured for audit."""

    ran_at: str  # ISO-8601 UTC wall-clock time the run executed
    as_of: str  # the market date the run acted on (ISO)
    command: str  # "daily" (cron) | "dashboard" (local preview)
    action: str  # human summary, e.g. "held — no scheduled rebalance" / "auto-applied 5 orders"
    decision_reason: str  # the decide_rebalance reason string
    equity: str  # marked book equity (Decimal as str)
    return_pct: float  # return since inception (%)
    go_verdict: str  # GO / NO-GO / READY / NOT YET
    freshness: str  # paper-freshness note
    warnings: list[str]  # health flags (stale feed, missed marks, …); empty = clean

    def to_dict(self) -> dict[str, object]:
        return {
            "ran_at": self.ran_at,
            "as_of": self.as_of,
            "command": self.command,
            "action": self.action,
            "decision_reason": self.decision_reason,
            "equity": self.equity,
            "return_pct": self.return_pct,
            "go_verdict": self.go_verdict,
            "freshness": self.freshness,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> RunLogEntry:
        return cls(
            ran_at=str(d["ran_at"]),
            as_of=str(d["as_of"]),
            command=str(d["command"]),
            action=str(d["action"]),
            decision_reason=str(d["decision_reason"]),
            equity=str(d["equity"]),
            return_pct=float(d["return_pct"]),  # type: ignore[arg-type]
            go_verdict=str(d["go_verdict"]),
            freshness=str(d["freshness"]),
            warnings=[str(w) for w in cast("list[object]", d.get("warnings") or [])],
        )


def now_utc_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def append_run(entry: RunLogEntry, path: Path = RUN_LOG_PATH) -> None:
    """Append one run entry as a JSON line (creating the file/dir on first run)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry.to_dict()) + "\n")


def load_runs(path: Path = RUN_LOG_PATH, *, limit: int | None = None) -> list[RunLogEntry]:
    """Load run entries oldest→newest (last ``limit`` if given). Empty if the log doesn't exist yet."""
    if not path.exists():
        return []
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if limit is not None:
        lines = lines[-limit:]
    return [RunLogEntry.from_dict(json.loads(ln)) for ln in lines]


def health_markdown(entries: list[RunLogEntry], *, tail: int = 10) -> str:
    """Render the 'system health + autonomous run log' section (latest status + a recent-runs table)."""
    if not entries:
        return (
            "## 🩺 System health & run log\n\n"
            "_No autonomous runs recorded yet — the daily pipeline hasn't logged a run._"
        )
    latest = entries[-1]
    status = "🟢 healthy" if not latest.warnings else "🟠 attention"
    lines = [
        "## 🩺 System health & run log",
        "",
        f"**{status}** — last autonomous run **{latest.ran_at}** (market date {latest.as_of}, "
        f"`{latest.command}`).",
        "",
        f"- Action: {latest.action}",
        f"- Decision: {latest.decision_reason}",
        f"- Equity: ₹{float(latest.equity):,.0f} ({latest.return_pct:+.2f}%) · GO: **{latest.go_verdict}**",
        f"- Freshness: {latest.freshness}",
    ]
    if latest.warnings:
        lines.append("- ⚠️ Warnings: " + "; ".join(latest.warnings))
    lines += [
        "",
        f"_Recent runs (last {min(tail, len(entries))} of {len(entries)}):_",
        "",
        "| Ran (UTC) | As of | Cmd | Action | GO | Warnings |",
        "|---|---|---|---|---|---|",
    ]
    for e in reversed(entries[-tail:]):
        warn = "—" if not e.warnings else f"⚠️ {len(e.warnings)}"
        lines.append(
            f"| {e.ran_at} | {e.as_of} | {e.command} | {e.action} | {e.go_verdict} | {warn} |"
        )
    return "\n".join(lines)
