"""The evening's task ledger: work is keyed to its inputs, recorded as it finishes, never redone.

Stop the machine halfway and come back in two days: the next run resumes at the task it had not
reached, because a task finished against these exact inputs is on file. Change the inputs — a new
price panel, a new holding, a new extraction version — and the digest changes, so the work is
pending again rather than silently carried over.

A task is written the moment it finishes, never before. Pure: no network, no clock of its own.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal

SESSION_DIR = Path("data/session")
LEDGER_PATH = SESSION_DIR / "ledger.jsonl"

TaskState = Literal["done", "failed"]


def research_digest(
    *, as_of: date, names: Sequence[str], panels: Sequence[Path], extraction_version: str
) -> str:
    """The id for an evening's research: exactly what would make re-reading give a different answer.

    The date, the names in scope (a name bought today is a name nobody has read), the **whole bytes**
    of every price panel (a candidate's rank depends on a year of its prices, not the last row), and
    the extraction version. A missing panel is part of the identity too: work done blind is not work
    done once the file arrives.
    """
    h = hashlib.sha256()
    h.update(
        json.dumps(
            {
                "as_of": as_of.isoformat(),
                "names": sorted(names),
                "extraction_version": extraction_version,
            },
            sort_keys=True,
        ).encode()
    )
    for panel in panels:
        h.update(panel.name.encode())
        h.update(panel.read_bytes() if panel.exists() else b"<missing>")
    return h.hexdigest()[:16]


#: The task name an evening's own summary is written under, so the whole run is one journal.
RUN_TASK = "evening"


@dataclass(frozen=True)
class TaskRecord:
    """One unit of work against one snapshot. Written the moment it finishes, never before."""

    digest: str
    task: str
    state: TaskState
    at: datetime
    detail: str = ""


def record_task(
    digest: str,
    task: str,
    state: TaskState,
    at: datetime,
    *,
    detail: str = "",
    path: Path | None = None,
) -> None:
    """Append one finished task. Append-only: a failure stays on file after its later success.

    A ledger that erased failures would hide the thing most worth seeing — that a task needed three
    attempts, or that it has been failing quietly for a week.
    """
    path = path or LEDGER_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "digest": digest,
        "task": task,
        "state": state,
        "at": at.isoformat(),
        "detail": detail,
    }
    # HEAL A TORN TAIL BEFORE APPENDING. A process killed mid-write leaves a line with no trailing
    # newline; the next append lands ON that line and BOTH records become one unparseable string —
    # so the completion just recorded is lost, silently, and its task runs again. Being killed
    # mid-write is the normal case for this file, not the exotic one.
    #
    # The first version of the test for this wrote a partial line *with* a newline, which is not a
    # torn write at all. It passed, and the bug shipped.
    needs_newline = False
    if path.exists() and path.stat().st_size:
        with path.open("rb") as fh:
            fh.seek(-1, 2)
            needs_newline = fh.read(1) != b"\n"
    with path.open("a", encoding="utf-8") as fh:
        if needs_newline:
            fh.write("\n")
        fh.write(json.dumps(row) + "\n")
        fh.flush()
        os.fsync(fh.fileno())  # the record must be on the platter before the caller moves on


def completed(digest: str, path: Path | None = None) -> set[str]:
    """Tasks already done for this snapshot. A failed task is NOT done and will be retried.

    Scoped by digest on purpose: change the inputs and every task is pending again, because work
    finished against different holdings is not work finished against these.
    """
    path = path or LEDGER_PATH
    if not path.exists():
        return set()
    done: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("digest") == digest and row.get("state") == "done":
            done.add(str(row.get("task")))
    return done


def pending(digest: str, tasks: Iterable[str], path: Path | None = None) -> list[str]:
    """What is left to do, in the order given. This is the whole of "resume where it stopped"."""
    done = completed(digest, path)
    return [t for t in tasks if t not in done]


def record_run(
    *, at: datetime, notes: Sequence[str], complete: bool, path: Path | None = None
) -> None:
    """Write the evening itself into the same journal its steps went to.

    One file answers "what has this machine done, and what went wrong" — a second place for the
    run's own summary is how a failure ends up recorded in one file and reported from another.
    """
    record_task(
        f"run:{at.isoformat(timespec='seconds')}",
        RUN_TASK,
        "done" if complete else "failed",
        at,
        detail=" · ".join(notes) if notes else "nothing to report",
        path=path,
    )


def last_run(path: Path | None = None) -> TaskRecord | None:
    """The most recent evening's own row, or ``None`` when none has been recorded."""
    runs = [r for r in history(path or LEDGER_PATH, limit=500) if r.task == RUN_TASK]
    return runs[-1] if runs else None


def history(path: Path | None = None, *, limit: int = 50) -> list[TaskRecord]:
    """The recent trail, newest last — what ran, what failed, and when.

    The path is resolved **at call time**: a module constant bound as a default argument is fixed at
    import, so a caller that redirects the journal would be read from the old one.
    """
    path = path or LEDGER_PATH
    if not path.exists():
        return []
    out: list[TaskRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            out.append(
                TaskRecord(
                    digest=str(row["digest"]),
                    task=str(row["task"]),
                    state="done" if row.get("state") == "done" else "failed",
                    at=datetime.fromisoformat(str(row["at"])),
                    detail=str(row.get("detail", "")),
                )
            )
        except (KeyError, ValueError):
            continue
    return out[-limit:]
