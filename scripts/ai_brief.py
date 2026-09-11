"""Daily AI market brief CLI — the "macro analyst" that rides the paper cron.

**Context only, never a signal** (see :mod:`qalpha.live.ai_brief`). One call per trading day →
archive to ``reports/ai_brief.md`` → optionally push to Telegram. **Rule (a) intact:** it never
computes a number for the validated engine.

**Two routes.** A local model reads the headlines the `news` step archived this run and cites an
item id for every claim (``BRIEF-2-local``); with a cloud key and no local model, Claude searches the
web (``BRIEF-1``). The stamp records which, because they are not the same brief. With neither, and
with no headlines, nothing is written — a model asked what happened today with nothing to read would
answer from its training data, and that answer would look exactly like the feature working.

    ai_brief.py daily              # generate → write reports/ai_brief.md (+ Telegram if configured)
    ai_brief.py daily --dry-run    # generate + print only (no send, no file write)

A missing key or an empty response skips the brief and returns 0 — those are *absences*, and the
page says the brief is missing. An actual failure is raised, because the caller
(:mod:`qalpha.live.daily`) writes down what happened, and a swallowed exception would be recorded as
a brief that was written.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path

from qalpha.live.ai_brief import (
    BRIEF_VERSION,
    BriefResult,
    Headline,
    generate_brief,
    generate_local_brief,
    index_move,
    load_watchlist_lines,
)
from qalpha.live.console import use_utf8
from qalpha.live.localmodel import choose_backend
from qalpha.live.news import MARKET_FEEDS, market_headlines
from qalpha.live.notify import send_telegram
from qalpha.live.panels import BENCHMARK_PANEL

WATCHLIST_CSV = Path("data/universes/nifty100_watchlist.csv")
BRIEF_MD = Path("reports/ai_brief.md")
#: WHEN the brief was written, beside it. The markdown carries no date, and a file's mtime is reset
#: by a fresh checkout — so a brief about a market three weeks gone would render as this morning's
#: with nothing to contradict it. The page refuses to date an unstamped brief rather than guess.
BRIEF_STAMP = Path("reports/ai_brief.json")


def _usage_footer(result: BriefResult) -> str:
    """A compact token-usage line appended to the brief — cost/completeness visible on the phone and
    in the committed archive without opening the Anthropic console."""
    usage = result.usage or {}
    note = " ⚠️ cut off (raise max_tokens)" if usage.get("truncated") else " ✓ complete"
    return f"\n\n— 🤖 {result.model} · {usage.get('input', 0):,} in / {usage.get('output', 0):,} out tokens ·{note}"


def main(argv: list[str] | None = None) -> int:
    # UTF-8 FIRST, before anything prints. Windows falls back to cp1252 when stdout is a pipe,
    # and `uv run` pipes its child: on 2026-09-11 the `mark` step died on a rupee sign.
    use_utf8()
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_daily = sub.add_parser("daily", help="generate today's brief, archive it, send to Telegram")
    p_daily.add_argument(
        "--dry-run", action="store_true", help="print the brief without sending or writing"
    )
    args = parser.parse_args(argv)

    # No swallow here either, for the reason spelled out in scripts/twin.py: the caller is now a
    # ledger that writes down what happened, and an exception turned into `return 0` would be
    # recorded as a brief that was written. `run_pipeline` catches this and carries on.
    watchlist = load_watchlist_lines(str(WATCHLIST_CSV)) if WATCHLIST_CSV.exists() else []
    if not watchlist:
        print(f"[ai-brief] watchlist missing at {WATCHLIST_CSV} — skipping.")
        return 0

    # WHICH ROUTE, AND SAY SO. A local model reads headlines this run archived; the cloud one
    # searches the web. They are different briefs and the stamp records which was written, because
    # "the market, in words" means something different depending on where the words came from.
    backend = choose_backend()
    move = index_move(str(BENCHMARK_PANEL))
    source, headlines = "web-search", []
    if backend.kind == "local" and backend.generate is not None:
        items = market_headlines(date.today())
        headlines = [
            Headline(
                id=i.id,
                title=i.title,
                source=i.source or i.feed_id,
                when=i.published_at.strftime("%Y-%m-%d"),
            )
            for i in items
        ]
        print(f"[ai-brief] {backend.model}, from {len(headlines)} archived headline(s)")
        result = generate_local_brief(
            headlines, watchlist, generate=backend.generate, model=backend.model
        )
        source = "local-rss"
    else:
        result = generate_brief(watchlist)

    if result is None:
        return 0  # already logged the reason

    footer = _usage_footer(result)
    print(f"[ai-brief] {footer.strip().lstrip('—').strip()}")
    if args.dry_run:
        print("\n--- brief (dry run, not sent) ---\n")
        print(result.text + footer)
        return 0

    BRIEF_MD.parent.mkdir(parents=True, exist_ok=True)
    # THE NUMBER IS WRITTEN BY CODE, ABOVE THE MODEL'S WORDS. Asking a model to restate a figure
    # this system already computed is how two versions of one number end up on one page.
    heading = f"_{move.sentence()}_\n\n" if move is not None else ""
    if move is None:
        heading = "_The benchmark panel does not carry two closes, so no move is quoted here. "
        heading += "Unmeasured, not flat._\n\n"
    BRIEF_MD.write_text(heading + result.raw + footer + "\n", encoding="utf-8")
    BRIEF_STAMP.write_text(
        json.dumps(
            {
                "as_of": date.today().isoformat(),
                "written_at": datetime.now(UTC).isoformat(),
                "model": result.model,
                "brief_version": BRIEF_VERSION if source == "local-rss" else "BRIEF-1",
                "source": source,
                "headlines": len(headlines),
                "feeds": [f.id for f in MARKET_FEEDS] if source == "local-rss" else ["web search"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    ok = send_telegram(result.text + footer)
    print(
        f"[ai-brief] archived → {BRIEF_MD} · telegram: {'sent' if ok else 'not configured/failed'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
