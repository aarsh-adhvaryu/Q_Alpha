"""Daily AI market brief CLI — the "macro analyst" that rides the paper cron.

**Context only, never a signal** (see :mod:`qalpha.live.ai_brief`). One web-searched Claude Haiku call
per trading day → archive to ``reports/ai_brief.md`` (committed, read by the Auto-pilot tab) → emit the
machine-readable ``SIGNAL`` line the auto-pilot's Book B acts on via a fixed rule. Optionally pushes to
Telegram if configured. **Rule (a) intact:** it never computes a number for the validated engine.

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

from qalpha.live.ai_brief import BriefResult, generate_brief, load_watchlist_lines
from qalpha.live.notify import send_telegram

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
    BRIEF_MD.write_text(result.raw + footer + "\n", encoding="utf-8")
    BRIEF_STAMP.write_text(
        json.dumps(
            {
                "as_of": date.today().isoformat(),
                "written_at": datetime.now(UTC).isoformat(),
                "model": result.model,
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
