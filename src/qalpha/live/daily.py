"""The evening pipeline, on this machine — what the cron used to do, where you can watch it.

### Why this module exists

``.github/workflows/paper.yml`` ran five steps every weekday at 12:23 UTC: refresh prices, mark the
paper book, read filings, write the brief, step the twin. Across 60 scheduled runs **not one fired
on time** — median lateness 2.4 hours — and the workflow's own ``continue-on-error`` reported a step
that had been SIGKILLed at 20m12s as a success. The schedule was never the useful part; the *step
list* was. This module is that list, run when you press the button, on hardware you can see.

### The three rules it is built on

1. **A failed step is recorded and the run continues.** The cron was fail-soft too, and that was
   the problem: every step reported success whatever happened, so a dead credential degraded the
   whole pipeline silently for as long as nobody looked. Here a failure is *written down and
   surfaced on the page*, which is what fail-soft was supposed to mean.
2. **Finished work is never redone.** Each step's completion is appended to the task ledger against
   the digest of the inputs it ran on. Stop the machine halfway, come back in two days, and it
   resumes at the step it had not reached — because that is what a ledger is for.
3. **Changing the inputs makes everything pending again.** The digest covers the holdings, the cash
   and the price panel. Work finished against yesterday's prices is not work finished against
   today's, and pretending otherwise is how a stale number becomes an order.

Nothing here places an order, and no step in the list could.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from qalpha.live.progress import LOG, Progress
from qalpha.live.session import LEDGER_PATH, completed, record_task


@dataclass(frozen=True)
class Step:
    """One unit of the evening's work, named so its absence can be reported."""

    name: str
    #: One line, written for the page rather than the log — this is what the user reads while it runs.
    what: str
    run: Callable[[], None]
    #: Environment variables without which this step cannot do its job. A step missing one is
    #: **skipped and said so**, never run into a confusing failure.
    needs: tuple[str, ...] = ()
    #: Why it is worth the wait, shown when it is the slow one.
    slow: bool = False


@dataclass(frozen=True)
class StepOutcome:
    """What became of one step. ``skipped`` is a first-class result, not a quiet nothing."""

    name: str
    state: str  # "done" | "failed" | "skipped" | "already"
    detail: str
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.state in ("done", "already")


@dataclass
class PipelineResult:
    """The evening, summarised for the page."""

    outcomes: list[StepOutcome] = field(default_factory=list)

    @property
    def failed(self) -> list[StepOutcome]:
        return [o for o in self.outcomes if o.state == "failed"]

    @property
    def skipped(self) -> list[StepOutcome]:
        return [o for o in self.outcomes if o.state == "skipped"]

    @property
    def complete(self) -> bool:
        """True only when every step either ran or had already run. A skip is not completeness."""
        return bool(self.outcomes) and all(o.state in ("done", "already") for o in self.outcomes)

    def notes(self) -> list[str]:
        """Sentences for the page. Silence about a step that did not run is the failure mode here."""
        out: list[str] = []
        for outcome in self.failed:
            out.append(f"{outcome.name} FAILED: {outcome.detail}. Anything it feeds is unchanged.")
        for outcome in self.skipped:
            out.append(f"{outcome.name} was skipped: {outcome.detail}")
        return out


# --------------------------------------------------------------------------------------------
# The steps themselves. Each is a thin call into an entry point that already exists and is already
# tested; this module owns the ORDER and the BOOKKEEPING, and deliberately owns no analysis.
# --------------------------------------------------------------------------------------------


def _step_prices() -> None:
    import paper

    paper._refresh_prices()


def _step_mark() -> None:
    import paper

    paper.main(["dashboard"])


def _step_evidence() -> None:
    import evidence

    evidence.main(["daily"])


def _step_twin() -> None:
    import twin

    twin.main(["daily"])


def _step_brief() -> None:
    import ai_brief

    ai_brief.main(["daily"])


