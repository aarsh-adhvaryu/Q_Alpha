"""The local run's spine: one saved input snapshot, and a ledger that survives being interrupted.

### What this is for

The design is: sync when you start it, run the whole analysis on this machine, save every decision
and its reason, and **pick up where it stopped** — whether it stopped because the laptop closed or
because you did not open it for two days.

Two things have to be true for that, and neither was:

1. **Every book must read the same inputs.** ``runner.Market`` already says so — *"Passed in rather
   than fetched so a step is pure: same market, same book, same decisions"* — but nothing ever
   **saved** it. A snapshot that exists only in memory cannot be the thing a decision cites, cannot
   be compared against tomorrow's, and cannot be replayed to check what the system saw.

2. **Work must be resumable at the task, not at the run.** The evidence spine was killed at its
   20-minute cap on 2026-09-08 having produced 110 events and no coverage; the fix was to make each
   name durable as it finished. This generalises that: a run is a list of tasks against one
   snapshot, each recorded the moment it completes.

### The ordering rule, which is the same rule as everywhere else here

**The snapshot is written before any book steps.** A decision that cites inputs nobody kept is not
auditable, and "I will save it at the end" is how 110 events reached disk with no coverage beside
them. The receipt is written after the thing it is a receipt for; the *inputs* are written before.

### What it refuses to do

A snapshot records what could **not** be refreshed in :attr:`InputSnapshot.stale`. It never
substitutes a previous value for a missing one, and :meth:`InputSnapshot.usable` is false when
something load-bearing is absent — so a run degrades to "I could not check this" rather than to a
confident answer computed on yesterday's prices.

Pure: no network, no broker, no clock of its own. The caller gathers; this records.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

SESSION_DIR = Path("data/session")
SNAPSHOT_PATH = SESSION_DIR / "snapshot.json"
LEDGER_PATH = SESSION_DIR / "ledger.jsonl"

TaskState = Literal["done", "failed"]


@dataclass(frozen=True)
class InputSnapshot:
    """Everything every book reads on one run, timestamped and hashed.

    ``holdings`` and ``cash`` come from the reconciled account — the copy of what you actually own,
    which is what makes "if I buy a stock in Kite it shows up" true. ``budget`` is the mandate's, not
    the broker balance: the account holds several future instalments and only one is deployable.
    """

    as_of: date
    taken_at: datetime
    holdings: Mapping[str, int]
    cash: Decimal
    budget: Decimal
    universe: Sequence[str]
    #: Content hash of the price panel actually used. Two runs quoting the same figure must be able
    #: to prove they read the same prices; a filename cannot do that and a mtime is reset by a
    #: fresh checkout.
    prices_sha: str = ""
    #: Inputs that could not be refreshed this run. Named, never silently carried forward.
    stale: Sequence[str] = field(default_factory=tuple)
    #: Inputs whose absence makes a decision impossible, as opposed to merely less informed.
    missing_critical: Sequence[str] = field(default_factory=tuple)

    @property
    def usable(self) -> bool:
        """May a book decide anything on this snapshot? False is a real answer, not a failure."""
        return not self.missing_critical

    def digest(self) -> str:
        """The id every decision made on this snapshot cites. Stable across processes and machines.

        Deliberately covers the *inputs*, not the outputs: two runs on the same inputs share a
        digest, which is exactly what lets a resumed run recognise its own unfinished work — and
        what makes a changed input start fresh work rather than silently continuing the old.
        """
        payload = json.dumps(
            {
                "as_of": self.as_of.isoformat(),
                "holdings": dict(sorted(self.holdings.items())),
                "cash": str(self.cash),
                "budget": str(self.budget),
                "universe": sorted(self.universe),
                "prices_sha": self.prices_sha,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, object]:
        return {
            "as_of": self.as_of.isoformat(),
            "taken_at": self.taken_at.isoformat(),
            "holdings": dict(sorted(self.holdings.items())),
            "cash": str(self.cash),
            "budget": str(self.budget),
            "universe": list(self.universe),
            "prices_sha": self.prices_sha,
            "stale": list(self.stale),
            "missing_critical": list(self.missing_critical),
            "digest": self.digest(),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> InputSnapshot:
        def _seq(key: str) -> tuple[str, ...]:
            value = raw.get(key)
            return tuple(str(t) for t in value) if isinstance(value, list | tuple) else ()

        held = raw.get("holdings")
        holdings = {str(k): int(str(v)) for k, v in held.items()} if isinstance(held, dict) else {}
        return cls(
            as_of=date.fromisoformat(str(raw["as_of"])),
            taken_at=datetime.fromisoformat(str(raw["taken_at"])),
            holdings=holdings,
            cash=Decimal(str(raw.get("cash", "0"))),
            budget=Decimal(str(raw.get("budget", "0"))),
            universe=_seq("universe"),
            prices_sha=str(raw.get("prices_sha", "")),
            stale=_seq("stale"),
            missing_critical=_seq("missing_critical"),
        )

    def save(self, path: Path = SNAPSHOT_PATH) -> None:
        """Write the snapshot **before** any book steps. See the ordering rule in the module docs."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)

    def changes_against(self, other: InputSnapshot | None) -> list[str]:
        """What moved since the last run, in words. ``[]`` when nothing did.

        This is how "if I add a stock in Kite, does it appear?" gets answered out loud instead of
        being assumed: a position that arrived while the machine was off is named here.
        """
        if other is None:
            return ["first snapshot — nothing to compare against"]
        out: list[str] = []
        mine, theirs = dict(self.holdings), dict(other.holdings)
        for t in sorted(set(mine) - set(theirs)):
            out.append(f"new holding {t} ({mine[t]})")
        for t in sorted(set(theirs) - set(mine)):
            out.append(f"holding gone {t} (was {theirs[t]})")
        for t in sorted(set(mine) & set(theirs)):
            if mine[t] != theirs[t]:
                out.append(f"{t} {theirs[t]} → {mine[t]}")
        if self.cash != other.cash:
            out.append(f"cash ₹{other.cash:,.0f} → ₹{self.cash:,.0f}")
        return out


def load_snapshot(path: Path = SNAPSHOT_PATH) -> InputSnapshot | None:
    """The last saved snapshot, or ``None``. Unreadable is treated as absent and said so."""
    if not path.exists():
        return None
    try:
        return InputSnapshot.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError):
        print(f"[session] {path} is unreadable — treating as no previous snapshot")
        return None


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
    path: Path = LEDGER_PATH,
) -> None:
    """Append one finished task. Append-only: a failure stays on file after its later success.

    A ledger that erased failures would hide the thing most worth seeing — that a task needed three
    attempts, or that it has been failing quietly for a week.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "digest": digest,
        "task": task,
        "state": state,
        "at": at.isoformat(),
        "detail": detail,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def completed(digest: str, path: Path = LEDGER_PATH) -> set[str]:
    """Tasks already done for this snapshot. A failed task is NOT done and will be retried.

    Scoped by digest on purpose: change the inputs and every task is pending again, because work
    finished against different holdings is not work finished against these.
    """
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


def pending(digest: str, tasks: Iterable[str], path: Path = LEDGER_PATH) -> list[str]:
    """What is left to do, in the order given. This is the whole of "resume where it stopped"."""
    done = completed(digest, path)
    return [t for t in tasks if t not in done]


def history(path: Path = LEDGER_PATH, *, limit: int = 50) -> list[TaskRecord]:
    """The recent trail, newest last — what ran, what failed, and when."""
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
