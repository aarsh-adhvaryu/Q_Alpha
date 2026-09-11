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
    #: Variables of which **at least one** must be set. For work that has two routes: the brief can
    #: be written by a local model over archived headlines or by a cloud model over web search, and
    #: requiring the cloud key alone would skip it on a machine that can do the job.
    needs_any: tuple[str, ...] = ()
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
            detail = outcome.detail.rstrip(".")
            out.append(f"{outcome.name} FAILED: {detail}. Anything it feeds is unchanged.")
        for outcome in self.skipped:
            out.append(f"{outcome.name} was skipped: {outcome.detail}")
        return out


# --------------------------------------------------------------------------------------------
# The steps themselves. Each is a thin call into an entry point that already exists and is already
# tested; this module owns the ORDER and the BOOKKEEPING, and deliberately owns no analysis.
# --------------------------------------------------------------------------------------------


def _checked(name: str, code: int) -> None:
    """Turn a non-zero exit code into a failure the ledger can see.

    These entry points are CLI programs: they report refusals by exit code, not by raising. The
    twin's abort is the case that matters — it declines to write when the tradebook reads empty but
    the books hold flows, which is a failed read rather than an empty account. Ignoring the code
    meant the ledger recorded the twin as having stepped while the model book stood still, and the
    page told the user the evening had completed.
    """
    if code:
        raise RuntimeError(
            f"{name} exited {code} — it declined to write. Whatever it maintains is unchanged "
            f"from the last successful run; see the output above for the reason it gave."
        )


def _step_prices() -> None:
    """Bring EVERY panel a run reads up to date, not just the paper book's.

    This used to call ``paper._refresh_prices()`` alone, which rebuilds the book's panel from the
    Nifty-50 membership list. The screen reads a different panel built from the 96-name watchlist,
    and nothing refreshed it — so the gate said "prices are 13 days old" and pressing **Refresh
    market data** could never make that untrue. See :mod:`qalpha.live.panels`.
    """
    from qalpha.data.ingest import download_prices, save_parquet
    from qalpha.data.prices import PriceData
    from qalpha.live.panels import BENCHMARK_PANEL, BENCHMARK_TICKER, refresh_targets

    failures: list[str] = []
    for panel, universe in refresh_targets():
        if not universe.exists():
            # NOT skipped quietly: a missing ticker list means this panel silently stops being
            # refreshed, which is the exact failure this function was rewritten to end.
            failures.append(
                f"{panel.name}: its universe {universe} is missing, so it was NOT refreshed"
            )
            continue
        tickers = [str(t) for t in _universe_tickers(universe)]
        LOG.say(f"{panel.name}: {len(tickers)} names…", "detail")
        frame = download_prices(tickers, "2012-01-01", None)
        save_parquet(frame, str(panel))
        LOG.say(f"{panel.name} → {PriceData.from_long(frame).dates[-1].date()}", "detail")

    # The benchmark, inline rather than through `paper._refresh_benchmark`: this is three lines,
    # and a module under src/ reaching into scripts/ only works when scripts/ happens to be on
    # sys.path — which is true when launched by local_run and false everywhere else, tests included.
    LOG.say(f"{BENCHMARK_PANEL.name}: the Nifty TRI proxy…", "detail")
    save_parquet(download_prices([BENCHMARK_TICKER], "2012-01-01", None), str(BENCHMARK_PANEL))

    if failures:
        raise RuntimeError("; ".join(failures))


def _universe_tickers(path: Path) -> list[str]:
    """The distinct tickers of a universe CSV, in file order.

    **De-duplicated, and that is not tidiness.** The two universes have different shapes: the
    watchlist is one row per name, while the book's file is point-in-time *membership* — one row per
    name PER SPELL, so a name that left the index and came back appears twice (GRASIM and VEDL do).
    Passing the raw column downloads those names twice and the resulting frame cannot be pivoted::

        ValueError: Index contains duplicate entries, cannot reshape

    The first version returned the column verbatim, which is right for one file and wrong for the
    other. Found by running the refresh, not by reading it.
    """
    import csv

    seen: dict[str, None] = {}
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            ticker = (row.get("ticker") or "").strip()
            if ticker:
                seen.setdefault(ticker, None)
    return list(seen)


def _step_mark() -> None:
    import paper

    _checked("paper dashboard", paper.main(["dashboard"]))


def _step_evidence() -> None:
    import evidence

    _checked("evidence", evidence.main(["daily"]))


def _step_news() -> None:
    import news

    _checked("news", news.main(["daily"]))


def _step_twin() -> None:
    import twin

    _checked("twin", twin.main(["daily"]))


def _step_brief() -> None:
    import ai_brief

    _checked("ai_brief", ai_brief.main(["daily"]))


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

    Filings, then headlines, then the twin — so the autonomous books step on the evidence rather
    than ahead of it, and the brief is written from headlines this run actually fetched. The account
    layer is **not** in this list: it runs after, in ``local_run``, because a proposal must be the
    last thing decided and must see everything above it.
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
            "news",
            "Fetching, archiving and reading the day's headlines",
            _step_news,
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
            # **The objection was never the model; it was the retrieval.** A local model asked for
            # today's news would produce fluent recalled training data with today's date on it,
            # which is this repo's worst failure mode wearing the feature's clothes. The `news`
            # step above now archives real headlines, so a local model has something to read and
            # every claim in the brief cites an item on disk. Either route works; with neither, it
            # does not run and the page says the brief is missing.
            needs_any=("QALPHA_LOCAL_MODEL", "ANTHROPIC_API_KEY"),
        ),
    ]


def steps() -> list[Step]:
    """Both phases, in the order they run. For display and for tests; the runner takes them apart."""
    return refresh_steps() + research_steps()


def _missing(needs: Sequence[str]) -> list[str]:
    import os

    from qalpha.live.credentials import load_env

    # HYDRATE .env FIRST. The app is launched from a shortcut whose shell exports nothing, so a
    # check reading os.environ alone would skip a step for a credential the user had already set —
    # the defect `localmodel.configured` and `server._token_rows` were both fixed for.
    load_env()
    return [name for name in needs if not os.environ.get(name, "").strip()]


def _none_of(names: Sequence[str]) -> bool:
    """True when a step's alternatives are ALL absent. Empty means the step has no alternatives."""
    return bool(names) and len(_missing(names)) == len(names)


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
        if not absent and _none_of(step.needs_any):
            absent = list(step.needs_any)
        if absent:
            detail = (
                f"{', '.join(absent)} is not set, so it could not run"
                if len(absent) == 1
                else f"none of {', '.join(absent)} is set, so it could not run"
            )
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
