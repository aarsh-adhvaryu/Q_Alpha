"""Every backtest run, saved with the inputs that produced it — so a result can be re-derived.

**Why this exists.** A number in a chat log or a terminal scrollback is not evidence. Six weeks later
nobody can say which universe, which window, which parameters or which code produced it, and the
temptation is to re-run until it looks right and quote the run you liked. That is the failure this
repo's pre-registration discipline exists to prevent, and it needs a record, not a resolution.

Each run writes one JSON file carrying **the parameters, the git commit, the results, and any stated
caveat**. Runs are append-only and never overwritten: a later run does not replace an earlier one, it
sits beside it, which is what makes a changed answer visible instead of silent.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RUNS_DIR = Path("data/backtest_runs")


def _git_commit() -> str:
    """The commit the run executed at — without it a result cannot be reproduced, only re-obtained."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        commit = out.stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout.strip()
        return f"{commit}{'-dirty' if dirty else ''}" if commit else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


@dataclass
class RunRecord:
    """One backtest run: what was asked, what came back, and what it does not establish."""

    label: str
    #: Everything that could change the answer — universe, window, cadence, sizing, seeds.
    params: dict[str, Any]
    #: Named result → value. Rupees as floats here; the engine keeps Decimal, this is a record.
    results: dict[str, float]
    #: ⚠️ Stated limits. Required: a result recorded without its caveats gets quoted without them.
    caveats: list[str]
    commit: str = field(default_factory=_git_commit)
    run_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    def __post_init__(self) -> None:
        if not self.caveats:
            raise ValueError(
                f"run '{self.label}' recorded no caveats. Every backtest here has them — survivorship, "
                "one window, in-sample development, a null of finite size. A result stored without "
                "its limits is a result that will be quoted without them."
            )


def save_run(record: RunRecord, *, runs_dir: Path = RUNS_DIR) -> Path:
    """Append a run. Never overwrites — a changed answer must be visible beside the old one."""
    runs_dir.mkdir(parents=True, exist_ok=True)
    stamp = record.run_at.replace(":", "").replace("-", "")
    path = runs_dir / f"{stamp}_{record.label}.json"
    n = 1
    while path.exists():
        path = runs_dir / f"{stamp}_{record.label}_{n}.json"
        n += 1
    path.write_text(json.dumps(asdict(record), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_runs(*, label: str | None = None, runs_dir: Path = RUNS_DIR) -> list[RunRecord]:
    """Every saved run, oldest first, optionally filtered to one label."""
    if not runs_dir.exists():
        return []
    out: list[RunRecord] = []
    for path in sorted(runs_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if label is not None and data.get("label") != label:
            continue
        out.append(RunRecord(**data))
    return out


def drift_report(label: str, metric: str, *, runs_dir: Path = RUNS_DIR) -> str:
    """How one metric has moved across runs of the same label — the point of keeping them.

    A result that changes when nothing was supposed to change is the signal worth catching, and it
    is invisible unless the old runs are still there to compare against.
    """
    runs = [r for r in load_runs(label=label, runs_dir=runs_dir) if metric in r.results]
    if not runs:
        return f"No saved runs of '{label}' carry '{metric}'."
    lines = [f"**{label} · {metric}** across {len(runs)} run(s):", ""]
    previous: float | None = None
    for r in runs:
        value = r.results[metric]
        delta = "" if previous is None else f"  ({value - previous:+,.0f} vs previous)"
        lines.append(f"- {r.run_at} · `{r.commit}` · {value:,.0f}{delta}")
        previous = value
    if (
        len(runs) > 1
        and runs[0].commit == runs[-1].commit
        and runs[0].results[metric] != runs[-1].results[metric]
    ):
        lines += [
            "",
            "⚠️ **The same commit produced different answers.** Either an input changed outside the "
            "recorded parameters, or the run is not deterministic. Both need explaining before "
            "either number is quoted.",
        ]
    return "\n".join(lines)


__all__ = ["RUNS_DIR", "RunRecord", "drift_report", "load_runs", "save_run"]
