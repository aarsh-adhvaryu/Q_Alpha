"""Which code is this process actually running, and is it still the code on disk?

### Why this exists

A fix was written, the app was restarted — except it was not, and the app looked identical either
way. The user pressed a button, got the same error as before, and reasonably concluded the fix had
not worked. The gap between "the file is fixed" and "the running process has the fix" was five
minutes and completely invisible from the page.

A long-running local server started by double-clicking a shortcut is exactly the shape of program
where this happens: nothing about it says when it started, and the fix arrives by editing files
underneath it. The window that launched it usually is not the window you are reading.

### What it reports, and what it refuses to guess

The process start time is known exactly. The code's age is the newest modification time across the
live modules and the entry point — good enough to answer "is the thing on disk newer than the thing
running", which is the only question being asked. It is **not** used to claim a version: an mtime is
reset by a fresh checkout, so a checkout can look newer than a process it predates. That is why
:attr:`Build.stale` is the headline and the timestamps are the supporting detail — the comparison is
reliable in the direction that matters (code newer than process ⇒ restart), and a false alarm costs
a restart while a false all-clear costs an afternoon.

The git revision is reported when git can be asked and omitted when it cannot. A commit id nobody
can produce is worse than no commit id.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from qalpha.live.progress import IST

#: When this interpreter started. Bound at import, which is as close as it gets.
STARTED = datetime.now(IST)

#: Everything whose edit means the running process is out of date.
WATCHED = ("src/qalpha/live", "scripts/local_run.py")


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def code_changed_at(root: Path | None = None) -> datetime | None:
    """Newest modification time across the watched paths, or ``None`` when none can be read."""
    base = root or _root()
    newest: float | None = None
    for name in WATCHED:
        target = base / name
        candidates = target.rglob("*.py") if target.is_dir() else [target]
        for path in candidates:
            try:
                stamp = path.stat().st_mtime
            except OSError:
                continue
            if newest is None or stamp > newest:
                newest = stamp
    return None if newest is None else datetime.fromtimestamp(newest, IST)


def revision(root: Path | None = None) -> str:
    """``<short sha>`` (plus ``+dirty``), or ``""`` when git cannot say."""
    base = root or _root()
    try:
        sha = subprocess.run(
            ["git", "-C", str(base), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if sha.returncode != 0:
            return ""
        head = sha.stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(base), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return f"{head}+dirty" if dirty.stdout.strip() else head
    except (OSError, subprocess.SubprocessError):
        return ""


@dataclass(frozen=True)
class Build:
    """What is running, when it started, and whether the disk has moved on since."""

    started: datetime
    code_at: datetime | None
    rev: str

    @property
    def stale(self) -> bool:
        """Has the code been edited since this process loaded it?

        ``None`` code time answers ``False``: not knowing is not evidence of staleness, and a
        permanent restart nag is a warning people learn to ignore.
        """
        return self.code_at is not None and self.code_at > self.started

    def chip_text(self) -> str:
        if self.stale:
            return "restart to pick up changes"
        return f"started {self.started:%H:%M}" + (f" · {self.rev}" if self.rev else "")

    def sentence(self) -> str:
        """The long form, for when the chip is not enough."""
        started = f"This app started at {self.started:%H:%M} IST"
        if self.rev:
            started += f", running {self.rev}"
        if not self.stale:
            return started + ". The code on disk has not changed since."
        assert self.code_at is not None
        return (
            f"{started}, but the code was edited at {self.code_at:%H:%M} — AFTER this process "
            "loaded it. What you are looking at is the old version. Close the window that launched "
            "this and start it again."
        )


def current(root: Path | None = None) -> Build:
    return Build(started=STARTED, code_at=code_changed_at(root), rev=revision(root))
