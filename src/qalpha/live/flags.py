"""What the exchange and the filings say about names you are about to buy. **Flags, never vetoes.**

The iron rule on the buy list is *flag, don't veto* — selection stays deterministic and the decision
stays the user's. This module renders what the evidence layer found next to the basket, so a warning
is in front of him at the moment it matters instead of sitting in a report nobody opens.

It **cannot change the basket**. It takes an already-decided list of tickers and returns markdown.
There is no path from here back into selection or sizing, and that is deliberate: the moment a
warning can silently remove a name, the screen is no longer the thing being measured.

**It reads only what is on disk.** No network, no model call, no clock. The daily job archives the
exchange file and the filings; this reads that archive. If the archive is stale or missing it says
so rather than implying a clean bill — an absent warning and no warning are different facts, and
only one of them is reassuring.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from datetime import date, timedelta
from pathlib import Path

from qalpha.live import news
from qalpha.live.evidence import BLOCK, PASS, UNKNOWN, WATCH, Provenance, load_archive
from qalpha.live.evidence import assess as exchange_assess
from qalpha.live.extraction import EXTRACTION_VERSION

EVENT_LOG = Path("data/evidence/events.jsonl")
COVERAGE_LOG = Path("data/evidence/coverage.jsonl")
#: Imported rather than re-spelled, so the reader and the writer cannot drift apart.
NEWS_EVENT_LOG = news.NEWS_EVENTS
NEWS_COVERAGE_LOG = Path("data/evidence/news_coverage.jsonl")

#: A coverage row older than this cannot speak for today's basket.
MAX_COVERAGE_AGE_DAYS = 4

#: How far back to look for an archived exchange file before giving up. The exchange publishes on
#: trading days, so a Monday reads Friday's; beyond this the file is too old to speak for today and
#: the panel says so instead of quietly using it.
MAX_FILE_AGE_DAYS = 4

#: Events at or above this concern level are shown. Defined in the EX-2 prompt as *how much this
#: should worry someone who already owns the shares* — not how newsworthy it is. EX-1 rated routine
#: results `high` and is ignored here by version.
SHOWN_CONCERN = {"high"}


def filings_read(tickers: Iterable[str], *, as_of: date, path: Path | None = None) -> set[str]:
    """Names whose filings were **actually read**, at the current extractor, recently enough.

    ### Why this exists, and why its absence was the worst defect in this file

    The panel used to call a name "clear" whenever the exchange passed and no current-version event
    mentioned it. With zero EX-2 events on file — which is the state after every version bump — that
    made **every** name clear, including names whose filings had never been opened. The module
    docstring in this very file says an absent warning and no warning are different facts and only
    one of them is reassuring. The code said otherwise.

    A name counts as read only when the day's coverage row says ``complete``, was produced by the
    current extraction version, and is no older than :data:`MAX_COVERAGE_AGE_DAYS`.
    """
    wanted = {t.removesuffix(".NS") for t in tickers}
    cutoff = (as_of - timedelta(days=MAX_COVERAGE_AGE_DAYS)).isoformat()
    read: set[str] = set()
    # AT THE CURRENT REVISION. A coverage row that read `complete` this morning and was superseded
    # by an incomplete one this evening must not still say the filings were read — see `_rows`.
    for row in _rows(path or COVERAGE_LOG):
        if not row.get("complete"):
            continue
        if row.get("extraction_version") != EXTRACTION_VERSION:
            continue
        if str(row.get("as_of", "")) < cutoff:
            continue
        ticker = str(row.get("ticker", "")).removesuffix(".NS")
        if ticker in wanted:
            read.add(ticker)
    return read


def _latest_exchange_file(
    as_of: date,
) -> tuple[dict[str, dict[str, str]], Provenance | None, int]:
    """The most recent archived regulatory-indicator file, and how many days old it is."""
    for back in range(MAX_FILE_AGE_DAYS + 1):
        rows, prov = load_archive(as_of - timedelta(days=back))
        if prov is not None:
            return rows, prov, back
    return {}, None, -1


def recent_concerns(
    tickers: Iterable[str], *, since: date, path: Path | None = None
) -> dict[str, list[dict[str, str]]]:
    """High-concern verified events per ticker, newest first, from the current extractor only.

    Three filters, each of which has already been a defect somewhere in this repo: the quote must
    have been **verified** against the stored document, the row must come from the **current**
    extraction version, and the event must be recent enough to still matter.
    """
    wanted = {t.removesuffix(".NS") for t in tickers}
    out: dict[str, list[dict[str, str]]] = {}
    for row in _rows(path or EVENT_LOG):
        if row.get("kind") != "event" or not row.get("verified"):
            continue
        if row.get("extraction_version") != EXTRACTION_VERSION:
            continue
        if str(row.get("materiality", "")).lower() not in SHOWN_CONCERN:
            continue
        ticker = str(row.get("ticker", "")).removesuffix(".NS")
        if ticker not in wanted:
            continue
        if str(row.get("as_of", "")) < since.isoformat():
            continue
        out.setdefault(ticker, []).append(
            {
                "type": str(row.get("event_type", "")),
                "summary": str(row.get("summary", "")),
                "passage": str(row.get("passage", "")),
                "url": str(row.get("doc_url", "")),
                "on": str(row.get("as_of", "")),
            }
        )
    for events in out.values():
        events.sort(key=lambda e: e["on"], reverse=True)
    return out


def _rows(path: Path) -> list[dict[str, object]]:
    """Every readable row **at its current revision**. An unreadable line is skipped, never guessed.

    ### Why the revision rule is not optional here

    These logs are append-only: a re-read does not replace a row, it appends a new one with the same
    ``_key`` and a higher ``revision``, and the superseded copy stays on file as the record of what
    was believed at the time. Every other reader in this repo follows that (``twin.load_history``,
    ``twin.inceptions``); these two did not, and counted lines.

    **Found in a scratch run on 2026-09-10, before this shipped.** The first archived news run left
    99 lines carrying 90 distinct events, and 9 of those had been re-read in a later batch and come
    back at a lower materiality. Counting lines gave **12 high-materiality negative items**;
    counting the current revision gives **4**. The panel would have printed a number three times
    the one the record actually holds, under a label that says what the record holds.
    """
    if not path.exists():
        return []
    out: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if any("_key" in row for row in out):
        from qalpha.live.twin import latest_by_key

        return latest_by_key(out, key="_key")
    return out


def news_read(tickers: Iterable[str], *, as_of: date, path: Path | None = None) -> set[str]:
    """Names whose day's headlines were **actually read**, at the current version, recently enough.

    The same three filters as :func:`filings_read`, and for the same reason: with zero rows on file
    — the state after every version bump — an "any events?" test would call every name clear.
    """
    wanted = {t.removesuffix(".NS") for t in tickers}
    cutoff = (as_of - timedelta(days=MAX_COVERAGE_AGE_DAYS)).isoformat()
    read: set[str] = set()
    for row in _rows(path or NEWS_COVERAGE_LOG):
        if not row.get("extraction_ran") or row.get("news_version") != news.NEWS_VERSION:
            continue
        if str(row.get("as_of", "")) < cutoff:
            continue
        ticker = str(row.get("ticker", "")).removesuffix(".NS")
        if ticker in wanted:
            read.add(ticker)
    return read


def recent_news(
    tickers: Iterable[str], *, since: date, path: Path | None = None
) -> dict[str, list[dict[str, str]]]:
    """High-materiality verified headline items per ticker, newest first, current version only.

    **Both stances are returned.** The negative ones are the flags; the positive ones exist so the
    page can say *3 negative / 1 positive* rather than showing only the bad half, which would be a
    different claim about the day.
    """
    wanted = {t.removesuffix(".NS") for t in tickers}
    out: dict[str, list[dict[str, str]]] = {}
    for row in _rows(path or NEWS_EVENT_LOG):
        if row.get("kind") != "news" or not row.get("verified"):
            continue
        if row.get("news_version") != news.NEWS_VERSION:
            continue
        if str(row.get("materiality", "")).lower() not in SHOWN_CONCERN:
            continue
        ticker = str(row.get("ticker", "")).removesuffix(".NS")
        if ticker not in wanted:
            continue
        if str(row.get("as_of", "")) < since.isoformat():
            continue
        out.setdefault(ticker, []).append(
            {
                "type": str(row.get("event_type", "")),
                "stance": str(row.get("stance", "")),
                "summary": str(row.get("summary", "")),
                "passage": str(row.get("passage", "")),
                "link": str(row.get("link", "")),
                "source": str(row.get("source", "")),
                "on": str(row.get("as_of", "")),
            }
        )
    for items in out.values():
        items.sort(key=lambda e: e["on"], reverse=True)
    return out


def news_counts(items: Sequence[dict[str, str]]) -> tuple[int, int]:
    """``(negative, positive)`` among high-materiality items. **Counts of ITEMS, never a score.**

    A number in [0, 1] would invite being ranked against, averaged, or optimised for, and a local
    8B model labelling a headline has earned none of that. Two integers and the window they cover
    can be checked by opening the items.

    **An item is a report, not an event, and the first archived run made that concrete:** nine
    flagged items on SHREECEM were nine outlets carrying one Meghalaya High Court order. The count
    is correct and would be misread as nine problems, so every surface that prints it says what it
    counts. Clustering them would mean inventing a similarity score, which is the thing this layer
    is not allowed to have.
    """
    negative = sum(1 for i in items if i.get("stance") == "negative")
    positive = sum(1 for i in items if i.get("stance") == "positive")
    return negative, positive


def flags_markdown(tickers: Sequence[str], *, as_of: date, lookback_days: int = 30) -> str:
    """The panel. Renders under a basket and changes nothing about it."""
    if not tickers:
        return ""
    rows, prov, age = _latest_exchange_file(as_of)
    concerns = recent_concerns(tickers, since=as_of - timedelta(days=lookback_days))

    lines: list[str] = ["#### ⚠️ What the exchange and the filings say", ""]
    if prov is None:
        lines.append(
            f"**No archived exchange file within {MAX_FILE_AGE_DAYS} days.** These names have "
            "**not** been checked against NSE's own indicators. That is not a clean bill — it is a "
            "gap. The daily job archives the file; if this persists, it is not running."
        )
        return "\n".join(lines)

    read = filings_read(tickers, as_of=as_of)
    headlines = recent_news(tickers, since=as_of - timedelta(days=news.LOOKBACK_DAYS))
    heard = news_read(tickers, as_of=as_of)
    flagged: list[str] = []
    clean: list[str] = []
    unread: list[str] = []
    for ticker in tickers:
        verdict = exchange_assess(ticker, rows, prov, as_of=as_of)
        bare = ticker.removesuffix(".NS")
        events = concerns.get(bare, [])
        items = headlines.get(bare, [])
        bad_news = [i for i in items if i.get("stance") == "negative"]
        if verdict.state == PASS and not events and not bad_news:
            # Clear on the exchange and nothing found in the filings — but "nothing found" only
            # means something if the filings were read. Otherwise this is a gap wearing a tick.
            (clean if bare in read else unread).append(ticker)
            continue
        bits: list[str] = []
        if verdict.state == BLOCK:
            bits.append(f"🔴 **exchange: {verdict.detail}**")
        elif verdict.state == WATCH:
            bits.append(f"🟡 exchange: {verdict.detail}")
        elif verdict.state == UNKNOWN:
            bits.append(f"⚪ exchange: {verdict.detail}")
        for event in events[:2]:
            source = f" · [filing]({event['url']})" if event["url"] else ""
            bits.append(f"🟡 {event['type'].replace('_', ' ')}: {event['summary']}{source}")
        for item in bad_news[:2]:
            where = f" · [{item['source'] or 'item'}]({item['link']})" if item["link"] else ""
            bits.append(f"🟡 news: {item['summary']}{where}")
        flagged.append(f"- **{ticker.removesuffix('.NS')}** — " + "; ".join(bits))

    if flagged:
        lines += flagged
    else:
        lines.append("Nothing flagged on any name in this basket.")
    if unread:
        lines += [
            "",
            "⚪ **Filings NOT read for: "
            + ", ".join(t.removesuffix(".NS") for t in unread)
            + ".** The exchange lists nothing against them, and nobody has opened their filings. "
            "That is a gap, not a clean bill.",
        ]
    if clean:
        lines += [
            "",
            f"_Clear (exchange **and** filings read): "
            f"{', '.join(t.removesuffix('.NS') for t in clean)}._",
        ]
    all_items = [i for items in headlines.values() for i in items]
    negative, positive = news_counts(all_items)
    unheard = [t for t in tickers if t.removesuffix(".NS") not in heard]
    if unheard and len(unheard) == len(tickers):
        news_line = (
            f"_Headlines: **not read** for any name in this basket ({news.NEWS_VERSION}). "
            "That is a gap, not a quiet week._"
        )
    else:
        news_line = (
            f"_Headlines ({news.NEWS_VERSION}, model-labelled from archived snippets, last "
            f"{news.LOOKBACK_DAYS} days): **{negative} negative / {positive} positive** "
            "high-materiality item(s) across this basket. These are reports, not events — several "
            "outlets carry one story — so this counts coverage, and it is not a score._"
        )
    stamp = "today's" if age == 0 else f"{age}-day-old"
    lines += [
        "",
        news_line,
        "",
        f"_Exchange indicators from the {stamp} NSE file "
        f"(`{prov.sha256[:12]}…`); filings from the last {lookback_days} days._",
        "_**These are flags, not vetoes.** Nothing here removed a name from the basket above — "
        "the screen chose it and the decision is yours._",
    ]
    return "\n".join(lines)
