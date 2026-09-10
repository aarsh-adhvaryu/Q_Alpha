"""What the run is doing **right now** — the thing a file cannot tell you.

A static page says what happened once the work is over. Watching it happen is a different need:
"is it stuck, or is it downloading nine hundred filings?" is a question you can only answer while it
is still running, and the honest answer to it prevents the two worst reactions to a slow run —
killing it, and assuming it is fine.

So the pipeline narrates itself into this log and the local page reads it. Deliberately small:

* **Thread-safe**, because the run happens on a worker while the page is served on another.
* **Bounded**, because a run that emits ten thousand lines must not grow without limit.
* **Timestamped in IST**, the same clock everything else on the page uses.
* **It never fails the run.** A progress log that can raise is a progress log that can take down the
  thing it is describing, which is an absurd way to lose a day's work.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Literal

IST = timezone(timedelta(hours=5, minutes=30))
Level = Literal["step", "detail", "warn", "error", "done"]

#: Beyond this the oldest lines are dropped. Generous enough to hold a whole run's narration.
MAX_LINES = 400


@dataclass(frozen=True)
class Line:
    at: datetime
    level: Level
    text: str

    def to_dict(self) -> dict[str, str]:
        return {
            "at": self.at.astimezone(IST).strftime("%H:%M:%S"),
            "level": self.level,
            "text": self.text,
        }


class Progress:
    """One run's narration. Written by the pipeline, read by the page."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._lines: list[Line] = []
        self._running = False
        self._started: datetime | None = None
        self._finished: datetime | None = None
        self._failure: str | None = None

    # --- writing -------------------------------------------------------------------------------
    def say(self, text: str, level: Level = "detail") -> None:
        """Add a line. Never raises — see the module docstring."""
        try:
            with self._lock:
                self._lines.append(Line(datetime.now(UTC), level, text))
                if len(self._lines) > MAX_LINES:
                    del self._lines[: len(self._lines) - MAX_LINES]
        except Exception:
            pass

    @contextmanager
    def step(self, text: str) -> Iterator[None]:
        """A named stage. Its failure is recorded and re-raised — the caller still decides."""
        self.say(text, "step")
        try:
            yield
        except Exception as exc:
            self.say(f"{text} — failed: {type(exc).__name__}: {exc}", "error")
            raise

    def begin(self) -> None:
        with self._lock:
            self._lines.clear()
            self._running = True
            self._started = datetime.now(UTC)
            self._finished = None
            self._failure = None

    def end(self, failure: str | None = None) -> None:
        with self._lock:
            self._running = False
            self._finished = datetime.now(UTC)
            self._failure = failure
        self.say(failure or "Finished.", "error" if failure else "done")

    # --- reading -------------------------------------------------------------------------------
    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    def snapshot(self) -> dict[str, object]:
        """Everything the page needs, in one consistent read.

        Taken under the lock so the page can never show a line count that disagrees with the lines —
        two reads of a moving structure is how a status display starts contradicting itself.
        """
        with self._lock:
            elapsed = None
            if self._started is not None:
                end = self._finished or datetime.now(UTC)
                elapsed = int((end - self._started).total_seconds())
            return {
                "running": self._running,
                "elapsed_seconds": elapsed,
                "failure": self._failure,
                "lines": [line.to_dict() for line in self._lines],
            }


#: The process-wide log. One run at a time by design — two concurrent runs would interleave their
#: narration into nonsense and, worse, race on the same ledgers.
LOG = Progress()
