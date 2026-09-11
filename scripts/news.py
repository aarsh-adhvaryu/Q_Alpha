"""The news spine — fetch the day's headlines, archive them, map them, read them. Flags only.

    uv run python scripts/news.py daily      # the step the evening runs
    uv run python scripts/news.py daily --dry-run   # fetch and archive; read nothing

Rules frozen in ``reports/PREREGISTRATION_NEWS_V1.md`` before the first feed was archived.

**It decides nothing.** It writes verified rows to ``data/evidence/news_events.jsonl`` and a coverage
row per name; :mod:`qalpha.live.pretrade` decides what they mean, and the strongest thing they can
produce is a ``WATCH``. Nothing here can remove a name from a basket.

**The bytes come first.** Every feed response is written with its provenance sidecar before anything
parses it, so a quote in an event row can be checked against the characters that produced it a year
from now — the property that separates this from the veto that cited a stock quote page.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qalpha.config import Config
from qalpha.live.localmodel import choose_backend
from qalpha.live.news import (
    ALIASES,
    LOOKBACK_DAYS,
    MARKET_FEEDS,
    NEWS_EVENTS,
    NEWS_VERSION,
    FeedArchive,
    NewsItem,
    fetch_and_archive_feed,
    google_news_feed,
    load_aliases,
    map_items,
    news_rows,
    read_news,
    write_items,
)
from qalpha.live.pretrade import NewsCoverage

NEWS_COVERAGE = Path("data/evidence/news_coverage.jsonl")

#: A budget, not a cap — the same shape the evidence spine uses. Everything read before it is on
#: disk; the names not reached are named, and tomorrow's run continues rather than restarting.
BUDGET_SECONDS = int(os.environ.get("NEWS_BUDGET_SECONDS", "600"))


def _scope(cfg: Config, as_of: date) -> list[str]:
    """The names worth spending a search on: what the screen proposes plus what is held.

    Not the whole watchlist. Ninety-six searches a day is a request rate that gets a machine
    blocked, and the flags exist for the basket in front of the user, not for the index.
    """
    from evidence import _screen_basket

    return list(_screen_basket(cfg, as_of).tickers)


def _archive(scope: list[str], as_of: date) -> tuple[list[FeedArchive], list[str], int]:
    """Fetch and keep every feed. Returns ``(archives, failures, attempted)``.

    A failed fetch and an empty feed are different facts and are counted differently: the first is
    a gap this run must report, the second is a day on which that source published nothing.
    """
    aliases = load_aliases(ALIASES)
    feeds = list(MARKET_FEEDS)
    for ticker in scope:
        names = aliases.get(ticker)
        if names:
            feeds.append(google_news_feed(ticker, names[0]))
        else:
            print(f"  {ticker:<16} no alias on file — it cannot be searched for or matched")

    archives: list[FeedArchive] = []
    failures: list[str] = []
    for feed in feeds:
        archive = fetch_and_archive_feed(feed, as_of)
        if archive is None:
            failures.append(feed.id)
            print(f"  {feed.id:<20} UNREACHABLE — that is a gap, not a quiet day")
            continue
        if archive.stale(as_of):
            failures.append(feed.id)
            newest = archive.items[0].published_at.date() if archive.items else None
            print(f"  {feed.id:<20} STALE (newest item {newest}) — treated as unreadable")
            continue
        archives.append(archive)
    return archives, failures, len(feeds)


def _record_coverage(as_of: date, ticker: str, coverage: NewsCoverage) -> None:
    """One row per name, written **inside the loop**.

    The evidence spine learned this the hard way: a bulk write after the loop meant a timeout left
    110 events on disk and zero coverage rows, so every name read "not read" while its findings sat
    in the log beside it.
    """
    from qalpha.live.twin import _append_jsonl

    _append_jsonl(
        NEWS_COVERAGE,
        [
            {
                "as_of": as_of.isoformat(),
                "ticker": ticker,
                "feeds_attempted": coverage.feeds_attempted,
                "feeds_failed": coverage.feeds_failed,
                "items_scanned": coverage.items_scanned,
                "items_for_name": coverage.items_for_name,
                "extraction_ran": coverage.extraction_ran,
                "news_version": NEWS_VERSION,
                "_key": f"{as_of.isoformat()}:{ticker}",
            }
        ],
        key="_key",
    )


def cmd_daily(cfg: Config, as_of: date, *, dry_run: bool = False) -> int:
    print(f"[news] {NEWS_VERSION} — archives headlines, flags names, decides nothing")
    scope = _scope(cfg, as_of)
    if not scope:
        print("[news] no candidates and no holdings — nothing to cover")
        return 0

    archives, failures, attempted = _archive(scope, as_of)
    if not archives:
        # NON-ZERO. Every feed failing is a dead layer, and the ledger has to record it as a failure
        # so tomorrow's run tries again rather than resuming past it.
        print(
            f"[news] every one of {attempted} feed(s) failed or was stale. Nothing was read.",
            file=sys.stderr,
        )
        return 1

    items: list[NewsItem] = []
    seen: set[str] = set()
    for archive in archives:
        for item in archive.items:
            if item.id not in seen and (as_of - item.published_at.date()).days <= LOOKBACK_DAYS:
                seen.add(item.id)
                items.append(item)

    aliases = load_aliases(ALIASES)
    mapped = map_items(items, aliases)
    # Only what is about a name we care about, plus the market feeds' own items, which the brief is
    # written from. The rest is a day's newspaper about companies nobody here holds.
    market_ids = {f.id for f in MARKET_FEEDS}
    keep = [i for i in mapped if i.tickers or i.feed_id in market_ids]
    write_items(keep, as_of)
    for_scope = [i for i in keep if any(t in scope for t in i.tickers)]
    print(
        f"[news] {len(archives)} feed(s) read, {len(failures)} failed/stale · {len(items)} item(s) "
        f"in the last {LOOKBACK_DAYS} days · {len(for_scope)} about the {len(scope)} name(s) in scope"
    )

    backend = choose_backend()
    print(f"[news] {backend.note}")
    if dry_run or backend.generate is None:
        if backend.generate is None:
            print("[news] nothing read them, so every name reads UNKNOWN. Archived is not read.")
        for ticker in scope:
            _record_coverage(
                as_of,
                ticker,
                NewsCoverage(
                    feeds_attempted=attempted,
                    feeds_failed=len(failures),
                    items_scanned=len(keep),
                    items_for_name=sum(1 for i in for_scope if ticker in i.tickers),
                    extraction_ran=False,
                    news_version=NEWS_VERSION,
                ),
            )
        return 0

    started = datetime.now(UTC)
    budget = timedelta(seconds=BUDGET_SECONDS)
    read_any = False
    for index, ticker in enumerate(scope):
        if datetime.now(UTC) - started > budget:
            print(
                f"[news] time budget {budget} reached after {index}/{len(scope)} name(s). Stopping "
                "cleanly — everything read is on disk and the rest resume tomorrow."
            )
            break
        mine = [i for i in for_scope if ticker in i.tickers]
        ran = False
        if mine:
            found, discarded, _raw, usage = read_news(
                mine,
                generate=backend.generate,
                model=backend.model,
                batch_chars=min(backend.batch_chars or 12_000, 12_000),
            )
            ran = usage["failed_batches"] == 0
            if not ran:
                cut = usage["truncated_batches"]
                why = f"{usage['failed_batches']} failed batch(es)"
                if cut:
                    why += f", {cut} cut off at the token cap"
                print(f"  {ticker:<16} {why} — coverage stays incomplete")
            elif found:
                rows = news_rows(found, as_of=as_of)
                from qalpha.live.twin import _append_jsonl

                _append_jsonl(NEWS_EVENTS, rows, key="_key")
                flagged = sum(1 for e in found if e.flags)
                print(
                    f"  {ticker:<16} {len(mine)} item(s) read → {len(found)} labelled"
                    + (f", {flagged} FLAGGED" if flagged else "")
                    + (f" ({discarded} discarded)" if discarded else "")
                )
        else:
            ran = True  # nothing matched: a real answer, and the coverage row says how many we read
        read_any = read_any or ran
        _record_coverage(
            as_of,
            ticker,
            NewsCoverage(
                feeds_attempted=attempted,
                feeds_failed=len(failures),
                items_scanned=len(keep),
                items_for_name=len(mine),
                extraction_ran=ran,
                news_version=NEWS_VERSION,
            ),
        )
    return 0 if read_any else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    daily = sub.add_parser("daily", help="fetch, archive, map and read today's headlines")
    daily.add_argument("--dry-run", action="store_true", help="archive only; read nothing")
    daily.add_argument("--as-of", default="", help="YYYY-MM-DD (defaults to today)")
    args = parser.parse_args(argv)
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    return cmd_daily(Config(), as_of, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