def refresh_steps() -> list[Step]:
    """The step that **creates** the day's inputs, so it cannot be guarded by their digest.

    Everything downstream is keyed to a fingerprint of the prices and the holdings. Refreshing
    prices is what *changes* that fingerprint, so it runs first and is scoped to the calendar day
    instead — see :func:`day_scope`. Re-running it is harmless and is usually what you want.
    """
    return [Step("prices", "Pulling closing prices and the benchmark", _step_prices)]


def day_scope(on: date) -> str:
    """The ledger key for work scoped to a day rather than to a set of inputs."""
    return f"day:{on.isoformat()}"


def research_steps() -> list[Step]:
    """The work done **against** a fixed set of inputs, and therefore resumable across days.

    Filings before the twin, so the autonomous books step on the evidence rather than ahead of it.
    The account layer is **not** in this list — it runs after, in ``local_run``, because a proposal
    must be the last thing decided and must see everything above it.
    """
    return [
        Step(
            "mark",
            "Marking the model book to today's close",
            _step_mark,
        ),
        Step(
            "evidence",
            "Reading company filings and the exchange's own surveillance file",
            _step_evidence,
            slow=True,
        ),
        Step(
            "twin",
            "Stepping the autonomous books and grading them against the fund",
            _step_twin,
        ),
        Step(
            "brief",
            "Writing the market brief",
            _step_brief,
            # The brief is built on server-side web search. There is no local substitute: a local
            # model asked for today's news would produce fluent recalled training data with
            # today's date on it, which is this repo's worst failure mode wearing the feature's
            # clothes. Absent a key it does not run, and the page says the brief is missing.
            needs=("ANTHROPIC_API_KEY",),
        ),
    ]


def steps() -> list[Step]:
    """Both phases, in the order they run. For display and for tests; the runner takes them apart."""
    return refresh_steps() + research_steps()


def _missing(needs: Sequence[str]) -> list[str]:
    import os

    return [name for name in needs if not os.environ.get(name, "").strip()]


def run_pipeline(
    digest: str,
    *,
    plan: Sequence[Step] | None = None,
    ledger: Path = LEDGER_PATH,
    log: Progress = LOG,
    force: bool = False,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> PipelineResult:
    """Run what this digest still needs. Returns what happened to every step, including the skips.

    ``force`` re-runs steps already marked done for this digest — for when a step succeeded but its
    output was wrong, which the ledger cannot know.
    """
    plan = list(plan if plan is not None else steps())
    done = set() if force else completed(digest, ledger)
    result = PipelineResult()

    for step in plan:
        if step.name in done:
            log.say(f"{step.name}: already done for these inputs — skipping.", "detail")
            result.outcomes.append(
                StepOutcome(step.name, "already", "already run against these exact inputs")
            )
            continue

        absent = _missing(step.needs)
        if absent:
            detail = f"{', '.join(absent)} is not set, so it could not run"
            log.say(f"{step.name}: {detail}.", "warn")
            # NOT written to the ledger. A skip is not a completion, and tomorrow — with the
            # credential in place — this step must be pending again rather than counted as done.
            result.outcomes.append(StepOutcome(step.name, "skipped", detail))
            continue

        log.say(step.what + ("… (this is the slow one)" if step.slow else "…"), "step")
        started = time.monotonic()
        try:
            step.run()
        except Exception as exc:  # one dead step must not end the evening
            elapsed = time.monotonic() - started
            detail = f"{type(exc).__name__}: {exc}"
            log.say(f"{step.name} failed after {elapsed:.0f}s — {detail}", "error")
            record_task(digest, step.name, "failed", now(), detail=detail, path=ledger)
            result.outcomes.append(StepOutcome(step.name, "failed", detail, elapsed))
            continue

        elapsed = time.monotonic() - started
        log.say(f"{step.name} finished in {elapsed:.0f}s.", "done")
        record_task(digest, step.name, "done", now(), detail=f"{elapsed:.0f}s", path=ledger)
        result.outcomes.append(StepOutcome(step.name, "done", f"{elapsed:.0f}s", elapsed))

    return result
