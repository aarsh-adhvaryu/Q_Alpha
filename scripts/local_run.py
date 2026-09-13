"""Q-Alpha, local: run the evening, write the page.

    uv run python scripts/local_run.py --app --autorun   # the app, evening started (the desktop click)
    uv run python scripts/local_run.py                   # run once, write the page, open it
    uv run python scripts/local_run.py --no-pipeline     # redraw the page from what is on disk
    uv run python scripts/local_run.py --prices-only     # refresh prices, then redraw
    uv run python scripts/local_run.py --force           # re-run steps the ledger calls done

The evening: prices → filings → headlines → the books. Each step's completion is keyed to its inputs,
so an interrupted evening resumes where it stopped. A failed step is recorded and the evening goes on;
its failure is written into the page, never swallowed.

No broker is contacted. The books are seeded from the tradebook exports in ``data/tradebooks/``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qalpha.live import atomic
from qalpha.live.browser import open_url
from qalpha.live.console import use_utf8
from qalpha.live.daily import day_scope, refresh_steps, research_steps, run_pipeline
from qalpha.live.extraction import EXTRACTION_VERSION
from qalpha.live.panels import BENCHMARK_PANEL, NIFTY50_PANEL, WATCHLIST_PANEL
from qalpha.live.progress import LOG
from qalpha.live.session import research_digest

PAGE = Path("data/session/qalpha.html")
LAST_RUN = Path("data/session/last_run.json")
LEDGER = Path("data/session/ledger.jsonl")


def _scope(today: date, notes: list[str]) -> list[str]:
    """The names this evening reads about. A scope that cannot be computed is said, not guessed."""
    from qalpha.live.screen import research_scope

    try:
        return research_scope(today)
    except Exception as exc:
        notes.append(
            f"Could not work out which names to read about ({type(exc).__name__}: {exc}). "
            "Filings and headlines were not read this evening."
        )
        return []


def main(argv: list[str] | None = None) -> int:
    use_utf8()  # first: Windows pipes fall back to cp1252 and die on a rupee sign
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--app", action="store_true", help="serve the local app instead")
    ap.add_argument("--port", type=int, default=8787, help="port for --app (loopback only)")
    ap.add_argument("--autorun", action="store_true", help="with --app: start the evening at once")
    ap.add_argument("--no-open", action="store_true", help="write the page, do not open a browser")
    ap.add_argument("--no-pipeline", action="store_true", help="redraw the page only")
    ap.add_argument("--prices-only", action="store_true", help="refresh prices, then redraw")
    ap.add_argument(
        "--force", action="store_true", help="re-run steps already done for these inputs"
    )
    args = ap.parse_args(argv)

    if args.app:
        from qalpha.live.server import serve

        serve(args.port, open_browser=not args.no_open, autorun=args.autorun)
        return 0

    today = date.today()
    notes: list[str] = []
    if not args.no_pipeline:
        # Prices first: they CREATE the inputs everything after is keyed to, so this step is scoped
        # to the calendar day rather than to a digest of what it is about to change.
        refresh = run_pipeline(
            day_scope(today), plan=refresh_steps(), ledger=LEDGER, force=args.force
        )
        notes += refresh.notes()
    if not (args.no_pipeline or args.prices_only):
        names = _scope(today, notes)
        digest = research_digest(
            as_of=today,
            names=names,
            panels=[WATCHLIST_PANEL, BENCHMARK_PANEL, NIFTY50_PANEL],
            extraction_version=EXTRACTION_VERSION,
        )
        research = run_pipeline(digest, plan=research_steps(), ledger=LEDGER, force=args.force)
        notes += research.notes()
        if not research.complete:
            LOG.say("The evening is INCOMPLETE — the page says which step and why.", "warn")
        atomic.write_text(
            LAST_RUN,
            json.dumps(
                {"finished_at": datetime.now(UTC).isoformat(timespec="seconds"), "notes": notes},
                indent=2,
            )
            + "\n",
        )

    from qalpha.live.record import dashboard_html

    atomic.write_text(PAGE, dashboard_html())
    LOG.say(f"Wrote {PAGE}", "done")
    for note in notes:
        print(f"  · {note}")
    if not args.no_open and not open_url(PAGE.resolve().as_uri()):
        print(f"Could not open a browser. The page is at {PAGE.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
